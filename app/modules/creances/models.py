"""Creance ORM models: customer debts and payments."""

from datetime import datetime
from decimal import Decimal

from sqlalchemy import DateTime, Enum, ForeignKey, Numeric, String
from sqlalchemy.orm import Mapped, mapped_column

from app.database.base import Entity
from app.database.enums import CreanceStatut, PaiementMode


class Creance(Entity):
    __tablename__ = "creances"

    vente_id: Mapped[int | None] = mapped_column(
        ForeignKey("ventes.id", ondelete="SET NULL"), nullable=True, index=True
    )
    client_id: Mapped[int] = mapped_column(
        ForeignKey("clients.id", ondelete="CASCADE"), nullable=False, index=True
    )
    boutique_id: Mapped[int] = mapped_column(
        ForeignKey("stores.id", ondelete="CASCADE"), nullable=False, index=True
    )
    montant_initial: Mapped[Decimal] = mapped_column(Numeric(14, 2), default=0, nullable=False)
    montant_restant: Mapped[Decimal] = mapped_column(Numeric(14, 2), default=0, nullable=False)
    date_echeance: Mapped[datetime | None] = mapped_column(DateTime, nullable=True, index=True)
    statut: Mapped[CreanceStatut] = mapped_column(
        Enum(CreanceStatut, native_enum=False, length=25, create_constraint=False),
        default=CreanceStatut.active,
        nullable=False,
        index=True,
    )


class Paiement(Entity):
    __tablename__ = "paiements"

    vente_id: Mapped[int | None] = mapped_column(
        ForeignKey("ventes.id", ondelete="SET NULL"), nullable=True, index=True
    )
    creance_id: Mapped[int | None] = mapped_column(
        ForeignKey("creances.id", ondelete="SET NULL"), nullable=True, index=True
    )
    montant: Mapped[Decimal] = mapped_column(Numeric(14, 2), default=0, nullable=False)
    mode: Mapped[PaiementMode] = mapped_column(
        Enum(PaiementMode, native_enum=False, length=20, create_constraint=False),
        default=PaiementMode.especes,
        nullable=False,
    )
    reference: Mapped[str | None] = mapped_column(String(100), nullable=True)
