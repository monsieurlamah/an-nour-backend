"""Tests for VenteRetourService and VenteRemboursementService.

Same in-memory SQLite fixtures as ``test_ventes_engine.py`` — each test
exercises the service directly, no HTTP layer involved.
"""

from decimal import Decimal

import pytest
from fastapi import HTTPException
from sqlalchemy import select

from app.database.enums import CashMovementType, CreanceStatut, VenteStatut
from app.modules.cash.models import CashMovement
from app.modules.ventes.models import Vente
from app.modules.ventes.schemas import (
    VenteCreate,
    VenteLigneCreate,
    VentePaiementCreate,
    VenteRemboursementCreate,
    VenteRetourCreate,
    VenteRetourLigneCreate,
)
from app.modules.ventes.services import VenteRemboursementService, VenteRetourService, VenteService


def _ligne(product, qty=5, price=Decimal("100000")) -> VenteLigneCreate:
    return VenteLigneCreate(produit_id=product.id, quantite=qty, prix_unitaire=price)


async def _stock_qty(db, product_id: int, location_id: int) -> int:
    from app.modules.stock.models import ProductStock

    row = (
        await db.execute(
            select(ProductStock).where(
                ProductStock.product_id == product_id, ProductStock.location_id == location_id
            )
        )
    ).scalar_one()
    return row.quantity


async def _vente_comptant(db, store, stocked_product, user, open_cash_session, qty=5):
    payload = VenteCreate(
        boutique_id=store.id,
        lignes=[_ligne(stocked_product, qty=qty)],
        paiements=[VentePaiementCreate(mode="especes", montant=Decimal("100000") * qty)],
    )
    return await VenteService(db).create(payload, user)


async def _vente_credit_partielle(
    db, store, stocked_product, user, client_, open_cash_session, qty=5
):
    """5 units @ 100 000, only 200 000 paid → créance of 300 000."""
    payload = VenteCreate(
        boutique_id=store.id,
        client_id=client_.id,
        lignes=[_ligne(stocked_product, qty=qty)],
        paiements=[VentePaiementCreate(mode="especes", montant=Decimal("200000"))],
    )
    return await VenteService(db).create(payload, user)


# ── Retours ──────────────────────────────────────────────────────────────────


async def test_retour_proratise_la_remise_de_ligne(
    db, store, store_location, stocked_product, user, open_cash_session
):
    """A line sold at 100 000/unit with a 20 000 line-wide remise (2 units,
    total 180 000) nets to 90 000/unit. Returning 1 unit must restitute
    90 000 — the price actually paid — never the pre-remise 100 000."""
    payload = VenteCreate(
        boutique_id=store.id,
        lignes=[VenteLigneCreate(
            produit_id=stocked_product.id, quantite=2,
            prix_unitaire=Decimal("100000"), remise=Decimal("20000"),
        )],
        paiements=[VentePaiementCreate(mode="especes", montant=Decimal("180000"))],
    )
    vente = await VenteService(db).create(payload, user)
    assert vente.lignes[0].total_ligne == Decimal("180000")
    ligne_id = vente.lignes[0].id

    retour = await VenteRetourService(db).create(
        vente,
        VenteRetourCreate(
            lignes=[VenteRetourLigneCreate(vente_ligne_id=ligne_id, quantite=1)],
            motif="Erreur de prix",
        ),
        user,
    )

    assert retour.total_retourne == Decimal("90000")
    assert retour.lignes[0].prix_unitaire == Decimal("90000")


async def test_retour_partiel_restaure_stock_et_marque_partiellement_retournee(
    db, store, store_location, stocked_product, user, open_cash_session
):
    vente = await _vente_comptant(db, store, stocked_product, user, open_cash_session, qty=5)
    assert await _stock_qty(db, stocked_product.id, store_location.id) == 5

    ligne_id = vente.lignes[0].id
    retour = await VenteRetourService(db).create(
        vente,
        VenteRetourCreate(
            lignes=[VenteRetourLigneCreate(vente_ligne_id=ligne_id, quantite=2)],
            motif="Produit défectueux",
        ),
        user,
    )

    assert retour.total_retourne == Decimal("200000")
    assert len(retour.lignes) == 1
    assert retour.lignes[0].quantite == 2

    assert await _stock_qty(db, stocked_product.id, store_location.id) == 7

    await db.refresh(vente)
    assert vente.statut == VenteStatut.partiellement_retournee


async def test_retour_total_marque_vente_retournee(
    db, store, store_location, stocked_product, user, open_cash_session
):
    vente = await _vente_comptant(db, store, stocked_product, user, open_cash_session, qty=3)
    ligne_id = vente.lignes[0].id

    await VenteRetourService(db).create(
        vente,
        VenteRetourCreate(
            lignes=[VenteRetourLigneCreate(vente_ligne_id=ligne_id, quantite=3)],
            motif="Client insatisfait",
        ),
        user,
    )

    await db.refresh(vente)
    assert vente.statut == VenteStatut.retournee
    assert await _stock_qty(db, stocked_product.id, store_location.id) == 10


