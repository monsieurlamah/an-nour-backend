"""Commande ORM models: internal replenishment requests (boutique -> HQ
central stock) and every document/audit table the full workflow produces.

Nothing here ever touches ``ProductStock`` directly — see
``CommandeService.confirm_reception`` (services.py) for the one and only
place stock actually moves, and only after the boutique confirms receipt.
"""

from datetime import datetime
from decimal import Decimal

from sqlalchemy import JSON, Boolean, DateTime, Enum, ForeignKey, Integer, Numeric, String, Text
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.database.base import Entity, LogEntity
from app.database.enums import (
    CommandeAnomalieType,
    CommandeEvenementType,
    CommandeReceptionStatut,
    CommandeStatut,
)


class Commande(Entity):
    __tablename__ = "commandes"

    boutique_id: Mapped[int] = mapped_column(
        ForeignKey("stores.id", ondelete="CASCADE"), nullable=False, index=True
    )
    created_by: Mapped[int | None] = mapped_column(
        ForeignKey("users.id", ondelete="SET NULL"), nullable=True
    )
    validated_by: Mapped[int | None] = mapped_column(
        ForeignKey("users.id", ondelete="SET NULL"), nullable=True
    )
    statut: Mapped[CommandeStatut] = mapped_column(
        Enum(CommandeStatut, native_enum=False, length=32, create_constraint=False),
        default=CommandeStatut.brouillon,
        nullable=False,
        index=True,
    )
    # Own reference for the demande itself — assigned on first exit from
    # brouillon (see CommandeService.submit). Nullable while still a draft.
    numero: Mapped[str | None] = mapped_column(String(30), unique=True, nullable=True)

    montant_total: Mapped[Decimal] = mapped_column(Numeric(14, 2), default=0, nullable=False)
    montant_ht: Mapped[Decimal] = mapped_column(Numeric(14, 2), default=0, nullable=False)
    tva_taux: Mapped[Decimal] = mapped_column(Numeric(5, 2), default=0, nullable=False)
    montant_tva: Mapped[Decimal] = mapped_column(Numeric(14, 2), default=0, nullable=False)
    montant_ttc: Mapped[Decimal] = mapped_column(Numeric(14, 2), default=0, nullable=False)

    numero_proforma: Mapped[str | None] = mapped_column(String(30), unique=True, nullable=True)
    numero_facture: Mapped[str | None] = mapped_column(String(30), unique=True, nullable=True)

    refus_motif: Mapped[str | None] = mapped_column(Text, nullable=True)
    refused_by: Mapped[int | None] = mapped_column(
        ForeignKey("users.id", ondelete="SET NULL"), nullable=True
    )
    refused_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)

    # Distinct from refus_motif/refused_by/refused_at above (the boutique's
    # demande-level refusal, at EN_ATTENTE): this tracks the gérant rejecting
    # a PROFORMA_GENEREE proforma, sending it back to the Boss for revision —
    # see CommandeService.reject_proforma / resubmit_proforma.
    proforma_refus_motif: Mapped[str | None] = mapped_column(Text, nullable=True)
    proforma_refused_by: Mapped[int | None] = mapped_column(
        ForeignKey("users.id", ondelete="SET NULL"), nullable=True
    )
    proforma_refused_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)

    validated_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    delivered_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)

    lignes: Mapped[list["CommandeLigne"]] = relationship(
        back_populates="commande", cascade="all, delete-orphan", lazy="selectin"
    )
    livraison: Mapped["CommandeLivraison | None"] = relationship(
        back_populates="commande", cascade="all, delete-orphan", uselist=False, lazy="selectin"
    )


class CommandeLigne(Entity):
    __tablename__ = "commande_lignes"

    commande_id: Mapped[int] = mapped_column(
        ForeignKey("commandes.id", ondelete="CASCADE"), nullable=False, index=True
    )
    # Nullable: a boutique can request a product that doesn't exist yet in the
    # catalog by name alone (see `nom_libre`). The line stays unresolved —
    # visible on the demande PDF, but blocking validation — until the Boss
    # attaches it to a real Product (CommandeService.resolve_ligne).
    produit_id: Mapped[int | None] = mapped_column(
        ForeignKey("products.id", ondelete="RESTRICT"), nullable=True, index=True
    )
    nom_libre: Mapped[str | None] = mapped_column(String(255), nullable=True)
    quantite_demandee: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    quantite_validee: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    # Filled in progressively by the later workflow steps — never touched by
    # create()/validate(). quantite_recue accumulates across possibly more
    # than one CommandeReception (a partial delivery followed by a
    # complement) — see confirm_reception's "credit only the increment" rule.
    quantite_livree: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    quantite_recue: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    prix_unitaire: Mapped[Decimal] = mapped_column(Numeric(14, 2), default=0, nullable=False)
    total_ligne: Mapped[Decimal] = mapped_column(Numeric(14, 2), default=0, nullable=False)
    observation: Mapped[str | None] = mapped_column(Text, nullable=True)

    commande: Mapped["Commande"] = relationship(back_populates="lignes")


