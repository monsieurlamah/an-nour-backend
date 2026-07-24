"""expenses: add category_label (free-text precision for "Autre")

Revision ID: b4d6e8f1a3c9
Revises: a91c2d4e5f7b
Create Date: 2026-07-21 13:38:00.000000
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "b4d6e8f1a3c9"
down_revision: str | None = "a91c2d4e5f7b"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column("expenses", sa.Column("category_label", sa.String(length=150), nullable=True))


def downgrade() -> None:
    op.drop_column("expenses", "category_label")
