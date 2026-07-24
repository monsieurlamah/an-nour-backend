"""Business logic for the creances module."""

from collections.abc import Sequence
from datetime import UTC, datetime
from decimal import Decimal

from fastapi import HTTPException, status
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.logging import get_logger
from app.database.enums import (
    CashMovementType,
    CashSessionStatus,
    CreanceStatut,
    NotificationType,
    PaiementMode,
    ReferenceType,
    VenteStatut,
)
from app.modules.cash.models import CashSession
from app.modules.cash.schemas import CashMovementCreate
from app.modules.cash.services import CashMovementService
from app.modules.clients.models import Client
from app.modules.common.crud import CRUDService
from app.modules.creances.models import Creance, Paiement
from app.modules.creances.schemas import CreanceCreate, PaiementCreate
from app.modules.notifications.schemas import NotificationCreate
from app.modules.notifications.services import NotificationService
from app.modules.stores.models import Store
from app.modules.users.models import User
from app.modules.ventes.models import Vente

logger = get_logger("creances")


class CreanceService(CRUDService[Creance]):
    model = Creance

    _READ_FIELDS = (
        "id", "uuid", "status", "created_at", "updated_at",
        "vente_id", "client_id", "boutique_id", "montant_initial",
        "montant_restant", "date_echeance", "statut",
    )

    @staticmethod
    def _to_dict(creance: Creance, client: Client | None, store: Store | None) -> dict:
        return {
            **{k: getattr(creance, k) for k in CreanceService._READ_FIELDS},
            "client_name": (
                f"{client.name} {client.prenom or ''}".strip()
                if client else f"Client #{creance.client_id}"
            ),
            "client_phone": client.phone if client else None,
            "store_name": store.name if store else f"Boutique #{creance.boutique_id}",
        }

    async def enrich(self, creance: Creance) -> dict:
        """Attach client_name/client_phone/store_name for a single créance.
        Looks up the client directly via db.get() rather than ClientService,
        deliberately bypassing the soft-delete filter — a créance must still
        show who owes what even if the client was later deleted."""
        client = await self.db.get(Client, creance.client_id)
        store = await self.db.get(Store, creance.boutique_id)
        return self._to_dict(creance, client, store)

    async def list_enriched(self, **filters) -> list[dict]:
        """Same filters as list(), each row denormalized with client/store
        names in one extra pair of bulk queries (never N+1)."""
        creances = await self.list(**filters)
        client_ids = {c.client_id for c in creances}
        store_ids = {c.boutique_id for c in creances}
        clients: dict[int, Client] = {}
        stores: dict[int, Store] = {}
        if client_ids:
            result = await self.db.execute(select(Client).where(Client.id.in_(client_ids)))
            clients = {c.id: c for c in result.scalars().all()}
        if store_ids:
            result = await self.db.execute(select(Store).where(Store.id.in_(store_ids)))
            stores = {s.id: s for s in result.scalars().all()}

        return [
            self._to_dict(c, clients.get(c.client_id), stores.get(c.boutique_id))
            for c in creances
        ]

    async def create_creance(self, payload: CreanceCreate) -> Creance:
        data = payload.model_dump()
        if data.get("montant_restant") is None:
            data["montant_restant"] = payload.montant_initial
        return await self.create(data)

    async def flag_overdue(self) -> tuple[int, int]:
        """Flip every créance whose échéance has passed (and still has a
        balance) to EN_RETARD, notifying the boutique's gérant and the Boss
        who created it. Meant to be run on a schedule (see
        ``poetry run check-overdue-creances``) — "overdue" is purely a
        function of time passing, not a user action.

        Idempotent by construction: once a créance is EN_RETARD it no longer
        matches the query below, so it's never re-notified on a later run —
        the state transition itself is the one-time trigger, no separate
        dedup log needed (unlike stock alerts, which can re-trigger at the
        same threshold). Returns (overdue_count, notifications_sent)."""
        now = datetime.now(UTC).replace(tzinfo=None)
        result = await self.db.execute(
            select(Creance).where(
                Creance.deleted_at.is_(None),
                Creance.date_echeance.is_not(None),
                Creance.date_echeance < now,
                Creance.montant_restant > 0,
                Creance.statut.in_([CreanceStatut.active, CreanceStatut.partiellement_payee]),
            )
        )
        overdue = result.scalars().all()
        notif_service = NotificationService(self.db)
        notified = 0

        for creance in overdue:
            creance.statut = CreanceStatut.en_retard
            self.db.add(creance)

            client = await self.db.get(Client, creance.client_id)
            store = await self.db.get(Store, creance.boutique_id)
            client_name = (
                f"{client.name} {client.prenom or ''}".strip()
                if client
                else f"Client #{creance.client_id}"
            )
            days_late = (now - creance.date_echeance).days
            montant = f"{Decimal(creance.montant_restant):,.0f}".replace(",", " ")
            title = f"Créance en retard : {client_name}"
            message = f"Solde dû de {montant} GNF, en retard de {days_late} jour(s)."

            recipient_ids: set[int] = set()
            if store and store.gerant_id:
                recipient_ids.add(store.gerant_id)
            if store and store.created_by:
                recipient_ids.add(store.created_by)

            for user_id in recipient_ids:
                try:
                    await notif_service.create(
                        NotificationCreate(
                            user_id=user_id,
                            title=title,
                            message=message,
                            type=NotificationType.creance,
                            link="/app/debts",
                        )
                    )
                    notified += 1
                except Exception:
                    logger.error(
                        "Failed to notify user_id=%s for overdue creance #%s",
                        user_id,
                        creance.id,
                        exc_info=True,
                    )

        await self.db.flush()
        return len(overdue), notified


