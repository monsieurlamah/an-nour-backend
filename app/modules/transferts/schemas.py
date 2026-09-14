"""Pydantic schemas for the transferts module (cahier des charges §7.4/§12)."""

from datetime import datetime

from pydantic import BaseModel, Field, model_validator

from app.database.enums import TransfertStatut
from app.modules.common.schemas import EntityRead


class TransfertLigneCreate(BaseModel):
    produit_id: int
    quantite: int = Field(ge=1)


class TransfertLigneRead(EntityRead):
    transfert_id: int
    produit_id: int
    quantite_envoyee: int
    quantite_recue: int
    observation: str | None


class TransfertCreate(BaseModel):
    # Exactly one of each pair (id vs the "is the boutique principale" flag)
    # is required per side — see _resolve_location in services.py for how a
    # None boutique id then resolves to the central stock location.
    boutique_source_id: int | None = None
    source_est_principale: bool = False
    boutique_destination_id: int | None = None
    destination_est_principale: bool = False
    motif: str | None = Field(default=None, max_length=2000)
    lignes: list[TransfertLigneCreate] = Field(min_length=1)

    @model_validator(mode="after")
    def _valid_endpoints(self) -> "TransfertCreate":
        if bool(self.boutique_source_id) == bool(self.source_est_principale):
            if self.boutique_source_id is None and not self.source_est_principale:
                raise ValueError("La boutique source est obligatoire (ou source_est_principale).")
            if self.boutique_source_id is not None and self.source_est_principale:
                raise ValueError(
                    "Choisissez une boutique source OU la boutique principale, pas les deux."
                )
        if bool(self.boutique_destination_id) == bool(self.destination_est_principale):
            if self.boutique_destination_id is None and not self.destination_est_principale:
                raise ValueError(
                    "La boutique destination est obligatoire (ou destination_est_principale)."
                )
            if self.boutique_destination_id is not None and self.destination_est_principale:
                raise ValueError(
                    "Choisissez une boutique destination OU la boutique principale, pas les deux."
                )
        if (
            self.boutique_source_id is not None
            and self.boutique_source_id == self.boutique_destination_id
        ):
            raise ValueError(
                "La boutique source et la boutique destination doivent être différentes."
            )
        if self.source_est_principale and self.destination_est_principale:
            raise ValueError(
                "La source et la destination ne peuvent pas être toutes deux la principale."
            )
        return self


class TransfertReceptionLigne(BaseModel):
    ligne_id: int
    quantite_recue: int = Field(ge=0)
    observation: str | None = Field(default=None, max_length=500)


class TransfertReceive(BaseModel):
    lignes: list[TransfertReceptionLigne] = Field(min_length=1)


class TransfertCancel(BaseModel):
    motif: str = Field(min_length=1, max_length=2000)


class TransfertRead(EntityRead):
    boutique_source_id: int | None
    boutique_destination_id: int | None
    created_by: int | None
    receptionne_par: int | None
    annule_par: int | None
    numero: str
    statut: TransfertStatut
    motif: str | None
    annule_motif: str | None
    expedie_at: datetime | None = None
    receptionne_at: datetime | None = None
    annule_at: datetime | None = None
    lignes: list[TransfertLigneRead] = []
    # Denormalized at read time (TransfertService.enrich) — same pattern as
    # CreanceService._to_dict.
    boutique_source_name: str | None = None
    boutique_destination_name: str | None = None
