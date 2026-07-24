"""Business logic for the ventes module.

``VenteService.create`` is the transactional engine of the ERP: a single sale
triggers stock consumption, payment recording, automatic debt (créance)
creation and cash-register movements — all within the one DB transaction
already managed by ``app.database.session.get_db`` (commit on success,
rollback on any exception, no partial writes possible).
"""

from collections.abc import Sequence
from datetime import date, timedelta
from decimal import Decimal

from fastapi import HTTPException, status
from sqlalchemy import String, cast, func, or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.logging import get_logger
from app.database.enums import (
    CashMovementType,
    CashSessionStatus,
    CreanceStatut,
    ReferenceType,
    VenteLivraisonStatut,
    VenteStatut,
    VenteType,
)
from app.modules.cash.models import CashSession
from app.modules.cash.schemas import CashMovementCreate
from app.modules.cash.services import CashMovementService
from app.modules.creances.schemas import CreanceCreate, PaiementCreate
from app.modules.creances.services import CreanceService, PaiementService
from app.modules.stock.services import StockSaleService
from app.modules.stores.models import Store
from app.modules.users.models import User
from app.modules.ventes.models import (
    Vente,
    VenteLigne,
    VenteRemboursement,
    VenteRetour,
    VenteRetourLigne,
)
from app.modules.ventes.schemas import VenteCreate, VenteRemboursementCreate, VenteRetourCreate
from app.utils.helpers import utcnow

logger = get_logger("ventes.service")


