"""products: optional per-product credit ceiling (plafond_credit_ligne)

Cahier des charges §8.1 extension — the super-admin can optionally cap how
much of a given product may go out on credit in a single vente-à-crédit
line, on top of the existing per-client plafond_credit. NULL (the default)
means unrestricted, same convention as Store.remise_max_percent.

Revision ID: 84522fdc5019
Revises: b7c8d9e0f1a2
Create Date: 2026-09-15 14:00:00
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "84522fdc5019"
down_revision: str | None = "b7c8d9e0f1a2"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column(
        "products",
        sa.Column("plafond_credit_ligne", sa.Numeric(precision=14, scale=2), nullable=True),
    )


def downgrade() -> None:
    op.drop_column("products", "plafond_credit_ligne")
