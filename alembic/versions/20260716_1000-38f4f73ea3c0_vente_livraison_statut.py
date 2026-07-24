"""ventes: delivery status independent from payment status (bon de livraison)

Revision ID: 38f4f73ea3c0
Revises: 320d028427db
Create Date: 2026-07-16 10:00:00.000000
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "38f4f73ea3c0"
down_revision: str | None = "320d028427db"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column(
        "ventes",
        sa.Column(
            "livraison_statut", sa.String(length=20), nullable=False, server_default="livre"
        ),
    )
    op.add_column("ventes", sa.Column("numero_bon_livraison", sa.String(length=30), nullable=True))
    op.add_column("ventes", sa.Column("livree_at", sa.DateTime(), nullable=True))
    op.add_column("ventes", sa.Column("livree_by", sa.BigInteger(), nullable=True))
    op.create_foreign_key(
        op.f("fk_ventes_livree_by_users"), "ventes", "users", ["livree_by"], ["id"], ondelete="SET NULL",
    )
    op.create_index("ix_ventes_livraison_statut", "ventes", ["livraison_statut"])
    op.create_index("uq_ventes_numero_bon_livraison", "ventes", ["numero_bon_livraison"], unique=True)

    # Every sale that exists today was, by definition, delivered immediately
    # (the old, only behaviour) — backfill numero_bon_livraison/livree_at so
    # historical sales are indistinguishable from new `livre` ones.
    op.execute(
        "UPDATE ventes SET livree_at = created_at, "
        "numero_bon_livraison = CONCAT('BL-', YEAR(created_at), '-', LPAD(id, 6, '0')) "
        "WHERE deleted_at IS NULL"
    )


def downgrade() -> None:
    op.drop_index("uq_ventes_numero_bon_livraison", table_name="ventes")
    op.drop_index("ix_ventes_livraison_statut", table_name="ventes")
    op.drop_constraint(op.f("fk_ventes_livree_by_users"), "ventes", type_="foreignkey")
    op.drop_column("ventes", "livree_by")
    op.drop_column("ventes", "livree_at")
    op.drop_column("ventes", "numero_bon_livraison")
    op.drop_column("ventes", "livraison_statut")
