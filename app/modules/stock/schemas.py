"""Pydantic schemas for the stock module."""

from decimal import Decimal

from pydantic import BaseModel, Field

from app.database.enums import MovementReason, MovementType, StockLocationType
from app.modules.common.schemas import EntityRead, LogRead


# --- Stock locations ---------------------------------------------------------
class StockLocationCreate(BaseModel):
    name: str = Field(min_length=1, max_length=150)
    type: StockLocationType
    store_id: int | None = None


class StockLocationUpdate(BaseModel):
    name: str | None = Field(default=None, min_length=1, max_length=150)


class StockLocationRead(EntityRead):
    name: str
    type: StockLocationType
    store_id: int | None
    created_by: int | None


# --- Product stocks ----------------------------------------------------------
class ProductStockRead(EntityRead):
    product_id: int
    location_id: int
    quantity: int
    alert_threshold: int


class ProductStockUpdate(BaseModel):
    alert_threshold: int | None = Field(default=None, ge=0)


# --- Stock operations (atomic) -----------------------------------------------
class AddStockRequest(BaseModel):
    product_id: int
    location_id: int
    quantity: int = Field(gt=0)
    alert_threshold: int = Field(default=0, ge=0)
    reason: MovementReason = MovementReason.STOCK_INITIAL
    unit_cost: Decimal | None = Field(default=None, ge=0)
    reference: str | None = Field(default=None, max_length=100)
    notes: str | None = None


class AdjustStockRequest(BaseModel):
    product_id: int
    location_id: int
    physical_count: int = Field(ge=0)
    alert_threshold: int | None = Field(default=None, ge=0)
    reason: MovementReason = MovementReason.INVENTORY
    notes: str | None = None


class TransferStockRequest(BaseModel):
    product_id: int
    from_location_id: int
    to_location_id: int
    quantity: int = Field(gt=0)
    dest_alert_threshold: int | None = Field(default=None, ge=0)
    notes: str | None = None


class TransferStockResult(BaseModel):
    from_stock: ProductStockRead
    to_stock: ProductStockRead


# --- Movements (read-only) ---------------------------------------------------
class StockMovementRead(LogRead):
    product_id: int
    from_location_id: int | None
    to_location_id: int | None
    movement_type: MovementType
    reason: MovementReason | None
    quantity: int
    quantity_before: int
    quantity_after: int
    unit_cost: Decimal | None
    total_cost: Decimal | None
    reference: str | None
    notes: str | None
    created_by: int | None
