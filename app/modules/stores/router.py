"""HTTP routes for the stores module: stores and store-user assignments."""

from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, Query, status

from app.api.deps import CurrentUser, DbSession
from app.core.authz import UserStoreScope, require_permission
from app.modules.common.store_scope import in_scope, resolve_list_scope
from app.modules.stock.services import StockLocationService
from app.modules.stores.schemas import (
    StoreCreate,
    StoreRead,
    StoreUpdate,
    StoreUserCreate,
    StoreUserRead,
)
from app.modules.stores.services import StoreService, StoreUserService

router = APIRouter(prefix="/stores", tags=["stores"])


@router.get("", response_model=list[StoreRead])
async def list_stores(
    db: DbSession,
    _: CurrentUser,
    _perm: Annotated[None, Depends(require_permission("stores.view"))],
    scope: UserStoreScope,
    skip: int = Query(0, ge=0),
    limit: int = Query(100, ge=1, le=500),
) -> list[StoreRead]:
    store_id = resolve_list_scope(None, scope)
    items = await StoreService(db).list(skip=skip, limit=limit, id=store_id)
    return list(items)  # type: ignore[return-value]


@router.post("", response_model=StoreRead, status_code=status.HTTP_201_CREATED)
async def create_store(
    payload: StoreCreate,
    db: DbSession,
    user: CurrentUser,
    _perm: Annotated[None, Depends(require_permission("stores.manage"))],
) -> StoreRead:
    service = StoreService(db)
    data = payload.model_dump()
    data["slug"] = payload.slug or await service.unique_slug(payload.name)
    data["created_by"] = user.id
    store = await service.create(data)

    # A gérant set on the form must also get the StoreUser link the RBAC
    # scope system reads from — otherwise they're assigned but scope-less.
    if store.gerant_id is not None:
        await service.sync_gerant_link(store.id, store.gerant_id)

    # Auto-create the STORE stock location linked to this store
    await StockLocationService(db).create({
        "name": store.name,
        "type": "STORE",
        "store_id": store.id,
        "created_by": user.id,
    })

    return store  # type: ignore[return-value]


@router.get("/{store_id}", response_model=StoreRead)
async def get_store(
    store_id: int,
    db: DbSession,
    _: CurrentUser,
    _perm: Annotated[None, Depends(require_permission("stores.view"))],
    scope: UserStoreScope,
) -> StoreRead:
    store = await StoreService(db).get(store_id)
    if store is None or not in_scope(store.id, scope):  # type: ignore[attr-defined]
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Store not found")
    return store  # type: ignore[return-value]


@router.patch("/{store_id}", response_model=StoreRead)
async def update_store(
    store_id: int,
    payload: StoreUpdate,
    db: DbSession,
    user: CurrentUser,
    _perm: Annotated[None, Depends(require_permission("stores.manage"))],
) -> StoreRead:
    service = StoreService(db)
    store = await service.get(store_id)
    if store is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Store not found")

    updates = payload.model_dump(exclude_unset=True)
    previous_gerant_id = store.gerant_id
    store = await service.update(store, updates)

    # Keep the gérant's StoreUser link in sync when the assignment changes.
    if "gerant_id" in updates and updates["gerant_id"] != previous_gerant_id:
        await service.sync_gerant_link(store.id, store.gerant_id, previous_gerant_id)

    # If store name changed, sync the stock_location name
    if "name" in updates:
        loc_service = StockLocationService(db)
        locations = await loc_service.list(store_id=store_id, limit=10)
        for loc in locations:
            if loc.type == "STORE":  # type: ignore[attr-defined]
                await loc_service.update(loc, {"name": updates["name"]})
                break

    return store  # type: ignore[return-value]


@router.delete("/{store_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_store(
    store_id: int,
    db: DbSession,
    _: CurrentUser,
    _perm: Annotated[None, Depends(require_permission("stores.manage"))],
) -> None:
    service = StoreService(db)
    store = await service.get(store_id)
    if store is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Store not found")
    await service.delete(store)


# --- Store ↔ User ------------------------------------------------------------
@router.get("/{store_id}/users", response_model=list[StoreUserRead])
async def list_store_users(
    store_id: int,
    db: DbSession,
    _: CurrentUser,
    _perm: Annotated[None, Depends(require_permission("stores.view"))],
    scope: UserStoreScope,
) -> list[StoreUserRead]:
    store = await StoreService(db).get(store_id)
    if store is None or not in_scope(store.id, scope):  # type: ignore[attr-defined]
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Store not found")
    items = await StoreUserService(db).list(store_id=store_id, limit=500)
    return list(items)  # type: ignore[return-value]


@router.post(
    "/{store_id}/users",
    response_model=StoreUserRead,
    status_code=status.HTTP_201_CREATED,
)
async def assign_store_user(
    store_id: int,
    payload: StoreUserCreate,
    db: DbSession,
    _: CurrentUser,
    _perm: Annotated[None, Depends(require_permission("stores.manage"))],
) -> StoreUserRead:
    data = payload.model_dump()
    data["store_id"] = store_id
    return await StoreUserService(db).create(data)  # type: ignore[return-value]


@router.delete("/users/{link_id}", status_code=status.HTTP_204_NO_CONTENT)
async def remove_store_user(
    link_id: int,
    db: DbSession,
    _: CurrentUser,
    _perm: Annotated[None, Depends(require_permission("stores.manage"))],
) -> None:
    service = StoreUserService(db)
    link = await service.get(link_id)
    if link is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Assignment not found")
    await service.delete(link)
