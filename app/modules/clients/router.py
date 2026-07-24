"""HTTP routes for the clients module."""

from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, Query, status

from app.api.deps import CurrentUser, DbSession
from app.core.authz import UserStoreScope, require_permission
from app.core.i18n import t
from app.modules.clients.schemas import ClientCreate, ClientRead, ClientUpdate
from app.modules.clients.services import ClientService
from app.modules.common.store_scope import (
    assert_creatable,
    in_scope,
    resolve_create_store_id,
    resolve_list_scope,
)

router = APIRouter(prefix="/clients", tags=["clients"])


@router.get("", response_model=list[ClientRead])
async def list_clients(
    db: DbSession,
    _: CurrentUser,
    _perm: Annotated[None, Depends(require_permission("clients.view"))],
    scope: UserStoreScope,
    store_id: int | None = Query(default=None),
    skip: int = Query(0, ge=0),
    limit: int = Query(100, ge=1, le=500),
) -> list[ClientRead]:
    scoped_store_id = resolve_list_scope(store_id, scope)
    return await ClientService(db).list_enriched(  # type: ignore[return-value]
        skip=skip, limit=limit, store_id=scoped_store_id
    )


@router.post("", response_model=ClientRead, status_code=status.HTTP_201_CREATED)
async def create_client(
    payload: ClientCreate,
    db: DbSession,
    user: CurrentUser,
    _perm: Annotated[None, Depends(require_permission("clients.manage"))],
    scope: UserStoreScope,
) -> ClientRead:
    store_id = resolve_create_store_id(payload.store_id, scope)
    assert_creatable(store_id, scope)
    payload = payload.model_copy(update={"store_id": store_id})
    service = ClientService(db)
    client = await service.create(payload, created_by=user.id)
    return await service.enrich(client)  # type: ignore[return-value]


@router.get("/{client_id}", response_model=ClientRead)
async def get_client(
    client_id: int,
    db: DbSession,
    _: CurrentUser,
    _perm: Annotated[None, Depends(require_permission("clients.view"))],
    scope: UserStoreScope,
) -> ClientRead:
    service = ClientService(db)
    client = await service.get(client_id)
    if client is None or not in_scope(client.store_id, scope):  # type: ignore[attr-defined]
        raise HTTPException(status.HTTP_404_NOT_FOUND, t("client_not_found"))
    return await service.enrich(client)  # type: ignore[return-value]


@router.patch("/{client_id}", response_model=ClientRead)
async def update_client(
    client_id: int,
    payload: ClientUpdate,
    db: DbSession,
    _: CurrentUser,
    _perm: Annotated[None, Depends(require_permission("clients.manage"))],
    scope: UserStoreScope,
) -> ClientRead:
    service = ClientService(db)
    client = await service.get(client_id)
    if client is None or not in_scope(client.store_id, scope):  # type: ignore[attr-defined]
        raise HTTPException(status.HTTP_404_NOT_FOUND, t("client_not_found"))
    updated = await service.update(client, payload)
    return await service.enrich(updated)  # type: ignore[return-value]


@router.delete("/{client_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_client(
    client_id: int,
    db: DbSession,
    _: CurrentUser,
    _perm: Annotated[None, Depends(require_permission("clients.manage"))],
    scope: UserStoreScope,
) -> None:
    service = ClientService(db)
    client = await service.get(client_id)
    if client is None or not in_scope(client.store_id, scope):  # type: ignore[attr-defined]
        raise HTTPException(status.HTTP_404_NOT_FOUND, t("client_not_found"))
    await service.delete(client)
