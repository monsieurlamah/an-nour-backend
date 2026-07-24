"""stock: add stock_alert_logs table

Revision ID: b2c3d4e5f6a7
Revises: a1b2c3d4e5f6
Create Date: 2026-06-26 16:00:00.000000
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "b2c3d4e5f6a7"
down_revision: str | None = "a1b2c3d4e5f6"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "stock_alert_logs",
        sa.Column("id", sa.BigInteger(), autoincrement=True, nullable=False),
        sa.Column("uuid", sa.String(length=36), nullable=False),
        sa.Column("product_stock_id", sa.BigInteger(), nullable=False),
        sa.Column("product_id", sa.BigInteger(), nullable=False),
        sa.Column("stock_location_id", sa.BigInteger(), nullable=False),
        sa.Column("alert_type", sa.String(length=20), nullable=False),
        sa.Column("quantity", sa.Integer(), nullable=False),
        sa.Column("alert_threshold", sa.Integer(), nullable=False),
        sa.Column("sent_to", sa.Text(), nullable=False),
        sa.Column("created_at", sa.DateTime(), server_default=sa.text("now()"), nullable=False),
        sa.ForeignKeyConstraint(
            ["product_id"], ["products.id"],
            name="fk_stock_alert_logs_product_id_products",
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["product_stock_id"], ["product_stocks.id"],
            name="fk_stock_alert_logs_product_stock_id_product_stocks",
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["stock_location_id"], ["stock_locations.id"],
            name="fk_stock_alert_logs_stock_location_id_stock_locations",
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("id", name="pk_stock_alert_logs"),
        sa.UniqueConstraint("uuid", name="uq_stock_alert_logs_uuid"),
    )
    op.create_index("ix_stock_alert_logs_uuid", "stock_alert_logs", ["uuid"], unique=True)
    op.create_index("ix_stock_alert_logs_product_stock_id", "stock_alert_logs", ["product_stock_id"])
    op.create_index("ix_stock_alert_logs_product_id", "stock_alert_logs", ["product_id"])
    op.create_index("ix_stock_alert_logs_stock_location_id", "stock_alert_logs", ["stock_location_id"])
    op.create_index("ix_stock_alert_logs_alert_type", "stock_alert_logs", ["alert_type"])


def downgrade() -> None:
    op.drop_index("ix_stock_alert_logs_alert_type", table_name="stock_alert_logs")
    op.drop_index("ix_stock_alert_logs_stock_location_id", table_name="stock_alert_logs")
    op.drop_index("ix_stock_alert_logs_product_id", table_name="stock_alert_logs")
    op.drop_index("ix_stock_alert_logs_product_stock_id", table_name="stock_alert_logs")
    op.drop_index("ix_stock_alert_logs_uuid", table_name="stock_alert_logs")
    op.drop_table("stock_alert_logs")
