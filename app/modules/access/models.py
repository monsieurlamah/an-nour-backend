"""RBAC ORM models: roles, groups, permissions and their links.

Access model:
- A **group** (super-admin, fournisseur, gerant-boutique, vendeur-boutique)
  carries a set of permissions via ``group_permissions``.
- A **user** belongs to one or more groups (``user_groups``) and can receive
  per-store permission overrides (``user_permissions.allowed`` true/false).
- **roles** are used to qualify a user inside a given store (see
  ``stores.StoreUser``).

Improvement vs. the original spec: ``group_permissions`` was added so groups can
actually own permissions (otherwise group-based access could not be enforced).
"""

from sqlalchemy import Boolean, ForeignKey, String, Text
from sqlalchemy.orm import Mapped, mapped_column

from app.database.base import Entity


class Role(Entity):
    __tablename__ = "roles"

    name: Mapped[str] = mapped_column(String(120), nullable=False)
    slug: Mapped[str] = mapped_column(String(120), unique=True, index=True, nullable=False)
    description: Mapped[str | None] = mapped_column(Text, nullable=True)
    created_by: Mapped[int | None] = mapped_column(
        ForeignKey("users.id", ondelete="SET NULL"), nullable=True
    )


class Group(Entity):
    __tablename__ = "groups"

    name: Mapped[str] = mapped_column(String(120), nullable=False)
    slug: Mapped[str] = mapped_column(String(120), unique=True, index=True, nullable=False)
    description: Mapped[str | None] = mapped_column(Text, nullable=True)


class UserGroup(Entity):
    __tablename__ = "user_groups"

    user_id: Mapped[int] = mapped_column(
        ForeignKey("users.id", ondelete="CASCADE"), nullable=False, index=True
    )
    group_id: Mapped[int] = mapped_column(
        ForeignKey("groups.id", ondelete="CASCADE"), nullable=False, index=True
    )


class Permission(Entity):
    __tablename__ = "permissions"

    name: Mapped[str] = mapped_column(String(150), nullable=False)
    slug: Mapped[str] = mapped_column(String(150), unique=True, index=True, nullable=False)
    module: Mapped[str] = mapped_column(String(80), index=True, nullable=False)
    description: Mapped[str | None] = mapped_column(Text, nullable=True)


class GroupPermission(Entity):
    __tablename__ = "group_permissions"

    group_id: Mapped[int] = mapped_column(
        ForeignKey("groups.id", ondelete="CASCADE"), nullable=False, index=True
    )
    permission_id: Mapped[int] = mapped_column(
        ForeignKey("permissions.id", ondelete="CASCADE"), nullable=False, index=True
    )
    allowed: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)


class UserPermission(Entity):
    __tablename__ = "user_permissions"

    user_id: Mapped[int] = mapped_column(
        ForeignKey("users.id", ondelete="CASCADE"), nullable=False, index=True
    )
    # Optional scope: when set, the override applies only within this store.
    store_id: Mapped[int | None] = mapped_column(
        ForeignKey("stores.id", ondelete="CASCADE"), nullable=True, index=True
    )
    permission_id: Mapped[int] = mapped_column(
        ForeignKey("permissions.id", ondelete="CASCADE"), nullable=False, index=True
    )
    allowed: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)
