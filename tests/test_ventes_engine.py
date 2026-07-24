"""Tests for the Ventes transactional engine (Phase 1).

Each test exercises ``VenteService.create`` directly against an isolated
in-memory SQLite session (see ``conftest.py``) — no HTTP layer involved, but
the exact same service code the API routes call.
"""

from decimal import Decimal

import pytest
from fastapi import HTTPException
from sqlalchemy import select

from app.database.enums import (
    CreanceStatut,
    MovementReason,
    MovementType,
    VenteLivraisonStatut,
    VenteStatut,
)
from app.modules.cash.models import CashMovement
from app.modules.creances.models import Creance, Paiement
from app.modules.creances.schemas import PaiementCreate
from app.modules.creances.services import PaiementService
from app.modules.stock.models import ProductStock, StockMovement
from app.modules.ventes.models import Vente
from app.modules.ventes.schemas import (
    VenteCreate,
    VenteLigneCreate,
    VentePaiementCreate,
    VenteRetourCreate,
    VenteRetourLigneCreate,
)
from app.modules.ventes.services import VenteRetourService, VenteService
from tests.conftest import assign_group, link_store_user


def _ligne(product, qty=2, price=Decimal("100000")) -> VenteLigneCreate:
    return VenteLigneCreate(produit_id=product.id, quantite=qty, prix_unitaire=price)


async def _stock_qty(db, product_id: int, location_id: int) -> int:
    row = (
        await db.execute(
            select(ProductStock).where(
                ProductStock.product_id == product_id, ProductStock.location_id == location_id
            )
        )
    ).scalar_one()
    return row.quantity


async def _all(db, stmt) -> list:
    return (await db.execute(stmt)).scalars().all()


def _paiements_of(vente_id: int):
    return select(Paiement).where(Paiement.vente_id == vente_id)


def _creances_of(vente_id: int):
    return select(Creance).where(Creance.vente_id == vente_id)


def _cash_moves_of(session_id: int):
    return select(CashMovement).where(CashMovement.cash_session_id == session_id)


# ── Vente comptant (full cash payment) ──────────────────────────────────────


async def test_vente_comptant_completee_sans_creance(
    db, store, store_location, stocked_product, user, open_cash_session
):
    payload = VenteCreate(
        boutique_id=store.id,
        lignes=[_ligne(stocked_product, qty=2, price=Decimal("100000"))],
        paiements=[VentePaiementCreate(mode="especes", montant=Decimal("200000"))],
    )
    vente = await VenteService(db).create(payload, user)

    assert vente.montant_total == Decimal("200000")
    assert vente.montant_paye == Decimal("200000")
    assert vente.montant_restant == Decimal("0")
    assert vente.statut == VenteStatut.completee
    assert vente.creance is None

    # Stock decremented + movement logged
    assert await _stock_qty(db, stocked_product.id, store_location.id) == 8
    movements = await _all(
        db, select(StockMovement).where(StockMovement.product_id == stocked_product.id)
    )
    assert len(movements) == 1
    assert movements[0].movement_type == MovementType.OUT
    assert movements[0].reason == MovementReason.SALE
    assert movements[0].quantity == 2
    assert movements[0].quantity_before == 10
    assert movements[0].quantity_after == 8

    # One Paiement, one CashMovement, zero Creance
    paiements = await _all(db, _paiements_of(vente.id))
    assert len(paiements) == 1
    assert paiements[0].montant == Decimal("200000")

    cash_moves = await _all(db, _cash_moves_of(open_cash_session.id))
    assert len(cash_moves) == 1
    assert cash_moves[0].amount == Decimal("200000")
    assert cash_moves[0].type == "entree"

    assert await _all(db, _creances_of(vente.id)) == []


# ── Vente avec paiement partiel ─────────────────────────────────────────────


async def test_vente_paiement_partiel_cree_creance_du_solde(
    db, store, store_location, stocked_product, user, client_, open_cash_session
):
    payload = VenteCreate(
        boutique_id=store.id,
        client_id=client_.id,
        lignes=[_ligne(stocked_product, qty=2, price=Decimal("100000"))],  # total 200 000
        paiements=[VentePaiementCreate(mode="especes", montant=Decimal("120000"))],
    )
    vente = await VenteService(db).create(payload, user)

    assert vente.statut == VenteStatut.partiellement_payee
    assert vente.montant_paye == Decimal("120000")
    assert vente.montant_restant == Decimal("80000")

    creance = vente.creance
    assert creance is not None
    assert creance.montant_initial == Decimal("80000")
    assert creance.montant_restant == Decimal("80000")
    assert creance.client_id == client_.id
    assert creance.statut == CreanceStatut.active

    cash_moves = await _all(db, _cash_moves_of(open_cash_session.id))
    assert len(cash_moves) == 1
    assert cash_moves[0].amount == Decimal("120000")  # never the unpaid 80 000


