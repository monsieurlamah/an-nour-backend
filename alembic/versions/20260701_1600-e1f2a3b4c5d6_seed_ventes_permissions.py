"""Seed official ventes permissions (annuler/retourner/rembourser/imprimer/exporter).

Revision ID: e1f2a3b4c5d6
Revises: bd45949311cf
Create Date: 2026-07-01 16:00:00
"""

import uuid
from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "e1f2a3b4c5d6"
down_revision: str | None = "bd45949311cf"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

PERMISSIONS = [
    ("ventes.annuler", "ventes", "Annuler une vente"),
    ("ventes.retourner", "ventes", "Retourner des produits vendus"),
    ("ventes.rembourser", "ventes", "Rembourser une vente"),
    ("ventes.imprimer", "ventes", "Imprimer un ticket de vente"),
    ("ventes.exporter", "ventes", "Exporter les ventes"),
]


def upgrade() -> None:
    conn = op.get_bind()
    for slug, module, name in PERMISSIONS:
        conn.execute(
            sa.text(
                "INSERT IGNORE INTO permissions (uuid, slug, module, name, status) "
                "VALUES (:uuid, :slug, :module, :name, 'active')"
            ),
            {"uuid": str(uuid.uuid4()), "slug": slug, "module": module, "name": name},
        )


def downgrade() -> None:
    raise NotImplementedError(
        "Downgrade not supported — these permissions are part of the official seed."
    )
