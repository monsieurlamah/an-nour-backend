"""Declarative base for all ORM models.

Models must import ``Base`` from here and compose the reusable mixins from
``app.database.mixins``. To keep table metadata complete for ``create_all`` /
migrations, every model module is imported lazily in
``app.database.session.init_models`` (avoids circular imports).
"""

from datetime import datetime

from sqlalchemy import DateTime, MetaData, func
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column

from app.database.mixins import (
    IDMixin,
    InfosMixin,
    SoftDeleteMixin,
    StatusMixin,
    TimestampMixin,
    UUIDMixin,
)

# Predictable constraint names make Alembic migrations deterministic.
NAMING_CONVENTION = {
    "ix": "ix_%(column_0_label)s",
    "uq": "uq_%(table_name)s_%(column_0_name)s",
    "ck": "ck_%(table_name)s_%(constraint_name)s",
    "fk": "fk_%(table_name)s_%(column_0_name)s_%(referred_table_name)s",
    "pk": "pk_%(table_name)s",
}


class Base(DeclarativeBase):
    metadata = MetaData(naming_convention=NAMING_CONVENTION)


class Entity(
    Base,
    IDMixin,
    UUIDMixin,
    StatusMixin,
    InfosMixin,
    TimestampMixin,
    SoftDeleteMixin,
):
    """Standard mutable entity: id, uuid, status, infos, timestamps, soft-delete."""

    __abstract__ = True


class LogEntity(Base, IDMixin, UUIDMixin):
    """Append-only entity (immutable audit/log rows): id, uuid, created_at."""

    __abstract__ = True

    created_at: Mapped[datetime] = mapped_column(
        DateTime, server_default=func.now(), nullable=False
    )
