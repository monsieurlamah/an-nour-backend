"""Store ORM models: stores and per-store user/role assignments."""
from __future__ import annotations

from decimal import Decimal

from sqlalchemy import ForeignKey, Numeric, String, Text
from sqlalchemy.orm import Mapped, mapped_column

from app.database.base import Entity


class Store(Entity):
    __tablename__ = "stores"

    name: Mapped[str] = mapped_column(String(200), index=True, nullable=False)
    slug: Mapped[str] = mapped_column(String(200), unique=True, index=True, nullable=False)
    code: Mapped[str | None] = mapped_column(String(50), unique=True, nullable=True, index=True)
    description: Mapped[str | None] = mapped_column(Text, nullable=True)
    logo: Mapped[str | None] = mapped_column(String(512), nullable=True)
    address: Mapped[str | None] = mapped_column(String(255), nullable=True)
    city: Mapped[str | None] = mapped_column(String(100), nullable=True)
    phone: Mapped[str | None] = mapped_column(String(30), nullable=True)
    timezone: Mapped[str] = mapped_column(String(50), default="Africa/Conakry", nullable=False)
    devise: Mapped[str] = mapped_column(String(10), default="GNF", nullable=False)
    # Cahier des charges §6.1/§9.2 — "taux de remise maximum autorisé pour les
    # gérants, paramétrable par boutique". NULL = no cap configured (existing
    # behaviour, unrestricted); set (0-100) to actually enforce one. Applies
    # to any vente/proforma created for this boutique, regardless of who
    # rings it up — the cap is a property of the boutique's policy, not of
    # one individual gérant's account.
    remise_max_percent: Mapped[Decimal | None] = mapped_column(Numeric(5, 2), nullable=True)
    gerant_id: Mapped[int | None] = mapped_column(
        ForeignKey("users.id", ondelete="SET NULL"), nullable=True, index=True
    )
    category_store_id: Mapped[int | None] = mapped_column(
        ForeignKey("category_stores.id", ondelete="SET NULL"), nullable=True, index=True
    )
    created_by: Mapped[int | None] = mapped_column(
        ForeignKey("users.id", ondelete="SET NULL"), nullable=True
    )


class StoreUser(Entity):
    __tablename__ = "store_users"

    store_id: Mapped[int] = mapped_column(
        ForeignKey("stores.id", ondelete="CASCADE"), nullable=False, index=True
    )
    user_id: Mapped[int] = mapped_column(
        ForeignKey("users.id", ondelete="CASCADE"), nullable=False, index=True
    )
    role_id: Mapped[int | None] = mapped_column(
        ForeignKey("roles.id", ondelete="SET NULL"), nullable=True, index=True
    )
