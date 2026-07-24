"""commandes: gérant validate/reject proforma (Boss can revise & resubmit)

Revision ID: 320d028427db
Revises: d4e5f6a7b8c9
Create Date: 2026-07-14 10:00:00.000000
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "320d028427db"
down_revision: str | None = "d4e5f6a7b8c9"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column("commandes", sa.Column("proforma_refus_motif", sa.Text(), nullable=True))
    op.add_column("commandes", sa.Column("proforma_refused_by", sa.BigInteger(), nullable=True))
    op.add_column("commandes", sa.Column("proforma_refused_at", sa.DateTime(), nullable=True))
    op.create_foreign_key(
        op.f("fk_commandes_proforma_refused_by_users"),
        "commandes", "users", ["proforma_refused_by"], ["id"], ondelete="SET NULL",
    )


def downgrade() -> None:
    op.drop_constraint(
        op.f("fk_commandes_proforma_refused_by_users"), "commandes", type_="foreignkey"
    )
    op.drop_column("commandes", "proforma_refused_at")
    op.drop_column("commandes", "proforma_refused_by")
    op.drop_column("commandes", "proforma_refus_motif")
