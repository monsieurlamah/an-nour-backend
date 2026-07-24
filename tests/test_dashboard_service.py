"""Tests for DashboardService — store scoping, custom date-range filtering,
caisse (cash session) balance, and décaissement aggregation.

Ventes/paiements/cash rows are inserted directly (not via VenteService) so
each test has full control over ``created_at`` — the dashboard reads raw
tables, so this is a faithful, much simpler substitute than going through
the full sales engine for pure aggregation checks.
"""

from datetime import date, datetime, timedelta
from decimal import Decimal

import pytest_asyncio

from app.database.enums import CashMovementType, CashSessionStatus, VenteStatut
from app.modules.cash.models import CashMovement, CashSession
from app.modules.dashboard.services import DashboardService
from app.modules.ventes.models import Vente, VenteLigne

# Matches the service's own `date.today()` reference point exactly, so tests
# never race a UTC/local midnight mismatch.
TODAY = datetime.combine(date.today(), datetime.min.time())


async def _vente(db, store_id, montant, created_at, statut=VenteStatut.completee) -> Vente:
    v = Vente(boutique_id=store_id, montant_total=montant, statut=statut, created_at=created_at)
    db.add(v)
    await db.flush()
    return v


async def _ligne(db, vente_id, product_id, quantite, prix_unitaire) -> VenteLigne:
    total = Decimal(quantite) * prix_unitaire
    lig = VenteLigne(
        vente_id=vente_id, produit_id=product_id, quantite=quantite,
        prix_unitaire=prix_unitaire, total_ligne=total,
    )
    db.add(lig)
    await db.flush()
    return lig


@pytest_asyncio.fixture
async def store2(db, store):
    from app.modules.stores.models import Store
    s = Store(name="Boutique 2 Test", slug="boutique-2-test")
    db.add(s)
    await db.commit()
    await db.refresh(s)
    return s


async def test_kpi_scoped_to_boutique_excludes_other_stores(db, store, store2, product):
    await _vente(db, store.id, Decimal("100000"), TODAY)
    await _vente(db, store2.id, Decimal("999999"), TODAY)
    await db.commit()

    stats = await DashboardService(db).get_stats(store.id)

    assert stats.kpi.ca_mois == Decimal("100000")
    assert stats.kpi.ventes_mois == 1


async def test_hq_view_aggregates_across_stores(db, store, store2):
    await _vente(db, store.id, Decimal("100000"), TODAY)
    await _vente(db, store2.id, Decimal("50000"), TODAY)
    await db.commit()

    stats = await DashboardService(db).get_stats(None)

    assert stats.kpi.ca_mois == Decimal("150000")
    assert stats.kpi.ventes_mois == 2


async def test_custom_date_range_filters_ca(db, store):
    old = await _vente(db, store.id, Decimal("70000"), TODAY - timedelta(days=10))
    recent = await _vente(db, store.id, Decimal("30000"), TODAY)
    await db.commit()

    today_only = await DashboardService(db).get_stats(
        store.id, date_from=TODAY.date(), date_to=TODAY.date()
    )
    assert today_only.kpi.ca_mois == Decimal("30000")
    assert today_only.kpi.ventes_mois == 1

    full_range = await DashboardService(db).get_stats(
        store.id, date_from=(TODAY - timedelta(days=10)).date(), date_to=TODAY.date()
    )
    assert full_range.kpi.ca_mois == Decimal("100000")
    assert full_range.kpi.ventes_mois == 2
    assert old.id and recent.id  # both rows genuinely used


async def test_produits_vendus_sums_quantities(db, store, product):
    v = await _vente(db, store.id, Decimal("0"), TODAY)
    await _ligne(db, v.id, product.id, 3, Decimal("1000"))
    await _ligne(db, v.id, product.id, 5, Decimal("1000"))
    await db.commit()

    stats = await DashboardService(db).get_stats(store.id)
    assert stats.kpi.produits_vendus == 8


async def test_annulee_ventes_excluded_from_kpis(db, store, product):
    await _vente(db, store.id, Decimal("50000"), TODAY, statut=VenteStatut.annulee)
    await db.commit()

    stats = await DashboardService(db).get_stats(store.id)
    assert stats.kpi.ca_mois == Decimal("0")
    assert stats.kpi.ventes_mois == 0


