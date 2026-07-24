"""Business logic for the commandes module: the internal réappro workflow
(boutique -> HQ central stock).

The state machine below is the ONLY way a Commande can move between statuses.
Every transition writes a ``CommandeEvenement`` audit row (actor, IP,
comment, structured extra) — see ``_log_event``. Stock itself only ever
moves inside ``confirm_reception``, via ``StockSaleService.receive_transfer``,
and only for the quantity received at that specific event (never the
cumulative total) so a later complementary delivery can't double-credit.
"""

from collections.abc import Sequence
from decimal import Decimal

from fastapi import HTTPException, status
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.logging import get_logger
from app.database.enums import CommandeEvenementType, CommandeStatut, NotificationType
from app.modules.commandes.models import (
    Commande,
    CommandeAnomalie,
    CommandeEvenement,
    CommandeLigne,
    CommandeLivraison,
    CommandeReception,
)
from app.modules.commandes.schemas import (
    CommandeCreate,
    CommandeLigneResolve,
    CommandeProformaReject,
    CommandeProformaRevise,
    CommandeReceptionCreate,
    CommandeRefuse,
    CommandeShip,
    CommandeValidate,
)
from app.modules.notifications.schemas import NotificationCreate
from app.modules.notifications.services import NotificationService
from app.modules.stock.services import StockSaleService
from app.modules.stores.models import Store
from app.modules.users.models import User
from app.utils.email import send_proforma_rejected_email
from app.utils.helpers import utcnow

logger = get_logger("commandes")

# Statuses in which a commande may still be prepared/queued for a
# magasinier/livreur — used by the two RBAC "queue" routes.
PREPARATION_QUEUE_STATUSES = (
    CommandeStatut.validee,
    CommandeStatut.proforma_generee,
    CommandeStatut.facture_generee,
    CommandeStatut.en_preparation,
)
LIVRAISON_QUEUE_STATUSES = (CommandeStatut.pret_a_expedier, CommandeStatut.expedie)

# Statuses that still allow cancellation — once a commande has physically
# shipped, cancelling it would leave goods in transit unaccounted for, so
# ANNULE is only reachable before EXPEDIE.
_CANCELLABLE_STATUSES = (
    CommandeStatut.brouillon,
    CommandeStatut.en_attente,
    CommandeStatut.validee,
    CommandeStatut.proforma_generee,
    CommandeStatut.proforma_rejetee,
    CommandeStatut.facture_generee,
    CommandeStatut.en_preparation,
    CommandeStatut.pret_a_expedier,
)


def _invalid_transition(commande: Commande, expected: str) -> HTTPException:
    return HTTPException(
        status.HTTP_409_CONFLICT,
        f"Transition invalide : la commande #{commande.id} est au statut "
        f"'{commande.statut.value}', attendu '{expected}'.",
    )


