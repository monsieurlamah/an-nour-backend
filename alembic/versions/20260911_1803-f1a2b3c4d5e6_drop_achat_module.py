"""drop achat module (suppliers/purchases) — out of scope per cahier des
charges: the network's only "fournisseur" is the boutique principale
itself, already covered by the commandes module. No external-supplier
concept exists in the spec.

Revision ID: f1a2b3c4d5e6
Revises: b4d6e8f1a3c9
Create Date: 2026-09-11 18:03:00.000000
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "f1a2b3c4d5e6"
down_revision: str | None = "b4d6e8f1a3c9"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

_ORPHANED_SLUGS = ("suppliers.view", "suppliers.manage", "purchases.view", "purchases.manage")


def upgrade() -> None:
    conn = op.get_bind()

    # Drop the group/user overrides referencing the permissions we're about
    # to remove, then the permission rows themselves — FK-safe order.
    slugs_sql = ", ".join(f"'{s}'" for s in _ORPHANED_SLUGS)
    conn.execute(sa.text(
        f"DELETE gp FROM group_permissions gp "
        f"JOIN permissions p ON p.id = gp.permission_id WHERE p.slug IN ({slugs_sql})"
    ))
    conn.execute(sa.text(
        f"DELETE up FROM user_permissions up "
        f"JOIN permissions p ON p.id = up.permission_id WHERE p.slug IN ({slugs_sql})"
    ))
    conn.execute(sa.text(f"DELETE FROM permissions WHERE slug IN ({slugs_sql})"))

    op.drop_table("purchase_lines")
    op.drop_table("purchases")
    op.drop_table("suppliers")


def downgrade() -> None:
    op.create_table(
        "suppliers",
        sa.Column("name", sa.String(length=200), nullable=False),
        sa.Column("phone", sa.String(length=30), nullable=True),
        sa.Column("email", sa.String(length=255), nullable=True),
        sa.Column("address", sa.String(length=255), nullable=True),
        sa.Column("id", sa.BigInteger(), autoincrement=True, nullable=False),
        sa.Column("uuid", sa.String(length=36), nullable=False),
        sa.Column("status", sa.Enum("active", "inactive", "archived", name="recordstatus", native_enum=False, length=20), nullable=False),
        sa.Column("infos", sa.JSON(), nullable=True),
        sa.Column("created_at", sa.DateTime(), server_default=sa.text("now()"), nullable=False),
        sa.Column("updated_at", sa.DateTime(), server_default=sa.text("now()"), nullable=False),
        sa.Column("deleted_at", sa.DateTime(), nullable=True),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_suppliers")),
    )
    op.create_index(op.f("ix_suppliers_deleted_at"), "suppliers", ["deleted_at"], unique=False)
    op.create_index(op.f("ix_suppliers_name"), "suppliers", ["name"], unique=False)
    op.create_index(op.f("ix_suppliers_status"), "suppliers", ["status"], unique=False)
    op.create_index(op.f("ix_suppliers_uuid"), "suppliers", ["uuid"], unique=True)

    op.create_table(
        "purchases",
        sa.Column("supplier_id", sa.BigInteger(), nullable=False),
        sa.Column("created_by", sa.BigInteger(), nullable=True),
        sa.Column("montant_total", sa.Numeric(precision=14, scale=2), nullable=False),
        sa.Column("statut", sa.Enum("brouillon", "commandee", "partiellement_recue", "recue", "annulee", name="purchasestatut", native_enum=False, length=25), nullable=False),
        sa.Column("id", sa.BigInteger(), autoincrement=True, nullable=False),
        sa.Column("uuid", sa.String(length=36), nullable=False),
        sa.Column("status", sa.Enum("active", "inactive", "archived", name="recordstatus", native_enum=False, length=20), nullable=False),
        sa.Column("infos", sa.JSON(), nullable=True),
        sa.Column("created_at", sa.DateTime(), server_default=sa.text("now()"), nullable=False),
        sa.Column("updated_at", sa.DateTime(), server_default=sa.text("now()"), nullable=False),
        sa.Column("deleted_at", sa.DateTime(), nullable=True),
        sa.ForeignKeyConstraint(["created_by"], ["users.id"], name=op.f("fk_purchases_created_by_users"), ondelete="SET NULL"),
        sa.ForeignKeyConstraint(["supplier_id"], ["suppliers.id"], name=op.f("fk_purchases_supplier_id_suppliers"), ondelete="RESTRICT"),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_purchases")),
    )
    op.create_index(op.f("ix_purchases_deleted_at"), "purchases", ["deleted_at"], unique=False)
    op.create_index(op.f("ix_purchases_status"), "purchases", ["status"], unique=False)
    op.create_index(op.f("ix_purchases_statut"), "purchases", ["statut"], unique=False)
    op.create_index(op.f("ix_purchases_supplier_id"), "purchases", ["supplier_id"], unique=False)
    op.create_index(op.f("ix_purchases_uuid"), "purchases", ["uuid"], unique=True)

    op.create_table(
        "purchase_lines",
        sa.Column("purchase_id", sa.BigInteger(), nullable=False),
        sa.Column("product_id", sa.BigInteger(), nullable=False),
        sa.Column("quantity", sa.Integer(), nullable=False),
        sa.Column("prix_unitaire", sa.Numeric(precision=14, scale=2), nullable=False),
        sa.Column("total_ligne", sa.Numeric(precision=14, scale=2), nullable=False),
        sa.Column("id", sa.BigInteger(), autoincrement=True, nullable=False),
        sa.Column("uuid", sa.String(length=36), nullable=False),
        sa.Column("status", sa.Enum("active", "inactive", "archived", name="recordstatus", native_enum=False, length=20), nullable=False),
        sa.Column("infos", sa.JSON(), nullable=True),
        sa.Column("created_at", sa.DateTime(), server_default=sa.text("now()"), nullable=False),
        sa.Column("updated_at", sa.DateTime(), server_default=sa.text("now()"), nullable=False),
        sa.Column("deleted_at", sa.DateTime(), nullable=True),
        sa.ForeignKeyConstraint(["product_id"], ["products.id"], name=op.f("fk_purchase_lines_product_id_products"), ondelete="RESTRICT"),
        sa.ForeignKeyConstraint(["purchase_id"], ["purchases.id"], name=op.f("fk_purchase_lines_purchase_id_purchases"), ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_purchase_lines")),
    )
    op.create_index(op.f("ix_purchase_lines_deleted_at"), "purchase_lines", ["deleted_at"], unique=False)
    op.create_index(op.f("ix_purchase_lines_product_id"), "purchase_lines", ["product_id"], unique=False)
    op.create_index(op.f("ix_purchase_lines_purchase_id"), "purchase_lines", ["purchase_id"], unique=False)
    op.create_index(op.f("ix_purchase_lines_status"), "purchase_lines", ["status"], unique=False)
    # Note: permission rows and group/user grants are not restored on
    # downgrade — re-seed (poetry run seed) after downgrading if needed.
