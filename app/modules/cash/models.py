"""Cash register ORM models: cash sessions and cash movements."""

from datetime import datetime
from decimal import Decimal

from sqlalchemy import JSON, DateTime, Enum, ForeignKey, Integer, Numeric, String, func
from sqlalchemy.orm import Mapped, mapped_column

from app.database.base import Base, LogEntity
from app.database.enums import CashMovementType, CashSessionStatus, ReferenceType
from app.database.mixins import IDMixin, UUIDMixin


class CashSession(Base, IDMixin, UUIDMixin):
    __tablename__ = "cash_sessions"

    store_id: Mapped[int] = mapped_column(
        ForeignKey("stores.id", ondelete="CASCADE"), nullable=False, index=True
    )
    opened_by: Mapped[int | None] = mapped_column(
        ForeignKey("users.id", ondelete="SET NULL"), nullable=True
    )
    closed_by: Mapped[int | None] = mapped_column(
        ForeignKey("users.id", ondelete="SET NULL"), nullable=True
    )
    opening_amount: Mapped[Decimal] = mapped_column(Numeric(14, 2), default=0, nullable=False)
    closing_amount: Mapped[Decimal | None] = mapped_column(Numeric(14, 2), nullable=True)
    expected_amount: Mapped[Decimal | None] = mapped_column(Numeric(14, 2), nullable=True)
    difference_amount: Mapped[Decimal | None] = mapped_column(Numeric(14, 2), nullable=True)
    status: Mapped[CashSessionStatus] = mapped_column(
        Enum(CashSessionStatus, native_enum=False, length=20, create_constraint=False),
        default=CashSessionStatus.ouverte,
        nullable=False,
        index=True,
    )
    infos: Mapped[dict | None] = mapped_column(JSON, nullable=True)
    opened_at: Mapped[datetime] = mapped_column(
        DateTime, server_default=func.now(), nullable=False
    )
    closed_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)


class CashMovement(LogEntity):
    __tablename__ = "cash_movements"

    cash_session_id: Mapped[int] = mapped_column(
        ForeignKey("cash_sessions.id", ondelete="CASCADE"), nullable=False, index=True
    )
    type: Mapped[CashMovementType] = mapped_column(
        Enum(CashMovementType, native_enum=False, length=20, create_constraint=False),
        nullable=False,
    )
    amount: Mapped[Decimal] = mapped_column(Numeric(14, 2), default=0, nullable=False)
    reason: Mapped[str | None] = mapped_column(String(255), nullable=True)
    reference_type: Mapped[ReferenceType | None] = mapped_column(
        Enum(ReferenceType, native_enum=False, length=30, create_constraint=False),
        nullable=True,
    )
    reference_id: Mapped[int | None] = mapped_column(Integer, nullable=True)
    created_by: Mapped[int | None] = mapped_column(
        ForeignKey("users.id", ondelete="SET NULL"), nullable=True
    )