class VenteService:
    def __init__(self, db: AsyncSession) -> None:
        self.db = db

    async def get(self, vente_id: int) -> Vente | None:
        vente = await self.db.get(Vente, vente_id)
        if vente is None or vente.deleted_at is not None:
            return None
        return vente

    def _apply_filters(
        self,
        stmt: object,
        boutique_id: int | None,
        client_id: int | None,
        vendeur_id: int | None,
        statut: VenteStatut | None,
        type_vente: VenteType | None,
        search: str | None,
        date_debut: date | None,
        date_fin: date | None,
    ) -> object:
        """Shared filter logic — used by both list() and count()."""
        from app.modules.clients.models import Client  # local to avoid circular

        stmt = stmt.where(Vente.deleted_at.is_(None))
        if boutique_id is not None:
            stmt = stmt.where(Vente.boutique_id == boutique_id)
        if client_id is not None:
            stmt = stmt.where(Vente.client_id == client_id)
        if vendeur_id is not None:
            stmt = stmt.where(Vente.vendeur_id == vendeur_id)
        if statut is not None:
            stmt = stmt.where(Vente.statut == statut)
        if type_vente is not None:
            stmt = stmt.where(Vente.type_vente == type_vente)
        if date_debut is not None:
            stmt = stmt.where(Vente.created_at >= date_debut)
        if date_fin is not None:
            stmt = stmt.where(Vente.created_at < date_fin + timedelta(days=1))
        if search is not None and search.strip():
            needle = search.strip()
            stmt = stmt.outerjoin(Client, Vente.client_id == Client.id).where(
                or_(
                    cast(Vente.id, String).contains(needle),
                    Client.name.ilike(f"%{needle}%"),
                    Client.prenom.ilike(f"%{needle}%"),
                )
            )
        return stmt

    async def list(
        self,
        skip: int = 0,
        limit: int = 100,
        boutique_id: int | None = None,
        client_id: int | None = None,
        vendeur_id: int | None = None,
        statut: VenteStatut | None = None,
        type_vente: VenteType | None = None,
        search: str | None = None,
        date_debut: date | None = None,
        date_fin: date | None = None,
    ) -> Sequence[Vente]:
        stmt = self._apply_filters(
            select(Vente), boutique_id, client_id, vendeur_id,
            statut, type_vente, search, date_debut, date_fin,
        )
        stmt = stmt.order_by(Vente.id.desc()).offset(skip).limit(limit)
        return (await self.db.execute(stmt)).scalars().all()

    async def count(
        self,
        boutique_id: int | None = None,
        client_id: int | None = None,
        vendeur_id: int | None = None,
        statut: VenteStatut | None = None,
        type_vente: VenteType | None = None,
        search: str | None = None,
        date_debut: date | None = None,
        date_fin: date | None = None,
    ) -> int:
        stmt = self._apply_filters(
            select(func.count(Vente.id)), boutique_id, client_id, vendeur_id,
            statut, type_vente, search, date_debut, date_fin,
        )
        result = (await self.db.execute(stmt)).scalar_one()
        return int(result)

    # ── Enriched list (Boss overview) ───────────────────────────────────────
    # Denormalizes store_name on each row in one extra bulk query — the Boss
    # must see which boutique made a sale without a second lookup per row.
    # Only the list endpoint enriches; get/create/void return the raw ORM
    # object as before (store_name stays unset there — the sale-detail page
    # already resolves the store name itself via a separate storesApi.get()).
    _READ_FIELDS = (
        "id", "uuid", "status", "created_at", "updated_at",
        "boutique_id", "vendeur_id", "client_id", "type_vente",
        "montant_total", "remise", "statut", "montant_paye", "montant_restant",
        "livraison_statut", "numero_bon_livraison", "livree_at", "livree_by",
        "lignes", "paiements", "creance",
    )

    @staticmethod
    def _to_dict(vente: Vente, store: Store | None) -> dict:
        return {
            **{k: getattr(vente, k) for k in VenteService._READ_FIELDS},
            "store_name": store.name if store else f"Boutique #{vente.boutique_id}",
        }

    async def list_enriched(self, **filters) -> list[dict]:
        ventes = await self.list(**filters)
        ids = {v.boutique_id for v in ventes}
        stores: dict[int, Store] = {}
        if ids:
            result = await self.db.execute(select(Store).where(Store.id.in_(ids)))
            stores = {s.id: s for s in result.scalars().all()}
        return [self._to_dict(v, stores.get(v.boutique_id)) for v in ventes]

    # ── Helpers ───────────────────────────────────────────────────────────────

    @staticmethod
    def _resolve_statut(montant_paye: Decimal, montant_total: Decimal) -> VenteStatut:
        if montant_total <= 0 or montant_paye >= montant_total:
            return VenteStatut.completee
        if montant_paye <= 0:
            return VenteStatut.impayee
        return VenteStatut.partiellement_payee

    async def _get_open_cash_session(self, store_id: int) -> CashSession:
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

    # ── Create: the transactional engine ─────────────────────────────────────

    async def create(self, payload: VenteCreate, user: User) -> Vente:
        logger.info(
            "vente.create.start boutique_id=%s client_id=%s lignes=%d paiements=%d",
            payload.boutique_id, payload.client_id, len(payload.lignes), len(payload.paiements),
        )

        # ── 1. Validation ────────────────────────────────────────────────────
        if not payload.lignes:
            raise HTTPException(
                status.HTTP_422_UNPROCESSABLE_ENTITY, "Une vente doit contenir au moins une ligne."
            )

        subtotal = Decimal("0")
        line_totals: list[Decimal] = []
        for line in payload.lignes:
            line_total = Decimal(line.quantite) * line.prix_unitaire - line.remise
            if line_total < 0:
                line_total = Decimal("0")
            line_totals.append(line_total)
            subtotal += line_total

        montant_total = subtotal - payload.remise
        if montant_total < 0:
            montant_total = Decimal("0")

        montant_paye = sum((p.montant for p in payload.paiements), Decimal("0"))
        if montant_paye > montant_total:
            raise HTTPException(
                status.HTTP_422_UNPROCESSABLE_ENTITY,
                f"Le total des paiements ({montant_paye}) dépasse le montant de la vente "
                f"({montant_total}).",
            )

        montant_restant = montant_total - montant_paye

        if montant_restant > 0 and payload.client_id is None:
            raise HTTPException(
                status.HTTP_422_UNPROCESSABLE_ENTITY,
                "Un client est obligatoire pour une vente avec un solde restant (crédit).",
            )

        logger.info(
            "vente.create.validated montant_total=%s montant_paye=%s montant_restant=%s",
            montant_total, montant_paye, montant_restant,
        )

        # ── 2. Stock control (read-only — fail fast before mutating anything) ─
        # Availability is always checked, even for a deferred (non_livre) sale
        # — selling something the boutique doesn't physically have at all is
        # never valid, regardless of when it leaves. Only the actual
        # decrement (step 4) is conditional on livraison_statut.
        stock_service = StockSaleService(self.db)
        location = await stock_service.get_store_location(payload.boutique_id)
        for line in payload.lignes:
            await stock_service.check_available(line.produit_id, location.id, line.quantite)

        logger.info("vente.create.stock_checked boutique_id=%s", payload.boutique_id)

        # ── 3. Create Vente + VenteLignes ──────────────────────────────────────
        statut = self._resolve_statut(montant_paye, montant_total)
        is_delivered_now = payload.livraison_statut == VenteLivraisonStatut.livre
        vente = Vente(
            boutique_id=payload.boutique_id,
            vendeur_id=user.id,
            client_id=payload.client_id,
            type_vente=payload.type_vente,
            remise=payload.remise,
            statut=statut,
            montant_total=montant_total,
            livraison_statut=payload.livraison_statut,
        )
        for line, line_total in zip(payload.lignes, line_totals, strict=True):
            vente.lignes.append(
                VenteLigne(
                    produit_id=line.produit_id,
                    quantite=line.quantite,
                    prix_unitaire=line.prix_unitaire,
                    remise=line.remise,
                    total_ligne=line_total,
                )
            )
        self.db.add(vente)
        await self.db.flush()
        await self.db.refresh(vente)

        if is_delivered_now:
            vente.numero_bon_livraison = f"BL-{utcnow().year}-{vente.id:06d}"
            vente.livree_at = utcnow()
            vente.livree_by = user.id
            self.db.add(vente)
            await self.db.flush()
            # `updated_at` has a DB-side `onupdate=func.now()` — after this
            # UPDATE, SQLAlchemy can't know the new value without asking, so
            # it marks the column expired. The later
            # `refresh(attribute_names=["paiements", "creance"])` below only
            # reloads THOSE two relationships (a separate query against their
            # own tables), never touching `ventes` — so it never clears this
            # expiry. Left alone, that lazy-load only fires once something
            # accesses `.updated_at` again, which ends up being Pydantic
            # during response serialization — outside FastAPI/Starlette's
            # async-safe (greenlet) context, causing a hard 500. Refresh
            # eagerly, right here, instead.
            await self.db.refresh(vente)

        logger.info(
            "vente.create.vente_created vente_id=%s statut=%s livraison_statut=%s",
            vente.id, vente.statut, vente.livraison_statut,
        )

        # ── 4. Decrement stock + StockMovement (SALE/OUT) per line ────────────
        # Skipped entirely for a non_livre sale — the goods haven't left yet,
        # see VenteService.confirm_livraison for when this actually happens.
        if is_delivered_now:
            for line in payload.lignes:
                await stock_service.consume(
                    product_id=line.produit_id,
                    location_id=location.id,
                    quantity=line.quantite,
                    reference=f"VENTE-{vente.id}",
                    created_by=user.id,
                )
            logger.info("vente.create.stock_consumed vente_id=%s", vente.id)
        else:
            logger.info("vente.create.stock_deferred vente_id=%s (non_livre)", vente.id)

        # ── 5. Paiements (only the amounts actually received) ──────────────────
        paiement_service = PaiementService(self.db)
        for p in payload.paiements:
            await paiement_service.create(
                PaiementCreate(
                    vente_id=vente.id, montant=p.montant, mode=p.mode, reference=p.reference
                )
            )

        logger.info(
            "vente.create.paiements_created vente_id=%s count=%d", vente.id, len(payload.paiements)
        )

        # ── 6. Automatic Creance for the unpaid remainder, if any ──────────────
        # Rule: a Creance is NEVER created directly by a client — only ever as a
        # side effect of a sale whose payments don't cover the full total.
        if montant_restant > 0:
            await CreanceService(self.db).create_creance(
                CreanceCreate(
                    client_id=payload.client_id,  # required + validated above
                    boutique_id=payload.boutique_id,
                    vente_id=vente.id,
                    montant_initial=montant_restant,
                )
            )
            logger.info(
                "vente.create.creance_created vente_id=%s montant=%s", vente.id, montant_restant
            )
        else:
            logger.info("vente.create.no_creance vente_id=%s", vente.id)

        # ── 7. Cash movements — one per payment, never for the unpaid part ─────
        if payload.paiements:
            cash_session = await self._get_open_cash_session(payload.boutique_id)
            cash_service = CashMovementService(self.db)
            for p in payload.paiements:
                await cash_service.create(
                    CashMovementCreate(
                        cash_session_id=cash_session.id,
                        type=CashMovementType.entree,
                        amount=p.montant,
                        reason=f"Vente #{vente.id}",
                        reference_type=ReferenceType.VENTE,
                        reference_id=vente.id,
                    ),
                    user,
                )
            logger.info(
                "vente.create.cash_movements_created vente_id=%s count=%d",
                vente.id, len(payload.paiements),
            )
        else:
            logger.info("vente.create.no_cash_movement vente_id=%s (no payments)", vente.id)

        # ── 8. Reload computed relations for the response ──────────────────────
        await self.db.refresh(vente, attribute_names=["paiements", "creance"])

        logger.info(
            "vente.create.ready_to_commit vente_id=%s statut=%s montant_total=%s",
            vente.id, vente.statut, vente.montant_total,
        )
        return vente

    # ── Delivery (deferred at sale time) ──────────────────────────────────────

    async def confirm_livraison(self, vente: Vente, user: User) -> Vente:
        """The customer collects the goods for a sale that was rung up as
        non_livre — the only place stock actually moves for such a sale.
        Entirely orthogonal to payment: a créance/partial payment is neither
        required nor resolved by this call."""
        if vente.livraison_statut != VenteLivraisonStatut.non_livre:
            raise HTTPException(
                status.HTTP_409_CONFLICT,
                f"La vente #{vente.id} est déjà livrée ou n'est pas en attente de livraison.",
            )
        if vente.statut == VenteStatut.annulee:
            raise HTTPException(
                status.HTTP_422_UNPROCESSABLE_ENTITY,
                "Impossible de livrer une vente annulée.",
            )

        stock_service = StockSaleService(self.db)
        location = await stock_service.get_store_location(vente.boutique_id)
        for ligne in vente.lignes:
            await stock_service.check_available(ligne.produit_id, location.id, ligne.quantite)
        for ligne in vente.lignes:
            await stock_service.consume(
                product_id=ligne.produit_id,
                location_id=location.id,
                quantity=ligne.quantite,
                reference=f"VENTE-{vente.id}",
                created_by=user.id,
            )

        vente.livraison_statut = VenteLivraisonStatut.livre
        vente.numero_bon_livraison = f"BL-{utcnow().year}-{vente.id:06d}"
        vente.livree_at = utcnow()
        vente.livree_by = user.id
        self.db.add(vente)
        await self.db.flush()
        await self.db.refresh(vente)
        logger.info("vente.confirm_livraison.done vente_id=%s", vente.id)
        return vente

    # ── Void / cancel ─────────────────────────────────────────────────────────

    async def void(self, vente: Vente, user: User | None = None) -> Vente:
        """Annuler une vente : status → annulee + stock inversé (si déjà
        livrée) + créance annulée.

        Completes every TODO that Phase 1 deliberately deferred. The actual
        cash refund (sortie) is NOT created here — that is a deliberate
        decision: the cashier records a separate VenteRemboursement if money
        must be returned to the client. Cancellation ≠ refund in this ERP.
        """
        logger.info("vente.void.start vente_id=%s previous_statut=%s", vente.id, vente.statut)
        if vente.statut == VenteStatut.annulee:
            raise HTTPException(
                status.HTTP_422_UNPROCESSABLE_ENTITY, "Cette vente est déjà annulée."
            )

        # Stock only ever left the boutique if the sale was actually
        # delivered — a non_livre sale never consumed anything, so voiding it
        # must NOT restore stock that was never taken (that would inflate it).
        if vente.livraison_statut == VenteLivraisonStatut.livre:
            stock_service = StockSaleService(self.db)
            location = await stock_service.get_store_location(vente.boutique_id)
            for ligne in vente.lignes:
                await stock_service.restore(
                    product_id=ligne.produit_id,
                    location_id=location.id,
                    quantity=ligne.quantite,
                    reference=f"VENTE-{vente.id}",
                    created_by=user.id if user else None,
                )

        # 2. Cancel the linked créance (if any, and if not already settled)
        if vente.creance and vente.creance.statut not in (
            CreanceStatut.soldee, CreanceStatut.annulee
        ):
            vente.creance.statut = CreanceStatut.annulee
            vente.creance.montant_restant = 0
            self.db.add(vente.creance)

        # 3. Flip status
        vente.statut = VenteStatut.annulee
        self.db.add(vente)
        await self.db.flush()
        await self.db.refresh(vente)
        logger.info("vente.void.done vente_id=%s stock_reversed=True", vente.id)
        return vente

    async def soft_delete(self, vente: Vente) -> None:
        vente.deleted_at = utcnow()
        self.db.add(vente)
        await self.db.flush()


