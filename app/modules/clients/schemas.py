"""Pydantic schemas for the clients module."""

from decimal import Decimal

from pydantic import BaseModel, Field

from app.database.enums import ClientType
from app.modules.common.schemas import EntityRead


class ClientCreate(BaseModel):
    name: str = Field(min_length=1, max_length=200)
    prenom: str | None = Field(default=None, max_length=100)
    phone: str | None = Field(default=None, max_length=30)
    email: str | None = Field(default=None, max_length=255)
    address: str | None = Field(default=None, max_length=255)
    ville: str | None = Field(default=None, max_length=100)
    type_client: ClientType = ClientType.particulier
    entreprise: str | None = Field(default=None, max_length=200)
    notes: str | None = Field(default=None, max_length=2000)
    plafond_credit: Decimal = Field(default=Decimal("0"), ge=0)
    store_id: int | None = None


class ClientUpdate(BaseModel):
    name: str | None = Field(default=None, min_length=1, max_length=200)
    prenom: str | None = Field(default=None, max_length=100)
    phone: str | None = Field(default=None, max_length=30)
    email: str | None = Field(default=None, max_length=255)
    address: str | None = Field(default=None, max_length=255)
    ville: str | None = Field(default=None, max_length=100)
    type_client: ClientType | None = None
    entreprise: str | None = Field(default=None, max_length=200)
    notes: str | None = Field(default=None, max_length=2000)
    plafond_credit: Decimal | None = Field(default=None, ge=0)
    store_id: int | None = None


class ClientRead(EntityRead):
    code_client: str
    name: str
    prenom: str | None
    phone: str | None
    email: str | None
    address: str | None
    ville: str | None
    type_client: ClientType
    entreprise: str | None
    notes: str | None
    plafond_credit: Decimal
    store_id: int | None
    created_by: int | None
    # Denormalized at read time (see ClientService.list_enriched) — the Boss
    # must see which boutique a client belongs to without a second lookup.
    store_name: str | None = None
