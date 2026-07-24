"""Pydantic schemas for the commandes module (internal réappro workflow)."""

from datetime import datetime
from decimal import Decimal

from pydantic import BaseModel, ConfigDict, Field, model_validator

from app.database.enums import (
    CommandeAnomalieType,
    CommandeEvenementType,
    CommandeReceptionStatut,
    CommandeStatut,
)
from app.modules.common.schemas import EntityRead, LogRead


class CommandeLigneCreate(BaseModel):
    """Exactly one of ``produit_id`` (real catalog product) or ``nom_libre``
    (product not yet in the catalog — see CommandeService.resolve_ligne) must
    be given."""

    produit_id: int | None = None
    nom_libre: str | None = Field(default=None, min_length=1, max_length=255)
    quantite_demandee: int = Field(ge=1)
    prix_unitaire: Decimal = Field(default=Decimal("0"), ge=0)
    observation: str | None = None

    @model_validator(mode="after")
    def _exactly_one_product_reference(self) -> "CommandeLigneCreate":
        if bool(self.produit_id) == bool(self.nom_libre):
            raise ValueError(
                "Chaque ligne doit référencer soit un produit_id, soit un nom_libre (pas les deux)."
            )
        return self


class CommandeLigneRead(EntityRead):
    commande_id: int
    produit_id: int | None
    nom_libre: str | None
    quantite_demandee: int
    quantite_validee: int
    quantite_livree: int
    quantite_recue: int
    prix_unitaire: Decimal
    total_ligne: Decimal
    observation: str | None


class CommandeLigneResolve(BaseModel):
    produit_id: int


class CommandeCreate(BaseModel):
    boutique_id: int
    lignes: list[CommandeLigneCreate] = Field(default_factory=list)


class CommandeUpdate(BaseModel):
    statut: CommandeStatut | None = None


class CommandeValidate(BaseModel):
    """Accept a commande fully or partially. Omitting a line id from
    ``quantites_validees`` keeps its originally requested quantity;
    setting it lower than requested is what "partial acceptance" means —
    no separate status exists for that, only the per-line quantities differ."""

    quantites_validees: dict[int, int] | None = None
    commentaire: str | None = None


class CommandeRefuse(BaseModel):
    motif: str = Field(min_length=1)


class CommandeProformaReject(BaseModel):
    """Gérant rejects a PROFORMA_GENEREE proforma — sent back to the Boss."""

    motif: str = Field(min_length=1)


class CommandeProformaRevise(BaseModel):
    """Boss edits quantities/prices after a gérant rejection and resubmits
    the same proforma for another round of gérant decision. Omitting a line
    id from either dict keeps its current value."""

    quantites: dict[int, int] | None = None
    prix: dict[int, Decimal] | None = None
    commentaire: str | None = None


class CommandeShip(BaseModel):
    transporteur: str = Field(min_length=1)
    livreur_id: int | None = None
    livreur_nom: str | None = None


class CommandeAnomalieCreate(BaseModel):
    ligne_id: int | None = None
    type_anomalie: CommandeAnomalieType
    quantite_ecart: int = Field(default=0, ge=0)
    description: str | None = None


class CommandeReceptionCreate(BaseModel):
    statut_reception: CommandeReceptionStatut
    commentaire: str | None = None
    # ligne_id -> quantity received in THIS reception event (not cumulative —
    # see CommandeService.confirm_reception).
    lignes: dict[int, int] = Field(default_factory=dict)
    anomalies: list[CommandeAnomalieCreate] = Field(default_factory=list)


class CommandeEvenementRead(LogRead):
    model_config = ConfigDict(populate_by_name=True)

    commande_id: int
    type_evenement: CommandeEvenementType
    acteur_id: int | None
    commentaire: str | None
    ip_address: str | None
    extra: dict | None = Field(validation_alias="extra", serialization_alias="metadata")


class CommandeLivraisonRead(EntityRead):
    commande_id: int
    numero_bon_preparation: str | None
    preparateur_id: int | None
    prepared_at: datetime | None
    transporteur: str | None
    livreur_id: int | None
    livreur_nom: str | None
    numero_bon_livraison: str | None
    date_expedition: datetime | None
    date_livraison: datetime | None
    qr_content: str | None
    code_barre: str | None
    signature_hq_by: int | None
    signature_hq_at: datetime | None
    signature_boutique_by: int | None
    signature_boutique_at: datetime | None


class CommandeReceptionRead(EntityRead):
    commande_id: int
    recu_par: int | None
    date_reception: datetime | None
    statut_reception: CommandeReceptionStatut
    commentaire: str | None


class CommandeAnomalieRead(EntityRead):
    commande_id: int
    reception_id: int | None
    ligne_id: int | None
    type_anomalie: CommandeAnomalieType
    quantite_ecart: int
    description: str | None
    created_by: int | None
    resolved: bool


class CommandeRead(EntityRead):
    boutique_id: int
    created_by: int | None
    validated_by: int | None
    statut: CommandeStatut
    numero: str | None
    montant_total: Decimal
    montant_ht: Decimal
    tva_taux: Decimal
    montant_tva: Decimal
    montant_ttc: Decimal
    numero_proforma: str | None
    numero_facture: str | None
    refus_motif: str | None
    refused_by: int | None
    refused_at: datetime | None
    proforma_refus_motif: str | None
    proforma_refused_by: int | None
    proforma_refused_at: datetime | None
    validated_at: datetime | None
    delivered_at: datetime | None
    lignes: list[CommandeLigneRead]
    livraison: CommandeLivraisonRead | None = None


class CommandeStats(BaseModel):
    en_attente: int
    validees: int
    refusees: int
    valeur_totale: Decimal
    delai_moyen_jours: float | None
    par_boutique: list["CommandeStatsBoutique"]


class CommandeStatsBoutique(BaseModel):
    boutique_id: int
    boutique_nom: str
    nb_commandes: int
    valeur_totale: Decimal
