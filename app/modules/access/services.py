"""Business logic for the access (RBAC) module."""

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.modules.access.models import (
    Group,
    GroupPermission,
    Permission,
    Role,
    UserGroup,
    UserPermission,
)
from app.modules.common.crud import CRUDService

SUPER_ADMIN_SLUG = "super-admin"


class AccessService:
    """Resolves a user's effective RBAC state (groups + permissions)."""

    def __init__(self, db: AsyncSession) -> None:
        self.db = db

    async def get_group_slugs(self, user_id: int) -> list[str]:
        result = await self.db.execute(
            select(Group.slug)
            .join(UserGroup, UserGroup.group_id == Group.id)
            .where(
                UserGroup.user_id == user_id,
                UserGroup.deleted_at.is_(None),
                Group.deleted_at.is_(None),
            )
        )
        return sorted(set(result.scalars().all()))

    async def get_effective_permission_slugs(self, user_id: int) -> list[str]:
        """Return the global permission slugs the user effectively holds.

        Resolution order:
        1. Union of slugs granted by the user's groups (``GroupPermission.allowed``).
        2. Global user overrides (``UserPermission`` with ``store_id IS NULL``):
           ``allowed=True`` grants, ``allowed=False`` revokes.

        Store-scoped overrides (``store_id`` set) are intentionally ignored here;
        this is the global menu-gating view.
        """
        granted: set[str] = set()

        # 1. Group-granted permissions.
        group_rows = await self.db.execute(
            select(Permission.slug)
            .join(GroupPermission, GroupPermission.permission_id == Permission.id)
            .join(UserGroup, UserGroup.group_id == GroupPermission.group_id)
            .where(
                UserGroup.user_id == user_id,
                UserGroup.deleted_at.is_(None),
                GroupPermission.allowed.is_(True),
                GroupPermission.deleted_at.is_(None),
                Permission.deleted_at.is_(None),
            )
        )
        granted.update(group_rows.scalars().all())

        # 2. Global direct overrides.
        override_rows = await self.db.execute(
            select(Permission.slug, UserPermission.allowed)
            .join(UserPermission, UserPermission.permission_id == Permission.id)
            .where(
                UserPermission.user_id == user_id,
                UserPermission.store_id.is_(None),
                UserPermission.deleted_at.is_(None),
                Permission.deleted_at.is_(None),
            )
        )
        for slug, allowed in override_rows.all():
            if allowed:
                granted.add(slug)
            else:
                granted.discard(slug)

        return sorted(granted)


class RoleService(CRUDService[Role]):
    model = Role


class GroupService(CRUDService[Group]):
    model = Group


class PermissionService(CRUDService[Permission]):
    model = Permission


class UserGroupService(CRUDService[UserGroup]):
    model = UserGroup


class GroupPermissionService(CRUDService[GroupPermission]):
    model = GroupPermission


class UserPermissionService(CRUDService[UserPermission]):
    model = UserPermission
