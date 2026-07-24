"""Achat ORM models: suppliers, purchases and purchase lines."""

from decimal import Decimal

from sqlalchemy import Enum, ForeignKey, Integer, Numeric, String
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.database.base import Entity
from app.database.enums import PurchaseStatut


class Supplier(Entity):
    __tablename__ = "suppliers"

    name: Mapped[str] = mapped_column(String(200), index=True, nullable=False)
    phone: Mapped[str | None] = mapped_column(String(30), nullable=True)
    email: Mapped[str | None] = mapped_column(String(255), nullable=True)
    address: Mapped[str | None] = mapped_column(String(255), nullable=True)


class Purchase(Entity):
    __tablename__ = "purchases"

    supplier_id: Mapped[int] = mapped_column(
        ForeignKey("suppliers.id", ondelete="RESTRICT"), nullable=False, index=True
    )
    created_by: Mapped[int | None] = mapped_column(
        ForeignKey("users.id", ondelete="SET NULL"), nullable=True
    )
    montant_total: Mapped[Decimal] = mapped_column(Numeric(14, 2), default=0, nullable=False)
    statut: Mapped[PurchaseStatut] = mapped_column(
        Enum(PurchaseStatut, native_enum=False, length=25, create_constraint=False),
        default=PurchaseStatut.brouillon,
        nullable=False,
        index=True,
    )

    lignes: Mapped[list["PurchaseLine"]] = relationship(
        back_populates="purchase", cascade="all, delete-orphan", lazy="selectin"
    )


class PurchaseLine(Entity):
    __tablename__ = "purchase_lines"

    purchase_id: Mapped[int] = mapped_column(
        ForeignKey("purchases.id", ondelete="CASCADE"), nullable=False, index=True
    )
    product_id: Mapped[int] = mapped_column(
        ForeignKey("products.id", ondelete="RESTRICT"), nullable=False, index=True
    )
    quantity: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    prix_unitaire: Mapped[Decimal] = mapped_column(Numeric(14, 2), default=0, nullable=False)
    total_ligne: Mapped[Decimal] = mapped_column(Numeric(14, 2), default=0, nullable=False)

    purchase: Mapped["Purchase"] = relationship(back_populates="lignes")
