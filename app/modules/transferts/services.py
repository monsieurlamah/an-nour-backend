"""Business logic for the transferts module — cahier des charges §7.4/§12.

The whole cycle in two service calls (see TransfertStatut's docstring for
why there's no separate "brouillon"/"expédier" step):

  create()  — validates + decrements the SOURCE boutique's stock immediately
              (§7.4 step 1-2), statut = en_transit.
  receive() — the DESTINATION boutique confirms actual quantities received
              (§7.4 step 3), credits its own stock with exactly those
              quantities, and records any écart (step 4) — statut becomes
              receptionne or receptionne_avec_ecart depending on whether
              every line matched exactly.
  cancel()  — only while still en_transit (before any réception): reverses
              the source decrement and closes the dossier out.

Every step also writes a StockMovement (reason=TRANSFERT — §7.3's "tout
mouvement de stock... avec l'utilisateur à l'origine") and a central
ActivityLog entry (§14) via TransfertService._log.
"""
from __future__ import annotations

from collections.abc import Sequence

from fastapi import HTTPException, status
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.logging import get_logger
from app.database.enums import MovementReason, NotificationType, ReferenceType, TransfertStatut
from app.modules.catalog.models import Product
from app.modules.notifications.schemas import NotificationCreate
from app.modules.notifications.services import NotificationService
from app.modules.stock.models import StockLocation
from app.modules.stock.services import StockSaleService
from app.modules.stores.models import Store
from app.modules.system.services import log_activity
from app.modules.transferts.models import Transfert, TransfertLigne
from app.modules.transferts.schemas import TransfertCancel, TransfertCreate, TransfertReceive
from app.modules.users.models import User
from app.utils.helpers import utcnow

logger = get_logger("transferts")

_PRINCIPALE_LABEL = "Boutique principale (AN-NOUR — Direction Générale)"


