"""Transfert ORM models — cahier des charges §7.4/§12: moving stock between
any two boutiques of the network (principale <-> délocalisée, or délocalisée
<-> délocalisée), independent of the réapprovisionnement circuit
(app.modules.commandes, boutique -> HQ only).

Nothing here ever touches ``ProductStock`` directly — see
``TransfertService.create`` (decrements the source) and
``TransfertService.receive`` (credits the destination) in services.py for
the only two places stock actually moves.
"""
from __future__ import annotations

from datetime import datetime

from sqlalchemy import DateTime, Enum, ForeignKey, Integer, String, Text
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.database.base import Entity
from app.database.enums import TransfertStatut


class Transfert(Entity):
    __tablename__ = "transferts"

    # NULL means the boutique principale (central stock) — see
    # TransfertService._resolve_location. Never both NULL (validated at
    # creation) and never equal when both are set.
    boutique_source_id: Mapped[int | None] = mapped_column(
        ForeignKey("stores.id", ondelete="SET NULL"), nullable=True, index=True
    )
    boutique_destination_id: Mapped[int | None] = mapped_column(
        ForeignKey("stores.id", ondelete="SET NULL"), nullable=True, index=True
    )
    created_by: Mapped[int | None] = mapped_column(
        ForeignKey("users.id", ondelete="SET NULL"), nullable=True
    )
    receptionne_par: Mapped[int | None] = mapped_column(
        ForeignKey("users.id", ondelete="SET NULL"), nullable=True
    )
    annule_par: Mapped[int | None] = mapped_column(
        ForeignKey("users.id", ondelete="SET NULL"), nullable=True
    )

    # Nullable — briefly None between the initial INSERT (which needs the
    # auto-increment id first) and the numero assignment right after, same
    # pattern as Commande.numero. Two NULLs never collide under a UNIQUE
    # index, so there's no placeholder-value race to worry about.
    numero: Mapped[str | None] = mapped_column(String(30), unique=True, nullable=True)
    statut: Mapped[TransfertStatut] = mapped_column(
        Enum(TransfertStatut, native_enum=False, length=25, create_constraint=False),
        default=TransfertStatut.en_transit,
        nullable=False,
        index=True,
    )
    motif: Mapped[str | None] = mapped_column(Text, nullable=True)
    annule_motif: Mapped[str | None] = mapped_column(Text, nullable=True)

    expedie_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    receptionne_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    annule_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)

    lignes: Mapped[list["TransfertLigne"]] = relationship(
        back_populates="transfert", cascade="all, delete-orphan", lazy="selectin"
    )


class TransfertLigne(Entity):
    __tablename__ = "transfert_lignes"

    transfert_id: Mapped[int] = mapped_column(
        ForeignKey("transferts.id", ondelete="CASCADE"), nullable=False, index=True
    )
    produit_id: Mapped[int] = mapped_column(
        ForeignKey("products.id", ondelete="RESTRICT"), nullable=False, index=True
    )
    quantite_envoyee: Mapped[int] = mapped_column(Integer, nullable=False)
    # Filled in only at réception (§7.4 step 3) — 0 until then, never used to
    # mean "nothing received" vs "not yet reconciled": the parent's statut
    # (en_transit vs receptionne*) is what actually distinguishes those.
    quantite_recue: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    observation: Mapped[str | None] = mapped_column(Text, nullable=True)

    transfert: Mapped["Transfert"] = relationship(back_populates="lignes")
