"""stores: phone + remise_max_percent · creances: relance tracking

Cahier des charges §6.1/§9.2 (per-boutique gérant discount cap, phone on the
fiche boutique) and §8.2 (relance tracking on a créance). Purely additive —
all new columns nullable/defaulted, no existing row touched.

Revision ID: c4d5e6f7a8b9
Revises: a3b4c5d6e7f8
Create Date: 2026-09-13 09:00:00.000000
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "c4d5e6f7a8b9"
down_revision: str | None = "a3b4c5d6e7f8"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column("stores", sa.Column("phone", sa.String(length=30), nullable=True))
    op.add_column(
        "stores", sa.Column("remise_max_percent", sa.Numeric(precision=5, scale=2), nullable=True)
    )
    op.add_column("creances", sa.Column("derniere_relance_at", sa.DateTime(), nullable=True))
    op.add_column(
        "creances",
        sa.Column("nombre_relances", sa.Integer(), nullable=False, server_default="0"),
    )


def downgrade() -> None:
    op.drop_column("creances", "nombre_relances")
    op.drop_column("creances", "derniere_relance_at")
    op.drop_column("stores", "remise_max_percent")
    op.drop_column("stores", "phone")
