"""commandes: internal réappro workflow (statuses, documents, audit trail, stock link)

Revision ID: c9d8e7f6a5b4
Revises: e1f2a3b4c5d6
Create Date: 2026-07-12 10:00:00.000000
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "c9d8e7f6a5b4"
down_revision: str | None = "e1f2a3b4c5d6"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    # --- commandes: widen statut, add document/refusal/amount columns ---
    op.alter_column(
        "commandes", "statut",
        existing_type=sa.String(length=20),
        type_=sa.String(length=32),
        existing_nullable=False,
    )
    op.add_column("commandes", sa.Column("numero", sa.String(length=30), nullable=True))
    op.add_column("commandes", sa.Column("montant_ht", sa.Numeric(precision=14, scale=2), nullable=False, server_default="0"))
    op.add_column("commandes", sa.Column("tva_taux", sa.Numeric(precision=5, scale=2), nullable=False, server_default="0"))
    op.add_column("commandes", sa.Column("montant_tva", sa.Numeric(precision=14, scale=2), nullable=False, server_default="0"))
    op.add_column("commandes", sa.Column("montant_ttc", sa.Numeric(precision=14, scale=2), nullable=False, server_default="0"))
    op.add_column("commandes", sa.Column("numero_proforma", sa.String(length=30), nullable=True))
    op.add_column("commandes", sa.Column("numero_facture", sa.String(length=30), nullable=True))
    op.add_column("commandes", sa.Column("refus_motif", sa.Text(), nullable=True))
    op.add_column("commandes", sa.Column("refused_by", sa.BigInteger(), nullable=True))
    op.add_column("commandes", sa.Column("refused_at", sa.DateTime(), nullable=True))
    op.create_foreign_key(
        op.f("fk_commandes_refused_by_users"), "commandes", "users", ["refused_by"], ["id"], ondelete="SET NULL",
    )
    op.create_index("uq_commandes_numero", "commandes", ["numero"], unique=True)
    op.create_index("uq_commandes_numero_proforma", "commandes", ["numero_proforma"], unique=True)
    op.create_index("uq_commandes_numero_facture", "commandes", ["numero_facture"], unique=True)

    # --- commande_lignes: delivered/received quantities + observation ---
    op.add_column("commande_lignes", sa.Column("quantite_livree", sa.Integer(), nullable=False, server_default="0"))
    op.add_column("commande_lignes", sa.Column("quantite_recue", sa.Integer(), nullable=False, server_default="0"))
    op.add_column("commande_lignes", sa.Column("observation", sa.Text(), nullable=True))

    # --- notifications: deep-link column ---
    op.add_column("notifications", sa.Column("link", sa.String(length=255), nullable=True))

    # --- commande_evenements: append-only audit trail (LogEntity) ---
    op.create_table(
        "commande_evenements",
        sa.Column("id", sa.BigInteger(), autoincrement=True, nullable=False),
        sa.Column("uuid", sa.String(length=36), nullable=False),
        sa.Column("commande_id", sa.BigInteger(), nullable=False),
        sa.Column(
            "type_evenement",
            sa.Enum(
                "creation", "soumission", "validation", "refus", "proforma", "facture",
                "preparation", "expedition", "livraison", "reception", "anomalie",
                "quantites_modifiees", "commentaire", "annulation",
                name="commandeevenementtype", native_enum=False, length=32,
            ),
            nullable=False,
        ),
        sa.Column("acteur_id", sa.BigInteger(), nullable=True),
        sa.Column("commentaire", sa.Text(), nullable=True),
        sa.Column("ip_address", sa.String(length=45), nullable=True),
        sa.Column("metadata", sa.JSON(), nullable=True),
        sa.Column("created_at", sa.DateTime(), server_default=sa.text("now()"), nullable=False),
        sa.ForeignKeyConstraint(["acteur_id"], ["users.id"], name=op.f("fk_commande_evenements_acteur_id_users"), ondelete="SET NULL"),
        sa.ForeignKeyConstraint(["commande_id"], ["commandes.id"], name=op.f("fk_commande_evenements_commande_id_commandes"), ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_commande_evenements")),
        sa.UniqueConstraint("uuid", name="uq_commande_evenements_uuid"),
    )
    op.create_index("ix_commande_evenements_uuid", "commande_evenements", ["uuid"], unique=True)
    op.create_index("ix_commande_evenements_commande_id", "commande_evenements", ["commande_id"])
    op.create_index("ix_commande_evenements_type_evenement", "commande_evenements", ["type_evenement"])

    # --- commande_livraisons: progressive logistics record, 1:1 with commande ---
    op.create_table(
        "commande_livraisons",
        sa.Column("commande_id", sa.BigInteger(), nullable=False),
        sa.Column("numero_bon_preparation", sa.String(length=30), nullable=True),
        sa.Column("preparateur_id", sa.BigInteger(), nullable=True),
        sa.Column("prepared_at", sa.DateTime(), nullable=True),
        sa.Column("transporteur", sa.String(length=150), nullable=True),
        sa.Column("livreur_id", sa.BigInteger(), nullable=True),
        sa.Column("livreur_nom", sa.String(length=150), nullable=True),
        sa.Column("numero_bon_livraison", sa.String(length=30), nullable=True),
        sa.Column("date_expedition", sa.DateTime(), nullable=True),
        sa.Column("date_livraison", sa.DateTime(), nullable=True),
        sa.Column("qr_content", sa.String(length=100), nullable=True),
        sa.Column("code_barre", sa.String(length=100), nullable=True),
        sa.Column("signature_hq_by", sa.BigInteger(), nullable=True),
        sa.Column("signature_hq_at", sa.DateTime(), nullable=True),
        sa.Column("signature_boutique_by", sa.BigInteger(), nullable=True),
        sa.Column("signature_boutique_at", sa.DateTime(), nullable=True),
        sa.Column("id", sa.BigInteger(), autoincrement=True, nullable=False),
        sa.Column("uuid", sa.String(length=36), nullable=False),
        sa.Column("status", sa.Enum("active", "inactive", "archived", name="recordstatus", native_enum=False, length=20), nullable=False),
        sa.Column("infos", sa.JSON(), nullable=True),
        sa.Column("created_at", sa.DateTime(), server_default=sa.text("now()"), nullable=False),
        sa.Column("updated_at", sa.DateTime(), server_default=sa.text("now()"), nullable=False),
        sa.Column("deleted_at", sa.DateTime(), nullable=True),
        sa.ForeignKeyConstraint(["commande_id"], ["commandes.id"], name=op.f("fk_commande_livraisons_commande_id_commandes"), ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["preparateur_id"], ["users.id"], name=op.f("fk_commande_livraisons_preparateur_id_users"), ondelete="SET NULL"),
        sa.ForeignKeyConstraint(["livreur_id"], ["users.id"], name=op.f("fk_commande_livraisons_livreur_id_users"), ondelete="SET NULL"),
        sa.ForeignKeyConstraint(["signature_hq_by"], ["users.id"], name=op.f("fk_commande_livraisons_signature_hq_by_users"), ondelete="SET NULL"),
        sa.ForeignKeyConstraint(["signature_boutique_by"], ["users.id"], name=op.f("fk_commande_livraisons_signature_boutique_by_users"), ondelete="SET NULL"),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_commande_livraisons")),
        sa.UniqueConstraint("uuid", name="uq_commande_livraisons_uuid"),
        sa.UniqueConstraint("commande_id", name="uq_commande_livraisons_commande_id"),
        sa.UniqueConstraint("numero_bon_preparation", name="uq_commande_livraisons_numero_bon_preparation"),
        sa.UniqueConstraint("numero_bon_livraison", name="uq_commande_livraisons_numero_bon_livraison"),
    )
    op.create_index("ix_commande_livraisons_uuid", "commande_livraisons", ["uuid"], unique=True)
    op.create_index("ix_commande_livraisons_status", "commande_livraisons", ["status"])

    # --- commande_receptions: 1:many with commande (a partial delivery can be
    # followed by a later complement — see CommandeService.confirm_reception) ---
    op.create_table(
        "commande_receptions",
        sa.Column("commande_id", sa.BigInteger(), nullable=False),
        sa.Column("recu_par", sa.BigInteger(), nullable=True),
        sa.Column("date_reception", sa.DateTime(), nullable=True),
        sa.Column(
            "statut_reception",
            sa.Enum("accepte", "refuse", "partiel", name="commandereceptionstatut", native_enum=False, length=20),
            nullable=False,
        ),
        sa.Column("commentaire", sa.Text(), nullable=True),
        sa.Column("id", sa.BigInteger(), autoincrement=True, nullable=False),
        sa.Column("uuid", sa.String(length=36), nullable=False),
        sa.Column("status", sa.Enum("active", "inactive", "archived", name="recordstatus", native_enum=False, length=20), nullable=False),
        sa.Column("infos", sa.JSON(), nullable=True),
        sa.Column("created_at", sa.DateTime(), server_default=sa.text("now()"), nullable=False),
        sa.Column("updated_at", sa.DateTime(), server_default=sa.text("now()"), nullable=False),
        sa.Column("deleted_at", sa.DateTime(), nullable=True),
        sa.ForeignKeyConstraint(["commande_id"], ["commandes.id"], name=op.f("fk_commande_receptions_commande_id_commandes"), ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["recu_par"], ["users.id"], name=op.f("fk_commande_receptions_recu_par_users"), ondelete="SET NULL"),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_commande_receptions")),
        sa.UniqueConstraint("uuid", name="uq_commande_receptions_uuid"),
    )
    op.create_index("ix_commande_receptions_uuid", "commande_receptions", ["uuid"], unique=True)
    op.create_index("ix_commande_receptions_commande_id", "commande_receptions", ["commande_id"])
    op.create_index("ix_commande_receptions_status", "commande_receptions", ["status"])

    # --- commande_anomalies ---
    op.create_table(
        "commande_anomalies",
        sa.Column("commande_id", sa.BigInteger(), nullable=False),
        sa.Column("reception_id", sa.BigInteger(), nullable=True),
        sa.Column("ligne_id", sa.BigInteger(), nullable=True),
        sa.Column(
            "type_anomalie",
            sa.Enum("quantite_manquante", "produit_casse", "erreur_preparation", "autre", name="commandeanomalietype", native_enum=False, length=30),
            nullable=False,
        ),
        sa.Column("quantite_ecart", sa.Integer(), nullable=False),
        sa.Column("description", sa.Text(), nullable=True),
        sa.Column("created_by", sa.BigInteger(), nullable=True),
        sa.Column("resolved", sa.Boolean(), nullable=False),
        sa.Column("id", sa.BigInteger(), autoincrement=True, nullable=False),
        sa.Column("uuid", sa.String(length=36), nullable=False),
        sa.Column("status", sa.Enum("active", "inactive", "archived", name="recordstatus", native_enum=False, length=20), nullable=False),
        sa.Column("infos", sa.JSON(), nullable=True),
        sa.Column("created_at", sa.DateTime(), server_default=sa.text("now()"), nullable=False),
        sa.Column("updated_at", sa.DateTime(), server_default=sa.text("now()"), nullable=False),
        sa.Column("deleted_at", sa.DateTime(), nullable=True),
        sa.ForeignKeyConstraint(["commande_id"], ["commandes.id"], name=op.f("fk_commande_anomalies_commande_id_commandes"), ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["reception_id"], ["commande_receptions.id"], name=op.f("fk_commande_anomalies_reception_id_commande_receptions"), ondelete="SET NULL"),
        sa.ForeignKeyConstraint(["ligne_id"], ["commande_lignes.id"], name=op.f("fk_commande_anomalies_ligne_id_commande_lignes"), ondelete="SET NULL"),
        sa.ForeignKeyConstraint(["created_by"], ["users.id"], name=op.f("fk_commande_anomalies_created_by_users"), ondelete="SET NULL"),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_commande_anomalies")),
        sa.UniqueConstraint("uuid", name="uq_commande_anomalies_uuid"),
    )
    op.create_index("ix_commande_anomalies_uuid", "commande_anomalies", ["uuid"], unique=True)
    op.create_index("ix_commande_anomalies_commande_id", "commande_anomalies", ["commande_id"])
    op.create_index("ix_commande_anomalies_reception_id", "commande_anomalies", ["reception_id"])
    op.create_index("ix_commande_anomalies_status", "commande_anomalies", ["status"])


def downgrade() -> None:
    op.drop_index("ix_commande_anomalies_status", table_name="commande_anomalies")
    op.drop_index("ix_commande_anomalies_reception_id", table_name="commande_anomalies")
    op.drop_index("ix_commande_anomalies_commande_id", table_name="commande_anomalies")
    op.drop_index("ix_commande_anomalies_uuid", table_name="commande_anomalies")
    op.drop_table("commande_anomalies")

    op.drop_index("ix_commande_receptions_status", table_name="commande_receptions")
    op.drop_index("ix_commande_receptions_commande_id", table_name="commande_receptions")
    op.drop_index("ix_commande_receptions_uuid", table_name="commande_receptions")
    op.drop_table("commande_receptions")

    op.drop_index("ix_commande_livraisons_status", table_name="commande_livraisons")
    op.drop_index("ix_commande_livraisons_uuid", table_name="commande_livraisons")
    op.drop_table("commande_livraisons")

    op.drop_index("ix_commande_evenements_type_evenement", table_name="commande_evenements")
    op.drop_index("ix_commande_evenements_commande_id", table_name="commande_evenements")
    op.drop_index("ix_commande_evenements_uuid", table_name="commande_evenements")
    op.drop_table("commande_evenements")

    op.drop_column("notifications", "link")

    op.drop_column("commande_lignes", "observation")
    op.drop_column("commande_lignes", "quantite_recue")
    op.drop_column("commande_lignes", "quantite_livree")

    op.drop_index("uq_commandes_numero_facture", table_name="commandes")
    op.drop_index("uq_commandes_numero_proforma", table_name="commandes")
    op.drop_index("uq_commandes_numero", table_name="commandes")
    op.drop_constraint(op.f("fk_commandes_refused_by_users"), "commandes", type_="foreignkey")
    op.drop_column("commandes", "refused_at")
    op.drop_column("commandes", "refused_by")
    op.drop_column("commandes", "refus_motif")
    op.drop_column("commandes", "numero_facture")
    op.drop_column("commandes", "numero_proforma")
    op.drop_column("commandes", "montant_ttc")
    op.drop_column("commandes", "montant_tva")
    op.drop_column("commandes", "tva_taux")
    op.drop_column("commandes", "montant_ht")
    op.drop_column("commandes", "numero")
    op.alter_column(
        "commandes", "statut",
        existing_type=sa.String(length=32),
        type_=sa.String(length=20),
        existing_nullable=False,
    )
