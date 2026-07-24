"""Reusable column mixins composed by the ORM models.

Conventions applied across the whole schema:
- ``id``          : BIGINT auto-increment primary key.
- ``uuid``        : public, unique, indexed identifier (CHAR(36)).
- ``status``      : record lifecycle (active/inactive) — see ``RecordStatus``.
- ``infos``       : free-form JSON metadata bag.
- ``created_at`` / ``updated_at`` : managed by the database.
- ``deleted_at``  : soft-delete marker (NULL = not deleted).
"""

import uuid as uuid_lib
from datetime import datetime

from sqlalchemy import JSON, BigInteger, DateTime, Enum, Integer, String, func
from sqlalchemy.orm import Mapped, mapped_column

from app.database.enums import RecordStatus

# SQLite only treats a column as an alias for its ROWID (and thus
# auto-increments it) when its declared type is exactly INTEGER — BIGINT
# doesn't qualify. This variant keeps MySQL on BIGINT unchanged while making
# the same models usable against an in-memory SQLite test database.
_ID_TYPE = BigInteger().with_variant(Integer, "sqlite")


def _uuid4() -> str:
    return str(uuid_lib.uuid4())


class IDMixin:
    id: Mapped[int] = mapped_column(_ID_TYPE, primary_key=True, autoincrement=True)


class UUIDMixin:
    uuid: Mapped[str] = mapped_column(
        String(36), unique=True, index=True, default=_uuid4, nullable=False
    )


class TimestampMixin:
    created_at: Mapped[datetime] = mapped_column(
        DateTime, server_default=func.now(), nullable=False
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime, server_default=func.now(), onupdate=func.now(), nullable=False
    )


class SoftDeleteMixin:
    deleted_at: Mapped[datetime | None] = mapped_column(
        DateTime, nullable=True, default=None, index=True
    )


class StatusMixin:
    status: Mapped[RecordStatus] = mapped_column(
        Enum(RecordStatus, native_enum=False, length=20, create_constraint=False),
        default=RecordStatus.active,
        nullable=False,
        index=True,
    )


class InfosMixin:
    infos: Mapped[dict | None] = mapped_column(JSON, nullable=True)
