"""Centralised enumerations shared across the domain models.

All enums subclass ``str`` so they serialise cleanly through Pydantic/JSON and
are stored as VARCHAR (``native_enum=False``) in MySQL.
"""

import enum


class RecordStatus(str, enum.Enum):
    """Generic record lifecycle, independent from domain-specific states."""

    active = "active"
    inactive = "inactive"
    archived = "archived"


class UserStatus(str, enum.Enum):
    active = "active"
    inactive = "inactive"
    suspended = "suspended"
    invited = "invited"


# --- Commandes (internal store -> central supply orders) ---
class CommandeStatut(str, enum.Enum):
    brouillon = "brouillon"
    en_attente = "en_attente"
    validee = "validee"
    rejetee = "rejetee"
    proforma_generee = "proforma_generee"
    proforma_rejetee = "proforma_rejetee"
    facture_generee = "facture_generee"
    en_preparation = "en_preparation"
    pret_a_expedier = "pret_a_expedier"
    expedie = "expedie"
    livree = "livree"
    reception_confirmee = "reception_confirmee"
    partiellement_recu = "partiellement_recu"
    annulee = "annulee"


class CommandeEvenementType(str, enum.Enum):
    """One row per audit-trail entry on a Commande — see CommandeEvenement.
    Covers both status transitions and non-status events (a quantity edit or
    a free-text comment don't necessarily change ``Commande.statut``)."""

    creation = "creation"
    soumission = "soumission"
    validation = "validation"
    refus = "refus"
    proforma = "proforma"
    proforma_acceptee = "proforma_acceptee"
    proforma_rejetee = "proforma_rejetee"
    proforma_resoumise = "proforma_resoumise"
    facture = "facture"
    preparation = "preparation"
    expedition = "expedition"
    livraison = "livraison"
    reception = "reception"
    anomalie = "anomalie"
    quantites_modifiees = "quantites_modifiees"
    produit_resolu = "produit_resolu"
    commentaire = "commentaire"
    annulation = "annulation"


class CommandeReceptionStatut(str, enum.Enum):
    accepte = "accepte"
    refuse = "refuse"
    partiel = "partiel"


class CommandeAnomalieType(str, enum.Enum):
    quantite_manquante = "quantite_manquante"
    produit_casse = "produit_casse"
    erreur_preparation = "erreur_preparation"
    autre = "autre"


# --- Ventes ---
class VenteType(str, enum.Enum):
    directe = "directe"      # paid immediately
    credit = "credit"        # generates a creance


class VenteStatut(str, enum.Enum):
    en_cours = "en_cours"
    completee = "completee"
    partiellement_payee = "partiellement_payee"
    impayee = "impayee"
    annulee = "annulee"
    # Return / refund lifecycle (native_enum=False — no column migration needed)
    partiellement_retournee = "partiellement_retournee"
    retournee = "retournee"
    partiellement_remboursee = "partiellement_remboursee"
    remboursee = "remboursee"


class VenteLivraisonStatut(str, enum.Enum):
    """Whether the sold goods have physically left the boutique — entirely
    independent from payment status (VenteStatut/CreanceStatut already cover
    that). A credit sale with an outstanding balance is still `livre` the
    moment the goods are handed over; conversely a fully-paid sale can stay
    `non_livre` until the customer actually collects the goods."""

    livre = "livre"
    non_livre = "non_livre"


# --- Creances ---
class CreanceStatut(str, enum.Enum):
    active = "active"
    partiellement_payee = "partiellement_payee"
    soldee = "soldee"
    en_retard = "en_retard"
    annulee = "annulee"


# --- Paiements ---
class PaiementMode(str, enum.Enum):
    especes = "especes"
    mobile_money = "mobile_money"
    carte = "carte"
    virement = "virement"
    cheque = "cheque"


# --- Achats fournisseurs ---
class PurchaseStatut(str, enum.Enum):
    brouillon = "brouillon"
    commandee = "commandee"
    partiellement_recue = "partiellement_recue"
    recue = "recue"
    annulee = "annulee"


# --- Alertes de stock ---
class StockAlertType(str, enum.Enum):
    LOW_STOCK = "LOW_STOCK"
    OUT_OF_STOCK = "OUT_OF_STOCK"


# --- Mouvements de stock ---
class StockLocationType(str, enum.Enum):
    CENTRAL = "CENTRAL"
    STORE = "STORE"
    WAREHOUSE = "WAREHOUSE"


class MovementType(str, enum.Enum):
    IN = "IN"
    OUT = "OUT"
    TRANSFER = "TRANSFER"
    ADJUSTMENT = "ADJUSTMENT"


class MovementReason(str, enum.Enum):
    STOCK_INITIAL = "STOCK_INITIAL"
    PURCHASE = "PURCHASE"
    SALE = "SALE"
    RETURN = "RETURN"
    DAMAGE = "DAMAGE"
    LOSS = "LOSS"
    THEFT = "THEFT"
    INVENTORY = "INVENTORY"
    REAPPRO = "REAPPRO"
    OTHER = "OTHER"


class ReferenceType(str, enum.Enum):
    """Polymorphic pointer target used by payments, attachments, logs."""

    COMMANDE = "COMMANDE"
    VENTE = "VENTE"
    PURCHASE = "PURCHASE"
    PAIEMENT = "PAIEMENT"
    CREANCE = "CREANCE"
    EXPENSE = "EXPENSE"
    CASH_SESSION = "CASH_SESSION"
    PRODUCT = "PRODUCT"
    STORE = "STORE"
    USER = "USER"


# --- Trésorerie / caisse ---
class CashSessionStatus(str, enum.Enum):
    ouverte = "ouverte"
    fermee = "fermee"


class CashMovementType(str, enum.Enum):
    entree = "entree"
    sortie = "sortie"


# --- Notifications ---
class NotificationType(str, enum.Enum):
    stock = "stock"
    commande = "commande"
    vente = "vente"
    creance = "creance"
    paiement = "paiement"
    systeme = "systeme"


# --- Clients ---
class ClientType(str, enum.Enum):
    particulier = "particulier"
    entreprise = "entreprise"


# --- Settings ---
class SettingType(str, enum.Enum):
    string = "string"
    number = "number"
    boolean = "boolean"
    json = "json"