# ── Vente à crédit (zéro paiement) ──────────────────────────────────────────


async def test_vente_credit_sans_paiement_aucun_mouvement_caisse(
    db, store, store_location, stocked_product, user, client_
):
    payload = VenteCreate(
        boutique_id=store.id,
        client_id=client_.id,
        type_vente="credit",
        lignes=[_ligne(stocked_product, qty=1, price=Decimal("100000"))],
        paiements=[],
    )
    vente = await VenteService(db).create(payload, user)

    assert vente.statut == VenteStatut.impayee
    assert vente.montant_paye == Decimal("0")
    assert vente.montant_restant == Decimal("100000")
    assert vente.creance is not None
    assert vente.creance.montant_initial == Decimal("100000")

    # No cash session was even required since nothing was received.
    cash_moves = (await db.execute(select(CashMovement))).scalars().all()
    assert cash_moves == []


async def test_vente_credit_sans_client_rejetee(db, store, store_location, stocked_product, user):
    payload = VenteCreate(
        boutique_id=store.id,
        client_id=None,
        lignes=[_ligne(stocked_product, qty=1, price=Decimal("100000"))],
        paiements=[],
    )
    with pytest.raises(HTTPException) as exc:
        await VenteService(db).create(payload, user)
    assert exc.value.status_code == 422
    assert "client" in exc.value.detail.lower()


# ── Paiement multiple (mixte) ────────────────────────────────────────────────


async def test_paiement_multiple_cree_un_mouvement_caisse_par_paiement(
    db, store, store_location, stocked_product, user, client_, open_cash_session
):
    payload = VenteCreate(
        boutique_id=store.id,
        client_id=client_.id,
        lignes=[_ligne(stocked_product, qty=10, price=Decimal("100000"))],  # total 1 000 000
        paiements=[
            VentePaiementCreate(mode="especes", montant=Decimal("300000")),
            VentePaiementCreate(mode="mobile_money", montant=Decimal("200000"), reference="OM-123"),
        ],
    )
    vente = await VenteService(db).create(payload, user)

    assert vente.montant_paye == Decimal("500000")
    assert vente.montant_restant == Decimal("500000")
    assert vente.creance.montant_initial == Decimal("500000")

    paiements = await _all(db, _paiements_of(vente.id))
    assert len(paiements) == 2

    cash_moves = await _all(db, _cash_moves_of(open_cash_session.id))
    assert len(cash_moves) == 2
    assert sorted(m.amount for m in cash_moves) == [Decimal("200000"), Decimal("300000")]


async def test_paiements_superieurs_au_total_rejetes(
    db, store, store_location, stocked_product, user, open_cash_session
):
    payload = VenteCreate(
        boutique_id=store.id,
        lignes=[_ligne(stocked_product, qty=1, price=Decimal("100000"))],
        paiements=[VentePaiementCreate(mode="especes", montant=Decimal("150000"))],
    )
    with pytest.raises(HTTPException) as exc:
        await VenteService(db).create(payload, user)
    assert exc.value.status_code == 422


# ── Stock insuffisant ────────────────────────────────────────────────────────


async def test_stock_insuffisant_rejete_avant_toute_ecriture(
    db, store, store_location, stocked_product, user, client_
):
    payload = VenteCreate(
        boutique_id=store.id,
        client_id=client_.id,
        lignes=[_ligne(stocked_product, qty=999, price=Decimal("100000"))],
        paiements=[],
        type_vente="directe",
    )
    with pytest.raises(HTTPException) as exc:
        await VenteService(db).create(payload, user)
    assert exc.value.status_code == 422
    assert "stock insuffisant" in exc.value.detail.lower()

    assert (await db.execute(select(Vente))).scalars().all() == []
    assert await _stock_qty(db, stocked_product.id, store_location.id) == 10


# ── Rollback complet si une étape tardive échoue ─────────────────────────────