# ── Return service ────────────────────────────────────────────────────────────

class VenteRetourService:
    """Handles partial or total product returns for a given sale.

    For each returned line:
    - validates the requested quantity ≤ originally sold quantity
    - calls StockSaleService.restore() to re-increment stock
    - creates a VenteRetourLigne linked to the VenteRetour header
    - updates the vente.statut (partiellement_retournee / retournee)
    - adjusts the linked créance if applicable
    """

    def __init__(self, db: AsyncSession) -> None:
        self.db = db

    async def list(self, vente_id: int) -> list[VenteRetour]:
        from sqlalchemy import select as sa_select
        result = await self.db.execute(
            sa_select(VenteRetour)
            .where(VenteRetour.vente_id == vente_id, VenteRetour.deleted_at.is_(None))
            .order_by(VenteRetour.id.desc())
        )
        return list(result.scalars().all())

    async def create(self, vente: Vente, payload: VenteRetourCreate, user: User) -> VenteRetour:
        logger.info(
            "vente_retour.create.start vente_id=%s lignes=%d", vente.id, len(payload.lignes)
        )
        if vente.statut == VenteStatut.annulee:
            raise HTTPException(
                status.HTTP_422_UNPROCESSABLE_ENTITY,
                "Impossible de retourner une vente annulée.",
            )
        if vente.livraison_statut == VenteLivraisonStatut.non_livre:
            raise HTTPException(
                status.HTTP_422_UNPROCESSABLE_ENTITY,
                "Impossible de retourner une vente qui n'a pas encore été livrée.",
            )

        # Index original lines by id for validation
        original_by_id = {lg.id: lg for lg in vente.lignes}
        retour_lines_data = []
        for rl in payload.lignes:
            orig = original_by_id.get(rl.vente_ligne_id)
            if orig is None:
                raise HTTPException(
                    status.HTTP_422_UNPROCESSABLE_ENTITY,
                    f"La ligne #{rl.vente_ligne_id} n'appartient pas à cette vente.",
                )
            if rl.quantite > orig.quantite:
                raise HTTPException(
                    status.HTTP_422_UNPROCESSABLE_ENTITY,
                    f"Qté retournée ({rl.quantite}) > vendue ({orig.quantite})"
                    f" ligne #{rl.vente_ligne_id}.",
                )
            retour_lines_data.append((rl, orig))

        # Restore stock + build ligne objects
        stock_service = StockSaleService(self.db)
        location = await stock_service.get_store_location(vente.boutique_id)
        retour_lignes: list[VenteRetourLigne] = []
        total_retourne = Decimal("0")
        for rl, orig in retour_lines_data:
            await stock_service.restore(
                product_id=orig.produit_id,
                location_id=location.id,
                quantity=rl.quantite,
                reference=f"VENTE-{vente.id}",
                created_by=user.id,
            )
            # Prorate the line's discount into a net unit price so the return
            # restitutes exactly what the client paid per unit, never the
            # pre-remise gross price.
            net_unit_price = orig.total_ligne / Decimal(orig.quantite)
            line_total = net_unit_price * rl.quantite
            total_retourne += line_total
            retour_lignes.append(VenteRetourLigne(
                vente_ligne_id=orig.id,
                produit_id=orig.produit_id,
                quantite=rl.quantite,
                prix_unitaire=net_unit_price,
                total_ligne=line_total,
            ))

        # Create the VenteRetour header
        retour = VenteRetour(
            vente_id=vente.id,
            vendeur_id=user.id,
            motif=payload.motif,
            notes=payload.notes,
            total_retourne=total_retourne,
            lignes=retour_lignes,
        )
        self.db.add(retour)
        await self.db.flush()  # flush so the new retour_lignes are visible to queries below

        # Determine all_returned by querying the CUMULATIVE quantities across every
        # VenteRetour for this vente (including the one just flushed).
        # `select` and `func` are already imported at module level.
        cumul_rows = (await self.db.execute(
            select(VenteRetourLigne.vente_ligne_id, func.sum(VenteRetourLigne.quantite))
            .join(VenteRetour, VenteRetour.id == VenteRetourLigne.retour_id)
            .where(VenteRetour.vente_id == vente.id, VenteRetour.deleted_at.is_(None))
            .group_by(VenteRetourLigne.vente_ligne_id)
        )).all()
        returned_by_ligne = {ligne_id: qty for ligne_id, qty in cumul_rows}
        all_returned = all(
            returned_by_ligne.get(lg.id, 0) >= lg.quantite
            for lg in vente.lignes
        )

        vente.statut = (
            VenteStatut.retournee if all_returned else VenteStatut.partiellement_retournee
        )
        self.db.add(vente)

        # Cancel / reduce créance if applicable
        if vente.creance and vente.creance.statut not in (
            CreanceStatut.soldee, CreanceStatut.annulee
        ):
            if all_returned:
                # Total return: cancel the créance entirely (it's a cancellation, not a payment)
                vente.creance.statut = CreanceStatut.annulee
                vente.creance.montant_restant = Decimal("0")
            else:
                reduction = min(total_retourne, vente.creance.montant_restant)
                nouveau = max(Decimal("0"), vente.creance.montant_restant - reduction)
                vente.creance.montant_restant = nouveau
                # Partial return zeroing out créance → also cancelled, not paid
                if vente.creance.montant_restant == Decimal("0"):
                    vente.creance.statut = CreanceStatut.annulee
            self.db.add(vente.creance)

        await self.db.flush()
        await self.db.refresh(retour)
        logger.info("vente_retour.create.done retour_id=%s total=%s", retour.id, total_retourne)
        return retour


