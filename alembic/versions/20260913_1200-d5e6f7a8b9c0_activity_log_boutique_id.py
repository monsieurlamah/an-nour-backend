"""activity_logs: boutique_id — cahier des charges §14

Lets the journal be filtered "par boutique" and scoped so a gérant only
ever sees their own boutique's entries (enforced at the router).

Revision ID: d5e6f7a8b9c0
Revises: c4d5e6f7a8b9
Create Date: 2026-09-13 12:00:00.000000
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "d5e6f7a8b9c0"
down_revision: str | None = "c4d5e6f7a8b9"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column("activity_logs", sa.Column("boutique_id", sa.Integer(), nullable=True))
    op.create_index(
        op.f("ix_activity_logs_boutique_id"), "activity_logs", ["boutique_id"], unique=False
    )


def downgrade() -> None:
    op.drop_index(op.f("ix_activity_logs_boutique_id"), table_name="activity_logs")
    op.drop_column("activity_logs", "boutique_id")