async def test_rollback_complet_si_pas_de_session_caisse_ouverte(
    db, store, store_location, stocked_product, user
):
    """No open CashSession exists for the store — the failure happens *after*
    the Vente, lignes and stock movement have already been flushed (steps
    3-4), proving the whole operation rolls back as one unit, not just the
    failing step."""
    # Captured before rollback expires every object in the session's identity
    # map — accessing an expired attribute outside an awaited DB call raises
    # MissingGreenlet under the async driver.
    product_id = stocked_product.id
    location_id = store_location.id

    payload = VenteCreate(
        boutique_id=store.id,
        lignes=[_ligne(stocked_product, qty=2, price=Decimal("100000"))],
        paiements=[VentePaiementCreate(mode="especes", montant=Decimal("200000"))],
    )
    with pytest.raises(HTTPException) as exc:
        await VenteService(db).create(payload, user)
    assert exc.value.status_code == 422
    assert "caisse" in exc.value.detail.lower()

    await db.rollback()

    assert (await db.execute(select(Vente))).scalars().all() == []
    assert (await db.execute(select(StockMovement))).scalars().all() == []
    assert (await db.execute(select(Paiement))).scalars().all() == []
    # Stock must be back to its pre-attempt level after rollback.
    assert await _stock_qty(db, product_id, location_id) == 10


async def test_aucun_emplacement_stock_pour_la_boutique(db, store, product, user, client_):
    """Store has no STORE-type StockLocation configured at all."""
    payload = VenteCreate(
        boutique_id=store.id,
        client_id=client_.id,
        lignes=[_ligne(product, qty=1, price=Decimal("100000"))],
        paiements=[],
    )
    with pytest.raises(HTTPException) as exc:
        await VenteService(db).create(payload, user)
    assert exc.value.status_code == 422
    assert "emplacement de stock" in exc.value.detail.lower()


# ── Livraison différée (non_livre) ──────────────────────────────────────────


async def test_vente_livree_par_defaut_genere_bon_livraison_immediatement(
    db, store, store_location, stocked_product, user, open_cash_session
):
    payload = VenteCreate(
        boutique_id=store.id,
        lignes=[_ligne(stocked_product, qty=2, price=Decimal("100000"))],
        paiements=[VentePaiementCreate(mode="especes", montant=Decimal("200000"))],
    )
    vente = await VenteService(db).create(payload, user)

    assert vente.livraison_statut == VenteLivraisonStatut.livre
    assert vente.numero_bon_livraison is not None
    assert vente.numero_bon_livraison.startswith("BL-")
    assert vente.livree_at is not None
    assert vente.livree_by == user.id
    assert await _stock_qty(db, stocked_product.id, store_location.id) == 8


async def test_vente_non_livre_ne_decremente_pas_le_stock(
    db, store, store_location, stocked_product, user, open_cash_session
):
    payload = VenteCreate(
        boutique_id=store.id,
        lignes=[_ligne(stocked_product, qty=2, price=Decimal("100000"))],
        paiements=[VentePaiementCreate(mode="especes", montant=Decimal("200000"))],
        livraison_statut=VenteLivraisonStatut.non_livre,
    )
    vente = await VenteService(db).create(payload, user)

    assert vente.livraison_statut == VenteLivraisonStatut.non_livre
    assert vente.numero_bon_livraison is None
    assert vente.livree_at is None
    # Payment is entirely independent from delivery — still fully paid.
    assert vente.statut == VenteStatut.completee

    # Stock untouched, no movement logged at all.
    assert await _stock_qty(db, stocked_product.id, store_location.id) == 10
    movements = await _all(
        db, select(StockMovement).where(StockMovement.product_id == stocked_product.id)
    )
    assert movements == []


async def test_confirm_livraison_decremente_stock_et_genere_bon_livraison(
    db, store, store_location, stocked_product, user, other_user, open_cash_session
):
    payload = VenteCreate(
        boutique_id=store.id,
        lignes=[_ligne(stocked_product, qty=3, price=Decimal("100000"))],
        paiements=[VentePaiementCreate(mode="especes", montant=Decimal("300000"))],
        livraison_statut=VenteLivraisonStatut.non_livre,
    )
    vente = await VenteService(db).create(payload, user)
    assert await _stock_qty(db, stocked_product.id, store_location.id) == 10

    vente = await VenteService(db).confirm_livraison(vente, other_user)

    assert vente.livraison_statut == VenteLivraisonStatut.livre
    assert vente.numero_bon_livraison is not None
    assert vente.numero_bon_livraison.startswith("BL-")
    assert vente.livree_at is not None
    assert vente.livree_by == other_user.id
    assert await _stock_qty(db, stocked_product.id, store_location.id) == 7

    movements = await _all(
        db, select(StockMovement).where(StockMovement.product_id == stocked_product.id)
    )
    assert len(movements) == 1
    assert movements[0].movement_type == MovementType.OUT
    assert movements[0].reason == MovementReason.SALE
    assert movements[0].quantity == 3


