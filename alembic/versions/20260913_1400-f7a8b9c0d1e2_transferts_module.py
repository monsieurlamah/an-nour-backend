"""transferts module — cahier des charges §7.4/§12

New tables: transferts, transfert_lignes. Purely additive.

Revision ID: f7a8b9c0d1e2
Revises: e6f7a8b9c0d1
Create Date: 2026-09-13 14:00:00.000000
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "f7a8b9c0d1e2"
down_revision: str | None = "e6f7a8b9c0d1"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "transferts",
        sa.Column("boutique_source_id", sa.BigInteger(), nullable=True),
        sa.Column("boutique_destination_id", sa.BigInteger(), nullable=True),
        sa.Column("created_by", sa.BigInteger(), nullable=True),
        sa.Column("receptionne_par", sa.BigInteger(), nullable=True),
        sa.Column("annule_par", sa.BigInteger(), nullable=True),
        sa.Column("numero", sa.String(length=30), nullable=True),
        sa.Column(
            "statut",
            sa.Enum(
                "en_transit", "receptionne", "receptionne_avec_ecart", "annule",
                name="transfertstatut", native_enum=False, length=25,
            ),
            nullable=False,
        ),
        sa.Column("motif", sa.Text(), nullable=True),
        sa.Column("annule_motif", sa.Text(), nullable=True),
        sa.Column("expedie_at", sa.DateTime(), nullable=True),
        sa.Column("receptionne_at", sa.DateTime(), nullable=True),
        sa.Column("annule_at", sa.DateTime(), nullable=True),
        sa.Column("id", sa.BigInteger(), autoincrement=True, nullable=False),
        sa.Column("uuid", sa.String(length=36), nullable=False),
        sa.Column(
            "status",
            sa.Enum("active", "inactive", "archived", name="recordstatus", native_enum=False, length=20),
            nullable=False,
        ),
        sa.Column("infos", sa.JSON(), nullable=True),
        sa.Column("created_at", sa.DateTime(), server_default=sa.text("now()"), nullable=False),
        sa.Column("updated_at", sa.DateTime(), server_default=sa.text("now()"), nullable=False),
        sa.Column("deleted_at", sa.DateTime(), nullable=True),
        sa.ForeignKeyConstraint(
            ["boutique_source_id"], ["stores.id"],
            name=op.f("fk_transferts_boutique_source_id_stores"), ondelete="SET NULL",
        ),
        sa.ForeignKeyConstraint(
            ["boutique_destination_id"], ["stores.id"],
            name=op.f("fk_transferts_boutique_destination_id_stores"), ondelete="SET NULL",
        ),
        sa.ForeignKeyConstraint(
            ["created_by"], ["users.id"],
            name=op.f("fk_transferts_created_by_users"), ondelete="SET NULL",
        ),
        sa.ForeignKeyConstraint(
            ["receptionne_par"], ["users.id"],
            name=op.f("fk_transferts_receptionne_par_users"), ondelete="SET NULL",
        ),
        sa.ForeignKeyConstraint(
            ["annule_par"], ["users.id"],
            name=op.f("fk_transferts_annule_par_users"), ondelete="SET NULL",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_transferts")),
        sa.UniqueConstraint("numero", name=op.f("uq_transferts_numero")),
    )
    op.create_index(
        op.f("ix_transferts_boutique_source_id"), "transferts", ["boutique_source_id"], unique=False
    )
    op.create_index(
        op.f("ix_transferts_boutique_destination_id"), "transferts",
        ["boutique_destination_id"], unique=False,
    )
    op.create_index(op.f("ix_transferts_statut"), "transferts", ["statut"], unique=False)
    op.create_index(op.f("ix_transferts_status"), "transferts", ["status"], unique=False)
    op.create_index(op.f("ix_transferts_deleted_at"), "transferts", ["deleted_at"], unique=False)
    op.create_index(op.f("ix_transferts_uuid"), "transferts", ["uuid"], unique=True)

    op.create_table(
        "transfert_lignes",
        sa.Column("transfert_id", sa.BigInteger(), nullable=False),
        sa.Column("produit_id", sa.BigInteger(), nullable=False),
        sa.Column("quantite_envoyee", sa.Integer(), nullable=False),
        sa.Column("quantite_recue", sa.Integer(), nullable=False),
        sa.Column("observation", sa.Text(), nullable=True),
        sa.Column("id", sa.BigInteger(), autoincrement=True, nullable=False),
        sa.Column("uuid", sa.String(length=36), nullable=False),
        sa.Column(
            "status",
            sa.Enum("active", "inactive", "archived", name="recordstatus", native_enum=False, length=20),
            nullable=False,
        ),
        sa.Column("infos", sa.JSON(), nullable=True),
        sa.Column("created_at", sa.DateTime(), server_default=sa.text("now()"), nullable=False),
        sa.Column("updated_at", sa.DateTime(), server_default=sa.text("now()"), nullable=False),
        sa.Column("deleted_at", sa.DateTime(), nullable=True),
        sa.ForeignKeyConstraint(
            ["transfert_id"], ["transferts.id"],
            name=op.f("fk_transfert_lignes_transfert_id_transferts"), ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["produit_id"], ["products.id"],
            name=op.f("fk_transfert_lignes_produit_id_products"), ondelete="RESTRICT",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_transfert_lignes")),
    )
    op.create_index(
        op.f("ix_transfert_lignes_transfert_id"), "transfert_lignes", ["transfert_id"], unique=False
    )
    op.create_index(
        op.f("ix_transfert_lignes_produit_id"), "transfert_lignes", ["produit_id"], unique=False
    )
    op.create_index(op.f("ix_transfert_lignes_status"), "transfert_lignes", ["status"], unique=False)
    op.create_index(
        op.f("ix_transfert_lignes_deleted_at"), "transfert_lignes", ["deleted_at"], unique=False
    )
    op.create_index(op.f("ix_transfert_lignes_uuid"), "transfert_lignes", ["uuid"], unique=True)


def downgrade() -> None:
    op.drop_table("transfert_lignes")
    op.drop_table("transferts")
