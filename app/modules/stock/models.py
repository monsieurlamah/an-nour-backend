"""Stock ORM models: locations, per-location product stocks, and stock movements."""

from decimal import Decimal

from sqlalchemy import Enum, ForeignKey, Integer, Numeric, String, Text
from sqlalchemy.orm import Mapped, mapped_column

from app.database.base import Entity, LogEntity
from app.database.enums import MovementReason, MovementType, StockAlertType, StockLocationType


class StockLocation(Entity):
    """A named physical or logical location that can hold inventory."""

    __tablename__ = "stock_locations"

    name: Mapped[str] = mapped_column(String(150), nullable=False)
    type: Mapped[StockLocationType] = mapped_column(
        Enum(StockLocationType, native_enum=False, length=20, create_constraint=False),
        nullable=False,
        index=True,
    )
    store_id: Mapped[int | None] = mapped_column(
        ForeignKey("stores.id", ondelete="SET NULL"), nullable=True, index=True
    )
    created_by: Mapped[int | None] = mapped_column(
        ForeignKey("users.id", ondelete="SET NULL"), nullable=True
    )


class ProductStock(Entity):
    """Quantity of a product at a specific location. One row per (product, location) pair."""

    __tablename__ = "product_stocks"

    product_id: Mapped[int] = mapped_column(
        ForeignKey("products.id", ondelete="CASCADE"), nullable=False, index=True
    )
    location_id: Mapped[int] = mapped_column(
        ForeignKey("stock_locations.id", ondelete="CASCADE"), nullable=False, index=True
    )
    quantity: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    alert_threshold: Mapped[int] = mapped_column(Integer, default=0, nullable=False)


class StockMovement(LogEntity):
    """Append-only audit log of every stock quantity change."""

    __tablename__ = "stock_movements"

    product_id: Mapped[int] = mapped_column(
        ForeignKey("products.id", ondelete="CASCADE"), nullable=False, index=True
    )
    from_location_id: Mapped[int | None] = mapped_column(
        ForeignKey("stock_locations.id", ondelete="SET NULL"), nullable=True, index=True
    )
    to_location_id: Mapped[int | None] = mapped_column(
        ForeignKey("stock_locations.id", ondelete="SET NULL"), nullable=True, index=True
    )
    movement_type: Mapped[MovementType] = mapped_column(
        Enum(MovementType, native_enum=False, length=20, create_constraint=False),
        nullable=False,
        index=True,
    )
    reason: Mapped[MovementReason | None] = mapped_column(
        Enum(MovementReason, native_enum=False, length=30, create_constraint=False),
        nullable=True,
    )
    quantity: Mapped[int] = mapped_column(Integer, nullable=False)
    quantity_before: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    quantity_after: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    unit_cost: Mapped[Decimal | None] = mapped_column(Numeric(14, 2), nullable=True)
    total_cost: Mapped[Decimal | None] = mapped_column(Numeric(14, 2), nullable=True)
    reference: Mapped[str | None] = mapped_column(String(100), nullable=True)
    notes: Mapped[str | None] = mapped_column(Text, nullable=True)
    created_by: Mapped[int | None] = mapped_column(
        ForeignKey("users.id", ondelete="SET NULL"), nullable=True
    )


class StockAlertLog(LogEntity):
    """Record of each stock-alert email dispatch — used to prevent same-day duplicates."""

    __tablename__ = "stock_alert_logs"

    product_stock_id: Mapped[int] = mapped_column(
        ForeignKey("product_stocks.id", ondelete="CASCADE"), nullable=False, index=True
    )
    product_id: Mapped[int] = mapped_column(
        ForeignKey("products.id", ondelete="CASCADE"), nullable=False, index=True
    )
    stock_location_id: Mapped[int] = mapped_column(
        ForeignKey("stock_locations.id", ondelete="CASCADE"), nullable=False, index=True
    )
    alert_type: Mapped[StockAlertType] = mapped_column(
        Enum(StockAlertType, native_enum=False, length=20, create_constraint=False),
        nullable=False,
        index=True,
    )
    quantity: Mapped[int] = mapped_column(Integer, nullable=False)
    alert_threshold: Mapped[int] = mapped_column(Integer, nullable=False)
    sent_to: Mapped[str] = mapped_column(Text, nullable=False)
