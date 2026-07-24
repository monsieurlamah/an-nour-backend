"""Pure helpers applying a resolved ``StoreScope`` (see ``app.core.authz``)
to store-scoped list/create/get-by-id operations.

No FastAPI import beyond ``HTTPException`` — consistent with how services
already raise HTTP errors directly (see ``ClientService``), and keeps this
module usable from any service regardless of whether it extends
``CRUDService`` or is hand-rolled.

Convention: a missing permission is a 403 (checked separately by
``require_permission``); a resource that exists but falls outside the
caller's store scope is masked as a 404 — never confirm the existence of a
resource outside your own boutique.
"""

from fastapi import HTTPException, status

from app.core.authz import StoreScope
from app.core.i18n import t

# Matches no real primary key (ids start at 1) — used so a scoped-out list
# query returns an empty result set via a normal IN() clause instead of a
# special-cased "no filter" branch.
_NO_MATCH: list[int] = [-1]


def resolve_list_scope(requested: int | None, scope: StoreScope) -> int | list[int] | None:
    """Merge a caller-supplied store_id/boutique_id query param with the
    caller's real scope. Return value plugs directly into the existing
    `store_id=`/`boutique_id=` filter kwarg used by list()/count() calls."""
    if scope == "hq":
        return requested  # HQ may still narrow to one store if it asks to
    if requested is None:
        return list(scope) if scope else _NO_MATCH
    if requested not in scope:
        return _NO_MATCH  # silently empty — don't leak that another store exists
    return requested


def in_scope(store_id: int | None, scope: StoreScope) -> bool:
    return scope == "hq" or (store_id is not None and store_id in scope)


def assert_creatable(store_id: int | None, scope: StoreScope) -> None:
    """Raise 403 if the caller may not create a record for `store_id`."""
    if scope == "hq":
        return
    if store_id is None or store_id not in scope:
        raise HTTPException(status.HTTP_403_FORBIDDEN, detail=t("store_out_of_scope"))


def resolve_create_store_id(provided: int | None, scope: StoreScope) -> int | None:
    """Default `store_id` for a create payload when the field is nullable
    and the caller omitted it: auto-fill when the user has exactly one
    store in scope (preserves existing flows that never sent this field);
    otherwise leave it to `assert_creatable` to reject as ambiguous/missing."""
    if provided is not None or scope == "hq":
        return provided
    if len(scope) == 1:
        return next(iter(scope))
    return None


def assert_scope_nonempty(scope: StoreScope) -> None:
    """A store-scoped user with zero assigned stores can't sensibly create
    anything requiring a store_id — surface a clear error rather than a
    silent 403 that looks like a generic permission problem."""
    if scope != "hq" and not scope:
        raise HTTPException(status.HTTP_403_FORBIDDEN, detail=t("no_store_assigned"))


class StoreScopedMixin:
    """Opt-in mixin for services whose model carries a store dimension.
    Requires the composing class to define `store_field` (defaults to
    "store_id") and an async `get(obj_id)` coroutine returning the ORM
    object or None (already provided by CRUDService, or hand-rolled)."""

    store_field: str = "store_id"

    async def get_scoped(self, obj_id: int, scope: StoreScope):
        obj = await self.get(obj_id)  # type: ignore[attr-defined]
        if obj is None:
            return None
        if not in_scope(getattr(obj, self.store_field), scope):
            return None
        return obj
