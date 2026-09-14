"""Tests for CashMovementService.cancel — cahier des charges §10:
"Gestion des annulations/corrections d'encaissement avec motif et
validation." CashMovement stays append-only (see the model docstring) —
cancelling never mutates amount/type, it annotates the original and adds a
real compensating entry."""

from decimal import Decimal

import pytest
from fastapi import HTTPException

from app.database.enums import CashMovementType, CashSessionStatus
from app.modules.cash.models import CashMovement
from app.modules.cash.schemas import CashMovementCancel, CashMovementCreate, CashSessionClose
from app.modules.cash.services import CashMovementService, CashSessionService


async def _movement(db, session, user, amount=Decimal("50000")) -> CashMovement:
    return await CashMovementService(db).create(
        CashMovementCreate(
            cash_session_id=session.id, type=CashMovementType.entree,
            amount=amount, reason="Vente comptant",
        ),
        user,
    )


async def test_cancel_creates_compensating_movement(db, open_cash_session, user):
    movement = await _movement(db, open_cash_session, user, amount=Decimal("50000"))

    compensation = await CashMovementService(db).cancel(
        movement, CashMovementCancel(motif="Erreur de saisie"), user
    )

    assert compensation.type == CashMovementType.sortie
    assert compensation.amount == Decimal("50000")
    assert compensation.reverses_movement_id == movement.id

    await db.refresh(movement)
    assert movement.cancelled_at is not None
    assert movement.cancelled_by == user.id
    assert movement.cancel_reason == "Erreur de saisie"
    # The original's own type/amount are NEVER mutated — append-only.
    assert movement.type == CashMovementType.entree
    assert movement.amount == Decimal("50000")


async def test_cancel_twice_rejected(db, open_cash_session, user):
    movement = await _movement(db, open_cash_session, user)
    await CashMovementService(db).cancel(movement, CashMovementCancel(motif="Erreur"), user)

    with pytest.raises(HTTPException) as exc:
        await CashMovementService(db).cancel(movement, CashMovementCancel(motif="Encore"), user)
    assert exc.value.status_code == 409


async def test_cancel_a_compensation_rejected(db, open_cash_session, user):
    movement = await _movement(db, open_cash_session, user)
    compensation = await CashMovementService(db).cancel(
        movement, CashMovementCancel(motif="Erreur"), user
    )

    with pytest.raises(HTTPException) as exc:
        await CashMovementService(db).cancel(
            compensation, CashMovementCancel(motif="Double annulation"), user
        )
    assert exc.value.status_code == 422


async def test_cancel_after_session_closed_rejected(db, open_cash_session, user):
    movement = await _movement(db, open_cash_session, user)
    await CashSessionService(db).close(
        open_cash_session, CashSessionClose(closing_amount=Decimal("50000")), user,
    )
    assert open_cash_session.status == CashSessionStatus.fermee

    with pytest.raises(HTTPException) as exc:
        await CashMovementService(db).cancel(movement, CashMovementCancel(motif="Trop tard"), user)
    assert exc.value.status_code == 422
