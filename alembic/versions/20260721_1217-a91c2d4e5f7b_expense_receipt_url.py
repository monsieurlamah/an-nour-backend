"""expenses: add receipt_url (justificatif)

Revision ID: a91c2d4e5f7b
Revises: 38f4f73ea3c0
Create Date: 2026-07-21 12:17:00.000000
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "a91c2d4e5f7b"
down_revision: str | None = "38f4f73ea3c0"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column("expenses", sa.Column("receipt_url", sa.String(length=512), nullable=True))


def downgrade() -> None:
    op.drop_column("expenses", "receipt_url")
