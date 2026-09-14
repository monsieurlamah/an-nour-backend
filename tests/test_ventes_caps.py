"""Tests for the two per-boutique/per-client business caps added to close
cahier des charges gaps:
  §9.2 — taux de remise maximum autorisé, paramétrable par boutique.
  §8.1 — plafond de créance autorisé par client, avec blocage au-delà.
"""

from decimal import Decimal

import pytest
from fastapi import HTTPException

from app.modules.ventes.schemas import VenteCreate, VenteLigneCreate, VenteProformaCreate
from app.modules.ventes.services import VenteService


def _ligne(product, qty=1, price=Decimal("100000"), remise=Decimal("0")) -> VenteLigneCreate:
    return VenteLigneCreate(produit_id=product.id, quantite=qty, prix_unitaire=price, remise=remise)


# ── §9.2 remise cap ──────────────────────────────────────────────────────────


async def test_remise_within_cap_is_accepted(db, store, stocked_product, user):
    store.remise_max_percent = Decimal("20")
    db.add(store)
    await db.commit()

    payload = VenteProformaCreate(
        boutique_id=store.id,
        remise=Decimal("15000"),  # 15% of 100000
        lignes=[_ligne(stocked_product, qty=1, price=Decimal("100000"))],
    )
    vente = await VenteService(db).create_proforma(payload, user)
    assert vente.montant_total == Decimal("85000")


async def test_remise_over_cap_rejected(db, store, stocked_product, user):
    store.remise_max_percent = Decimal("10")
    db.add(store)
    await db.commit()

    payload = VenteProformaCreate(
        boutique_id=store.id,
        remise=Decimal("25000"),  # 25% of 100000 > 10% cap
        lignes=[_ligne(stocked_product, qty=1, price=Decimal("100000"))],
    )
    with pytest.raises(HTTPException) as exc:
        await VenteService(db).create_proforma(payload, user)
    assert exc.value.status_code == 422
    assert "remise" in exc.value.detail.lower()


async def test_remise_cumulates_line_and_global_against_cap(db, store, stocked_product, user):
    """Line remise + global remise are cumulable (§9.2) — their COMBINED
    rate must respect the cap, not each checked separately."""
    store.remise_max_percent = Decimal("15")
    db.add(store)
    await db.commit()

    payload = VenteProformaCreate(
        boutique_id=store.id,
        remise=Decimal("6000"),  # +6% on top of the line's own 10% = 16% > 15% cap
        lignes=[_ligne(stocked_product, qty=1, price=Decimal("100000"), remise=Decimal("10000"))],
    )
    with pytest.raises(HTTPException) as exc:
        await VenteService(db).create_proforma(payload, user)
    assert exc.value.status_code == 422


async def test_no_cap_configured_is_unrestricted(db, store, stocked_product, user):
    """Store.remise_max_percent defaults to NULL — existing stores keep
    today's unrestricted behaviour until an owner explicitly sets a cap."""
    assert store.remise_max_percent is None
    payload = VenteProformaCreate(
        boutique_id=store.id,
        remise=Decimal("90000"),  # 90% — would fail any real cap
        lignes=[_ligne(stocked_product, qty=1, price=Decimal("100000"))],
    )
    vente = await VenteService(db).create_proforma(payload, user)
    assert vente.montant_total == Decimal("10000")


async def test_remise_cap_enforced_on_direct_sale(
    db, store, store_location, stocked_product, user, open_cash_session
):
    store.remise_max_percent = Decimal("5")
    db.add(store)
    await db.commit()

    payload = VenteCreate(
        boutique_id=store.id,
        remise=Decimal("50000"),  # 50% > 5% cap
        lignes=[_ligne(stocked_product, qty=1, price=Decimal("100000"))],
        paiements=[],
    )
    with pytest.raises(HTTPException) as exc:
        await VenteService(db).create(payload, user)
    assert exc.value.status_code == 422


# ── §8.1 plafond de crédit client ────────────────────────────────────────────


async def test_credit_sale_within_ceiling_accepted(
    db, store, store_location, stocked_product, user, client_
):
    client_.plafond_credit = Decimal("200000")
    db.add(client_)
    await db.commit()

    payload = VenteCreate(
        boutique_id=store.id,
        client_id=client_.id,
        lignes=[_ligne(stocked_product, qty=1, price=Decimal("100000"))],
        paiements=[],  # fully on credit — 100000 <= 200000 ceiling
    )
    vente = await VenteService(db).create(payload, user)
    assert vente.montant_restant == Decimal("100000")


async def test_credit_sale_over_ceiling_rejected(
    db, store, store_location, stocked_product, user, client_
):
    client_.plafond_credit = Decimal("50000")
    db.add(client_)
    await db.commit()

    payload = VenteCreate(
        boutique_id=store.id,
        client_id=client_.id,
        lignes=[_ligne(stocked_product, qty=1, price=Decimal("100000"))],
        paiements=[],  # 100000 > 50000 ceiling
    )
    with pytest.raises(HTTPException) as exc:
        await VenteService(db).create(payload, user)
    assert exc.value.status_code == 422
    assert "plafond" in exc.value.detail.lower()


async def test_credit_ceiling_accounts_for_existing_outstanding_balance(
    db, store, store_location, stocked_product, user, client_
):
    """A second credit sale must consider the créance the FIRST one already
    left outstanding — the ceiling is on the client's total encours, not
    per-sale."""
    client_.plafond_credit = Decimal("120000")
    db.add(client_)
    await db.commit()

    first = VenteCreate(
        boutique_id=store.id,
        client_id=client_.id,
        lignes=[_ligne(stocked_product, qty=1, price=Decimal("100000"))],
        paiements=[],
    )
    await VenteService(db).create(first, user)  # encours now 100000

    second = VenteCreate(
        boutique_id=store.id,
        client_id=client_.id,
        lignes=[_ligne(stocked_product, qty=1, price=Decimal("50000"))],
        paiements=[],  # 100000 + 50000 = 150000 > 120000 ceiling
    )
    with pytest.raises(HTTPException) as exc:
        await VenteService(db).create(second, user)
    assert exc.value.status_code == 422


async def test_zero_plafond_means_unrestricted(
    db, store, store_location, stocked_product, user, client_
):
    """plafond_credit defaults to 0 — the model's own default for every
    client created before this cap existed — which must mean "no ceiling
    configured", not "credit forbidden"."""
    assert client_.plafond_credit == Decimal("0")
    payload = VenteCreate(
        boutique_id=store.id,
        client_id=client_.id,
        lignes=[_ligne(stocked_product, qty=1, price=Decimal("999000"))],
        paiements=[],
    )
    vente = await VenteService(db).create(payload, user)
    assert vente.montant_restant == Decimal("999000")
