"""Business logic for the cash module."""

from collections.abc import Sequence
from decimal import Decimal

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.database.enums import CashSessionStatus
from app.modules.cash.models import CashMovement, CashSession
from app.modules.cash.schemas import CashMovementCreate, CashSessionClose, CashSessionOpen
from app.modules.users.models import User
from app.utils.helpers import utcnow


class CashSessionService:
    def __init__(self, db: AsyncSession) -> None:
        self.db = db

    async def get(self, session_id: int) -> CashSession | None:
        return await self.db.get(CashSession, session_id)

    async def list(
        self,
        skip: int = 0,
        limit: int = 100,
        store_id: int | None = None,
        status: CashSessionStatus | None = None,
    ) -> Sequence[CashSession]:
        stmt = select(CashSession)
        if store_id is not None:
            stmt = stmt.where(CashSession.store_id == store_id)
        if status is not None:
            stmt = stmt.where(CashSession.status == status)
        stmt = stmt.order_by(CashSession.id.desc()).offset(skip).limit(limit)
        return (await self.db.execute(stmt)).scalars().all()

    async def open(self, payload: CashSessionOpen, user: User) -> CashSession:
        session = CashSession(
            store_id=payload.store_id,
            opened_by=user.id,
            opening_amount=payload.opening_amount,
            status=CashSessionStatus.ouverte,
        )
        self.db.add(session)
        await self.db.flush()
        await self.db.refresh(session)
        return session

    async def close(
        self, session: CashSession, payload: CashSessionClose, user: User
    ) -> CashSession:
        session.closing_amount = payload.closing_amount
        session.expected_amount = payload.expected_amount
        if payload.expected_amount is not None:
            session.difference_amount = Decimal(payload.closing_amount) - payload.expected_amount
        session.status = CashSessionStatus.fermee
        session.closed_by = user.id
        session.closed_at = utcnow()
        self.db.add(session)
        await self.db.flush()
        await self.db.refresh(session)
        return session


class CashMovementService:
    def __init__(self, db: AsyncSession) -> None:
        self.db = db

    async def list(
        self, skip: int = 0, limit: int = 100, cash_session_id: int | None = None
    ) -> Sequence[CashMovement]:
        stmt = select(CashMovement)
        if cash_session_id is not None:
            stmt = stmt.where(CashMovement.cash_session_id == cash_session_id)
        stmt = stmt.order_by(CashMovement.id.desc()).offset(skip).limit(limit)
        return (await self.db.execute(stmt)).scalars().all()

    async def create(self, payload: CashMovementCreate, user: User) -> CashMovement:
        movement = CashMovement(**payload.model_dump(), created_by=user.id)
        self.db.add(movement)
        await self.db.flush()
        await self.db.refresh(movement)
        return movement