async def test_retours_cumulatifs_marquent_retournee_une_fois_tout_rendu(
    db, store, store_location, stocked_product, user, open_cash_session
):
    vente = await _vente_comptant(db, store, stocked_product, user, open_cash_session, qty=4)
    ligne_id = vente.lignes[0].id
    service = VenteRetourService(db)

    await service.create(
        vente,
        VenteRetourCreate(
            lignes=[VenteRetourLigneCreate(vente_ligne_id=ligne_id, quantite=1)], motif="Retour 1"
        ),
        user,
    )
    await db.refresh(vente)
    assert vente.statut == VenteStatut.partiellement_retournee

    await service.create(
        vente,
        VenteRetourCreate(
            lignes=[VenteRetourLigneCreate(vente_ligne_id=ligne_id, quantite=3)], motif="Retour 2"
        ),
        user,
    )
    await db.refresh(vente)
    assert vente.statut == VenteStatut.retournee

    retours = await service.list(vente.id)
    assert len(retours) == 2


async def test_retour_quantite_superieure_a_vendue_rejete(
    db, store, store_location, stocked_product, user, open_cash_session
):
    vente = await _vente_comptant(db, store, stocked_product, user, open_cash_session, qty=2)
    ligne_id = vente.lignes[0].id

    with pytest.raises(HTTPException) as exc:
        await VenteRetourService(db).create(
            vente,
            VenteRetourCreate(
                lignes=[VenteRetourLigneCreate(vente_ligne_id=ligne_id, quantite=5)],
                motif="Erreur",
            ),
            user,
        )
    assert exc.value.status_code == 422
    assert "vendue" in exc.value.detail.lower()

    # Nothing must have moved.
    assert await _stock_qty(db, stocked_product.id, store_location.id) == 8


async def test_retour_ligne_hors_vente_rejete(
    db, store, store_location, stocked_product, user, open_cash_session
):
    vente = await _vente_comptant(db, store, stocked_product, user, open_cash_session, qty=2)

    with pytest.raises(HTTPException) as exc:
        await VenteRetourService(db).create(
            vente,
            VenteRetourCreate(
                lignes=[VenteRetourLigneCreate(vente_ligne_id=999999, quantite=1)],
                motif="Erreur",
            ),
            user,
        )
    assert exc.value.status_code == 422
    assert "n'appartient pas" in exc.value.detail.lower()


async def test_retour_sur_vente_annulee_rejete(
    db, store, store_location, stocked_product, user, open_cash_session
):
    vente = await _vente_comptant(db, store, stocked_product, user, open_cash_session, qty=2)
    await VenteService(db).void(vente, user)
    ligne_id = vente.lignes[0].id

    with pytest.raises(HTTPException) as exc:
        await VenteRetourService(db).create(
            vente,
            VenteRetourCreate(
                lignes=[VenteRetourLigneCreate(vente_ligne_id=ligne_id, quantite=1)],
                motif="Erreur",
            ),
            user,
        )
    assert exc.value.status_code == 422
    assert "annulée" in exc.value.detail.lower()


async def test_retour_partiel_reduit_la_creance(
    db, store, store_location, stocked_product, user, client_, open_cash_session
):
    vente = await _vente_credit_partielle(
        db, store, stocked_product, user, client_, open_cash_session, qty=5
    )
    assert vente.creance.montant_restant == Decimal("300000")
    ligne_id = vente.lignes[0].id

    # Return 1 unit (100 000) — less than the 300 000 still owed.
    await VenteRetourService(db).create(
        vente,
        VenteRetourCreate(
            lignes=[VenteRetourLigneCreate(vente_ligne_id=ligne_id, quantite=1)],
            motif="Retour partiel",
        ),
        user,
    )

    await db.refresh(vente)
    await db.refresh(vente.creance)
    assert vente.creance.montant_restant == Decimal("200000")
    assert vente.creance.statut == CreanceStatut.active


async def test_retour_total_annule_la_creance_entierement(
    db, store, store_location, stocked_product, user, client_, open_cash_session
):
    vente = await _vente_credit_partielle(
        db, store, stocked_product, user, client_, open_cash_session, qty=5
    )
    ligne_id = vente.lignes[0].id

    await VenteRetourService(db).create(
        vente,
        VenteRetourCreate(
            lignes=[VenteRetourLigneCreate(vente_ligne_id=ligne_id, quantite=5)],
            motif="Retour total",
        ),
        user,
    )

    await db.refresh(vente)
    await db.refresh(vente.creance)
    assert vente.statut == VenteStatut.retournee
    assert vente.creance.statut == CreanceStatut.annulee
    assert vente.creance.montant_restant == Decimal("0")


