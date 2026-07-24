"""erp_stock_refactor

Revision ID: f3a8b9c2d1e4
Revises: e568baa6fa82
Create Date: 2026-06-26 12:00:00.000000

Full ERP stock architecture refactor:
- Create stock_locations and product_stocks tables
- Migrate data from stock_central / stock_boutique
- Redesign stock_movements (from/to location IDs, reason, costs)
- Add catalog fields to products (sku, barcode, brand, uom, tva)
- Drop denormalised products.quantity and products.alert_central
- Drop stock_central and stock_boutique tables
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "f3a8b9c2d1e4"
down_revision: str | None = "e568baa6fa82"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    # ── 1. Create stock_locations ─────────────────────────────────────────────
    op.create_table(
        "stock_locations",
        sa.Column("id", sa.BigInteger(), autoincrement=True, nullable=False),
        sa.Column("uuid", sa.String(36), nullable=False),
        sa.Column("name", sa.String(150), nullable=False),
        sa.Column("type", sa.String(20), nullable=False),
        sa.Column("store_id", sa.BigInteger(), nullable=True),
        sa.Column("created_by", sa.BigInteger(), nullable=True),
        sa.Column("status", sa.String(20), nullable=False, server_default="active"),
        sa.Column("infos", sa.JSON(), nullable=True),
        sa.Column("created_at", sa.DateTime(), server_default=sa.text("NOW()"), nullable=False),
        sa.Column("updated_at", sa.DateTime(), server_default=sa.text("NOW()"), nullable=False),
        sa.Column("deleted_at", sa.DateTime(), nullable=True),
        sa.ForeignKeyConstraint(
            ["store_id"], ["stores.id"],
            name="fk_stock_locations_store_id_stores", ondelete="SET NULL",
        ),
        sa.ForeignKeyConstraint(
            ["created_by"], ["users.id"],
            name="fk_stock_locations_created_by_users", ondelete="SET NULL",
        ),
        sa.PrimaryKeyConstraint("id", name="pk_stock_locations"),
        sa.UniqueConstraint("uuid", name="uq_stock_locations_uuid"),
    )
    op.create_index("ix_stock_locations_uuid", "stock_locations", ["uuid"], unique=True)
    op.create_index("ix_stock_locations_type", "stock_locations", ["type"])
    op.create_index("ix_stock_locations_store_id", "stock_locations", ["store_id"])
    op.create_index("ix_stock_locations_status", "stock_locations", ["status"])
    op.create_index("ix_stock_locations_deleted_at", "stock_locations", ["deleted_at"])

    # ── 2. Create product_stocks ──────────────────────────────────────────────
    op.create_table(
        "product_stocks",
        sa.Column("id", sa.BigInteger(), autoincrement=True, nullable=False),
        sa.Column("uuid", sa.String(36), nullable=False),
        sa.Column("product_id", sa.BigInteger(), nullable=False),
        sa.Column("location_id", sa.BigInteger(), nullable=False),
        sa.Column("quantity", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("alert_threshold", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("status", sa.String(20), nullable=False, server_default="active"),
        sa.Column("infos", sa.JSON(), nullable=True),
        sa.Column("created_at", sa.DateTime(), server_default=sa.text("NOW()"), nullable=False),
        sa.Column("updated_at", sa.DateTime(), server_default=sa.text("NOW()"), nullable=False),
        sa.Column("deleted_at", sa.DateTime(), nullable=True),
        sa.ForeignKeyConstraint(
            ["product_id"], ["products.id"],
            name="fk_product_stocks_product_id_products", ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["location_id"], ["stock_locations.id"],
            name="fk_product_stocks_location_id_stock_locations", ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("id", name="pk_product_stocks"),
        sa.UniqueConstraint("uuid", name="uq_product_stocks_uuid"),
    )
    op.create_index("ix_product_stocks_uuid", "product_stocks", ["uuid"], unique=True)
    op.create_index("ix_product_stocks_product_id", "product_stocks", ["product_id"])
    op.create_index("ix_product_stocks_location_id", "product_stocks", ["location_id"])
    op.create_index("ix_product_stocks_status", "product_stocks", ["status"])
    op.create_index("ix_product_stocks_deleted_at", "product_stocks", ["deleted_at"])

    # ── 3. Data: insert CENTRAL location ──────────────────────────────────────
    op.execute(
        "INSERT INTO stock_locations (uuid, name, type, status, created_at, updated_at) "
        "VALUES (UUID(), 'Stock Central', 'CENTRAL', 'active', NOW(), NOW())"
    )

    # ── 4. Data: migrate stock_central → product_stocks ───────────────────────
    op.execute("""
        INSERT INTO product_stocks (uuid, product_id, location_id, quantity, alert_threshold, status, created_at, updated_at)
        SELECT UUID(), sc.product_id, sl.id, sc.quantity, sc.seuil_alert, 'active', NOW(), NOW()
        FROM stock_central sc
        CROSS JOIN (SELECT id FROM stock_locations WHERE type = 'CENTRAL' LIMIT 1) sl
        WHERE sc.deleted_at IS NULL
    """)

    # ── 5. Data: insert STORE locations for each boutique in stock_boutique ───
    op.execute("""
        INSERT INTO stock_locations (uuid, name, type, store_id, status, created_at, updated_at)
        SELECT UUID(),
               CONCAT(COALESCE(s.name, CONCAT('Boutique #', sb.boutique_id)), ' (Stock)'),
               'STORE', sb.boutique_id, 'active', NOW(), NOW()
        FROM (SELECT DISTINCT boutique_id FROM stock_boutique WHERE deleted_at IS NULL) sb
        LEFT JOIN stores s ON s.id = sb.boutique_id
    """)

    # ── 6. Data: migrate stock_boutique → product_stocks ─────────────────────
    op.execute("""
        INSERT INTO product_stocks (uuid, product_id, location_id, quantity, alert_threshold, status, created_at, updated_at)
        SELECT UUID(), sb.product_id, sl.id, sb.quantity, sb.seuil_alert, 'active', NOW(), NOW()
        FROM stock_boutique sb
        JOIN stock_locations sl ON sl.store_id = sb.boutique_id AND sl.type = 'STORE'
        WHERE sb.deleted_at IS NULL
    """)

    # ── 7. Add new columns to stock_movements ─────────────────────────────────
    op.add_column("stock_movements", sa.Column("from_location_id", sa.BigInteger(), nullable=True))
    op.add_column("stock_movements", sa.Column("to_location_id", sa.BigInteger(), nullable=True))
    op.add_column("stock_movements", sa.Column("reason", sa.String(30), nullable=True))
    op.add_column("stock_movements", sa.Column("unit_cost", sa.Numeric(14, 2), nullable=True))
    op.add_column("stock_movements", sa.Column("total_cost", sa.Numeric(14, 2), nullable=True))
    op.add_column("stock_movements", sa.Column("reference", sa.String(100), nullable=True))

    # ── 8. Data: set reason from old movement_type values ────────────────────
    op.execute("""
        UPDATE stock_movements SET reason = CASE movement_type
            WHEN 'ACHAT'              THEN 'PURCHASE'
            WHEN 'LIVRAISON'          THEN 'PURCHASE'
            WHEN 'VENTE'              THEN 'SALE'
            WHEN 'RETOUR_CLIENT'      THEN 'RETURN'
            WHEN 'RETOUR_FOURNISSEUR' THEN 'RETURN'
            WHEN 'TRANSFERT'          THEN 'OTHER'
            WHEN 'AJUSTEMENT'         THEN 'INVENTORY'
            WHEN 'INVENTAIRE'         THEN 'INVENTORY'
            ELSE 'OTHER'
        END
    """)

    # ── 9. Data: remap movement_type to new enum values ───────────────────────
    op.execute("""
        UPDATE stock_movements SET movement_type = CASE movement_type
            WHEN 'ACHAT'              THEN 'IN'
            WHEN 'LIVRAISON'          THEN 'IN'
            WHEN 'VENTE'              THEN 'OUT'
            WHEN 'RETOUR_CLIENT'      THEN 'IN'
            WHEN 'RETOUR_FOURNISSEUR' THEN 'OUT'
            WHEN 'TRANSFERT'          THEN 'TRANSFER'
            WHEN 'AJUSTEMENT'         THEN 'ADJUSTMENT'
            WHEN 'INVENTAIRE'         THEN 'ADJUSTMENT'
            ELSE 'ADJUSTMENT'
        END
    """)

    # ── 10. Data: wire from/to location IDs on existing movements ─────────────
    # Movements without store_id → reference CENTRAL
    op.execute("""
        UPDATE stock_movements sm
        JOIN stock_locations sl ON sl.type = 'CENTRAL'
        SET sm.to_location_id   = CASE WHEN sm.movement_type = 'IN'         THEN sl.id ELSE sm.to_location_id   END,
            sm.from_location_id = CASE WHEN sm.movement_type IN ('OUT','ADJUSTMENT') THEN sl.id ELSE sm.from_location_id END
        WHERE sm.from_location_id IS NULL AND sm.to_location_id IS NULL
    """)

    # ── 11. Add FK constraints on the new location columns ────────────────────
    op.create_foreign_key(
        "fk_stock_movements_from_location_id_stock_locations",
        "stock_movements", "stock_locations",
        ["from_location_id"], ["id"], ondelete="SET NULL",
    )
    op.create_foreign_key(
        "fk_stock_movements_to_location_id_stock_locations",
        "stock_movements", "stock_locations",
        ["to_location_id"], ["id"], ondelete="SET NULL",
    )

    # ── 12. Drop old FK and columns from stock_movements ──────────────────────
    op.execute("ALTER TABLE stock_movements DROP FOREIGN KEY fk_stock_movements_store_id_stores")
    op.drop_column("stock_movements", "store_id")
    op.drop_column("stock_movements", "source_type")
    op.drop_column("stock_movements", "source_id")
    op.drop_column("stock_movements", "destination_type")
    op.drop_column("stock_movements", "destination_id")
    op.drop_column("stock_movements", "reference_type")
    op.drop_column("stock_movements", "reference_id")

    # ── 13. Add new catalog columns to products ───────────────────────────────
    op.add_column("products", sa.Column("sku", sa.String(100), nullable=True))
    op.add_column("products", sa.Column("barcode", sa.String(100), nullable=True))
    op.add_column("products", sa.Column("brand", sa.String(150), nullable=True))
    op.add_column("products", sa.Column("unit_of_measure", sa.String(50), nullable=True))
    op.add_column("products", sa.Column("tva", sa.Numeric(5, 2), nullable=False, server_default="0"))
    op.create_unique_constraint("uq_products_sku", "products", ["sku"])
    op.create_unique_constraint("uq_products_barcode", "products", ["barcode"])
    op.create_index("ix_products_sku", "products", ["sku"])
    op.create_index("ix_products_barcode", "products", ["barcode"])

    # ── 14. Drop denormalised stock columns from products ─────────────────────
    op.drop_column("products", "quantity")
    op.drop_column("products", "alert_central")

    # ── 15. Drop old stock tables ─────────────────────────────────────────────
    op.execute("SET FOREIGN_KEY_CHECKS = 0")
    op.drop_table("stock_boutique")
    op.drop_table("stock_central")
    op.execute("SET FOREIGN_KEY_CHECKS = 1")


def downgrade() -> None:
    raise NotImplementedError(
        "Downgrade not supported for this migration. "
        "Restore from a database backup if needed."
    )