class TransfertService:
    def __init__(self, db: AsyncSession) -> None:
        self.db = db
        self.stock = StockSaleService(db)

    # ── Read ─────────────────────────────────────────────────────────────────

    async def get(self, transfert_id: int) -> Transfert | None:
        transfert = await self.db.get(Transfert, transfert_id)
        if transfert is None or transfert.deleted_at is not None:
            return None
        return transfert

    async def list(
        self,
        skip: int = 0,
        limit: int = 100,
        boutique_id: int | list[int] | None = None,
        statut: TransfertStatut | None = None,
    ) -> Sequence[Transfert]:
        stmt = select(Transfert).where(Transfert.deleted_at.is_(None))
        if isinstance(boutique_id, (list, set, frozenset)):
            stmt = stmt.where(
                (Transfert.boutique_source_id.in_(boutique_id))
                | (Transfert.boutique_destination_id.in_(boutique_id))
            )
        elif boutique_id is not None:
            stmt = stmt.where(
                (Transfert.boutique_source_id == boutique_id)
                | (Transfert.boutique_destination_id == boutique_id)
            )
        if statut is not None:
            stmt = stmt.where(Transfert.statut == statut)
        stmt = stmt.order_by(Transfert.id.desc()).offset(skip).limit(limit)
        return (await self.db.execute(stmt)).scalars().all()

    async def enrich(self, transfert: Transfert) -> dict:
        source = (
            await self.db.get(Store, transfert.boutique_source_id)
            if transfert.boutique_source_id
            else None
        )
        dest = (
            await self.db.get(Store, transfert.boutique_destination_id)
            if transfert.boutique_destination_id
            else None
        )
        return {
            "id": transfert.id, "uuid": transfert.uuid, "status": transfert.status,
            "created_at": transfert.created_at, "updated_at": transfert.updated_at,
            "boutique_source_id": transfert.boutique_source_id,
            "boutique_destination_id": transfert.boutique_destination_id,
            "created_by": transfert.created_by,
            "receptionne_par": transfert.receptionne_par,
            "annule_par": transfert.annule_par,
            "numero": transfert.numero, "statut": transfert.statut,
            "motif": transfert.motif, "annule_motif": transfert.annule_motif,
            "expedie_at": transfert.expedie_at, "receptionne_at": transfert.receptionne_at,
            "annule_at": transfert.annule_at,
            "lignes": transfert.lignes,
            "boutique_source_name": source.name if source else _PRINCIPALE_LABEL,
            "boutique_destination_name": dest.name if dest else _PRINCIPALE_LABEL,
        }

    async def list_enriched(self, **filters) -> list[dict]:
        transferts = await self.list(**filters)
        return [await self.enrich(t) for t in transferts]

    # ── Helpers ──────────────────────────────────────────────────────────────

    async def _resolve_location(self, boutique_id: int | None) -> StockLocation:
        if boutique_id is None:
            return await self.stock.get_central_location()
        return await self.stock.get_store_location(boutique_id)

    async def _log(
        self, transfert: Transfert, user_id: int | None, action: str, boutique_id: int | None
    ) -> None:
        await log_activity(
            self.db, user_id, f"{action} — {transfert.numero}", "transferts",
            reference_type=ReferenceType.TRANSFERT, reference_id=transfert.id,
            boutique_id=boutique_id,
        )

    # ── Create (= expédier immédiatement, §7.4 étapes 1-2) ──────────────────

    async def create(self, payload: TransfertCreate, user: User) -> Transfert:
        source_id = None if payload.source_est_principale else payload.boutique_source_id
        dest_id = None if payload.destination_est_principale else payload.boutique_destination_id

        source_location = await self._resolve_location(source_id)
        await self._resolve_location(dest_id)  # 404s early if the destination is misconfigured

        # Fail fast on any missing product / insufficient stock BEFORE
        # mutating anything — same discipline as VenteService.create.
        products: dict[int, Product] = {}
        for line in payload.lignes:
            product = await self.db.get(Product, line.produit_id)
            if product is None or product.deleted_at is not None:
                raise HTTPException(
                    status.HTTP_422_UNPROCESSABLE_ENTITY,
                    f"Produit #{line.produit_id} introuvable.",
                )
            products[line.produit_id] = product
            await self.stock.check_available(line.produit_id, source_location.id, line.quantite)

        transfert = Transfert(
            boutique_source_id=source_id,
            boutique_destination_id=dest_id,
            created_by=user.id,
            statut=TransfertStatut.en_transit,
            motif=payload.motif,
            expedie_at=utcnow(),
        )
        for line in payload.lignes:
            transfert.lignes.append(
                TransfertLigne(produit_id=line.produit_id, quantite_envoyee=line.quantite)
            )
        self.db.add(transfert)
        await self.db.flush()
        await self.db.refresh(transfert)

        transfert.numero = f"TRF-{utcnow().year}-{transfert.id:06d}"
        self.db.add(transfert)

        # Decrement the source now — §7.4 step 2's stated default ("diminue
        # immédiatement... statut « en transit »").
        for line in payload.lignes:
            await self.stock.consume(
                product_id=line.produit_id,
                location_id=source_location.id,
                quantity=line.quantite,
                reference=None,  # filled in below once numero exists
                created_by=user.id,
                reason=MovementReason.TRANSFERT,
            )
        await self.db.flush()
        await self.db.refresh(transfert)

        await self._log(
            transfert, user.id, "Transfert créé et expédié",
            boutique_id=source_id if source_id is not None else dest_id,
        )

        # §19 — "Transfert de marchandise en attente de confirmation de
        # réception" — notify the destination's gérant.
        if dest_id is not None:
            dest_store = await self.db.get(Store, dest_id)
            if dest_store and dest_store.gerant_id:
                try:
                    await NotificationService(self.db).create(
                        NotificationCreate(
                            user_id=dest_store.gerant_id,
                            title=f"Transfert en attente — {transfert.numero}",
                            message=(
                                f"Un transfert de {len(payload.lignes)} article(s) "
                                "est en route vers votre boutique."
                            ),
                            type=NotificationType.stock,
                            link=f"/app/transfers/{transfert.id}",
                        )
                    )
                except Exception:
                    logger.error(
                        "Failed to notify gérant of incoming transfert #%s", transfert.id,
                        exc_info=True,
                    )

        logger.info(
            "transfert.create.done id=%s numero=%s source=%s dest=%s",
            transfert.id, transfert.numero, source_id, dest_id,
        )
        return transfert

    # ── Receive (§7.4 étapes 3-4) ────────────────────────────────────────────

    async def receive(
        self, transfert: Transfert, payload: TransfertReceive, user: User
    ) -> Transfert:
        if transfert.statut != TransfertStatut.en_transit:
            raise HTTPException(
                status.HTTP_409_CONFLICT,
                f"Le transfert {transfert.numero} n'est plus en transit "
                f"(statut '{transfert.statut.value}').",
            )
        lignes_by_id = {lg.id: lg for lg in transfert.lignes}
        received = {rl.ligne_id: rl for rl in payload.lignes}
        missing = set(lignes_by_id) - set(received)
        if missing:
            raise HTTPException(
                status.HTTP_422_UNPROCESSABLE_ENTITY,
                "Chaque ligne du transfert doit être réceptionnée (même à 0).",
            )
        unknown = set(received) - set(lignes_by_id)
        if unknown:
            raise HTTPException(
                status.HTTP_422_UNPROCESSABLE_ENTITY,
                f"Ligne(s) inconnue(s) pour ce transfert : {sorted(unknown)}.",
            )

        dest_location = await self._resolve_location(transfert.boutique_destination_id)

        has_ecart = False
        for ligne_id, rl in received.items():
            ligne = lignes_by_id[ligne_id]
            ligne.quantite_recue = rl.quantite_recue
            ligne.observation = rl.observation
            self.db.add(ligne)
            if rl.quantite_recue != ligne.quantite_envoyee:
                has_ecart = True
            if rl.quantite_recue > 0:
                await self.stock.restore(
                    product_id=ligne.produit_id,
                    location_id=dest_location.id,
                    quantity=rl.quantite_recue,
                    reference=transfert.numero,
                    created_by=user.id,
                    reason=MovementReason.TRANSFERT,
                )

        transfert.statut = (
            TransfertStatut.receptionne_avec_ecart if has_ecart else TransfertStatut.receptionne
        )
        transfert.receptionne_par = user.id
        transfert.receptionne_at = utcnow()
        self.db.add(transfert)
        await self.db.flush()
        await self.db.refresh(transfert)

        await self._log(
            transfert,
            user.id,
            "Transfert réceptionné avec écart" if has_ecart else "Transfert réceptionné",
            boutique_id=transfert.boutique_destination_id or transfert.boutique_source_id,
        )

        # §19 — "Écart de réception constaté" -> notify the source's gérant
        # (the boutique principale, i.e. the propriétaire, already sees
        # everything via the consolidated dashboard/journal).
        if has_ecart and transfert.boutique_source_id is not None:
            source_store = await self.db.get(Store, transfert.boutique_source_id)
            if source_store and source_store.gerant_id:
                try:
                    await NotificationService(self.db).create(
                        NotificationCreate(
                            user_id=source_store.gerant_id,
                            title=f"Écart de réception — {transfert.numero}",
                            message="La boutique destinataire a signalé un écart de quantité.",
                            type=NotificationType.stock,
                            link=f"/app/transfers/{transfert.id}",
                        )
                    )
                except Exception:
                    logger.error(
                        "Failed to notify gérant of transfert écart #%s", transfert.id,
                        exc_info=True,
                    )

        logger.info(
            "transfert.receive.done id=%s numero=%s has_ecart=%s",
            transfert.id, transfert.numero, has_ecart,
        )
        return transfert

    # ── Cancel (only before réception) ──────────────────────────────────────

    async def cancel(self, transfert: Transfert, payload: TransfertCancel, user: User) -> Transfert:
        if transfert.statut != TransfertStatut.en_transit:
            raise HTTPException(
                status.HTTP_409_CONFLICT,
                f"Seul un transfert encore en transit peut être annulé "
                f"(statut actuel : '{transfert.statut.value}').",
            )
        source_location = await self._resolve_location(transfert.boutique_source_id)
        for ligne in transfert.lignes:
            await self.stock.restore(
                product_id=ligne.produit_id,
                location_id=source_location.id,
                quantity=ligne.quantite_envoyee,
                reference=transfert.numero,
                created_by=user.id,
                reason=MovementReason.TRANSFERT,
            )
        transfert.statut = TransfertStatut.annule
        transfert.annule_par = user.id
        transfert.annule_at = utcnow()
        transfert.annule_motif = payload.motif
        self.db.add(transfert)
        await self.db.flush()
        await self.db.refresh(transfert)

        await self._log(
            transfert, user.id, f"Transfert annulé ({payload.motif})",
            boutique_id=transfert.boutique_source_id or transfert.boutique_destination_id,
        )
        logger.info("transfert.cancel.done id=%s numero=%s", transfert.id, transfert.numero)
        return transfert

    async def soft_delete(self, transfert: Transfert) -> None:
        transfert.deleted_at = utcnow()
        self.db.add(transfert)
        await self.db.flush()
