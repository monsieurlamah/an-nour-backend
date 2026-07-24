"""Pydantic schemas for the catalog module."""

from decimal import Decimal

from pydantic import BaseModel, Field

from app.modules.common.schemas import EntityRead


# --- Product categories ------------------------------------------------------
class CategoryProductCreate(BaseModel):
    name: str = Field(min_length=1, max_length=150)
    slug: str | None = Field(default=None, max_length=150)
    description: str | None = None
    image: str | None = Field(default=None, max_length=512)


class CategoryProductUpdate(BaseModel):
    name: str | None = Field(default=None, min_length=1, max_length=150)
    description: str | None = None
    image: str | None = Field(default=None, max_length=512)


class CategoryProductRead(EntityRead):
    name: str
    slug: str
    description: str | None
    image: str | None
    created_by: int | None


# --- Products ----------------------------------------------------------------
class ProductCreate(BaseModel):
    name: str = Field(min_length=1, max_length=255)
    slug: str | None = Field(default=None, max_length=255)
    sku: str | None = Field(default=None, max_length=100)
    barcode: str | None = Field(default=None, max_length=100)
    brand: str | None = Field(default=None, max_length=150)
    unit_of_measure: str | None = Field(default=None, max_length=50)
    tva: Decimal = Field(default=Decimal("0"), ge=0)
    description: str | None = None
    images: list[str] | None = None
    prix_vente: Decimal = Field(default=Decimal("0"), ge=0)
    prix_achat: Decimal = Field(default=Decimal("0"), ge=0)
    category_product_id: int | None = None


class ProductUpdate(BaseModel):
    name: str | None = Field(default=None, min_length=1, max_length=255)
    sku: str | None = Field(default=None, max_length=100)
    barcode: str | None = Field(default=None, max_length=100)
    brand: str | None = Field(default=None, max_length=150)
    unit_of_measure: str | None = Field(default=None, max_length=50)
    tva: Decimal | None = Field(default=None, ge=0)
    description: str | None = None
    images: list[str] | None = None
    prix_vente: Decimal | None = Field(default=None, ge=0)
    prix_achat: Decimal | None = Field(default=None, ge=0)
    category_product_id: int | None = None


class ProductRead(EntityRead):
    name: str
    slug: str
    sku: str | None
    barcode: str | None
    brand: str | None
    unit_of_measure: str | None
    tva: Decimal
    description: str | None
    images: list[str] | None
    prix_vente: Decimal
    prix_achat: Decimal
    category_product_id: int | None
    created_by: int | None


# --- Store categories --------------------------------------------------------
class CategoryStoreCreate(BaseModel):
    name: str = Field(min_length=1, max_length=150)
    slug: str | None = Field(default=None, max_length=150)
    description: str | None = None
    image: str | None = Field(default=None, max_length=512)


class CategoryStoreUpdate(BaseModel):
    name: str | None = Field(default=None, min_length=1, max_length=150)
    description: str | None = None
    image: str | None = Field(default=None, max_length=512)


class CategoryStoreRead(EntityRead):
    name: str
    slug: str
    description: str | None
    image: str | None
    created_by: int | None
