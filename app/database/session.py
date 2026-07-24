"""Async SQLAlchemy engine, session factory and FastAPI dependency."""

from collections.abc import AsyncGenerator

from sqlalchemy import text
from sqlalchemy.ext.asyncio import (
    AsyncEngine,
    AsyncSession,
    async_sessionmaker,
    create_async_engine,
)

from app.core.config import settings
from app.core.logging import get_logger
from app.database.base import Base

logger = get_logger("database")

engine: AsyncEngine = create_async_engine(
    settings.sqlalchemy_database_uri,
    echo=settings.DB_ECHO,
    pool_pre_ping=True,
    pool_size=settings.DB_POOL_SIZE,
    max_overflow=settings.DB_MAX_OVERFLOW,
    pool_recycle=settings.DB_POOL_RECYCLE,
)

SessionLocal: async_sessionmaker[AsyncSession] = async_sessionmaker(
    bind=engine,
    class_=AsyncSession,
    expire_on_commit=False,
    autoflush=False,
)


async def get_db() -> AsyncGenerator[AsyncSession, None]:
    """FastAPI dependency that yields a database session and commits/rolls back."""
    async with SessionLocal() as session:
        try:
            yield session
            await session.commit()
        except Exception:
            await session.rollback()
            raise


def init_models() -> None:
    """Import all model modules so they register on ``Base.metadata``.

    Imported for their side effects (model registration). Keep in sync with the
    modules that define tables.
    """
    from app.modules.access import models as _access  # noqa: F401
    from app.modules.achat import models as _achat  # noqa: F401
    from app.modules.auth import models as _auth  # noqa: F401
    from app.modules.cash import models as _cash  # noqa: F401
    from app.modules.catalog import models as _catalog  # noqa: F401
    from app.modules.clients import models as _clients  # noqa: F401
    from app.modules.commandes import models as _commandes  # noqa: F401
    from app.modules.creances import models as _creances  # noqa: F401
    from app.modules.expenses import models as _expenses  # noqa: F401
    from app.modules.notifications import models as _notifications  # noqa: F401
    from app.modules.stock import models as _stock  # noqa: F401
    from app.modules.stores import models as _stores  # noqa: F401
    from app.modules.system import models as _system  # noqa: F401
    from app.modules.users import models as _users  # noqa: F401
    from app.modules.ventes import models as _ventes  # noqa: F401


async def check_connection() -> bool:
    """Return True if the database is reachable (used at startup, non-fatal)."""
    try:
        async with engine.connect() as conn:
            await conn.execute(text("SELECT 1"))
        return True
    except Exception as exc:  # pragma: no cover - depends on runtime DB availability
        logger.warning("Database connection check failed: %s", exc)
        return False


async def create_all() -> None:
    """Create tables from metadata (development convenience; prefer migrations)."""
    init_models()
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    logger.info("Database tables ensured (create_all).")


async def dispose_engine() -> None:
    await engine.dispose()
