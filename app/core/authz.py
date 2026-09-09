"""Centralized authorization: permission checks + store-scope resolution.

``app/api/deps.py`` only answers "is this a valid, active account" —
authentication, not authorization. Every route that mutates or reads
non-public data must additionally depend on ``require_permission(slug)``
(and, for store-scoped resources, combine it with ``UserStoreScope`` —
see ``app/modules/common/store_scope.py`` for how the scope value is
applied to list/create/get-by-id operations).

Permissions are recomputed from the database on every request — never
cached in the JWT — so revoking a permission or removing a user from a
group takes effect on their very next request, no re-login required.
"""

from collections.abc import Callable
from typing import Annotated, Literal

from fastapi import Depends, HTTPException, status
from sqlalchemy import select

from app.api.deps import CurrentUser, DbSession
from app.core.i18n import t
from app.modules.access.services import SUPER_ADMIN_SLUG, AccessService
from app.modules.stores.models import Store, StoreUser

# Permissions that indicate "this user sees the whole network," not just the
# store(s) they're explicitly assigned to. Derived from the permission a
# group actually holds rather than hardcoding group slugs, so a future HQ-wide
# group keeps working without touching this file.
_HQ_INDICATOR_SLUGS = frozenset({"stores.manage", "dashboard.global.view"})

StoreScope = Literal["hq"] | frozenset[int]


async def get_effective_permissions(user: CurrentUser, db: DbSession) -> frozenset[str]:
    slugs = await AccessService(db).get_effective_permission_slugs(user.id)
    return frozenset(slugs)


EffectivePermissions = Annotated[frozenset[str], Depends(get_effective_permissions)]


async def get_group_slugs(user: CurrentUser, db: DbSession) -> frozenset[str]:
    slugs = await AccessService(db).get_group_slugs(user.id)
    return frozenset(slugs)


GroupSlugs = Annotated[frozenset[str], Depends(get_group_slugs)]


def require_permission(slug: str) -> Callable:
    """FastAPI dependency factory.

    Usage: ``_perm: Annotated[None, Depends(require_permission("ventes.create"))]``
    """

    async def _checker(permissions: EffectivePermissions, groups: GroupSlugs) -> None:
        # Belt-and-braces bypass, independent of whether every GroupPermission
        # row for this slug has actually been seeded — a missing seed entry
        # must never lock out the super-admin group.
        if SUPER_ADMIN_SLUG in groups:
            return
        if slug in permissions:
            return
        raise HTTPException(status.HTTP_403_FORBIDDEN, detail=t("permission_denied"))

    return _checker


def require_any_permission(*slugs: str) -> Callable:
    """Like ``require_permission``, but passes if the caller has ANY of the
    given slugs — e.g. a route reachable via either a central or a store
    variant of a capability."""

    async def _checker(permissions: EffectivePermissions, groups: GroupSlugs) -> None:
        if SUPER_ADMIN_SLUG in groups:
            return
        if permissions & set(slugs):
            return
        raise HTTPException(status.HTTP_403_FORBIDDEN, detail=t("permission_denied"))

    return _checker


async def get_user_store_scope(
    user: CurrentUser,
    db: DbSession,
    groups: GroupSlugs,
    permissions: EffectivePermissions,
) -> StoreScope:
    """Resolve the set of stores this user may act on.

    Returns the literal ``"hq"`` for network-wide access (super-admin, or
    any group carrying an HQ-indicator permission such as ``stores.manage``
    or ``dashboard.global.view``), otherwise the set of store ids the user
    is linked to via active ``StoreUser`` rows (possibly empty).
    """
    if SUPER_ADMIN_SLUG in groups or (permissions & _HQ_INDICATOR_SLUGS):
        return "hq"
    rows = await db.execute(
        select(StoreUser.store_id).where(
            StoreUser.user_id == user.id,
            StoreUser.deleted_at.is_(None),
        )
    )
    store_ids = set(rows.scalars().all())
    # Belt-and-braces: a user set as a store's gérant (``stores.gerant_id``)
    # is in scope for that store even if the ``StoreUser`` link row is missing
    # (older data, or a direct DB assignment). New assignments keep the link
    # in sync — see ``StoreService.sync_gerant_link``.
    gerant_rows = await db.execute(
        select(Store.id).where(Store.gerant_id == user.id, Store.deleted_at.is_(None))
    )
    store_ids.update(gerant_rows.scalars().all())
    return frozenset(store_ids)


UserStoreScope = Annotated[StoreScope, Depends(get_user_store_scope)]