class CommandeEvenement(LogEntity):
    """Append-only audit trail — one row per meaningful event on a Commande.
    The single source of truth for "who did what, when, from where, with what
    comment" instead of scattering *_by/*_at columns across Commande."""

    __tablename__ = "commande_evenements"

    commande_id: Mapped[int] = mapped_column(
        ForeignKey("commandes.id", ondelete="CASCADE"), nullable=False, index=True
    )
    type_evenement: Mapped[CommandeEvenementType] = mapped_column(
        Enum(CommandeEvenementType, native_enum=False, length=32, create_constraint=False),
        nullable=False,
        index=True,
    )
    acteur_id: Mapped[int | None] = mapped_column(
        ForeignKey("users.id", ondelete="SET NULL"), nullable=True
    )
    commentaire: Mapped[str | None] = mapped_column(Text, nullable=True)
    ip_address: Mapped[str | None] = mapped_column(String(45), nullable=True)  # IPv6-safe
    # Free-form structured payload (e.g. {"before": {...}, "after": {...}}
    # for a quantites_modifiees event). Named `extra`, not `metadata` —
    # `metadata` is reserved on every SQLAlchemy declarative model.
    extra: Mapped[dict | None] = mapped_column("metadata", JSON, nullable=True)


class CommandeLivraison(Entity):
    """Progressive logistics record for a Commande — created as soon as it
    enters EN_PREPARATION (not only at shipment), one row per Commande.
    Fields are filled in as the workflow advances: numero_bon_preparation
    first, then transporteur/numero_bon_livraison/signatures at shipment."""

    __tablename__ = "commande_livraisons"

    commande_id: Mapped[int] = mapped_column(
        ForeignKey("commandes.id", ondelete="CASCADE"), nullable=False, unique=True
    )

    numero_bon_preparation: Mapped[str | None] = mapped_column(
        String(30), unique=True, nullable=True
    )
    preparateur_id: Mapped[int | None] = mapped_column(
        ForeignKey("users.id", ondelete="SET NULL"), nullable=True
    )
    prepared_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)

    transporteur: Mapped[str | None] = mapped_column(String(150), nullable=True)
    livreur_id: Mapped[int | None] = mapped_column(
        ForeignKey("users.id", ondelete="SET NULL"), nullable=True
    )
    livreur_nom: Mapped[str | None] = mapped_column(String(150), nullable=True)
    numero_bon_livraison: Mapped[str | None] = mapped_column(String(30), unique=True, nullable=True)
    date_expedition: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    date_livraison: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)

    qr_content: Mapped[str | None] = mapped_column(String(100), nullable=True)
    code_barre: Mapped[str | None] = mapped_column(String(100), nullable=True)

    signature_hq_by: Mapped[int | None] = mapped_column(
        ForeignKey("users.id", ondelete="SET NULL"), nullable=True
    )
    signature_hq_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    signature_boutique_by: Mapped[int | None] = mapped_column(
        ForeignKey("users.id", ondelete="SET NULL"), nullable=True
    )
    signature_boutique_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)

    commande: Mapped["Commande"] = relationship(back_populates="livraison")


class CommandeReception(Entity):
    """One delivery-attempt record. Deliberately 1:many with Commande — a
    PARTIELLEMENT_RECU commande can get a follow-up delivery later that
    closes the gap, which is a second reception row, not an update to the
    first."""

    __tablename__ = "commande_receptions"

    commande_id: Mapped[int] = mapped_column(
        ForeignKey("commandes.id", ondelete="CASCADE"), nullable=False, index=True
    )
    recu_par: Mapped[int | None] = mapped_column(
        ForeignKey("users.id", ondelete="SET NULL"), nullable=True
    )
    date_reception: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    statut_reception: Mapped[CommandeReceptionStatut] = mapped_column(
        Enum(CommandeReceptionStatut, native_enum=False, length=20, create_constraint=False),
        nullable=False,
    )
    commentaire: Mapped[str | None] = mapped_column(Text, nullable=True)


class CommandeAnomalie(Entity):
    __tablename__ = "commande_anomalies"

    commande_id: Mapped[int] = mapped_column(
        ForeignKey("commandes.id", ondelete="CASCADE"), nullable=False, index=True
    )
    reception_id: Mapped[int | None] = mapped_column(
        ForeignKey("commande_receptions.id", ondelete="SET NULL"), nullable=True, index=True
    )
    ligne_id: Mapped[int | None] = mapped_column(
        ForeignKey("commande_lignes.id", ondelete="SET NULL"), nullable=True
    )
    type_anomalie: Mapped[CommandeAnomalieType] = mapped_column(
        Enum(CommandeAnomalieType, native_enum=False, length=30, create_constraint=False),
        nullable=False,
    )
    quantite_ecart: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    description: Mapped[str | None] = mapped_column(Text, nullable=True)
    created_by: Mapped[int | None] = mapped_column(
        ForeignKey("users.id", ondelete="SET NULL"), nullable=True
    )
    resolved: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
