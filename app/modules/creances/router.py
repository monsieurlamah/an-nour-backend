"""HTTP routes for the creances module: debts and payments."""

from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, Query, status

from app.api.deps import CurrentUser, DbSession
from app.core.authz import UserStoreScope, require_permission
from app.database.enums import CreanceStatut
from app.modules.common.store_scope import assert_creatable, in_scope, resolve_list_scope
from app.modules.creances.schemas import (
    CreanceCreate,
    CreanceRead,
    CreanceUpdate,
    PaiementCreate,
    PaiementRead,
)
from app.modules.creances.services import CreanceService, PaiementService
from app.modules.ventes.models import Vente

router = APIRouter(prefix="/creances", tags=["creances"])


@router.get("", response_model=list[CreanceRead])
async def list_creances(
    db: DbSession,
    _: CurrentUser,
    _perm: Annotated[None, Depends(require_permission("creances.view"))],
    scope: UserStoreScope,
    client_id: int | None = Query(default=None),
    boutique_id: int | None = Query(default=None),
    statut: CreanceStatut | None = Query(default=None),
    skip: int = Query(0, ge=0),
    limit: int = Query(100, ge=1, le=500),
) -> list[CreanceRead]:
    return await CreanceService(db).list_enriched(  # type: ignore[return-value]
        skip=skip,
        limit=limit,
        order_desc=True,
        client_id=client_id,
        boutique_id=resolve_list_scope(boutique_id, scope),
        statut=statut,
    )


@router.post("", response_model=CreanceRead, status_code=status.HTTP_201_CREATED)
async def create_creance(
    payload: CreanceCreate,
    db: DbSession,
    _: CurrentUser,
    _perm: Annotated[None, Depends(require_permission("creances.manage"))],
    scope: UserStoreScope,
) -> CreanceRead:
    assert_creatable(payload.boutique_id, scope)
    service = CreanceService(db)
    creance = await service.create_creance(payload)
    return await service.enrich(creance)  # type: ignore[return-value]


@router.get("/{creance_id}", response_model=CreanceRead)
async def get_creance(
    creance_id: int,
    db: DbSession,
    _: CurrentUser,
    _perm: Annotated[None, Depends(require_permission("creances.view"))],
    scope: UserStoreScope,
) -> CreanceRead:
    service = CreanceService(db)
    creance = await service.get(creance_id)
    if creance is None or not in_scope(creance.boutique_id, scope):  # type: ignore[attr-defined]
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Creance not found")
    return await service.enrich(creance)  # type: ignore[return-value]


@router.patch("/{creance_id}", response_model=CreanceRead)
async def update_creance(
    creance_id: int,
    payload: CreanceUpdate,
    db: DbSession,
    _: CurrentUser,
    _perm: Annotated[None, Depends(require_permission("creances.manage"))],
    scope: UserStoreScope,
) -> CreanceRead:
    service = CreanceService(db)
    creance = await service.get(creance_id)
    if creance is None or not in_scope(creance.boutique_id, scope):  # type: ignore[attr-defined]
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Creance not found")
    updated = await service.update(creance, payload.model_dump(exclude_unset=True))
    return await service.enrich(updated)  # type: ignore[return-value]


# --- Payments ------------------------------------------------------------------
# Paiement has no boutique_id of its own — scope is derived from the linked
# Creance/Vente, since that's the only store dimension available.

async def _assert_payment_target_in_scope(
    db, creance_id: int | None, vente_id: int | None, scope
) -> None:
    if scope == "hq":
        return
    if creance_id is not None:
        creance = await CreanceService(db).get(creance_id)
        if creance is None or not in_scope(creance.boutique_id, scope):  # type: ignore[attr-defined]
            raise HTTPException(status.HTTP_404_NOT_FOUND, "Creance not found")
        return
    if vente_id is not None:
        vente = await db.get(Vente, vente_id)
        if vente is None or vente.deleted_at is not None or not in_scope(vente.boutique_id, scope):
            raise HTTPException(status.HTTP_404_NOT_FOUND, "Vente not found")
        return
    # Neither reference given: a store-scoped user can't be trusted to
    # attribute the payment to their own boutique with no target at all.
    raise HTTPException(status.HTTP_422_UNPROCESSABLE_ENTITY, "creance_id or vente_id required")


@router.get("/payments/list", response_model=list[PaiementRead])
async def list_payments(
    db: DbSession,
    _: CurrentUser,
    _perm: Annotated[None, Depends(require_permission("creances.view"))],
    scope: UserStoreScope,
    creance_id: int | None = Query(default=None),
    vente_id: int | None = Query(default=None),
    skip: int = Query(0, ge=0),
    limit: int = Query(100, ge=1, le=500),
) -> list[PaiementRead]:
    if scope != "hq":
        # No target given -> nothing to safely scope; return empty rather
        # than leaking every payment on the platform.
        if creance_id is None and vente_id is None:
            return []
        await _assert_payment_target_in_scope(db, creance_id, vente_id, scope)
    items = await PaiementService(db).list(
        skip=skip, limit=limit, creance_id=creance_id, vente_id=vente_id
    )
    return list(items)  # type: ignore[return-value]


@router.post("/payments", response_model=PaiementRead, status_code=status.HTTP_201_CREATED)
async def create_payment(
    payload: PaiementCreate,
    db: DbSession,
    user: CurrentUser,
    _perm: Annotated[None, Depends(require_permission("paiements.create"))],
    scope: UserStoreScope,
) -> PaiementRead:
    await _assert_payment_target_in_scope(db, payload.creance_id, payload.vente_id, scope)
    return await PaiementService(db).create(payload, user)  # type: ignore[return-value]