# ── Remboursements ───────────────────────────────────────────────────────────


async def test_remboursement_cree_mouvement_caisse_sortie(
    db, store, store_location, stocked_product, user, open_cash_session
):
    vente = await _vente_comptant(db, store, stocked_product, user, open_cash_session, qty=2)

    remboursement = await VenteRemboursementService(db).create(
        vente,
        VenteRemboursementCreate(
            montant=Decimal("100000"), mode="especes", motif="Geste commercial"
        ),
        user,
    )

    assert remboursement.montant == Decimal("100000")
    assert remboursement.retour_id is None

    cash_moves = (
        await db.execute(
            select(CashMovement).where(CashMovement.cash_session_id == open_cash_session.id)
        )
    ).scalars().all()
    sorties = [m for m in cash_moves if m.type == CashMovementType.sortie]
    assert len(sorties) == 1
    assert sorties[0].amount == Decimal("100000")


async def test_remboursement_partiel_marque_partiellement_remboursee(
    db, store, store_location, stocked_product, user, open_cash_session
):
    vente = await _vente_comptant(db, store, stocked_product, user, open_cash_session, qty=2)
    # montant_paye = 200 000

    await VenteRemboursementService(db).create(
        vente,
        VenteRemboursementCreate(montant=Decimal("50000"), mode="especes", motif="Partiel"),
        user,
    )

    await db.refresh(vente)
    assert vente.statut == VenteStatut.partiellement_remboursee


async def test_remboursement_total_marque_vente_remboursee(
    db, store, store_location, stocked_product, user, open_cash_session
):
    vente = await _vente_comptant(db, store, stocked_product, user, open_cash_session, qty=2)
    # montant_paye = 200 000

    await VenteRemboursementService(db).create(
        vente,
        VenteRemboursementCreate(montant=Decimal("200000"), mode="especes", motif="Total"),
        user,
    )

    await db.refresh(vente)
    assert vente.statut == VenteStatut.remboursee


async def test_remboursement_sans_session_caisse_ouverte_rejete(
    db, store, store_location, stocked_product, user
):
    """No open_cash_session fixture used here — the sale itself needs a cash
    session to receive payment, so we void it first isn't relevant; instead
    we simulate the session having been closed after the sale completed."""
    from app.database.enums import CashSessionStatus
    from app.modules.cash.models import CashSession

    cs = CashSession(
        store_id=store.id, opened_by=user.id, opening_amount=Decimal("0"),
        status=CashSessionStatus.ouverte,
    )
    db.add(cs)
    await db.commit()
    await db.refresh(cs)

    vente = await _vente_comptant(db, store, stocked_product, user, cs, qty=2)

    # Close the session — no open cash session remains for the store.
    cs.status = CashSessionStatus.fermee
    db.add(cs)
    await db.commit()

    with pytest.raises(HTTPException) as exc:
        await VenteRemboursementService(db).create(
            vente,
            VenteRemboursementCreate(montant=Decimal("50000"), mode="especes", motif="Erreur"),
            user,
        )
    assert exc.value.status_code == 422
    assert "caisse" in exc.value.detail.lower()


async def test_remboursement_lie_a_un_retour(
    db, store, store_location, stocked_product, user, open_cash_session
):
    vente = await _vente_comptant(db, store, stocked_product, user, open_cash_session, qty=2)
    ligne_id = vente.lignes[0].id

    retour = await VenteRetourService(db).create(
        vente,
        VenteRetourCreate(
            lignes=[VenteRetourLigneCreate(vente_ligne_id=ligne_id, quantite=1)],
            motif="Défectueux",
        ),
        user,
    )

    remboursement = await VenteRemboursementService(db).create(
        vente,
        VenteRemboursementCreate(
            montant=Decimal("100000"), mode="especes", motif="Remb. sur retour",
            retour_id=retour.id,
        ),
        user,
    )

    assert remboursement.retour_id == retour.id


async def test_retour_et_remboursement_visibles_via_get(
    db, store, store_location, stocked_product, user, open_cash_session
):
    vente = await _vente_comptant(db, store, stocked_product, user, open_cash_session, qty=2)
    ligne_id = vente.lignes[0].id

    await VenteRetourService(db).create(
        vente,
        VenteRetourCreate(
            lignes=[VenteRetourLigneCreate(vente_ligne_id=ligne_id, quantite=1)], motif="Test"
        ),
        user,
    )
    await VenteRemboursementService(db).create(
        vente,
        VenteRemboursementCreate(montant=Decimal("100000"), mode="especes", motif="Test"),
        user,
    )

    retours = await VenteRetourService(db).list(vente.id)
    remboursements = await VenteRemboursementService(db).list(vente.id)
    assert len(retours) == 1
    assert len(remboursements) == 1

    reloaded = await db.get(Vente, vente.id)
    assert reloaded is not None