class PaiementService:
    def __init__(self, db: AsyncSession) -> None:
        self.db = db

    async def get(self, paiement_id: int) -> Paiement | None:
        paiement = await self.db.get(Paiement, paiement_id)
        if paiement is None or paiement.deleted_at is not None:
            return None
        return paiement

    async def list(
        self,
        skip: int = 0,
        limit: int = 100,
        creance_id: int | None = None,
        vente_id: int | None = None,
    ) -> Sequence[Paiement]:
        stmt = select(Paiement).where(Paiement.deleted_at.is_(None))
        if creance_id is not None:
            stmt = stmt.where(Paiement.creance_id == creance_id)
        if vente_id is not None:
            stmt = stmt.where(Paiement.vente_id == vente_id)
        stmt = stmt.order_by(Paiement.id.desc()).offset(skip).limit(limit)
        return (await self.db.execute(stmt)).scalars().all()

    async def _get_open_cash_session(self, store_id: int) -> CashSession:
        """Mirrors VenteService._get_open_cash_session exactly (ventes/services.py) —
        duplicated rather than imported to avoid a circular import (ventes.services
        already imports from creances.services)."""
        result = await self.db.execute(
            select(CashSession)
            .where(
                CashSession.store_id == store_id,
                CashSession.status == CashSessionStatus.ouverte,
            )
            .order_by(CashSession.id.desc())
        )
        cash_session = result.scalars().first()
        if cash_session is None:
            raise HTTPException(
                status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
                detail=(
                    f"Aucune session de caisse ouverte pour la boutique #{store_id} — "
                    "impossible d'encaisser un paiement sans caisse ouverte."
                ),
            )
        return cash_session

    async def create(self, payload: PaiementCreate, user: User | None = None) -> Paiement:
        paiement = Paiement(**payload.model_dump())

        # Resolve which Vente to sync BEFORE flushing the payment — explicit
        # vente_id, or via the créance it settles (covers both the
        # debts-page flow, which only sends creance_id, and a sale-detail
        # "Encaisser le reste" button). Also reflect the payment on the debt.
        # `boutique_id_for_cash` is tracked alongside — resolved from whichever
        # of créance/vente is actually available, for the cash movement below.
        vente_id_to_sync = payload.vente_id
        boutique_id_for_cash: int | None = None
        if payload.creance_id is not None:
            creance = await self.db.get(Creance, payload.creance_id)
            if creance is not None and creance.deleted_at is None:
                boutique_id_for_cash = creance.boutique_id
                remaining = Decimal(creance.montant_restant) - payload.montant
                creance.montant_restant = remaining if remaining > 0 else Decimal("0")
                if creance.montant_restant == 0:
                    creance.statut = CreanceStatut.soldee
                elif creance.montant_restant < creance.montant_initial:
                    creance.statut = CreanceStatut.partiellement_payee
                self.db.add(creance)
                if vente_id_to_sync is None:
                    vente_id_to_sync = creance.vente_id

        # Backfill vente_id on the payment itself when it was only reachable
        # via the créance — otherwise this payment would be invisible to the
        # SUM query below (and to anyone listing payments by vente_id).
        if paiement.vente_id is None and vente_id_to_sync is not None:
            paiement.vente_id = vente_id_to_sync

        self.db.add(paiement)
        # Flushed early so the direct SUM query below (used for the Vente
        # sync) already includes this payment — avoids touching Vente's
        # viewonly `paiements` relationship, whose lazy-load doesn't play
        # well with an async session mid-request.
        await self.db.flush()

        # A Vente's own statut is set once at creation and never otherwise
        # touched — without this, a sale stays "impayée"/"partiellement
        # payée" forever even after its créance is fully settled. Never
        # override a terminal statut unrelated to payment (annulée, a
        # return/refund state) — a payment can't resurrect those.
        if vente_id_to_sync is not None:
            vente = await self.db.get(Vente, vente_id_to_sync)
            if vente is not None and boutique_id_for_cash is None:
                boutique_id_for_cash = vente.boutique_id
            if vente is not None and vente.deleted_at is None and vente.statut in (
                VenteStatut.impayee, VenteStatut.partiellement_payee, VenteStatut.completee,
            ):
                total_paye_row = await self.db.execute(
                    select(func.coalesce(func.sum(Paiement.montant), 0)).where(
                        Paiement.vente_id == vente_id_to_sync, Paiement.deleted_at.is_(None)
                    )
                )
                total_paye = Decimal(total_paye_row.scalar_one())
                if total_paye >= vente.montant_total:
                    new_statut = VenteStatut.completee
                elif total_paye > 0:
                    new_statut = VenteStatut.partiellement_payee
                else:
                    new_statut = VenteStatut.impayee
                if new_statut != vente.statut:
                    vente.statut = new_statut
                    self.db.add(vente)
                    await self.db.flush()
                    # `updated_at` has a DB-side `onupdate=func.now()` — after
                    # an UPDATE, SQLAlchemy can't know the new value without
                    # asking, so it marks the column expired. Whoever ends up
                    # with this same Vente instance later (e.g. the router
                    # returning it straight from VenteService.create, still
                    # within the same request) would otherwise trigger a
                    # lazy load at response-serialization time, which fails
                    # under Starlette's BaseHTTPMiddleware (no greenlet
                    # context there). Refresh eagerly, right here, instead.
                    await self.db.refresh(vente)

        # ── Cash movement for a créance settlement paid in cash ─────────────
        # Only when `user` is passed — i.e. this call represents an actual
        # créance/vente-balance settlement made through the créance-payments
        # endpoint. Never when called from VenteService.create for a
        # brand-new sale's own payments (no `user` passed there): that flow
        # already creates its own cash movement (ventes/services.py, step 7)
        # and this would double it. Same pattern as
        # ventes/services.py:356-377, including the explicit failure when no
        # cash session is open — never silent.
        if user is not None and payload.mode == PaiementMode.especes:
            if boutique_id_for_cash is None:
                raise HTTPException(
                    status.HTTP_422_UNPROCESSABLE_ENTITY,
                    "Impossible de déterminer la boutique de ce règlement de créance.",
                )
            cash_session = await self._get_open_cash_session(boutique_id_for_cash)
            await CashMovementService(self.db).create(
                CashMovementCreate(
                    cash_session_id=cash_session.id,
                    type=CashMovementType.entree,
                    amount=payload.montant,
                    reason=f"Règlement créance — paiement #{paiement.id}",
                    reference_type=ReferenceType.PAIEMENT,
                    reference_id=paiement.id,
                ),
                user,
            )

        await self.db.flush()
        await self.db.refresh(paiement)
        return paiement
