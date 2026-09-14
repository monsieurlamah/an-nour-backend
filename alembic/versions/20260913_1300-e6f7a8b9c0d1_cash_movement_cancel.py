"""cash_movements: cancellation fields — cahier des charges §10

"Gestion des annulations/corrections d'encaissement avec motif et
validation." CashMovement stays append-only — these columns only annotate
the original row; the actual correction is a new compensating movement
(reverses_movement_id points back at what it reverses).

Revision ID: e6f7a8b9c0d1
Revises: d5e6f7a8b9c0
Create Date: 2026-09-13 13:00:00.000000
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "e6f7a8b9c0d1"
down_revision: str | None = "d5e6f7a8b9c0"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column("cash_movements", sa.Column("cancelled_at", sa.DateTime(), nullable=True))
    op.add_column("cash_movements", sa.Column("cancelled_by", sa.BigInteger(), nullable=True))
    op.add_column(
        "cash_movements", sa.Column("cancel_reason", sa.String(length=255), nullable=True)
    )
    op.add_column(
        "cash_movements", sa.Column("reverses_movement_id", sa.BigInteger(), nullable=True)
    )
    op.create_foreign_key(
        op.f("fk_cash_movements_cancelled_by_users"),
        "cash_movements", "users", ["cancelled_by"], ["id"], ondelete="SET NULL",
    )
    op.create_foreign_key(
        op.f("fk_cash_movements_reverses_movement_id_cash_movements"),
        "cash_movements", "cash_movements", ["reverses_movement_id"], ["id"], ondelete="SET NULL",
    )


def downgrade() -> None:
    op.drop_constraint(
        op.f("fk_cash_movements_reverses_movement_id_cash_movements"),
        "cash_movements", type_="foreignkey",
    )
    op.drop_constraint(
        op.f("fk_cash_movements_cancelled_by_users"), "cash_movements", type_="foreignkey"
    )
    op.drop_column("cash_movements", "reverses_movement_id")
    op.drop_column("cash_movements", "cancel_reason")
    op.drop_column("cash_movements", "cancelled_by")
    op.drop_column("cash_movements", "cancelled_at")
