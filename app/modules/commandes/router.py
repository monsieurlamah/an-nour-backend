"""HTTP routes for the commandes module (internal réappro workflow)."""

from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, Query, Request, status
from sqlalchemy import select

from app.api.deps import CurrentUser, DbSession
from app.core.authz import (
    EffectivePermissions,
    UserStoreScope,
    require_any_permission,
    require_permission,
)
from app.database.enums import CommandeStatut
from app.modules.commandes.schemas import (
    CommandeAnomalieRead,
    CommandeCreate,
    CommandeEvenementRead,
    CommandeLigneResolve,
    CommandeProformaReject,
    CommandeProformaRevise,
    CommandeRead,
    CommandeReceptionCreate,
    CommandeReceptionRead,
    CommandeRefuse,
    CommandeShip,
    CommandeValidate,
)
from app.modules.commandes.services import CommandeService
from app.modules.common.store_scope import assert_creatable, in_scope, resolve_list_scope
from app.modules.stores.models import StoreUser

router = APIRouter(prefix="/commandes", tags=["commandes"])


def _client_ip(request: Request) -> str | None:
    return request.client.host if request.client else None


async def _load_or_404(service: CommandeService, commande_id: int) -> CommandeRead:
    commande = await service.get(commande_id)
    if commande is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Commande not found")
    return commande  # type: ignore[return-value]


async def _is_boutique_member(db: DbSession, user_id: int, boutique_id: int) -> bool:
    """True only if the user has a real StoreUser row for this exact
    boutique — deliberately NOT ``in_scope``/``UserStoreScope``, which treat
    HQ (super-admin, stores.manage, ...) as "in scope everywhere." The
    proforma decision is the boutique gérant's own checks-and-balances on
    the Boss's proforma — it must belong to that boutique's real staff,
    never to HQ acting on the boutique's behalf."""
    result = await db.execute(
        select(StoreUser.id).where(
            StoreUser.user_id == user_id,
            StoreUser.store_id == boutique_id,
            StoreUser.deleted_at.is_(None),
        )
    )
    return result.scalar_one_or_none() is not None


# --- Queues (magasinier HQ / livreur — no store scope, permission-gated only) --


@router.get("/queue/preparation", response_model=list[CommandeRead])
async def queue_preparation(
    db: DbSession,
    _: CurrentUser,
    _perm: Annotated[None, Depends(require_permission("commandes.prepare"))],
    skip: int = Query(0, ge=0),
    limit: int = Query(100, ge=1, le=500),
) -> list[CommandeRead]:
    items = await CommandeService(db).list_queue_preparation(skip=skip, limit=limit)
    return list(items)  # type: ignore[return-value]


@router.get("/queue/livraison", response_model=list[CommandeRead])
async def queue_livraison(
    db: DbSession,
    _: CurrentUser,
    _perm: Annotated[None, Depends(require_permission("commandes.ship"))],
    skip: int = Query(0, ge=0),
    limit: int = Query(100, ge=1, le=500),
) -> list[CommandeRead]:
    items = await CommandeService(db).list_queue_livraison(skip=skip, limit=limit)
    return list(items)  # type: ignore[return-value]


# --- Collection ---------------------------------------------------------------


@router.get("", response_model=list[CommandeRead])
async def list_commandes(
    db: DbSession,
    _: CurrentUser,
    _perm: Annotated[None, Depends(require_permission("commandes.view"))],
    scope: UserStoreScope,
    boutique_id: int | None = Query(default=None),
    statut: CommandeStatut | None = Query(default=None),
    skip: int = Query(0, ge=0),
    limit: int = Query(100, ge=1, le=500),
) -> list[CommandeRead]:
    items = await CommandeService(db).list(
        skip=skip, limit=limit, boutique_id=resolve_list_scope(boutique_id, scope), statut=statut
    )
    return list(items)  # type: ignore[return-value]