async def test_caisse_solde_reflects_open_session_balance(db, store):
    session = CashSession(
        store_id=store.id, opening_amount=Decimal("10000"), status=CashSessionStatus.ouverte
    )
    db.add(session)
    await db.flush()
    db.add(CashMovement(
        cash_session_id=session.id, type=CashMovementType.entree, amount=Decimal("5000")
    ))
    db.add(CashMovement(
        cash_session_id=session.id, type=CashMovementType.sortie, amount=Decimal("2000")
    ))
    await db.commit()

    stats = await DashboardService(db).get_stats(store.id)
    assert stats.kpi.caisse_ouverte is True
    assert stats.kpi.caisse_solde == Decimal("13000")  # 10000 + 5000 - 2000


async def test_caisse_solde_none_when_no_open_session(db, store2):
    stats = await DashboardService(db).get_stats(store2.id)
    assert stats.kpi.caisse_ouverte is False
    assert stats.kpi.caisse_solde is None


async def test_caisse_solde_not_shown_in_hq_view(db, store):
    session = CashSession(
        store_id=store.id, opening_amount=Decimal("10000"), status=CashSessionStatus.ouverte
    )
    db.add(session)
    await db.commit()

    stats = await DashboardService(db).get_stats(None)
    assert stats.kpi.caisse_solde is None
    assert stats.kpi.caisse_ouverte is False


async def test_total_decaissement_sums_sorties_in_period(db, store):
    session = CashSession(
        store_id=store.id, opening_amount=Decimal("0"), status=CashSessionStatus.ouverte,
        opened_at=TODAY,
    )
    db.add(session)
    await db.flush()
    db.add(CashMovement(
        cash_session_id=session.id, type=CashMovementType.sortie, amount=Decimal("2500"),
        created_at=TODAY,
    ))
    db.add(CashMovement(
        cash_session_id=session.id, type=CashMovementType.entree, amount=Decimal("9000"),
        created_at=TODAY,
    ))
    db.add(CashMovement(
        cash_session_id=session.id, type=CashMovementType.sortie, amount=Decimal("1500"),
        created_at=TODAY - timedelta(days=45),
    ))
    await db.commit()

    stats = await DashboardService(db).get_stats(store.id)
    assert stats.kpi.total_decaissement == Decimal("2500")  # only the in-period sortie


async def test_caisse_fermee_alert_hidden_when_own_store_has_open_session(db, store, store2):
    """store has an open session, store2 doesn't — a store-scoped view of
    `store` must never mention store2's closed caisse."""
    db.add(CashSession(
        store_id=store.id, opening_amount=Decimal("0"), status=CashSessionStatus.ouverte
    ))
    await db.commit()

    stats = await DashboardService(db).get_stats(store.id)
    assert not any(a.type == "caisse_fermee" for a in stats.alertes)


async def test_caisse_fermee_alert_shown_for_own_closed_store(db, store):
    stats = await DashboardService(db).get_stats(store.id)
    alert = next((a for a in stats.alertes if a.type == "caisse_fermee"), None)
    assert alert is not None
    assert alert.count == 1
    assert "cette boutique" in alert.message


async def test_top_boutiques_populated_and_ranked_in_hq_view(db, store, store2):
    await _vente(db, store.id, Decimal("50000"), TODAY)
    await _vente(db, store2.id, Decimal("200000"), TODAY)
    await _vente(db, store2.id, Decimal("100000"), TODAY)
    await db.commit()

    stats = await DashboardService(db).get_stats(None)

    assert [b.boutique_id for b in stats.top_boutiques] == [store2.id, store.id]
    assert stats.top_boutiques[0].ca == Decimal("300000")
    assert stats.top_boutiques[0].nb_ventes == 2
    assert stats.top_boutiques[1].ca == Decimal("50000")


async def test_top_boutiques_empty_in_store_scoped_view(db, store):
    await _vente(db, store.id, Decimal("50000"), TODAY)
    await db.commit()

    stats = await DashboardService(db).get_stats(store.id)
    assert stats.top_boutiques == []
