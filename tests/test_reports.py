"""Tests for ReportsService — marge, recouvrement, and basic shape checks.

Same in-memory SQLite fixtures as test_ventes_engine.py.
"""

from decimal import Decimal

from app.modules.creances.models import Creance
from app.modules.reports.services import ReportsService
from app.modules.ventes.schemas import VenteCreate, VenteLigneCreate, VentePaiementCreate
from app.modules.ventes.services import VenteService


async def test_marge_pct_matches_ca_minus_cout_achat(
    db, store, store_location, stocked_product, user, open_cash_session
):
    # stocked_product: prix_achat=70000 (conftest). Vente de 2 unités à 100000.
    # CA=200000, coût=2*70000=140000, marge=(200000-140000)/200000*100=30.0%.
    payload = VenteCreate(
        boutique_id=store.id,
        lignes=[
            VenteLigneCreate(
                produit_id=stocked_product.id, quantite=2, prix_unitaire=Decimal("100000")
            )
        ],
        paiements=[VentePaiementCreate(mode="especes", montant=Decimal("200000"))],
    )
    await VenteService(db).create(payload, user)

    data = await ReportsService(db).get_data(store.id)

    assert data.kpi.ca_mois == Decimal("200000")
    assert data.kpi.ventes_mois == 1
    assert data.kpi.marge_pct == Decimal("30.0")


async def test_marge_pct_zero_when_no_sales_this_month(db, store):
    data = await ReportsService(db).get_data(store.id)
    assert data.kpi.ca_mois == Decimal("0")
    assert data.kpi.marge_pct == Decimal("0")


async def test_recouvrement_pct_reflects_paid_vs_initial(db, store, client_):
    # Deux créances : une soldée (100% recouvrée), une à moitié payée.
    db.add(Creance(
        client_id=client_.id, boutique_id=store.id,
        montant_initial=Decimal("100000"), montant_restant=Decimal("0"), statut="soldee",
    ))
    db.add(Creance(
        client_id=client_.id, boutique_id=store.id,
        montant_initial=Decimal("100000"), montant_restant=Decimal("50000"),
        statut="partiellement_payee",
    ))
    await db.commit()

    data = await ReportsService(db).get_data(store.id)

    # initial total=200000, restant total=50000 -> recouvré=150000 -> 75.0%
    assert data.kpi.recouvrement_pct == Decimal("75.0")


async def test_recouvrement_pct_ignores_annulee_creances(db, store, client_):
    db.add(Creance(
        client_id=client_.id, boutique_id=store.id,
        montant_initial=Decimal("100000"), montant_restant=Decimal("0"), statut="soldee",
    ))
    db.add(Creance(
        client_id=client_.id, boutique_id=store.id,
        montant_initial=Decimal("999999"), montant_restant=Decimal("999999"), statut="annulee",
    ))
    await db.commit()

    data = await ReportsService(db).get_data(store.id)

    # Seule la créance soldée compte -> 100% recouvré, la annulée est exclue.
    assert data.kpi.recouvrement_pct == Decimal("100.0")


async def test_get_data_shape_is_complete_even_with_empty_store(db, store):
    """A brand-new store with zero activity must still return valid,
    zeroed-out data for every section — never a partial/broken payload."""
    data = await ReportsService(db).get_data(store.id)

    assert len(data.revenue_trend) == 12
    assert all(p.ca == Decimal("0") for p in data.revenue_trend)
    assert data.stock_by_category == []
    assert len(data.collection_trend) == 8
    assert data.store_revenue == []
    assert data.seller_revenue == []


async def test_stock_by_category_aggregates_central_and_boutique(
    db, store, store_location, stocked_product, product
):
    from app.database.enums import StockLocationType
    from app.modules.catalog.models import CategoryProduct
    from app.modules.stock.models import ProductStock, StockLocation

    category = CategoryProduct(name="Alimentaire", slug="alimentaire")
    db.add(category)
    await db.commit()
    await db.refresh(category)
    product.category_product_id = category.id
    db.add(product)

    central_loc = StockLocation(name="Central", type=StockLocationType.CENTRAL)
    db.add(central_loc)
    await db.commit()
    await db.refresh(central_loc)
    db.add(ProductStock(product_id=product.id, location_id=central_loc.id, quantity=5))
    await db.commit()

    # stocked_product fixture already put 10 units at store_location (boutique).
    # + 5 units at central => valeur = (10+5) * prix_achat(70000) = 1 050 000
    data = await ReportsService(db).get_data(None)  # vue HQ : les deux comptent

    assert len(data.stock_by_category) == 1
    assert data.stock_by_category[0].category == "Alimentaire"
    assert data.stock_by_category[0].valeur == Decimal("1050000")