@router.post("", response_model=CommandeRead, status_code=status.HTTP_201_CREATED)
async def create_commande(
    payload: CommandeCreate,
    db: DbSession,
    user: CurrentUser,
    request: Request,
    _perm: Annotated[None, Depends(require_permission("commandes.create"))],
    scope: UserStoreScope,
) -> CommandeRead:
    assert_creatable(payload.boutique_id, scope)
    return await CommandeService(db).create(payload, user, _client_ip(request))  # type: ignore[return-value]


@router.get("/{commande_id}", response_model=CommandeRead)
async def get_commande(
    commande_id: int,
    db: DbSession,
    _: CurrentUser,
    _perm: Annotated[None, Depends(require_permission("commandes.view"))],
    scope: UserStoreScope,
    permissions: EffectivePermissions,
) -> CommandeRead:
    commande = await CommandeService(db).get(commande_id)
    # Own boutique OR HQ, but also visible to the magasinier/livreur queues —
    # those roles carry no StoreUser row so `scope` alone would 404 them out.
    allowed = commande is not None and (
        in_scope(commande.boutique_id, scope)  # type: ignore[attr-defined]
        or "commandes.prepare" in permissions
        or "commandes.ship" in permissions
    )
    if not allowed:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Commande not found")
    return commande  # type: ignore[return-value]


@router.get("/{commande_id}/events", response_model=list[CommandeEvenementRead])
async def list_commande_events(
    commande_id: int,
    db: DbSession,
    _: CurrentUser,
    _perm: Annotated[None, Depends(require_permission("commandes.view"))],
    scope: UserStoreScope,
    permissions: EffectivePermissions,
) -> list[CommandeEvenementRead]:
    service = CommandeService(db)
    commande = await service.get(commande_id)
    allowed = commande is not None and (
        in_scope(commande.boutique_id, scope)  # type: ignore[attr-defined]
        or "commandes.prepare" in permissions
        or "commandes.ship" in permissions
    )
    if not allowed:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Commande not found")
    return list(await service.list_events(commande_id))  # type: ignore[return-value]


@router.get("/{commande_id}/receptions", response_model=list[CommandeReceptionRead])
async def list_commande_receptions(
    commande_id: int,
    db: DbSession,
    _: CurrentUser,
    _perm: Annotated[None, Depends(require_permission("commandes.view"))],
    scope: UserStoreScope,
) -> list[CommandeReceptionRead]:
    service = CommandeService(db)
    commande = await service.get(commande_id)
    if commande is None or not in_scope(commande.boutique_id, scope):  # type: ignore[attr-defined]
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Commande not found")
    return list(await service.list_receptions(commande_id))  # type: ignore[return-value]


@router.get("/{commande_id}/anomalies", response_model=list[CommandeAnomalieRead])
async def list_commande_anomalies(
    commande_id: int,
    db: DbSession,
    _: CurrentUser,
    _perm: Annotated[None, Depends(require_permission("commandes.view"))],
    scope: UserStoreScope,
) -> list[CommandeAnomalieRead]:
    service = CommandeService(db)
    commande = await service.get(commande_id)
    if commande is None or not in_scope(commande.boutique_id, scope):  # type: ignore[attr-defined]
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Commande not found")
    return list(await service.list_anomalies(commande_id))  # type: ignore[return-value]


# --- Workflow transitions -------------------------------------------------------


@router.post("/{commande_id}/submit", response_model=CommandeRead)
async def submit_commande(
    commande_id: int,
    db: DbSession,
    user: CurrentUser,
    request: Request,
    _perm: Annotated[None, Depends(require_permission("commandes.create"))],
    scope: UserStoreScope,
) -> CommandeRead:
    service = CommandeService(db)
    commande = await service.get(commande_id)
    if commande is None or not in_scope(commande.boutique_id, scope):  # type: ignore[attr-defined]
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Commande not found")
    return await service.submit(commande, user, _client_ip(request))  # type: ignore[return-value]


