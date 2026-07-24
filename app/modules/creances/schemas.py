"""Pydantic schemas for the creances module."""

from datetime import datetime
from decimal import Decimal

from pydantic import BaseModel, Field

from app.database.enums import CreanceStatut, PaiementMode
from app.modules.common.schemas import EntityRead


class CreanceCreate(BaseModel):
    client_id: int
    boutique_id: int
    montant_initial: Decimal = Field(ge=0)
    vente_id: int | None = None
    montant_restant: Decimal | None = Field(default=None, ge=0)
    date_echeance: datetime | None = None


class CreanceUpdate(BaseModel):
    date_echeance: datetime | None = None
    statut: CreanceStatut | None = None


class CreanceRead(EntityRead):
    vente_id: int | None
    client_id: int
    boutique_id: int
    montant_initial: Decimal
    montant_restant: Decimal
    date_echeance: datetime | None
    statut: CreanceStatut
    # Denormalized at read time (see CreanceService.list_enriched) — a
    # créance must still show who owes what even if the client record was
    # since soft-deleted; the frontend has no scoped way to look that up
    # itself (clients.view only ever returns active clients).
    #
    # Optional (not just nullable, actually absent-safe via defaults):
    # VenteRead.creance nests a raw Creance ORM relationship that never goes
    # through CreanceService.enrich() — these three stay unset there rather
    # than breaking every credit-sale response's serialization.
    client_name: str | None = None
    client_phone: str | None = None
    store_name: str | None = None


class PaiementCreate(BaseModel):
    montant: Decimal = Field(gt=0)
    mode: PaiementMode = PaiementMode.especes
    reference: str | None = Field(default=None, max_length=100)
    vente_id: int | None = None
    creance_id: int | None = None


class PaiementRead(EntityRead):
    vente_id: int | None
    creance_id: int | None
    montant: Decimal
    mode: PaiementMode
    reference: str | None
