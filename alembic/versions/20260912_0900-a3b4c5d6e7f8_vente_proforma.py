"""ventes: proforma (devis) lifecycle — cahier des charges §9.1-§9.3

A Vente can now start life as a proforma (no stock/paiement impact) before
being transformed into the facture définitive. Additive only — every
existing sale keeps behaving exactly as before, just gains a
numero_facture it never had.

Revision ID: a3b4c5d6e7f8
Revises: f1a2b3c4d5e6
Create Date: 2026-09-12 09:00:00.000000
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "a3b4c5d6e7f8"
down_revision: str | None = "f1a2b3c4d5e6"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column("ventes", sa.Column("numero_proforma", sa.String(length=30), nullable=True))
    op.add_column("ventes", sa.Column("numero_facture", sa.String(length=30), nullable=True))
    op.add_column("ventes", sa.Column("proforma_valide_jusquau", sa.DateTime(), nullable=True))
    op.add_column("ventes", sa.Column("proforma_refus_motif", sa.Text(), nullable=True))
    op.add_column("ventes", sa.Column("proforma_refused_by", sa.BigInteger(), nullable=True))
    op.add_column("ventes", sa.Column("proforma_refused_at", sa.DateTime(), nullable=True))
    op.add_column("ventes", sa.Column("facture_by", sa.BigInteger(), nullable=True))
    op.add_column("ventes", sa.Column("facture_at", sa.DateTime(), nullable=True))

    op.create_unique_constraint(
        op.f("uq_ventes_numero_proforma"), "ventes", ["numero_proforma"]
    )
    op.create_unique_constraint(
        op.f("uq_ventes_numero_facture"), "ventes", ["numero_facture"]
    )
    op.create_foreign_key(
        op.f("fk_ventes_proforma_refused_by_users"),
        "ventes", "users", ["proforma_refused_by"], ["id"], ondelete="SET NULL",
    )
    op.create_foreign_key(
        op.f("fk_ventes_facture_by_users"),
        "ventes", "users", ["facture_by"], ["id"], ondelete="SET NULL",
    )


def downgrade() -> None:
    op.drop_constraint(op.f("fk_ventes_facture_by_users"), "ventes", type_="foreignkey")
    op.drop_constraint(op.f("fk_ventes_proforma_refused_by_users"), "ventes", type_="foreignkey")
    op.drop_constraint(op.f("uq_ventes_numero_facture"), "ventes", type_="unique")
    op.drop_constraint(op.f("uq_ventes_numero_proforma"), "ventes", type_="unique")

    op.drop_column("ventes", "facture_at")
    op.drop_column("ventes", "facture_by")
    op.drop_column("ventes", "proforma_refused_at")
    op.drop_column("ventes", "proforma_refused_by")
    op.drop_column("ventes", "proforma_refus_motif")
    op.drop_column("ventes", "proforma_valide_jusquau")
    op.drop_column("ventes", "numero_facture")
    op.drop_column("ventes", "numero_proforma")
