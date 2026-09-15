"""users: unique identifiant login + optional email

The super-admin can now create an account with no email at all — the user
logs in with a server-generated identifiant instead (communicated to them
directly). Every existing user is backfilled with one derived from their
name, e.g. "mamadou diallo" -> "mamadou-diallo" (then "-2", "-3", ... on
collision).

Revision ID: a1b2c3d4e5f6
Revises: f7a8b9c0d1e2
Create Date: 2026-09-15 09:00:00
"""

import re
import unicodedata
from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "b7c8d9e0f1a2"
down_revision: str | None = "f7a8b9c0d1e2"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

_SLUG_RE = re.compile(r"[^a-z0-9]+")


def _slugify(value: str) -> str:
    normalized = unicodedata.normalize("NFKD", value)
    ascii_only = normalized.encode("ascii", "ignore").decode("ascii")
    return _SLUG_RE.sub("-", ascii_only.strip().lower()).strip("-") or "user"


def upgrade() -> None:
    op.add_column("users", sa.Column("identifiant", sa.String(length=50), nullable=True))
    op.alter_column("users", "email", existing_type=sa.String(length=255), nullable=True)

    conn = op.get_bind()
    rows = conn.execute(sa.text("SELECT id, firstname, lastname FROM users")).fetchall()
    taken: set[str] = set()
    for user_id, firstname, lastname in rows:
        base = _slugify(f"{firstname} {lastname}")
        candidate = base
        suffix = 2
        while candidate in taken:
            candidate = f"{base}-{suffix}"
            suffix += 1
        taken.add(candidate)
        conn.execute(
            sa.text("UPDATE users SET identifiant = :identifiant WHERE id = :id"),
            {"identifiant": candidate, "id": user_id},
        )

    op.alter_column("users", "identifiant", existing_type=sa.String(length=50), nullable=False)
    op.create_index(op.f("ix_users_identifiant"), "users", ["identifiant"], unique=True)


def downgrade() -> None:
    op.drop_index(op.f("ix_users_identifiant"), table_name="users")
    op.drop_column("users", "identifiant")
    op.alter_column("users", "email", existing_type=sa.String(length=255), nullable=False)
