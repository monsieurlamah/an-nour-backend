"""Integration tests for the Ventes engine against the *real* MySQL dev
database (not SQLite).

Every test runs inside a single uncommitted transaction: fixtures and the
service under test only ever ``flush()`` (exactly like the production
``get_db`` dependency before its final ``commit()``), and the session is
rolled back — never committed — at teardown. This proves the engine behaves
identically on MySQL while leaving zero trace in the shared dev database,
regardless of whether a test passes or fails.

Skipped automatically (not failed) if the configured MySQL instance isn't
reachable, so ``pytest`` stays green on machines without a local database.
"""

import uuid
from collections.abc import AsyncGenerator
from decimal import Decimal

import pytest
import pytest_asyncio
from fastapi import HTTPException
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from app.core.config import settings
from app.database.enums import CashSessionStatus, StockLocationType, VenteStatut
from app.modules.cash.models import CashMovement, CashSession
from app.modules.catalog.models import Product
from app.modules.clients.models import Client
from app.modules.creances.models import Creance, Paiement
from app.modules.stock.models import ProductStock, StockLocation
from app.modules.stores.models import Store
from app.modules.users.models import User
from app.modules.ventes.models import Vente
from app.modules.ventes.schemas import VenteCreate, VenteLigneCreate, VentePaiementCreate
from app.modules.ventes.services import VenteService

pytestmark = pytest.mark.mysql


def _unique(prefix: str) -> str:
    return f"{prefix}-{uuid.uuid4().hex[:10]}"


async def _mysql_reachable() -> bool:
    try:
        engine = create_async_engine(settings.sqlalchemy_database_uri)
        async with engine.connect():
            pass
        await engine.dispose()
        return True
    except Exception:
        return False


@pytest_asyncio.fixture
async def mysql_db() -> AsyncGenerator[AsyncSession, None]:
    if not await _mysql_reachable():
        pytest.skip("MySQL dev database is not reachable — skipping MySQL integration tests.")

    engine = create_async_engine(settings.sqlalchemy_database_uri)
    session_maker = async_sessionmaker(bind=engine, class_=AsyncSession, expire_on_commit=False)
    session = session_maker()
    try:
        yield session
    finally:
        # Never commit — discard everything this test wrote, no matter the
        # outcome, so the shared dev database is left exactly as it was.
        await session.rollback()
        await session.close()
        await engine.dispose()


async def _seed(db: AsyncSession) -> dict:
    """Build one store + STORE location + stocked product + user, flushed
    (visible within this transaction) but never committed."""
    store = Store(name=_unique("Store"), slug=_unique("store"))
    db.add(store)
    await db.flush()

    location = StockLocation(
        name=_unique("Location"), type=StockLocationType.STORE, store_id=store.id
    )
    db.add(location)
    await db.flush()

    product = Product(
        name=_unique("Product"),
        slug=_unique("product"),
        prix_vente=Decimal("100000"),
        prix_achat=Decimal("70000"),
    )
    db.add(product)
    await db.flush()

    stock = ProductStock(product_id=product.id, location_id=location.id, quantity=10)
    db.add(stock)

    user = User(
        firstname="QA", lastname="MySQL", email=f"{_unique('qa')}@test.local", password="hashed"
    )
    db.add(user)
    await db.flush()

    client = Client(code_client=_unique("CLI"), name="Client MySQL", phone=_unique("+224"))
    db.add(client)
    await db.flush()

    return {
        "store": store, "location": location, "product": product, "user": user, "client": client,
    }


async def _open_cash_session(db: AsyncSession, store_id: int, user_id: int) -> CashSession:
    cs = CashSession(
        store_id=store_id, opened_by=user_id, opening_amount=Decimal("0"),
        status=CashSessionStatus.ouverte,
    )
    db.add(cs)
    await db.flush()
    return cs


def _ligne(product: Product, qty: int, price: Decimal) -> VenteLigneCreate:
    return VenteLigneCreate(produit_id=product.id, quantite=qty, prix_unitaire=price)


async def test_mysql_vente_comptant_transaction_complete(mysql_db: AsyncSession):
    ctx = await _seed(mysql_db)
    await _open_cash_session(mysql_db, ctx["store"].id, ctx["user"].id)

    payload = VenteCreate(
        boutique_id=ctx["store"].id,
        lignes=[_ligne(ctx["product"], qty=2, price=Decimal("100000"))],
        paiements=[VentePaiementCreate(mode="especes", montant=Decimal("200000"))],
    )
    vente = await VenteService(mysql_db).create(payload, ctx["user"])

    assert vente.statut == VenteStatut.completee
    assert vente.montant_restant == Decimal("0")
    assert vente.creance is None

    stock = (
        await mysql_db.execute(
            select(ProductStock).where(
                ProductStock.product_id == ctx["product"].id,
                ProductStock.location_id == ctx["location"].id,
            )
        )
    ).scalar_one()
    assert stock.quantity == 8

    cash_moves = (
        await mysql_db.execute(
            select(CashMovement).where(CashMovement.reference_id == vente.id)
        )
    ).scalars().all()
    assert len(cash_moves) == 1
    assert cash_moves[0].amount == Decimal("200000")