@router.post("/{commande_id}/validate", response_model=CommandeRead)
async def validate_commande(
    commande_id: int,
    payload: CommandeValidate,
    db: DbSession,
    user: CurrentUser,
    request: Request,
    # Validating a store's reorder request is a central/HQ authority action —
    # the validator does not need to belong to the requesting store.
    _perm: Annotated[None, Depends(require_permission("commandes.validate"))],
) -> CommandeRead:
    service = CommandeService(db)
    commande = await _load_or_404(service, commande_id)
    return await service.validate(commande, payload, user, _client_ip(request))  # type: ignore[return-value]


@router.post("/{commande_id}/refuse", response_model=CommandeRead)
async def refuse_commande(
    commande_id: int,
    payload: CommandeRefuse,
    db: DbSession,
    user: CurrentUser,
    request: Request,
    _perm: Annotated[None, Depends(require_permission("commandes.validate"))],
) -> CommandeRead:
    service = CommandeService(db)
    commande = await _load_or_404(service, commande_id)
    return await service.refuse(commande, payload, user, _client_ip(request))  # type: ignore[return-value]


@router.post("/{commande_id}/lignes/{ligne_id}/resolve", response_model=CommandeRead)
async def resolve_ligne(
    commande_id: int,
    ligne_id: int,
    payload: CommandeLigneResolve,
    db: DbSession,
    user: CurrentUser,
    request: Request,
    _perm: Annotated[None, Depends(require_permission("commandes.validate"))],
) -> CommandeRead:
    service = CommandeService(db)
    commande = await _load_or_404(service, commande_id)
    return await service.resolve_ligne(  # type: ignore[return-value]
        commande, ligne_id, payload, user, _client_ip(request)
    )


@router.post("/{commande_id}/proforma", response_model=CommandeRead)
async def generate_proforma(
    commande_id: int,
    db: DbSession,
    user: CurrentUser,
    request: Request,
    _perm: Annotated[None, Depends(require_permission("commandes.validate"))],
) -> CommandeRead:
    service = CommandeService(db)
    commande = await _load_or_404(service, commande_id)
    return await service.generate_proforma(commande, user, _client_ip(request))  # type: ignore[return-value]


@router.post("/{commande_id}/proforma/approve", response_model=CommandeRead)
async def approve_proforma(
    commande_id: int,
    db: DbSession,
    user: CurrentUser,
    request: Request,
    # Boutique-side decision — the gérant of the requesting store, not HQ.
    # Deliberately checked via _is_boutique_member, not UserStoreScope/in_scope:
    # this is the boutique's own check on the Boss's proforma, so even an
    # HQ-scoped account (super-admin, stores.manage) may not do it on the
    # boutique's behalf — only a real StoreUser of that exact boutique.
    _perm: Annotated[None, Depends(require_permission("commandes.approve_proforma"))],
) -> CommandeRead:
    service = CommandeService(db)
    commande = await service.get(commande_id)
    if commande is None or not await _is_boutique_member(db, user.id, commande.boutique_id):  # type: ignore[attr-defined]
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Commande not found")
    return await service.approve_proforma(commande, user, _client_ip(request))  # type: ignore[return-value]


@router.post("/{commande_id}/proforma/reject", response_model=CommandeRead)
async def reject_proforma(
    commande_id: int,
    payload: CommandeProformaReject,
    db: DbSession,
    user: CurrentUser,
    request: Request,
    _perm: Annotated[None, Depends(require_permission("commandes.approve_proforma"))],
) -> CommandeRead:
    service = CommandeService(db)
    commande = await service.get(commande_id)
    if commande is None or not await _is_boutique_member(db, user.id, commande.boutique_id):  # type: ignore[attr-defined]
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Commande not found")
    return await service.reject_proforma(commande, payload, user, _client_ip(request))  # type: ignore[return-value]


@router.post("/{commande_id}/proforma/resubmit", response_model=CommandeRead)
async def resubmit_proforma(
    commande_id: int,
    payload: CommandeProformaRevise,
    db: DbSession,
    user: CurrentUser,
    request: Request,
    # Revising and resubmitting a rejected proforma is a Boss/HQ action, same
    # authority level as generating it in the first place.
    _perm: Annotated[None, Depends(require_permission("commandes.validate"))],
) -> CommandeRead:
    service = CommandeService(db)
    commande = await _load_or_404(service, commande_id)
    return await service.resubmit_proforma(commande, payload, user, _client_ip(request))  # type: ignore[return-value]