class CommandeService:
    def __init__(self, db: AsyncSession) -> None:
        self.db = db
        self.stock = StockSaleService(db)

    # --- Reads ----------------------------------------------------------

    async def get(self, commande_id: int) -> Commande | None:
        commande = await self.db.get(Commande, commande_id)
        if commande is None or commande.deleted_at is not None:
            return None
        return commande

    async def list(
        self,
        skip: int = 0,
        limit: int = 100,
        boutique_id: int | list[int] | None = None,
        statut: CommandeStatut | None = None,
    ) -> Sequence[Commande]:
        stmt = select(Commande).where(Commande.deleted_at.is_(None))
        if isinstance(boutique_id, list):
            stmt = stmt.where(Commande.boutique_id.in_(boutique_id))
        elif boutique_id is not None:
            stmt = stmt.where(Commande.boutique_id == boutique_id)
        if statut is not None:
            stmt = stmt.where(Commande.statut == statut)
        stmt = stmt.order_by(Commande.id.desc()).offset(skip).limit(limit)
        return (await self.db.execute(stmt)).scalars().all()

    async def list_queue_preparation(self, skip: int = 0, limit: int = 100) -> Sequence[Commande]:
        stmt = (
            select(Commande)
            .where(Commande.deleted_at.is_(None), Commande.statut.in_(PREPARATION_QUEUE_STATUSES))
            .order_by(Commande.id.asc())
            .offset(skip)
            .limit(limit)
        )
        return (await self.db.execute(stmt)).scalars().all()

    async def list_queue_livraison(self, skip: int = 0, limit: int = 100) -> Sequence[Commande]:
        stmt = (
            select(Commande)
            .where(Commande.deleted_at.is_(None), Commande.statut.in_(LIVRAISON_QUEUE_STATUSES))
            .order_by(Commande.id.asc())
            .offset(skip)
            .limit(limit)
        )
        return (await self.db.execute(stmt)).scalars().all()

    async def list_events(self, commande_id: int) -> Sequence[CommandeEvenement]:
        stmt = (
            select(CommandeEvenement)
            .where(CommandeEvenement.commande_id == commande_id)
            .order_by(CommandeEvenement.id.asc())
        )
        return (await self.db.execute(stmt)).scalars().all()

    async def list_receptions(self, commande_id: int) -> Sequence[CommandeReception]:
        stmt = (
            select(CommandeReception)
            .where(CommandeReception.commande_id == commande_id)
            .order_by(CommandeReception.id.asc())
        )
        return (await self.db.execute(stmt)).scalars().all()

    async def list_anomalies(self, commande_id: int) -> Sequence[CommandeAnomalie]:
        stmt = (
            select(CommandeAnomalie)
            .where(CommandeAnomalie.commande_id == commande_id)
            .order_by(CommandeAnomalie.id.asc())
        )
        return (await self.db.execute(stmt)).scalars().all()

    # --- Audit trail ------------------------------------------------------

    async def _log_event(
        self,
        commande: Commande,
        type_evenement: CommandeEvenementType,
        acteur_id: int | None,
        ip_address: str | None,
        commentaire: str | None = None,
        extra: dict | None = None,
    ) -> CommandeEvenement:
        event = CommandeEvenement(
            commande_id=commande.id,
            type_evenement=type_evenement,
            acteur_id=acteur_id,
            commentaire=commentaire,
            ip_address=ip_address,
            extra=extra,
        )
        self.db.add(event)
        await self.db.flush()
        return event

    async def _persist(self, commande: Commande) -> Commande:
        self.db.add(commande)
        await self.db.flush()
        await self.db.refresh(commande)
        return commande

    # --- Étape 1-2 : création + soumission de la demande ------------------

    async def create(self, payload: CommandeCreate, user: User, ip: str | None) -> Commande:
        """A new demande always starts as BROUILLON — see submit() for the
        transition to EN_ATTENTE_VALIDATION."""
        commande = Commande(
            boutique_id=payload.boutique_id,
            created_by=user.id,
            statut=CommandeStatut.brouillon,
        )
        total = Decimal("0")
        for line in payload.lignes:
            line_total = Decimal(line.quantite_demandee) * line.prix_unitaire
            total += line_total
            commande.lignes.append(
                CommandeLigne(
                    produit_id=line.produit_id,
                    nom_libre=line.nom_libre,
                    quantite_demandee=line.quantite_demandee,
                    prix_unitaire=line.prix_unitaire,
                    total_ligne=line_total,
                    observation=line.observation,
                )
            )
        commande.montant_total = total
        self.db.add(commande)
        await self.db.flush()
        await self.db.refresh(commande)
        await self._log_event(commande, CommandeEvenementType.creation, user.id, ip)
        await self.db.flush()
        return commande

    async def submit(self, commande: Commande, user: User, ip: str | None) -> Commande:
        if commande.statut != CommandeStatut.brouillon:
            raise _invalid_transition(commande, CommandeStatut.brouillon.value)
        if not commande.lignes:
            raise HTTPException(
                status.HTTP_422_UNPROCESSABLE_ENTITY,
                "Impossible de soumettre une demande sans ligne de produit.",
            )
        commande.numero = f"DEM-{utcnow().year}-{commande.id:06d}"
        commande.statut = CommandeStatut.en_attente
        await self._persist(commande)
        await self._log_event(commande, CommandeEvenementType.soumission, user.id, ip)
        return commande

    # --- Étape 3 : décision HQ ---------------------------------------------

    async def validate(
        self, commande: Commande, payload: CommandeValidate, user: User, ip: str | None
    ) -> Commande:
        if commande.statut != CommandeStatut.en_attente:
            raise _invalid_transition(commande, CommandeStatut.en_attente.value)

        unresolved = [line for line in commande.lignes if line.produit_id is None]
        if unresolved:
            noms = ", ".join(f"« {line.nom_libre} »" for line in unresolved)
            raise HTTPException(
                status.HTTP_409_CONFLICT,
                f"Impossible de valider : {len(unresolved)} ligne(s) restent à rattacher à un "
                f"produit du catalogue avant validation ({noms}).",
            )

        validated = payload.quantites_validees or {}
        before = {line.id: line.quantite_demandee for line in commande.lignes}
        for line in commande.lignes:
            line.quantite_validee = validated.get(line.id, line.quantite_demandee)
            line.total_ligne = Decimal(line.quantite_validee) * line.prix_unitaire

        commande.montant_ht = sum((line.total_ligne for line in commande.lignes), Decimal("0"))
        commande.montant_tva = commande.montant_ht * commande.tva_taux / Decimal("100")
        commande.montant_ttc = commande.montant_ht + commande.montant_tva
        commande.montant_total = commande.montant_ttc
        commande.statut = CommandeStatut.validee
        commande.validated_by = user.id
        commande.validated_at = utcnow()
        await self._persist(commande)

        after = {line.id: line.quantite_validee for line in commande.lignes}
        partial = after != before
        await self._log_event(
            commande,
            CommandeEvenementType.validation,
            user.id,
            ip,
            commentaire=payload.commentaire,
            extra={"quantites_avant": before, "quantites_validees": after, "partiel": partial},
        )
        await self._notify_gerant_commande_decision(commande, approved=True)
        return commande

    async def refuse(
        self, commande: Commande, payload: CommandeRefuse, user: User, ip: str | None
    ) -> Commande:
        if commande.statut != CommandeStatut.en_attente:
            raise _invalid_transition(commande, CommandeStatut.en_attente.value)
        commande.statut = CommandeStatut.rejetee
        commande.refus_motif = payload.motif
        commande.refused_by = user.id
        commande.refused_at = utcnow()
        await self._persist(commande)
        await self._log_event(
            commande, CommandeEvenementType.refus, user.id, ip, commentaire=payload.motif
        )
        await self._notify_gerant_commande_decision(commande, approved=False)
        return commande

    async def _notify_gerant_commande_decision(self, commande: Commande, approved: bool) -> None:
        """Best-effort in-app notification to the gérant who submitted this
        demande — never raises, mirrors _notify_boss_proforma_rejected."""
        try:
            if commande.created_by is None:
                return
            numero = commande.numero or f"#{commande.id}"
            if approved:
                title = f"Commande {numero} approuvée"
                message = "Votre demande d'approvisionnement a été validée pour préparation."
            else:
                title = f"Commande {numero} refusée"
                message = commande.refus_motif or "Votre demande d'approvisionnement a été refusée."
            await NotificationService(self.db).create(
                NotificationCreate(
                    user_id=commande.created_by,
                    title=title,
                    message=message,
                    type=NotificationType.commande,
                    link="/app/orders",
                )
            )
        except Exception:
            logger.error(
                "Failed to create commande-decision notification for commande #%s",
                commande.id,
                exc_info=True,
            )

    async def resolve_ligne(
        self,
        commande: Commande,
        ligne_id: int,
        payload: CommandeLigneResolve,
        user: User,
        ip: str | None,
    ) -> Commande:
        """Attach a real catalog product to a line the boutique created with
        only a free-text name (``nom_libre``) — the only way such a line can
        ever move stock later. Only meaningful while the Boss is reviewing
        the demande; once validated every line is guaranteed resolved."""
        if commande.statut != CommandeStatut.en_attente:
            raise _invalid_transition(commande, CommandeStatut.en_attente.value)
        line = next((ln for ln in commande.lignes if ln.id == ligne_id), None)
        if line is None:
            raise HTTPException(
                status.HTTP_404_NOT_FOUND, f"Ligne #{ligne_id} introuvable sur cette commande."
            )
        if line.produit_id is not None:
            raise HTTPException(
                status.HTTP_409_CONFLICT, "Cette ligne est déjà rattachée à un produit."
            )
        nom_avant = line.nom_libre
        line.produit_id = payload.produit_id
        await self._persist(commande)
        await self._log_event(
            commande,
            CommandeEvenementType.produit_resolu,
            user.id,
            ip,
            commentaire=f"« {nom_avant} » rattaché au produit #{payload.produit_id}",
            extra={"ligne_id": ligne_id, "nom_libre": nom_avant, "produit_id": payload.produit_id},
        )
        return commande

    # --- Étape 4-5 : documents proforma / facture --------------------------

    async def generate_proforma(self, commande: Commande, user: User, ip: str | None) -> Commande:
        if commande.statut != CommandeStatut.validee:
            raise _invalid_transition(commande, CommandeStatut.validee.value)
        commande.numero_proforma = f"PRO-{utcnow().year}-{commande.id:06d}"
        commande.statut = CommandeStatut.proforma_generee
        await self._persist(commande)
        await self._log_event(commande, CommandeEvenementType.proforma, user.id, ip)
        return commande

    # --- Étape 5bis : décision du gérant sur la proforma --------------------
    # The Boss no longer generates the facture directly — once the proforma
    # is sent, the boutique's gérant is the one who accepts (facture
    # auto-generated) or rejects it (sent back to the Boss for revision).

    async def approve_proforma(self, commande: Commande, user: User, ip: str | None) -> Commande:
        if commande.statut != CommandeStatut.proforma_generee:
            raise _invalid_transition(commande, CommandeStatut.proforma_generee.value)
        commande.numero_facture = f"FAC-{utcnow().year}-{commande.id:06d}"
        commande.statut = CommandeStatut.facture_generee
        await self._persist(commande)
        await self._log_event(commande, CommandeEvenementType.proforma_acceptee, user.id, ip)
        return commande

    async def reject_proforma(
        self, commande: Commande, payload: CommandeProformaReject, user: User, ip: str | None
    ) -> Commande:
        if commande.statut != CommandeStatut.proforma_generee:
            raise _invalid_transition(commande, CommandeStatut.proforma_generee.value)
        commande.statut = CommandeStatut.proforma_rejetee
        commande.proforma_refus_motif = payload.motif
        commande.proforma_refused_by = user.id
        commande.proforma_refused_at = utcnow()
        await self._persist(commande)
        await self._log_event(
            commande, CommandeEvenementType.proforma_rejetee, user.id, ip, commentaire=payload.motif
        )
        await self._notify_boss_proforma_rejected(commande, user)
        return commande

    async def resubmit_proforma(
        self, commande: Commande, payload: CommandeProformaRevise, user: User, ip: str | None
    ) -> Commande:
        """Boss edits quantities/prices after a gérant rejection and puts the
        proforma back in front of the gérant for another decision."""
        if commande.statut != CommandeStatut.proforma_rejetee:
            raise _invalid_transition(commande, CommandeStatut.proforma_rejetee.value)
        quantites = payload.quantites or {}
        prix = payload.prix or {}
        for line in commande.lignes:
            if line.id in quantites:
                line.quantite_validee = quantites[line.id]
            if line.id in prix:
                line.prix_unitaire = prix[line.id]
            line.total_ligne = Decimal(line.quantite_validee) * line.prix_unitaire

        commande.montant_ht = sum((line.total_ligne for line in commande.lignes), Decimal("0"))
        commande.montant_tva = commande.montant_ht * commande.tva_taux / Decimal("100")
        commande.montant_ttc = commande.montant_ht + commande.montant_tva
        commande.montant_total = commande.montant_ttc
        commande.statut = CommandeStatut.proforma_generee
        await self._persist(commande)
        await self._log_event(
            commande,
            CommandeEvenementType.proforma_resoumise,
            user.id,
            ip,
            commentaire=payload.commentaire,
        )
        return commande

    async def _notify_boss_proforma_rejected(self, commande: Commande, gerant: User) -> None:
        """Best-effort email to the Boss/HQ user who validated this commande —
        never raises, mirrors StockAlertService.check_and_notify."""
        try:
            if commande.validated_by is None:
                return
            boss = await self.db.get(User, commande.validated_by)
            if boss is None or not boss.email:
                return
            store = await self.db.get(Store, commande.boutique_id)
            await send_proforma_rejected_email(
                to=boss.email,
                boss_name=f"{boss.firstname} {boss.lastname}",
                gerant_name=f"{gerant.firstname} {gerant.lastname}",
                boutique_name=store.name if store else f"Boutique #{commande.boutique_id}",
                numero=commande.numero or f"#{commande.id}",
                numero_proforma=commande.numero_proforma or "-",
                motif=commande.proforma_refus_motif or "",
            )
        except Exception:
            logger.error(
                "Failed to send proforma-rejected email for commande #%s",
                commande.id,
                exc_info=True,
            )

    # --- Étape 6 : préparation (magasinier HQ) ------------------------------

    async def start_preparation(self, commande: Commande, user: User, ip: str | None) -> Commande:
        if commande.statut != CommandeStatut.facture_generee:
            raise _invalid_transition(commande, CommandeStatut.facture_generee.value)
        commande.statut = CommandeStatut.en_preparation
        livraison = CommandeLivraison(
            commande_id=commande.id,
            numero_bon_preparation=f"BP-{utcnow().year}-{commande.id:06d}",
        )
        self.db.add(livraison)
        await self._persist(commande)
        await self._log_event(commande, CommandeEvenementType.preparation, user.id, ip)
        return commande

    async def confirm_preparation(self, commande: Commande, user: User, ip: str | None) -> Commande:
        if commande.statut != CommandeStatut.en_preparation:
            raise _invalid_transition(commande, CommandeStatut.en_preparation.value)
        if commande.livraison is None:
            raise HTTPException(
                status.HTTP_409_CONFLICT,
                "Aucun bon de préparation n'a été initialisé pour cette commande.",
            )
        commande.livraison.preparateur_id = user.id
        commande.livraison.prepared_at = utcnow()
        commande.statut = CommandeStatut.pret_a_expedier
        await self._persist(commande)
        await self._log_event(
            commande,
            CommandeEvenementType.preparation,
            user.id,
            ip,
            commentaire="Préparation confirmée",
        )
        return commande

    # --- Étape 7 : expédition (livreur) -------------------------------------

    async def ship(
        self, commande: Commande, payload: CommandeShip, user: User, ip: str | None
    ) -> Commande:
        if commande.statut != CommandeStatut.pret_a_expedier:
            raise _invalid_transition(commande, CommandeStatut.pret_a_expedier.value)
        if commande.livraison is None:
            raise HTTPException(
                status.HTTP_409_CONFLICT,
                "Aucun bon de préparation n'a été initialisé pour cette commande.",
            )
        livraison = commande.livraison
        livraison.transporteur = payload.transporteur
        livraison.livreur_id = payload.livreur_id
        livraison.livreur_nom = payload.livreur_nom
        livraison.numero_bon_livraison = f"BL-{utcnow().year}-{commande.id:06d}"
        livraison.date_expedition = utcnow()
        livraison.qr_content = livraison.numero_bon_livraison
        livraison.code_barre = livraison.numero_bon_livraison

        for line in commande.lignes:
            line.quantite_livree = line.quantite_validee

        commande.statut = CommandeStatut.expedie
        await self._persist(commande)
        await self._log_event(commande, CommandeEvenementType.expedition, user.id, ip)
        return commande

    async def mark_delivered(self, commande: Commande, user: User, ip: str | None) -> Commande:
        if commande.statut != CommandeStatut.expedie:
            raise _invalid_transition(commande, CommandeStatut.expedie.value)
        if commande.livraison is not None:
            commande.livraison.date_livraison = utcnow()
        commande.statut = CommandeStatut.livree
        commande.delivered_at = utcnow()
        await self._persist(commande)
        await self._log_event(commande, CommandeEvenementType.livraison, user.id, ip)
        return commande

    # --- Étape 8-9 : réception boutique + mise à jour des stocks -----------

    async def confirm_reception(
        self, commande: Commande, payload: CommandeReceptionCreate, user: User, ip: str | None
    ) -> Commande:
        if commande.statut not in (CommandeStatut.livree, CommandeStatut.partiellement_recu):
            raise _invalid_transition(commande, CommandeStatut.livree.value)

        central = await self.stock.get_central_location()
        store = await self.stock.get_store_location(commande.boutique_id)

        reception = CommandeReception(
            commande_id=commande.id,
            recu_par=user.id,
            date_reception=utcnow(),
            statut_reception=payload.statut_reception,
            commentaire=payload.commentaire,
        )
        self.db.add(reception)
        await self.db.flush()
        await self.db.refresh(reception)

        lignes_by_id = {line.id: line for line in commande.lignes}
        for ligne_id, qty_recue in payload.lignes.items():
            if qty_recue <= 0:
                continue
            line = lignes_by_id.get(ligne_id)
            if line is None:
                raise HTTPException(
                    status.HTTP_422_UNPROCESSABLE_ENTITY,
                    f"La ligne #{ligne_id} n'appartient pas à la commande #{commande.id}.",
                )
            restant = line.quantite_validee - line.quantite_recue
            if qty_recue > restant:
                raise HTTPException(
                    status.HTTP_422_UNPROCESSABLE_ENTITY,
                    f"Quantité reçue ({qty_recue}) supérieure à la quantité restant à recevoir "
                    f"({restant}) pour la ligne #{ligne_id}.",
                )
            await self.stock.receive_transfer(
                product_id=line.produit_id,
                central_location_id=central.id,
                store_location_id=store.id,
                quantity=qty_recue,
                reference=f"COMMANDE-{commande.id}",
                created_by=user.id,
            )
            line.quantite_recue += qty_recue

        for anomalie in payload.anomalies:
            self.db.add(
                CommandeAnomalie(
                    commande_id=commande.id,
                    reception_id=reception.id,
                    ligne_id=anomalie.ligne_id,
                    type_anomalie=anomalie.type_anomalie,
                    quantite_ecart=anomalie.quantite_ecart,
                    description=anomalie.description,
                    created_by=user.id,
                )
            )
        if payload.anomalies:
            await self.db.flush()
            await self._log_event(
                commande,
                CommandeEvenementType.anomalie,
                user.id,
                ip,
                commentaire=f"{len(payload.anomalies)} anomalie(s) signalée(s)",
                extra={"reception_id": reception.id},
            )

        total_validee = sum(line.quantite_validee for line in commande.lignes)
        total_recue = sum(line.quantite_recue for line in commande.lignes)
        commande.statut = (
            CommandeStatut.reception_confirmee
            if total_recue >= total_validee
            else CommandeStatut.partiellement_recu
        )
        await self._persist(commande)
        await self._log_event(
            commande,
            CommandeEvenementType.reception,
            user.id,
            ip,
            commentaire=payload.commentaire,
            extra={
                "reception_id": reception.id,
                "statut_reception": payload.statut_reception.value,
            },
        )
        return commande

    # --- Annulation ----------------------------------------------------------

    async def cancel(
        self, commande: Commande, user: User, ip: str | None, motif: str | None
    ) -> Commande:
        if commande.statut not in _CANCELLABLE_STATUSES:
            raise HTTPException(
                status.HTTP_409_CONFLICT,
                f"La commande #{commande.id} ne peut plus être annulée "
                f"(statut '{commande.statut.value}').",
            )
        commande.statut = CommandeStatut.annulee
        await self._persist(commande)
        await self._log_event(
            commande, CommandeEvenementType.annulation, user.id, ip, commentaire=motif
        )
        return commande

    async def soft_delete(self, commande: Commande) -> None:
        commande.deleted_at = utcnow()
        self.db.add(commande)
        await self.db.flush()
