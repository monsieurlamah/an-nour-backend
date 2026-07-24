"""clients: phase 1 — enrichissement du modèle Client

Ajouts :
- code_client (VARCHAR 20, unique, NOT NULL, séquentiel CLI-NNNNNN)
- prenom (VARCHAR 100, nullable)
- email (VARCHAR 255, nullable, unique)
- ville (VARCHAR 100, nullable)
- type_client (VARCHAR 20, NOT NULL, default 'particulier')
- entreprise (VARCHAR 200, nullable)
- notes (TEXT, nullable)
- plafond_credit (DECIMAL 14,2, NOT NULL, default 0)

Contraintes :
- phone devient UNIQUE (index non-unique existant remplacé)
- email UNIQUE + index
- code_client UNIQUE + index

Backfill : les clients existants reçoivent CLI-000001, CLI-000002 ...
ordonnés par id croissant (ROW_NUMBER sur MySQL 8+).

Migration idempotente : chaque opération DDL vérifie l'existence via
information_schema avant d'agir — safe même si une tentative précédente
a partiellement committé (MySQL DDL non transactionnel).

Revision ID: c1d2e3f4a5b6
Revises: b2c3d4e5f6a7
Create Date: 2026-06-27 10:00:00.000000
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "c1d2e3f4a5b6"
down_revision: str | None = "b2c3d4e5f6a7"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

_TABLE = "clients"


def _col_exists(bind: sa.engine.Connection, col: str) -> bool:
    r = bind.execute(
        sa.text(
            "SELECT COUNT(*) FROM information_schema.COLUMNS "
            "WHERE TABLE_SCHEMA = DATABASE() "
            "AND TABLE_NAME = :t AND COLUMN_NAME = :c"
        ),
        {"t": _TABLE, "c": col},
    )
    return bool(r.scalar())


def _index_exists(bind: sa.engine.Connection, idx: str) -> bool:
    r = bind.execute(
        sa.text(
            "SELECT COUNT(*) FROM information_schema.STATISTICS "
            "WHERE TABLE_SCHEMA = DATABASE() "
            "AND TABLE_NAME = :t AND INDEX_NAME = :i"
        ),
        {"t": _TABLE, "i": idx},
    )
    return bool(r.scalar())


def upgrade() -> None:
    bind = op.get_bind()

    # ── 1. Nouveaux champs (idempotents) ────────────────────────────────────────
    if not _col_exists(bind, "code_client"):
        op.add_column(_TABLE, sa.Column("code_client", sa.String(20), nullable=True))

    if not _col_exists(bind, "prenom"):
        op.add_column(_TABLE, sa.Column("prenom", sa.String(100), nullable=True))

    if not _col_exists(bind, "email"):
        op.add_column(_TABLE, sa.Column("email", sa.String(255), nullable=True))

    if not _col_exists(bind, "ville"):
        op.add_column(_TABLE, sa.Column("ville", sa.String(100), nullable=True))

    if not _col_exists(bind, "type_client"):
        op.add_column(
            _TABLE,
            sa.Column(
                "type_client",
                sa.String(20),
                nullable=False,
                server_default="particulier",
            ),
        )

    if not _col_exists(bind, "entreprise"):
        op.add_column(_TABLE, sa.Column("entreprise", sa.String(200), nullable=True))

    if not _col_exists(bind, "notes"):
        op.add_column(_TABLE, sa.Column("notes", sa.Text(), nullable=True))

    if not _col_exists(bind, "plafond_credit"):
        op.add_column(
            _TABLE,
            sa.Column(
                "plafond_credit",
                sa.Numeric(14, 2),
                nullable=False,
                server_default="0",
            ),
        )

    # ── 2. Backfill code_client pour les lignes sans code ───────────────────────
    bind.execute(
        sa.text(
            """
            UPDATE clients c
            INNER JOIN (
                SELECT id, ROW_NUMBER() OVER (ORDER BY id) AS rn
                FROM clients
            ) ranked ON c.id = ranked.id
            SET c.code_client = CONCAT('CLI-', LPAD(ranked.rn, 6, '0'))
            WHERE c.code_client IS NULL
            """
        )
    )

    # ── 3. Passer code_client à NOT NULL (raw SQL : MySQL exige le type complet) ─
    bind.execute(
        sa.text("ALTER TABLE clients MODIFY COLUMN code_client VARCHAR(20) NOT NULL")
    )

    # ── 4. Remplacer l'index non-unique sur phone par une contrainte unique ──────
    if _index_exists(bind, "ix_clients_phone"):
        op.drop_index(op.f("ix_clients_phone"), table_name=_TABLE)

    if not _index_exists(bind, "uq_clients_phone"):
        op.create_unique_constraint("uq_clients_phone", _TABLE, ["phone"])

    # ── 5. Contraintes uniques + index sur les nouveaux champs ─────────────────
    if not _index_exists(bind, "uq_clients_code_client"):
        op.create_unique_constraint("uq_clients_code_client", _TABLE, ["code_client"])

    if not _index_exists(bind, "ix_clients_code_client"):
        op.create_index("ix_clients_code_client", _TABLE, ["code_client"])

    if not _index_exists(bind, "uq_clients_email"):
        op.create_unique_constraint("uq_clients_email", _TABLE, ["email"])

    if not _index_exists(bind, "ix_clients_email"):
        op.create_index("ix_clients_email", _TABLE, ["email"])

    if not _index_exists(bind, "ix_clients_type_client"):
        op.create_index("ix_clients_type_client", _TABLE, ["type_client"])


def downgrade() -> None:
    bind = op.get_bind()

    if _index_exists(bind, "ix_clients_type_client"):
        op.drop_index("ix_clients_type_client", table_name=_TABLE)

    if _index_exists(bind, "ix_clients_email"):
        op.drop_index("ix_clients_email", table_name=_TABLE)
    if _index_exists(bind, "uq_clients_email"):
        op.drop_constraint("uq_clients_email", _TABLE, type_="unique")

    if _index_exists(bind, "ix_clients_code_client"):
        op.drop_index("ix_clients_code_client", table_name=_TABLE)
    if _index_exists(bind, "uq_clients_code_client"):
        op.drop_constraint("uq_clients_code_client", _TABLE, type_="unique")

    if _index_exists(bind, "uq_clients_phone"):
        op.drop_constraint("uq_clients_phone", _TABLE, type_="unique")
    if not _index_exists(bind, "ix_clients_phone"):
        op.create_index(op.f("ix_clients_phone"), _TABLE, ["phone"], unique=False)

    for col in ("plafond_credit", "notes", "entreprise", "type_client", "ville", "email", "prenom", "code_client"):
        if _col_exists(bind, col):
            op.drop_column(_TABLE, col)
