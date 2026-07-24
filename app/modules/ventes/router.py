"""HTTP routes for the ventes module."""

from datetime import date
from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, Query, status

from app.api.deps import CurrentUser, DbSession
from app.core.authz import UserStoreScope, require_permission
from app.database.enums import VenteStatut, VenteType
from app.modules.common.store_scope import assert_creatable, in_scope, resolve_list_scope
from app.modules.ventes.models import Vente
from app.modules.ventes.schemas import (
    VenteCreate,
    VenteRead,
    VenteRemboursementCreate,
    VenteRemboursementRead,
    VenteRetourCreate,
    VenteRetourRead,
)
from app.modules.ventes.services import VenteRemboursementService, VenteRetourService, VenteService

router = APIRouter(prefix="/ventes", tags=["ventes"])


async def _get_scoped_vente(vente_id: int, service: VenteService, scope) -> Vente:  # type: ignore[no-untyped-def]
    """Load a Vente and 404 if it doesn't exist or its boutique is outside
    the caller's scope — never confirm the existence of a sale in a store
    the caller can't see."""
    vente = await service.get(vente_id)
    if vente is None or not in_scope(vente.boutique_id, scope):
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Vente not found")
    return vente


@router.get("/count")
async def count_ventes(
    db: DbSession,
    _: CurrentUser,
    _perm: Annotated[None, Depends(require_permission("ventes.view"))],
    scope: UserStoreScope,
    boutique_id: int | None = Query(default=None),
    client_id: int | None = Query(default=None),
    vendeur_id: int | None = Query(default=None),
    statut: VenteStatut | None = Query(default=None),
    type_vente: VenteType | None = Query(default=None),
    search: str | None = Query(default=None),
    date_debut: date | None = Query(default=None),
    date_fin: date | None = Query(default=None),
) -> dict[str, int]:
    total = await VenteService(db).count(
        boutique_id=resolve_list_scope(boutique_id, scope),
        client_id=client_id,
        vendeur_id=vendeur_id,
        statut=statut,
        type_vente=type_vente,
        search=search,
        date_debut=date_debut,
        date_fin=date_fin,
    )
    return {"total": total}


@router.get("", response_model=list[VenteRead])
async def list_ventes(
    db: DbSession,
    _: CurrentUser,
    _perm: Annotated[None, Depends(require_permission("ventes.view"))],
    scope: UserStoreScope,
    boutique_id: int | None = Query(default=None),
    client_id: int | None = Query(default=None),
    vendeur_id: int | None = Query(default=None),
    statut: VenteStatut | None = Query(default=None),
    type_vente: VenteType | None = Query(default=None),
    search: str | None = Query(default=None),
    date_debut: date | None = Query(default=None),
    date_fin: date | None = Query(default=None),
    skip: int = Query(0, ge=0),
    limit: int = Query(50, ge=1, le=500),
) -> list[VenteRead]:
    return await VenteService(db).list_enriched(  # type: ignore[return-value]
        skip=skip, limit=limit,
        boutique_id=resolve_list_scope(boutique_id, scope),
        client_id=client_id, vendeur_id=vendeur_id,
        statut=statut, type_vente=type_vente,
        search=search, date_debut=date_debut, date_fin=date_fin,
    )


@router.post("", response_model=VenteRead, status_code=status.HTTP_201_CREATED)
async def create_vente(
    payload: VenteCreate,
    db: DbSession,
    user: CurrentUser,
    _perm: Annotated[None, Depends(require_permission("ventes.create"))],
    scope: UserStoreScope,
) -> VenteRead:
    assert_creatable(payload.boutique_id, scope)
    return await VenteService(db).create(payload, user)  # type: ignore[return-value]


@router.get("/{vente_id}", response_model=VenteRead)
async def get_vente(
    vente_id: int,
    db: DbSession,
    _: CurrentUser,
    _perm: Annotated[None, Depends(require_permission("ventes.view"))],
    scope: UserStoreScope,
) -> VenteRead:
    vente = await _get_scoped_vente(vente_id, VenteService(db), scope)
    return vente  # type: ignore[return-value]


@router.post("/{vente_id}/void", response_model=VenteRead)
async def void_vente(
    vente_id: int,
    db: DbSession,
    user: CurrentUser,
    _perm: Annotated[None, Depends(require_permission("ventes.annuler"))],
    scope: UserStoreScope,
) -> VenteRead:
    service = VenteService(db)
    vente = await _get_scoped_vente(vente_id, service, scope)
    return await service.void(vente, user)  # type: ignore[return-value]


@router.post("/{vente_id}/confirm-livraison", response_model=VenteRead)
async def confirm_livraison_vente(
    vente_id: int,
    db: DbSession,
    user: CurrentUser,
    _perm: Annotated[None, Depends(require_permission("ventes.livrer"))],
    scope: UserStoreScope,
) -> VenteRead:
    service = VenteService(db)
    vente = await _get_scoped_vente(vente_id, service, scope)
    return await service.confirm_livraison(vente, user)  # type: ignore[return-value]


@router.delete("/{vente_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_vente(
    vente_id: int,
    db: DbSession,
    _: CurrentUser,
    _perm: Annotated[None, Depends(require_permission("ventes.manage"))],
    scope: UserStoreScope,
) -> None:
    service = VenteService(db)
    vente = await _get_scoped_vente(vente_id, service, scope)
    await service.soft_delete(vente)


# ── Returns ───────────────────────────────────────────────────────────────────

@router.get("/{vente_id}/retours", response_model=list[VenteRetourRead])
async def list_retours(
    vente_id: int,
    db: DbSession,
    _: CurrentUser,
    _perm: Annotated[None, Depends(require_permission("ventes.view"))],
    scope: UserStoreScope,
) -> list[VenteRetourRead]:
    await _get_scoped_vente(vente_id, VenteService(db), scope)
    return await VenteRetourService(db).list(vente_id)  # type: ignore[return-value]


@router.post(
    "/{vente_id}/return",
    response_model=VenteRetourRead,
    status_code=status.HTTP_201_CREATED,
)
async def create_retour(
    vente_id: int,
    payload: VenteRetourCreate,
    db: DbSession,
    user: CurrentUser,
    _perm: Annotated[None, Depends(require_permission("ventes.retourner"))],
    scope: UserStoreScope,
) -> VenteRetourRead:
    vente = await _get_scoped_vente(vente_id, VenteService(db), scope)
    return await VenteRetourService(db).create(vente, payload, user)  # type: ignore[return-value]


# ── Refunds ───────────────────────────────────────────────────────────────────

@router.get("/{vente_id}/remboursements", response_model=list[VenteRemboursementRead])
async def list_remboursements(
    vente_id: int,
    db: DbSession,
    _: CurrentUser,
    _perm: Annotated[None, Depends(require_permission("ventes.view"))],
    scope: UserStoreScope,
) -> list[VenteRemboursementRead]:
    await _get_scoped_vente(vente_id, VenteService(db), scope)
    return await VenteRemboursementService(db).list(vente_id)  # type: ignore[return-value]


@router.post(
    "/{vente_id}/refund",
    response_model=VenteRemboursementRead,
    status_code=status.HTTP_201_CREATED,
)
async def create_remboursement(
    vente_id: int,
    payload: VenteRemboursementCreate,
    db: DbSession,
    user: CurrentUser,
    _perm: Annotated[None, Depends(require_permission("ventes.rembourser"))],
    scope: UserStoreScope,
) -> VenteRemboursementRead:
    vente = await _get_scoped_vente(vente_id, VenteService(db), scope)
    return await VenteRemboursementService(db).create(  # type: ignore[return-value]
        vente, payload, user
    )