async def test_confirm_livraison_rejects_already_livree(
    db, store, store_location, stocked_product, user, open_cash_session
):
    payload = VenteCreate(
        boutique_id=store.id,
        lignes=[_ligne(stocked_product, qty=1, price=Decimal("100000"))],
        paiements=[VentePaiementCreate(mode="especes", montant=Decimal("100000"))],
    )
    vente = await VenteService(db).create(payload, user)  # livre by default

    with pytest.raises(HTTPException) as exc:
        await VenteService(db).confirm_livraison(vente, user)
    assert exc.value.status_code == 409


async def test_void_non_livre_ne_restaure_pas_le_stock(
    db, store, store_location, stocked_product, user, open_cash_session
):
    """A non_livre sale never took stock — voiding it must not invent some."""
    payload = VenteCreate(
        boutique_id=store.id,
        lignes=[_ligne(stocked_product, qty=2, price=Decimal("100000"))],
        paiements=[VentePaiementCreate(mode="especes", montant=Decimal("200000"))],
        livraison_statut=VenteLivraisonStatut.non_livre,
    )
    vente = await VenteService(db).create(payload, user)
    assert await _stock_qty(db, stocked_product.id, store_location.id) == 10

    vente = await VenteService(db).void(vente, user)

    assert vente.statut == VenteStatut.annulee
    # Still 10 — must NOT become 12 (which would happen if void blindly restored).
    assert await _stock_qty(db, stocked_product.id, store_location.id) == 10


async def test_retour_rejete_si_vente_non_livree(
    db, store, store_location, stocked_product, user, open_cash_session
):
    payload = VenteCreate(
        boutique_id=store.id,
        lignes=[_ligne(stocked_product, qty=2, price=Decimal("100000"))],
        paiements=[VentePaiementCreate(mode="especes", montant=Decimal("200000"))],
        livraison_statut=VenteLivraisonStatut.non_livre,
    )
    vente = await VenteService(db).create(payload, user)

    with pytest.raises(HTTPException) as exc:
        await VenteRetourService(db).create(
            vente,
            VenteRetourCreate(
                lignes=[VenteRetourLigneCreate(vente_ligne_id=vente.lignes[0].id, quantite=1)],
                motif="Test",
            ),
            user,
        )
    assert exc.value.status_code == 422


# ── Paiement d'une créance synchronise le statut de la vente ────────────────


async def test_paiement_creance_synchronise_statut_vente_vers_completee(
    db, store, store_location, stocked_product, user, client_, open_cash_session
):
    payload = VenteCreate(
        boutique_id=store.id,
        client_id=client_.id,
        lignes=[_ligne(stocked_product, qty=2, price=Decimal("100000"))],  # total 200 000
        paiements=[VentePaiementCreate(mode="especes", montant=Decimal("120000"))],
    )
    vente = await VenteService(db).create(payload, user)
    assert vente.statut == VenteStatut.partiellement_payee

    await PaiementService(db).create(
        PaiementCreate(creance_id=vente.creance.id, montant=Decimal("80000"), mode="especes")
    )
    await db.refresh(vente, attribute_names=["paiements"])

    assert vente.statut == VenteStatut.completee
    assert vente.creance.statut == CreanceStatut.soldee


# ── HTTP-level regression: response serialization must not crash ───────────
#
# Unlike every other test above (service layer only), this one drives a real
# request through the FastAPI app (see test_authz.py for why: only the full
# stack exercises Pydantic's VenteRead.model_validate on the returned ORM
# object). It exists because a credit sale used to 500 here: setting the
# livraison fields mid-`create()` triggers an UPDATE, and `updated_at`
# (`onupdate=func.now()`) gets expired by SQLAlchemy as a result; the
# following `refresh(attribute_names=["paiements", "creance"])` only reloads
# those two relationships and never clears that expiry, so the first later
# access to `.updated_at` — Pydantic, during response serialization — tries
# a lazy load outside of Starlette's async-safe context and hard-crashes.


async def test_credit_sale_with_partial_payment_does_not_crash_http_response(
    client, db, rbac, store, store_location, stocked_product, client_, user, login_as,
    open_cash_session,
):
    await assign_group(db, user, rbac["gerant-boutique"])
    await link_store_user(db, store, user)
    login_as(user)

    resp = await client.post(
        "/api/v1/ventes",
        json={
            "boutique_id": store.id,
            "client_id": client_.id,
            "lignes": [{"produit_id": stocked_product.id, "quantite": 1, "prix_unitaire": 250000}],
            "paiements": [{"mode": "especes", "montant": 100000}],
        },
    )
    assert resp.status_code == 201, resp.text
    body = resp.json()
    assert body["statut"] == "partiellement_payee"
    assert body["montant_restant"] == "150000.00"
    assert body["livraison_statut"] == "livre"
    assert body["numero_bon_livraison"] is not None
