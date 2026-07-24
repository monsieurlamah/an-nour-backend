"""Shared pytest fixtures.

Tests run against an in-memory SQLite database (one fresh schema per test
function) instead of the real MySQL dev database — fast, isolated, and safe
to run repeatedly without touching real data. The ORM models are written to
be dialect-agnostic (``native_enum=False`` enums, generic column types), so
this is a faithful enough substitute for exercising the transactional logic.
"""

from collections.abc import AsyncGenerator
from decimal import Decimal

import pytest_asyncio
from httpx import ASGITransport, AsyncClient
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from app.api.deps import get_current_user
from app.database.base import Base
from app.database.enums import UserStatus
from app.database.session import get_db, init_models
from app.main import app as fastapi_app
from app.modules.access.models import Group, UserGroup
from app.modules.cash.models import CashSession
from app.modules.catalog.models import Product
from app.modules.clients.models import Client
from app.modules.stock.models import ProductStock, StockLocation
from app.modules.stores.models import Store, StoreUser
from app.modules.users.models import User
from app.seeds.runner import seed_group_permissions, seed_groups, seed_permissions


@pytest_asyncio.fixture
async def db() -> AsyncGenerator[AsyncSession, None]:
    init_models()
    engine = create_async_engine("sqlite+aiosqlite:///:memory:")
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)

    session_maker = async_sessionmaker(bind=engine, class_=AsyncSession, expire_on_commit=False)
    async with session_maker() as session:
        yield session

    await engine.dispose()


@pytest_asyncio.fixture
async def store(db: AsyncSession) -> Store:
    s = Store(name="Boutique Test", slug="boutique-test")
    db.add(s)
    await db.commit()
    await db.refresh(s)
    return s


@pytest_asyncio.fixture
async def store_location(db: AsyncSession, store: Store) -> StockLocation:
    from app.database.enums import StockLocationType

    loc = StockLocation(name="Boutique Test", type=StockLocationType.STORE, store_id=store.id)
    db.add(loc)
    await db.commit()
    await db.refresh(loc)
    return loc


@pytest_asyncio.fixture
async def user(db: AsyncSession) -> User:
    u = User(
        firstname="Awa",
        lastname="Vendeuse",
        email="awa@test.local",
        password="hashed",
        is_activated=True,
        status=UserStatus.active,
    )
    db.add(u)
    await db.commit()
    await db.refresh(u)
    return u


@pytest_asyncio.fixture
async def client_(db: AsyncSession) -> Client:
    c = Client(code_client="CLI-000001", name="Diallo", phone="+224600000001")
    db.add(c)
    await db.commit()
    await db.refresh(c)
    return c


@pytest_asyncio.fixture
async def product(db: AsyncSession) -> Product:
    p = Product(
        name="Riz 25kg",
        slug="riz-25kg",
        prix_vente=Decimal("100000"),
        prix_achat=Decimal("70000"),
    )
    db.add(p)
    await db.commit()
    await db.refresh(p)
    return p


@pytest_asyncio.fixture
async def stocked_product(
    db: AsyncSession, product: Product, store_location: StockLocation
) -> Product:
    """``product`` with 10 units available at the test store's location."""
    ps = ProductStock(product_id=product.id, location_id=store_location.id, quantity=10)
    db.add(ps)
    await db.commit()
    return product


@pytest_asyncio.fixture
async def open_cash_session(db: AsyncSession, store: Store, user: User) -> CashSession:
    from app.database.enums import CashSessionStatus

    cs = CashSession(
        store_id=store.id,
        opened_by=user.id,
        opening_amount=Decimal("0"),
        status=CashSessionStatus.ouverte,
    )
    db.add(cs)
    await db.commit()
    await db.refresh(cs)
    return cs


# --- HTTP-level harness (for authorization tests) -----------------------------
# Everything below drives requests through the real FastAPI app + dependency
# graph (so require_permission/UserStoreScope actually run), instead of
# calling service classes directly like the tests above.


@pytest_asyncio.fixture
async def rbac(db: AsyncSession) -> dict[str, Group]:
    """Seed real Permission/Group/GroupPermission rows from app.seeds.data
    (the same source of truth as production) into the in-memory test DB."""
    permissions = await seed_permissions(db)
    groups = await seed_groups(db)
    await seed_group_permissions(db, groups, permissions)
    await db.commit()
    return groups


@pytest_asyncio.fixture
async def client(db: AsyncSession) -> AsyncGenerator[AsyncClient, None]:
    async def _override_get_db() -> AsyncGenerator[AsyncSession, None]:
        yield db  # reuse the exact same in-memory session/engine as `db`

    fastapi_app.dependency_overrides[get_db] = _override_get_db
    transport = ASGITransport(app=fastapi_app)
    async with AsyncClient(transport=transport, base_url="http://test") as ac:
        yield ac
    fastapi_app.dependency_overrides.pop(get_db, None)


@pytest_asyncio.fixture
def login_as():
    """login_as(user) overrides get_current_user for the rest of the test —
    get_current_active_user (the real is_activated/status check) still runs
    for real on top of it."""

    def _set(as_user: User) -> None:
        async def _override_get_current_user() -> User:
            return as_user

        fastapi_app.dependency_overrides[get_current_user] = _override_get_current_user

    yield _set
    fastapi_app.dependency_overrides.pop(get_current_user, None)


@pytest_asyncio.fixture
async def store2(db: AsyncSession) -> Store:
    s = Store(name="Boutique 2", slug="boutique-2")
    db.add(s)
    await db.commit()
    await db.refresh(s)
    return s


@pytest_asyncio.fixture
async def other_user(db: AsyncSession) -> User:
    u = User(
        firstname="Mamadou",
        lastname="Gerant",
        email="mamadou@test.local",
        password="hashed",
        is_activated=True,
        status=UserStatus.active,
    )
    db.add(u)
    await db.commit()
    await db.refresh(u)
    return u


async def link_store_user(db: AsyncSession, target_store: Store, target_user: User) -> None:
    db.add(StoreUser(store_id=target_store.id, user_id=target_user.id))
    await db.commit()


async def assign_group(db: AsyncSession, target_user: User, group: Group) -> None:
    db.add(UserGroup(user_id=target_user.id, group_id=group.id))
    await db.commit()
