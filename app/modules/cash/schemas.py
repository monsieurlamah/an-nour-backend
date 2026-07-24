"""Pydantic schemas for the cash module."""

from datetime import datetime
from decimal import Decimal

from pydantic import BaseModel, Field

from app.database.enums import CashMovementType, CashSessionStatus, ReferenceType
from app.modules.common.schemas import LogRead, ORMModel


class CashSessionOpen(BaseModel):
    store_id: int
    opening_amount: Decimal = Field(default=Decimal("0"), ge=0)


class CashSessionClose(BaseModel):
    closing_amount: Decimal = Field(ge=0)
    expected_amount: Decimal | None = Field(default=None, ge=0)


class CashSessionRead(ORMModel):
    id: int
    uuid: str
    store_id: int
    opened_by: int | None
    closed_by: int | None
    opening_amount: Decimal
    closing_amount: Decimal | None
    expected_amount: Decimal | None
    difference_amount: Decimal | None
    status: CashSessionStatus
    opened_at: datetime
    closed_at: datetime | None


class CashMovementCreate(BaseModel):
    cash_session_id: int
    type: CashMovementType
    amount: Decimal = Field(gt=0)
    reason: str | None = Field(default=None, max_length=255)
    reference_type: ReferenceType | None = None
    reference_id: int | None = None


class CashMovementRead(LogRead):
    cash_session_id: int
    type: CashMovementType
    amount: Decimal
    reason: str | None
    reference_type: ReferenceType | None
    reference_id: int | None
    created_by: int | None