@router.post("/{commande_id}/prepare", response_model=CommandeRead)
async def start_preparation(
    commande_id: int,
    db: DbSession,
    user: CurrentUser,
    request: Request,
    _perm: Annotated[None, Depends(require_permission("commandes.prepare"))],
) -> CommandeRead:
    service = CommandeService(db)
    commande = await _load_or_404(service, commande_id)
    return await service.start_preparation(commande, user, _client_ip(request))  # type: ignore[return-value]


@router.post("/{commande_id}/prepare/confirm", response_model=CommandeRead)
async def confirm_preparation(
    commande_id: int,
    db: DbSession,
    user: CurrentUser,
    request: Request,
    _perm: Annotated[None, Depends(require_permission("commandes.prepare"))],
) -> CommandeRead:
    service = CommandeService(db)
    commande = await _load_or_404(service, commande_id)
    return await service.confirm_preparation(commande, user, _client_ip(request))  # type: ignore[return-value]


@router.post("/{commande_id}/ship", response_model=CommandeRead)
async def ship_commande(
    commande_id: int,
    payload: CommandeShip,
    db: DbSession,
    user: CurrentUser,
    request: Request,
    _perm: Annotated[None, Depends(require_permission("commandes.ship"))],
) -> CommandeRead:
    service = CommandeService(db)
    commande = await _load_or_404(service, commande_id)
    return await service.ship(commande, payload, user, _client_ip(request))  # type: ignore[return-value]


@router.post("/{commande_id}/deliver", response_model=CommandeRead)
async def mark_delivered(
    commande_id: int,
    db: DbSession,
    user: CurrentUser,
    request: Request,
    _perm: Annotated[None, Depends(require_permission("commandes.deliver"))],
) -> CommandeRead:
    service = CommandeService(db)
    commande = await _load_or_404(service, commande_id)
    return await service.mark_delivered(commande, user, _client_ip(request))  # type: ignore[return-value]


@router.post("/{commande_id}/reception", response_model=CommandeRead)
async def confirm_reception(
    commande_id: int,
    payload: CommandeReceptionCreate,
    db: DbSession,
    user: CurrentUser,
    request: Request,
    _perm: Annotated[None, Depends(require_permission("commandes.receive"))],
    scope: UserStoreScope,
) -> CommandeRead:
    service = CommandeService(db)
    commande = await service.get(commande_id)
    if commande is None or not in_scope(commande.boutique_id, scope):  # type: ignore[attr-defined]
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Commande not found")
    return await service.confirm_reception(commande, payload, user, _client_ip(request))  # type: ignore[return-value]


@router.post("/{commande_id}/cancel", response_model=CommandeRead)
async def cancel_commande(
    commande_id: int,
    db: DbSession,
    user: CurrentUser,
    request: Request,
    _perm: Annotated[
        None, Depends(require_any_permission("commandes.create", "commandes.validate"))
    ],
    scope: UserStoreScope,
    motif: str | None = Query(default=None),
) -> CommandeRead:
    service = CommandeService(db)
    commande = await service.get(commande_id)
    if commande is None or not in_scope(commande.boutique_id, scope):  # type: ignore[attr-defined]
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Commande not found")
    return await service.cancel(commande, user, _client_ip(request), motif)  # type: ignore[return-value]


@router.delete("/{commande_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_commande(
    commande_id: int,
    db: DbSession,
    _: CurrentUser,
    _perm: Annotated[None, Depends(require_permission("commandes.create"))],
    scope: UserStoreScope,
) -> None:
    service = CommandeService(db)
    commande = await service.get(commande_id)
    if commande is None or not in_scope(commande.boutique_id, scope):  # type: ignore[attr-defined]
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Commande not found")
    await service.soft_delete(commande)
