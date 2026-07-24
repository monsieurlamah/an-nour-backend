"""Vente ORM models: sales, lines, returns and refunds."""

from datetime import datetime
from decimal import Decimal
from typing import TYPE_CHECKING

from sqlalchemy import DateTime, Enum, ForeignKey, Integer, Numeric, String, Text
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.database.base import Entity, LogEntity
from app.database.enums import PaiementMode, VenteLivraisonStatut, VenteStatut, VenteType

if TYPE_CHECKING:
    from app.modules.creances.models import Creance, Paiement


class Vente(Entity):
    __tablename__ = "ventes"

    boutique_id: Mapped[int] = mapped_column(
        ForeignKey("stores.id", ondelete="CASCADE"), nullable=False, index=True
    )
    vendeur_id: Mapped[int | None] = mapped_column(
        ForeignKey("users.id", ondelete="SET NULL"), nullable=True, index=True
    )
    client_id: Mapped[int | None] = mapped_column(
        ForeignKey("clients.id", ondelete="SET NULL"), nullable=True, index=True
    )
    type_vente: Mapped[VenteType] = mapped_column(
        Enum(VenteType, native_enum=False, length=20, create_constraint=False),
        default=VenteType.directe,
        nullable=False,
    )
    montant_total: Mapped[Decimal] = mapped_column(Numeric(14, 2), default=0, nullable=False)
    remise: Mapped[Decimal] = mapped_column(Numeric(14, 2), default=0, nullable=False)
    statut: Mapped[VenteStatut] = mapped_column(
        Enum(VenteStatut, native_enum=False, length=25, create_constraint=False),
        default=VenteStatut.completee,
        nullable=False,
        index=True,
    )

    # Delivery — independent from payment status (see VenteLivraisonStatut).
    livraison_statut: Mapped[VenteLivraisonStatut] = mapped_column(
        Enum(VenteLivraisonStatut, native_enum=False, length=20, create_constraint=False),
        default=VenteLivraisonStatut.livre,
        nullable=False,
        index=True,
    )
    numero_bon_livraison: Mapped[str | None] = mapped_column(String(30), unique=True, nullable=True)
    livree_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    livree_by: Mapped[int | None] = mapped_column(
        ForeignKey("users.id", ondelete="SET NULL"), nullable=True
    )

    lignes: Mapped[list["VenteLigne"]] = relationship(
        back_populates="vente", cascade="all, delete-orphan", lazy="selectin"
    )
    # Read-only views onto the related financial records (owned by their own
    # modules — never mutated through these relationships).
    paiements: Mapped[list["Paiement"]] = relationship(viewonly=True, lazy="selectin")
    creance: Mapped["Creance | None"] = relationship(
        viewonly=True, uselist=False, lazy="selectin"
    )

    @property
    def montant_paye(self) -> Decimal:
        return sum((p.montant for p in self.paiements), Decimal("0"))

    @property
    def montant_restant(self) -> Decimal:
        restant = self.montant_total - self.montant_paye
        return restant if restant > 0 else Decimal("0")


class VenteLigne(Entity):
    __tablename__ = "vente_lignes"

    vente_id: Mapped[int] = mapped_column(
        ForeignKey("ventes.id", ondelete="CASCADE"), nullable=False, index=True
    )
    produit_id: Mapped[int] = mapped_column(
        ForeignKey("products.id", ondelete="RESTRICT"), nullable=False, index=True
    )
    quantite: Mapped[int] = mapped_column(Integer, default=1, nullable=False)
    prix_unitaire: Mapped[Decimal] = mapped_column(Numeric(14, 2), default=0, nullable=False)
    remise: Mapped[Decimal] = mapped_column(Numeric(14, 2), default=0, nullable=False)
    total_ligne: Mapped[Decimal] = mapped_column(Numeric(14, 2), default=0, nullable=False)

    vente: Mapped["Vente"] = relationship(back_populates="lignes")


# ── Return operations ──────────────────────────────────────────────────────────

class VenteRetour(Entity):
    """Header of a return operation (partial or total).

    Each return may cover any subset of the original VenteLignes. The linked
    VenteRetourLigne rows record exactly which products and quantities came back.
    """

    __tablename__ = "vente_retours"

    vente_id: Mapped[int] = mapped_column(
        ForeignKey("ventes.id", ondelete="RESTRICT"), nullable=False, index=True
    )
    vendeur_id: Mapped[int | None] = mapped_column(
        ForeignKey("users.id", ondelete="SET NULL"), nullable=True
    )
    motif: Mapped[str] = mapped_column(String(500), nullable=False)
    notes: Mapped[str | None] = mapped_column(Text, nullable=True)
    total_retourne: Mapped[Decimal] = mapped_column(Numeric(14, 2), default=0, nullable=False)

    lignes: Mapped[list["VenteRetourLigne"]] = relationship(
        back_populates="retour", cascade="all, delete-orphan", lazy="selectin"
    )


class VenteRetourLigne(LogEntity):
    """One returned product line within a VenteRetour."""

    __tablename__ = "vente_retour_lignes"

    retour_id: Mapped[int] = mapped_column(
        ForeignKey("vente_retours.id", ondelete="CASCADE"), nullable=False, index=True
    )
    vente_ligne_id: Mapped[int] = mapped_column(
        ForeignKey("vente_lignes.id", ondelete="RESTRICT"), nullable=False
    )
    produit_id: Mapped[int] = mapped_column(
        ForeignKey("products.id", ondelete="RESTRICT"), nullable=False
    )
    quantite: Mapped[int] = mapped_column(Integer, nullable=False)
    prix_unitaire: Mapped[Decimal] = mapped_column(Numeric(14, 2), nullable=False)
    total_ligne: Mapped[Decimal] = mapped_column(Numeric(14, 2), nullable=False)

    retour: Mapped["VenteRetour"] = relationship(back_populates="lignes")


# ── Refund operations ──────────────────────────────────────────────────────────

class VenteRemboursement(Entity):
    """A cash refund linked to a sale (and optionally to a return operation).

    Refunds are deliberately independent from returns: a sale can be returned
    without an immediate cash refund (store credit) or refunded without a
    physical return (goodwill gesture). Each refund creates a CashMovement
    (sortie) in the store's open cash session.
    """

    __tablename__ = "vente_remboursements"

    vente_id: Mapped[int] = mapped_column(
        ForeignKey("ventes.id", ondelete="RESTRICT"), nullable=False, index=True
    )
    retour_id: Mapped[int | None] = mapped_column(
        ForeignKey("vente_retours.id", ondelete="SET NULL"), nullable=True
    )
    vendeur_id: Mapped[int | None] = mapped_column(
        ForeignKey("users.id", ondelete="SET NULL"), nullable=True
    )
    montant: Mapped[Decimal] = mapped_column(Numeric(14, 2), nullable=False)
    mode: Mapped[PaiementMode] = mapped_column(
        Enum(PaiementMode, native_enum=False, length=20, create_constraint=False),
        nullable=False,
    )
    reference: Mapped[str | None] = mapped_column(String(200), nullable=True)
    motif: Mapped[str] = mapped_column(String(500), nullable=False)
    notes: Mapped[str | None] = mapped_column(Text, nullable=True)
