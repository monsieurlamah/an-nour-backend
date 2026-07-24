"""Pydantic schemas for the ventes module."""

from datetime import datetime
from decimal import Decimal

from pydantic import BaseModel, Field

from app.database.enums import PaiementMode, VenteLivraisonStatut, VenteStatut, VenteType
from app.modules.common.schemas import EntityRead
from app.modules.creances.schemas import CreanceRead, PaiementRead


class VenteLigneCreate(BaseModel):
    produit_id: int
    quantite: int = Field(ge=1)
    prix_unitaire: Decimal = Field(default=Decimal("0"), ge=0)
    remise: Decimal = Field(default=Decimal("0"), ge=0)


class VenteLigneRead(EntityRead):
    vente_id: int
    produit_id: int
    quantite: int
    prix_unitaire: Decimal
    remise: Decimal
    total_ligne: Decimal


class VentePaiementCreate(BaseModel):
    """One actually-received payment at sale time. Never used for the unpaid
    remainder — that portion becomes a Creance instead, not a Paiement."""

    mode: PaiementMode = PaiementMode.especes
    montant: Decimal = Field(gt=0)
    reference: str | None = Field(default=None, max_length=100)


class VenteCreate(BaseModel):
    boutique_id: int
    client_id: int | None = None
    type_vente: VenteType = VenteType.directe
    remise: Decimal = Field(default=Decimal("0"), ge=0)
    lignes: list[VenteLigneCreate] = Field(min_length=1)
    paiements: list[VentePaiementCreate] = Field(default_factory=list)
    # Whether the goods leave the boutique right away — see
    # VenteLivraisonStatut. Defaults to the historical (only) behaviour.
    livraison_statut: VenteLivraisonStatut = VenteLivraisonStatut.livre


class VenteRead(EntityRead):
    boutique_id: int
    vendeur_id: int | None
    client_id: int | None
    type_vente: VenteType
    montant_total: Decimal
    remise: Decimal
    statut: VenteStatut
    montant_paye: Decimal
    montant_restant: Decimal
    livraison_statut: VenteLivraisonStatut
    numero_bon_livraison: str | None
    livree_at: datetime | None
    livree_by: int | None
    lignes: list[VenteLigneRead]
    paiements: list[PaiementRead]
    creance: CreanceRead | None
    # Denormalized at read time (see VenteService.list_enriched) — only set
    # on the list endpoint; unset (None) on get/create/void, where the
    # frontend already resolves the store name itself.
    store_name: str | None = None

# ── Return schemas ─────────────────────────────────────────────────────────────

class VenteRetourLigneCreate(BaseModel):
    vente_ligne_id: int
    quantite: int = Field(ge=1)


class VenteRetourLigneRead(BaseModel):
    id: int
    vente_ligne_id: int
    produit_id: int
    quantite: int
    prix_unitaire: Decimal
    total_ligne: Decimal

    model_config = {"from_attributes": True}


class VenteRetourCreate(BaseModel):
    lignes: list[VenteRetourLigneCreate] = Field(min_length=1)
    motif: str = Field(min_length=1, max_length=500)
    notes: str | None = Field(default=None, max_length=2000)


class VenteRetourRead(EntityRead):
    vente_id: int
    vendeur_id: int | None
    motif: str
    notes: str | None
    total_retourne: Decimal
    lignes: list[VenteRetourLigneRead]


# ── Refund schemas ─────────────────────────────────────────────────────────────

class VenteRemboursementCreate(BaseModel):
    montant: Decimal = Field(gt=0)
    mode: PaiementMode = PaiementMode.especes
    reference: str | None = Field(default=None, max_length=200)
    motif: str = Field(min_length=1, max_length=500)
    notes: str | None = Field(default=None, max_length=2000)
    retour_id: int | None = None


class VenteRemboursementRead(EntityRead):
    vente_id: int
    retour_id: int | None
    vendeur_id: int | None
    montant: Decimal
    mode: PaiementMode
    reference: str | None
    motif: str
    notes: str | None