async def test_mysql_vente_partielle_cree_creance(mysql_db: AsyncSession):
    ctx = await _seed(mysql_db)
    await _open_cash_session(mysql_db, ctx["store"].id, ctx["user"].id)

    payload = VenteCreate(
        boutique_id=ctx["store"].id,
        client_id=ctx["client"].id,
        lignes=[_ligne(ctx["product"], qty=2, price=Decimal("100000"))],  # total 200 000
        paiements=[VentePaiementCreate(mode="mobile_money", montant=Decimal("120000"))],
    )
    vente = await VenteService(mysql_db).create(payload, ctx["user"])

    assert vente.statut == VenteStatut.partiellement_payee
    assert vente.creance is not None
    assert vente.creance.montant_initial == Decimal("80000")
    assert vente.creance.client_id == ctx["client"].id

    creances = (
        await mysql_db.execute(select(Creance).where(Creance.vente_id == vente.id))
    ).scalars().all()
    assert len(creances) == 1

    paiements = (
        await mysql_db.execute(select(Paiement).where(Paiement.vente_id == vente.id))
    ).scalars().all()
    assert len(paiements) == 1
    assert paiements[0].montant == Decimal("120000")


async def test_mysql_rollback_stock_insuffisant_ne_persiste_rien(mysql_db: AsyncSession):
    ctx = await _seed(mysql_db)
    await _open_cash_session(mysql_db, ctx["store"].id, ctx["user"].id)

    payload = VenteCreate(
        boutique_id=ctx["store"].id,
        client_id=ctx["client"].id,
        lignes=[_ligne(ctx["product"], qty=999, price=Decimal("100000"))],
        paiements=[],
    )
    with pytest.raises(HTTPException) as exc:
        await VenteService(mysql_db).create(payload, ctx["user"])
    assert exc.value.status_code == 422
    assert "stock insuffisant" in exc.value.detail.lower()

    ventes = (
        await mysql_db.execute(select(Vente).where(Vente.boutique_id == ctx["store"].id))
    ).scalars().all()
    assert ventes == []

    stock = (
        await mysql_db.execute(
            select(ProductStock).where(
                ProductStock.product_id == ctx["product"].id,
                ProductStock.location_id == ctx["location"].id,
            )
        )
    ).scalar_one()
    assert stock.quantity == 10  # untouched


async def test_mysql_paiement_multiple_un_mouvement_caisse_par_paiement(mysql_db: AsyncSession):
    ctx = await _seed(mysql_db)
    cash_session = await _open_cash_session(mysql_db, ctx["store"].id, ctx["user"].id)

    payload = VenteCreate(
        boutique_id=ctx["store"].id,
        client_id=ctx["client"].id,
        lignes=[_ligne(ctx["product"], qty=10, price=Decimal("100000"))],  # total 1 000 000
        paiements=[
            VentePaiementCreate(mode="especes", montant=Decimal("300000")),
            VentePaiementCreate(mode="mobile_money", montant=Decimal("200000"), reference="OM-1"),
        ],
    )
    vente = await VenteService(mysql_db).create(payload, ctx["user"])

    assert vente.montant_restant == Decimal("500000")
    assert vente.creance.montant_initial == Decimal("500000")

    cash_moves = (
        await mysql_db.execute(
            select(CashMovement).where(CashMovement.cash_session_id == cash_session.id)
        )
    ).scalars().all()
    assert len(cash_moves) == 2
    assert sorted(m.amount for m in cash_moves) == [Decimal("200000"), Decimal("300000")]


async def test_mysql_transaction_isolee_aucune_trace_apres_le_test():
    """End-to-end proof of isolation: write through one session/transaction,
    let the ``mysql_db``-style teardown roll it back, then open a brand new,
    independent connection and confirm the store is nowhere to be found."""
    if not await _mysql_reachable():
        pytest.skip("MySQL dev database is not reachable.")

    engine = create_async_engine(settings.sqlalchemy_database_uri)
    session_maker = async_sessionmaker(bind=engine, class_=AsyncSession, expire_on_commit=False)
    marker_slug = _unique("isolation-check")

    async with session_maker() as session:
        store = Store(name=marker_slug, slug=marker_slug)
        session.add(store)
        await session.flush()
        # Visible inside this same transaction:
        found = (
            await session.execute(select(Store).where(Store.slug == marker_slug))
        ).scalar_one_or_none()
        assert found is not None
        await session.rollback()  # discard — mirrors mysql_db's teardown

    async with session_maker() as session:
        leaked = (
            await session.execute(select(Store).where(Store.slug == marker_slug))
        ).scalar_one_or_none()
        assert leaked is None, "Rolled-back data must never reach a fresh connection."

    await engine.dispose()
