"""Integration tests for the commandes (internal réappro) engine against the
*real* MySQL dev database — specifically ``CommandeService.confirm_reception``,
the one code path in this codebase that takes row locks (``SELECT ... FOR
UPDATE`` on ``ProductStock``, see ``StockSaleService.receive_transfer``).

Unlike ``test_ventes_engine_mysql.py`` (which rolls back every test), the
concurrency test here needs two *genuinely separate, concurrently committing*
connections to exercise real InnoDB row locking — a single uncommitted
transaction can't race against itself. So this file commits real rows, then
deletes them again in a ``finally`` block, identified by unique slugs so a
failed cleanup never collides with real seed data.

Skipped automatically (not failed) if the configured MySQL instance isn't
reachable, so ``pytest`` stays green on machines without a local database.
"""

import asyncio
import uuid
from collections.abc import AsyncGenerator
from decimal import Decimal

import pytest
import pytest_asyncio
from sqlalchemy import delete, select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from app.core.config import settings
from app.database.enums import (
    CommandeReceptionStatut,
    CommandeStatut,
    MovementReason,
    MovementType,
    StockLocationType,
)
from app.modules.catalog.models import Product
from app.modules.commandes.models import (
    Commande,
    CommandeAnomalie,
    CommandeEvenement,
    CommandeLigne,
    CommandeLivraison,
    CommandeReception,
)
from app.modules.commandes.schemas import (
    CommandeCreate,
    CommandeLigneCreate,
    CommandeReceptionCreate,
    CommandeShip,
    CommandeValidate,
)
from app.modules.commandes.services import CommandeService
from app.modules.stock.models import ProductStock, StockLocation, StockMovement
from app.modules.stores.models import Store
from app.modules.users.models import User

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
    """Committing session — deliberately NOT the rollback-only pattern used
    elsewhere, since this file needs real cross-connection concurrency."""
    if not await _mysql_reachable():
        pytest.skip("MySQL dev database is not reachable — skipping MySQL integration tests.")

    engine = create_async_engine(settings.sqlalchemy_database_uri)
    session_maker = async_sessionmaker(bind=engine, class_=AsyncSession, expire_on_commit=False)
    session = session_maker()
    try:
        yield session
    finally:
        await session.close()
        await engine.dispose()


async def _get_central_location(db: AsyncSession) -> StockLocation:
    """Resolve the SAME central location ``get_central_location()`` will —
    reuse whatever real CENTRAL row already exists in the dev DB rather than
    creating a second one (which would make ``get_central_location`` ambiguous)."""
    row = (
        await db.execute(
            select(StockLocation)
            .where(
                StockLocation.type == StockLocationType.CENTRAL,
                StockLocation.deleted_at.is_(None),
            )
            .order_by(StockLocation.id)
        )
    ).scalars().first()
    assert row is not None, "Expected at least one CENTRAL StockLocation to exist in the dev DB."
    return row


async def _seed_boutique(db: AsyncSession) -> tuple[Store, StockLocation, User]:
    store = Store(name=_unique("Boutique"), slug=_unique("boutique"))
    db.add(store)
    await db.flush()

    location = StockLocation(name=_unique("Loc"), type=StockLocationType.STORE, store_id=store.id)
    db.add(location)

    user = User(
        firstname="QA", lastname="Reappro", email=f"{_unique('qa')}@test.local", password="hashed"
    )
    db.add(user)
    await db.flush()
    return store, location, user


async def _advance_to_livree(
    service: CommandeService, boutique_id: int, product_id: int, qty: int, gerant: User, boss: User
) -> Commande:
    payload = CommandeCreate(
        boutique_id=boutique_id,
        lignes=[
            CommandeLigneCreate(
                produit_id=product_id, quantite_demandee=qty, prix_unitaire=Decimal("1000")
            )
        ],
    )
    commande = await service.create(payload, gerant, None)
    commande = await service.submit(commande, gerant, None)
    commande = await service.validate(commande, CommandeValidate(), boss, None)
    commande = await service.generate_proforma(commande, boss, None)
    commande = await service.approve_proforma(commande, boss, None)
    commande = await service.start_preparation(commande, boss, None)
    commande = await service.confirm_preparation(commande, boss, None)
    commande = await service.ship(commande, CommandeShip(transporteur="Transco"), boss, None)
    return await service.mark_delivered(commande, boss, None)


