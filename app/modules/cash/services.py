"""Business logic for the cash module."""

from collections.abc import Sequence
from decimal import Decimal

from fastapi import HTTPException, status
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.database.enums import CashMovementType, CashSessionStatus, ReferenceType
from app.modules.cash.models import CashMovement, CashSession
from app.modules.cash.schemas import (
    CashMovementCancel,
    CashMovementCreate,
    CashSessionClose,
    CashSessionOpen,
)
from app.modules.system.services import log_activity
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

    async def get(self, movement_id: int) -> CashMovement | None:
        return await self.db.get(CashMovement, movement_id)

    async def cancel(
        self, movement: CashMovement, payload: CashMovementCancel, user: User
    ) -> CashMovement:
        """§10 — annotate the original row (audit trail, never deleted) and
        insert a real compensating entry in the opposite direction so the
        session's running total is corrected. Returns the compensating
        movement (the caller already has the original)."""
        if movement.cancelled_at is not None:
            raise HTTPException(
                status.HTTP_409_CONFLICT, "Cet encaissement a déjà été annulé."
            )
        if movement.reverses_movement_id is not None:
            raise HTTPException(
                status.HTTP_422_UNPROCESSABLE_ENTITY,
                "Impossible d'annuler une écriture de compensation elle-même.",
            )
        session = await self.db.get(CashSession, movement.cash_session_id)
        if session is None or session.status != CashSessionStatus.ouverte:
            raise HTTPException(
                status.HTTP_422_UNPROCESSABLE_ENTITY,
                "Impossible d'annuler un encaissement d'une session de caisse déjà fermée.",
            )

        movement.cancelled_at = utcnow()
        movement.cancelled_by = user.id
        movement.cancel_reason = payload.motif
        self.db.add(movement)

        opposite = (
            CashMovementType.sortie
            if movement.type == CashMovementType.entree
            else CashMovementType.entree
        )
        compensation = CashMovement(
            cash_session_id=movement.cash_session_id,
            type=opposite,
            amount=movement.amount,
            reason=f"Annulation — {payload.motif}",
            reference_type=ReferenceType.CASH_SESSION,
            reference_id=movement.id,
            reverses_movement_id=movement.id,
            created_by=user.id,
        )
        self.db.add(compensation)
        await self.db.flush()
        await self.db.refresh(movement)
        await self.db.refresh(compensation)

        await log_activity(
            self.db, user,
            f"Encaissement annulé — {movement.amount} GNF ({payload.motif})",
            "cash", reference_type=ReferenceType.CASH_SESSION, reference_id=movement.id,
            boutique_id=session.store_id,
        )
        return compensation
