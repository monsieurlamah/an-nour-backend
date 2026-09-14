"""HTTP routes for the transferts module — cahier des charges §7.4/§12."""

from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, Query, status

from app.api.deps import CurrentUser, DbSession
from app.core.authz import UserStoreScope, require_permission
from app.database.enums import TransfertStatut
from app.modules.common.store_scope import assert_creatable, in_scope, resolve_list_scope
from app.modules.transferts.schemas import (
    TransfertCancel,
    TransfertCreate,
    TransfertRead,
    TransfertReceive,
)
from app.modules.transferts.services import TransfertService

router = APIRouter(prefix="/transferts", tags=["transferts"])


def _in_scope_for_transfert(transfert, scope) -> bool:
    """A transfert is visible/actionable by whoever is in scope for EITHER
    endpoint — the source boutique shipping it or the destination boutique
    receiving it. `in_scope(None, scope)` (the boutique principale leg) is
    only ever True for an HQ-scoped caller — exactly the desired rule."""
    return in_scope(transfert.boutique_source_id, scope) or in_scope(
        transfert.boutique_destination_id, scope
    )


@router.get("", response_model=list[TransfertRead])
async def list_transferts(
    db: DbSession,
    _: CurrentUser,
    _perm: Annotated[None, Depends(require_permission("transferts.view"))],
    scope: UserStoreScope,
    boutique_id: int | None = Query(default=None),
    statut: TransfertStatut | None = Query(default=None),
    skip: int = Query(0, ge=0),
    limit: int = Query(100, ge=1, le=500),
) -> list[TransfertRead]:
    return await TransfertService(db).list_enriched(  # type: ignore[return-value]
        skip=skip, limit=limit, boutique_id=resolve_list_scope(boutique_id, scope), statut=statut,
    )


@router.post("", response_model=TransfertRead, status_code=status.HTTP_201_CREATED)
async def create_transfert(
    payload: TransfertCreate,
    db: DbSession,
    user: CurrentUser,
    _perm: Annotated[None, Depends(require_permission("transferts.create"))],
    scope: UserStoreScope,
) -> TransfertRead:
    source_id = None if payload.source_est_principale else payload.boutique_source_id
    assert_creatable(source_id, scope)
    service = TransfertService(db)
    transfert = await service.create(payload, user)
    return await service.enrich(transfert)  # type: ignore[return-value]


@router.get("/{transfert_id}", response_model=TransfertRead)
async def get_transfert(
    transfert_id: int,
    db: DbSession,
    _: CurrentUser,
    _perm: Annotated[None, Depends(require_permission("transferts.view"))],
    scope: UserStoreScope,
) -> TransfertRead:
    service = TransfertService(db)
    transfert = await service.get(transfert_id)
    if transfert is None or not _in_scope_for_transfert(transfert, scope):
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Transfert not found")
    return await service.enrich(transfert)  # type: ignore[return-value]


@router.post("/{transfert_id}/receive", response_model=TransfertRead)
async def receive_transfert(
    transfert_id: int,
    payload: TransfertReceive,
    db: DbSession,
    user: CurrentUser,
    _perm: Annotated[None, Depends(require_permission("transferts.receive"))],
    scope: UserStoreScope,
) -> TransfertRead:
    service = TransfertService(db)
    transfert = await service.get(transfert_id)
    if transfert is None or not in_scope(transfert.boutique_destination_id, scope):
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Transfert not found")
    updated = await service.receive(transfert, payload, user)
    return await service.enrich(updated)  # type: ignore[return-value]


@router.post("/{transfert_id}/cancel", response_model=TransfertRead)
async def cancel_transfert(
    transfert_id: int,
    payload: TransfertCancel,
    db: DbSession,
    user: CurrentUser,
    _perm: Annotated[None, Depends(require_permission("transferts.cancel"))],
    scope: UserStoreScope,
) -> TransfertRead:
    service = TransfertService(db)
    transfert = await service.get(transfert_id)
    if transfert is None or not _in_scope_for_transfert(transfert, scope):
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Transfert not found")
    updated = await service.cancel(transfert, payload, user)
    return await service.enrich(updated)  # type: ignore[return-value]
