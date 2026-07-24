"""Expense ORM models: expense categories and expenses."""

from decimal import Decimal

from sqlalchemy import Enum, ForeignKey, Numeric, String, Text
from sqlalchemy.orm import Mapped, mapped_column

from app.database.base import Entity
from app.database.enums import PaiementMode


class ExpenseCategory(Entity):
    __tablename__ = "expense_categories"

    name: Mapped[str] = mapped_column(String(150), nullable=False)
    slug: Mapped[str] = mapped_column(String(150), unique=True, index=True, nullable=False)
    description: Mapped[str | None] = mapped_column(Text, nullable=True)


class Expense(Entity):
    __tablename__ = "expenses"

    store_id: Mapped[int | None] = mapped_column(
        ForeignKey("stores.id", ondelete="SET NULL"), nullable=True, index=True
    )
    category_id: Mapped[int | None] = mapped_column(
        ForeignKey("expense_categories.id", ondelete="SET NULL"), nullable=True, index=True
    )
    # Free-text precision when category_id points to the "Autre" category —
    # a gérant has no permission to create new shared categories (see
    # expenses.categories.manage), so this lets them note what "Autre"
    # actually means for this expense without touching the taxonomy.
    category_label: Mapped[str | None] = mapped_column(String(150), nullable=True)
    montant: Mapped[Decimal] = mapped_column(Numeric(14, 2), default=0, nullable=False)
    description: Mapped[str | None] = mapped_column(Text, nullable=True)
    payment_mode: Mapped[PaiementMode] = mapped_column(
        Enum(PaiementMode, native_enum=False, length=20, create_constraint=False),
        default=PaiementMode.especes,
        nullable=False,
    )
    # Justificatif (photo/scan du reçu) — uploadé via /upload/image (Cloudinary),
    # jamais obligatoire en base (une dépense peut être justifiée par le seul
    # motif texte), mais fortement recommandé côté UI.
    receipt_url: Mapped[str | None] = mapped_column(String(512), nullable=True)
    created_by: Mapped[int | None] = mapped_column(
        ForeignKey("users.id", ondelete="SET NULL"), nullable=True
    )
