"""Pydantic schemas for the expenses module."""

from decimal import Decimal

from pydantic import BaseModel, Field

from app.database.enums import PaiementMode
from app.modules.common.schemas import EntityRead


# --- Categories --------------------------------------------------------------
class ExpenseCategoryCreate(BaseModel):
    name: str = Field(min_length=1, max_length=150)
    slug: str | None = Field(default=None, max_length=150)
    description: str | None = None


class ExpenseCategoryUpdate(BaseModel):
    name: str | None = Field(default=None, min_length=1, max_length=150)
    description: str | None = None


class ExpenseCategoryRead(EntityRead):
    name: str
    slug: str
    description: str | None


# --- Expenses ----------------------------------------------------------------
class ExpenseCreate(BaseModel):
    montant: Decimal = Field(gt=0)
    category_id: int | None = None
    # Free-text precision when category_id is the "Autre" category — a
    # gérant can't create new shared categories, only note what "Autre"
    # means for this particular expense.
    category_label: str | None = Field(default=None, max_length=150)
    store_id: int | None = None
    # Every expense must be justified — never optional at creation, even
    # when a receipt photo is also attached (see receipt_url).
    description: str = Field(min_length=3)
    payment_mode: PaiementMode = PaiementMode.especes
    receipt_url: str | None = None


class ExpenseUpdate(BaseModel):
    montant: Decimal | None = Field(default=None, gt=0)
    category_id: int | None = None
    category_label: str | None = Field(default=None, max_length=150)
    store_id: int | None = None
    description: str | None = Field(default=None, min_length=3)
    payment_mode: PaiementMode | None = None
    receipt_url: str | None = None


class ExpenseRead(EntityRead):
    store_id: int | None
    category_id: int | None
    category_label: str | None
    montant: Decimal
    description: str | None
    payment_mode: PaiementMode
    receipt_url: str | None
    created_by: int | None
    # Denormalized at read time (see ExpenseService.list_filtered_enriched) —
    # the Boss must see which boutique spent what without a second lookup.
    # Optional: a network-wide expense (store_id is None) has no store to name.
    store_name: str | None = None