# ── Refund service ────────────────────────────────────────────────────────────

class VenteRemboursementService:
    """Records a cash refund for a sale and creates the matching cash outflow.

    A refund is independent from a return: it can exist with or without a
    linked VenteRetour. Each refund triggers a CashMovement (sortie) on the
    store's currently open session.
    """

    def __init__(self, db: AsyncSession) -> None:
        self.db = db

    async def list(self, vente_id: int) -> list[VenteRemboursement]:
        from sqlalchemy import select as sa_select
        result = await self.db.execute(
            sa_select(VenteRemboursement)
            .where(VenteRemboursement.vente_id == vente_id, VenteRemboursement.deleted_at.is_(None))
            .order_by(VenteRemboursement.id.desc())
        )
        return list(result.scalars().all())

    async def create(
        self, vente: Vente, payload: VenteRemboursementCreate, user: User
    ) -> VenteRemboursement:
        logger.info(
            "vente_remboursement.create.start vente_id=%s montant=%s", vente.id, payload.montant
        )

        # Locate the open cash session
        from sqlalchemy import select as sa_select
        result = await self.db.execute(
            sa_select(CashSession)
            .where(
                CashSession.store_id == vente.boutique_id,
                CashSession.status == CashSessionStatus.ouverte,
            )
            .order_by(CashSession.id.desc())
        )
        cash_session = result.scalars().first()
        if cash_session is None:
            raise HTTPException(
                status.HTTP_422_UNPROCESSABLE_ENTITY,
                f"Aucune session de caisse ouverte pour la boutique #{vente.boutique_id} — "
                "impossible d'enregistrer un remboursement sans caisse ouverte.",
            )

        # Create the VenteRemboursement record
        remboursement = VenteRemboursement(
            vente_id=vente.id,
            retour_id=payload.retour_id,
            vendeur_id=user.id,
            montant=payload.montant,
            mode=payload.mode,
            reference=payload.reference,
            motif=payload.motif,
            notes=payload.notes,
        )
        self.db.add(remboursement)
        await self.db.flush()

        # Create CashMovement (sortie) for the refund
        cash_svc = CashMovementService(self.db)
        await cash_svc.create(
            CashMovementCreate(
                cash_session_id=cash_session.id,
                type=CashMovementType.sortie,
                amount=payload.montant,
                reference_type=ReferenceType.VENTE,
                reference_id=vente.id,
                reason=payload.motif,
            ),
            user,
        )

        # Update sale status
        total_rembourse = sum(
            r.montant for r in await self.list(vente.id)
        )
        if total_rembourse >= vente.montant_paye:
            vente.statut = VenteStatut.remboursee
        else:
            vente.statut = VenteStatut.partiellement_remboursee
        self.db.add(vente)

        await self.db.flush()
        await self.db.refresh(remboursement)
        logger.info("vente_remboursement.create.done remboursement_id=%s", remboursement.id)
        return remboursement