async def _cleanup(product_id: int, store_ids: list[int], user_ids: list[int]) -> None:
    """Best-effort teardown via a brand new connection — runs even if the
    test body raised, so a failed assertion never leaves rows behind."""
    engine = create_async_engine(settings.sqlalchemy_database_uri)
    session_maker = async_sessionmaker(bind=engine, class_=AsyncSession, expire_on_commit=False)
    async with session_maker() as db:
        commande_ids = (
            await db.execute(select(Commande.id).where(Commande.boutique_id.in_(store_ids)))
        ).scalars().all()
        if commande_ids:
            await db.execute(
                delete(CommandeAnomalie).where(CommandeAnomalie.commande_id.in_(commande_ids))
            )
            await db.execute(
                delete(CommandeReception).where(CommandeReception.commande_id.in_(commande_ids))
            )
            await db.execute(
                delete(CommandeEvenement).where(CommandeEvenement.commande_id.in_(commande_ids))
            )
            await db.execute(
                delete(CommandeLivraison).where(CommandeLivraison.commande_id.in_(commande_ids))
            )
            await db.execute(
                delete(CommandeLigne).where(CommandeLigne.commande_id.in_(commande_ids))
            )
            await db.execute(delete(Commande).where(Commande.id.in_(commande_ids)))
        await db.execute(delete(StockMovement).where(StockMovement.product_id == product_id))
        await db.execute(delete(ProductStock).where(ProductStock.product_id == product_id))
        if store_ids:
            await db.execute(delete(StockLocation).where(StockLocation.store_id.in_(store_ids)))
            await db.execute(delete(Store).where(Store.id.in_(store_ids)))
        if user_ids:
            await db.execute(delete(User).where(User.id.in_(user_ids)))
        await db.execute(delete(Product).where(Product.id == product_id))
        await db.commit()
    await engine.dispose()


async def test_mysql_confirm_reception_concurrent_no_lost_update(mysql_db: AsyncSession):
    central = await _get_central_location(mysql_db)

    product = Product(
        name=_unique("Product"), slug=_unique("product"),
        prix_vente=Decimal("1000"), prix_achat=Decimal("700"),
    )
    mysql_db.add(product)
    await mysql_db.flush()

    central_stock = ProductStock(product_id=product.id, location_id=central.id, quantity=100)
    mysql_db.add(central_stock)

    store_a, location_a, gerant_a = await _seed_boutique(mysql_db)
    store_b, location_b, gerant_b = await _seed_boutique(mysql_db)
    boss = User(
        firstname="QA", lastname="Boss", email=f"{_unique('boss')}@test.local", password="hashed"
    )
    mysql_db.add(boss)
    await mysql_db.flush()

    service = CommandeService(mysql_db)
    commande_a = await _advance_to_livree(service, store_a.id, product.id, 30, gerant_a, boss)
    commande_b = await _advance_to_livree(service, store_b.id, product.id, 20, gerant_b, boss)
    await mysql_db.commit()  # commandes + central stock row now visible cross-connection

    engine = create_async_engine(settings.sqlalchemy_database_uri)
    session_maker = async_sessionmaker(bind=engine, class_=AsyncSession, expire_on_commit=False)

    async def _receive(commande_id: int, ligne_id: int, qty: int, actor: User) -> None:
        async with session_maker() as session:
            svc = CommandeService(session)
            commande = await svc.get(commande_id)
            await svc.confirm_reception(
                commande,
                CommandeReceptionCreate(
                    statut_reception=CommandeReceptionStatut.accepte, lignes={ligne_id: qty}
                ),
                actor,
                None,
            )
            await session.commit()

    try:
        await asyncio.gather(
            _receive(commande_a.id, commande_a.lignes[0].id, 30, gerant_a),
            _receive(commande_b.id, commande_b.lignes[0].id, 20, gerant_b),
        )

        async with session_maker() as verify:
            central_after = (
                await verify.execute(
                    select(ProductStock).where(
                        ProductStock.product_id == product.id,
                        ProductStock.location_id == central.id,
                    )
                )
            ).scalar_one()
            assert central_after.quantity == 50  # 100 - 30 - 20, no lost update

            store_a_stock = (
                await verify.execute(
                    select(ProductStock).where(
                        ProductStock.product_id == product.id,
                        ProductStock.location_id == location_a.id,
                    )
                )
            ).scalar_one()
            assert store_a_stock.quantity == 30

            store_b_stock = (
                await verify.execute(
                    select(ProductStock).where(
                        ProductStock.product_id == product.id,
                        ProductStock.location_id == location_b.id,
                    )
                )
            ).scalar_one()
            assert store_b_stock.quantity == 20

            movements = (
                await verify.execute(
                    select(StockMovement).where(
                        StockMovement.product_id == product.id,
                        StockMovement.reason == MovementReason.REAPPRO,
                    )
                )
            ).scalars().all()
            assert len(movements) == 4  # 2 per reception (OUT central + IN boutique)
            out_quantities = sorted(
                m.quantity for m in movements if m.movement_type == MovementType.OUT
            )
            assert out_quantities == [20, 30]

            commande_a_after = await verify.get(Commande, commande_a.id)
            commande_b_after = await verify.get(Commande, commande_b.id)
            assert commande_a_after.statut == CommandeStatut.reception_confirmee
            assert commande_b_after.statut == CommandeStatut.reception_confirmee
    finally:
        await engine.dispose()
        await _cleanup(product.id, [store_a.id, store_b.id], [gerant_a.id, gerant_b.id, boss.id])
