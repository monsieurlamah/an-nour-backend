"""PaiementService.create — a créance settlement paid in cash must produce a
CashMovement on the boutique's open session, following the exact same
pattern as VenteService.create's own payment-time cash movements
(ventes/services.py:356-377). See app/modules/creances/services.py."""

from decimal import Decimal

import pytest
from fastapi import HTTPException
from sqlalchemy import select

from app.database.enums import CreanceStatut, PaiementMode, ReferenceType
from app.modules.cash.models import CashMovement
from app.modules.creances.models import Creance
from app.modules.creances.schemas import PaiementCreate
from app.modules.creances.services import PaiementService


async def _creance(db, *, client_id, boutique_id, montant=Decimal("80000")) -> Creance:
    c = Creance(
        client_id=client_id, boutique_id=boutique_id,
        montant_initial=montant, montant_restant=montant,
        statut=CreanceStatut.active,
    )
    db.add(c)
    await db.commit()
    await db.refresh(c)
    return c


def _cash_moves_of(session_id: int):
    return select(CashMovement).where(CashMovement.cash_session_id == session_id)


async def test_paiement_creance_especes_cree_un_cash_movement(
    db, store, client_, user, open_cash_session
):
    creance = await _creance(db, client_id=client_.id, boutique_id=store.id)

    paiement = await PaiementService(db).create(
        PaiementCreate(creance_id=creance.id, montant=Decimal("80000"), mode="especes"),
        user,
    )

    moves = (await db.execute(_cash_moves_of(open_cash_session.id))).scalars().all()
    assert len(moves) == 1
    assert moves[0].type == "entree"
    assert moves[0].amount == Decimal("80000")
    assert moves[0].reference_type == ReferenceType.PAIEMENT
    assert moves[0].reference_id == paiement.id


async def test_paiement_creance_mobile_money_ne_cree_pas_de_cash_movement(
    db, store, client_, user, open_cash_session
):
    creance = await _creance(db, client_id=client_.id, boutique_id=store.id)

    await PaiementService(db).create(
        PaiementCreate(
            creance_id=creance.id, montant=Decimal("80000"), mode=PaiementMode.mobile_money
        ),
        user,
    )

    moves = (await db.execute(_cash_moves_of(open_cash_session.id))).scalars().all()
    assert moves == []


async def test_paiement_creance_especes_sans_caisse_ouverte_echoue(db, store, client_, user):
    creance = await _creance(db, client_id=client_.id, boutique_id=store.id)

    with pytest.raises(HTTPException) as exc:
        await PaiementService(db).create(
            PaiementCreate(creance_id=creance.id, montant=Decimal("80000"), mode="especes"),
            user,
        )
    assert exc.value.status_code == 422


async def test_paiement_sans_user_ne_cree_pas_de_cash_movement(
    db, store, client_, user, open_cash_session
):
    """Called without `user` (the VenteService.create code path, which
    already books its own cash movement) must never create a second one."""
    creance = await _creance(db, client_id=client_.id, boutique_id=store.id)

    await PaiementService(db).create(
        PaiementCreate(creance_id=creance.id, montant=Decimal("80000"), mode="especes")
    )

    moves = (await db.execute(_cash_moves_of(open_cash_session.id))).scalars().all()
    assert moves == []
