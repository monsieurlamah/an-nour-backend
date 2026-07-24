"""commande_lignes: allow a free-text product name (no catalog match yet)

Revision ID: d4e5f6a7b8c9
Revises: c9d8e7f6a5b4
Create Date: 2026-07-13 09:00:00.000000
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "d4e5f6a7b8c9"
down_revision: str | None = "c9d8e7f6a5b4"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.alter_column(
        "commande_lignes", "produit_id",
        existing_type=sa.BigInteger(),
        nullable=True,
    )
    op.add_column("commande_lignes", sa.Column("nom_libre", sa.String(length=255), nullable=True))


def downgrade() -> None:
    op.drop_column("commande_lignes", "nom_libre")
    op.alter_column(
        "commande_lignes", "produit_id",
        existing_type=sa.BigInteger(),
        nullable=False,
    )
