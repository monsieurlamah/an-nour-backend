"""Pydantic schemas for the achat module: suppliers and purchases."""

from decimal import Decimal

from pydantic import BaseModel, EmailStr, Field

from app.database.enums import PurchaseStatut, RecordStatus
from app.modules.common.schemas import EntityRead


# --- Suppliers ---------------------------------------------------------------
class SupplierCreate(BaseModel):
    name: str = Field(min_length=1, max_length=200)
    phone: str | None = Field(default=None, max_length=30)
    email: EmailStr | None = None
    address: str | None = Field(default=None, max_length=255)


class SupplierUpdate(BaseModel):
    name: str | None = Field(default=None, min_length=1, max_length=200)
    phone: str | None = Field(default=None, max_length=30)
    email: EmailStr | None = None
    address: str | None = Field(default=None, max_length=255)
    # Activer/désactiver un fournisseur (jamais à la création — toujours actif
    # par défaut via StatusMixin).
    status: RecordStatus | None = None


class SupplierRead(EntityRead):
    name: str
    phone: str | None
    email: str | None
    address: str | None


# --- Purchases ---------------------------------------------------------------
class PurchaseLineCreate(BaseModel):
    product_id: int
    quantity: int = Field(ge=1)
    prix_unitaire: Decimal = Field(default=Decimal("0"), ge=0)


class PurchaseLineRead(EntityRead):
    purchase_id: int
    product_id: int
    quantity: int
    prix_unitaire: Decimal
    total_ligne: Decimal


class PurchaseCreate(BaseModel):
    supplier_id: int
    statut: PurchaseStatut = PurchaseStatut.brouillon
    lignes: list[PurchaseLineCreate] = Field(min_length=1)


class PurchaseStatusUpdate(BaseModel):
    statut: PurchaseStatut


class PurchaseRead(EntityRead):
    supplier_id: int
    created_by: int | None
    montant_total: Decimal
    statut: PurchaseStatut
    lignes: list[PurchaseLineRead]
