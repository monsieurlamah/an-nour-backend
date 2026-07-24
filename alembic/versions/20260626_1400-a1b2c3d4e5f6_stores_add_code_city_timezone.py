"""stores: add code, city, timezone columns

Revision ID: a1b2c3d4e5f6
Revises: f3a8b9c2d1e4
Create Date: 2026-06-26 14:00:00.000000
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "a1b2c3d4e5f6"
down_revision: str | None = "f3a8b9c2d1e4"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    # Add new columns to stores table
    op.add_column("stores", sa.Column("code", sa.String(length=50), nullable=True))
    op.add_column("stores", sa.Column("city", sa.String(length=100), nullable=True))
    op.add_column(
        "stores",
        sa.Column("timezone", sa.String(length=50), nullable=False, server_default="Africa/Conakry"),
    )

    # Unique index on code (NULL values are not considered duplicates in MySQL)
    op.create_index("ix_stores_code", "stores", ["code"], unique=True)

    # Backfill existing stock_locations that have store_id but no corresponding name match:
    # For any store that already exists (created before this migration),
    # create a stock_location if one does not already exist for that store.
    op.execute("""
        INSERT INTO stock_locations (name, type, store_id, created_by, uuid, status, created_at, updated_at)
        SELECT
            s.name,
            'STORE',
            s.id,
            s.created_by,
            UUID(),
            'active',
            NOW(),
            NOW()
        FROM stores s
        WHERE s.deleted_at IS NULL
          AND NOT EXISTS (
              SELECT 1 FROM stock_locations sl
              WHERE sl.store_id = s.id AND sl.deleted_at IS NULL
          )
    """)


def downgrade() -> None:
    op.drop_index("ix_stores_code", table_name="stores")
    op.drop_column("stores", "timezone")
    op.drop_column("stores", "city")
    op.drop_column("stores", "code")
