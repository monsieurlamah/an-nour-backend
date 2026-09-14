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
    numero_proforma: str | None
    numero_facture: str | None
    proforma_valide_jusquau: datetime | None
    proforma_refus_motif: str | None
    proforma_refused_by: int | None
    proforma_refused_at: datetime | None
    facture_by: int | None
    facture_at: datetime | None
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


# ── Proforma (devis) schemas — cahier des charges §9.1-§9.3 ─────────────────────
# A proforma never carries paiements (it "n'impacte pas le stock" — §9.1, and
# by construction no payment is ever taken against a mere quote either): the
# only fields that exist are the ones needed to price the devis.

class VenteProformaCreate(BaseModel):
    boutique_id: int
    client_id: int | None = None
    remise: Decimal = Field(default=Decimal("0"), ge=0)
    lignes: list[VenteLigneCreate] = Field(min_length=1)
    # Validity window (§9.1: "durée de validité paramétrable, au-delà de
    # laquelle elle expire automatiquement") — defaults to a week.
    validite_jours: int = Field(default=7, ge=1, le=90)


class VenteProformaUpdate(BaseModel):
    """Re-price a still-open proforma after client negotiation (§9.2) —
    replaces the lines and/or the global remise wholesale; only valid while
    `statut == proforma` and not expired."""

    remise: Decimal | None = Field(default=None, ge=0)
    lignes: list[VenteLigneCreate] | None = Field(default=None, min_length=1)


class VenteProformaReject(BaseModel):
    motif: str = Field(min_length=1, max_length=500)


class VenteTransformRequest(BaseModel):
    """Turns an open proforma into the facture définitive (§9.3) — same
    document/dossier, a new official invoice number, and (§9.3/§7.3) the
    moment stock actually leaves. Payment is optional here — §9.4 explicitly
    allows collecting it "au moment de la facturation définitive (ou
    après)", so an empty list just leaves the whole amount as a créance."""

    paiements: list[VentePaiementCreate] = Field(default_factory=list)
    livraison_statut: VenteLivraisonStatut = VenteLivraisonStatut.livre

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
