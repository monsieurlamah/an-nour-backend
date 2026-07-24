"""Pydantic schemas for the Dashboard module."""

from decimal import Decimal

from pydantic import BaseModel


class DashboardKpi(BaseModel):
    # Chiffre d'affaires — "_mois" reflète la période sélectionnée
    # (date_from/date_to), pas nécessairement le mois civil en cours.
    # "_precedent" compare à la période de même durée immédiatement avant,
    # pour que la tendance reste pertinente quelle que soit la période choisie.
    ca_jour: Decimal
    ca_mois: Decimal
    ca_mois_precedent: Decimal  # pour calcul tendance
    # Ventes
    ventes_jour: int
    ventes_mois: int
    ventes_mois_precedent: int
    # Produits vendus (quantité, sur la période) — distinct de ventes_mois
    # (nombre de transactions).
    produits_vendus: int
    # Clients
    clients_total: int
    clients_mois: int
    # Stock
    stock_valeur: Decimal
    stock_rupture: int
    stock_alerte: int
    # Créances
    creances_actives: int
    creances_montant: Decimal
    # Caisse
    encaissements_jour: Decimal
    remboursements_jour: Decimal
    # Décaissements (dépenses, remboursements en espèces, retraits...) sur
    # la période sélectionnée.
    total_decaissement: Decimal
    # Solde de la session de caisse actuellement ouverte — un solde
    # instantané, jamais un cumul sur la période. Uniquement pertinent pour
    # une vue boutique (None en vue HQ agrégée sur tout le réseau).
    caisse_solde: Decimal | None
    caisse_ouverte: bool
    # Réseau
    boutiques_total: int
    boutiques_actives: int


class VenteEvolution(BaseModel):
    date: str
    count: int
    ca: Decimal


class TopProduit(BaseModel):
    produit_id: int
    nom: str
    quantite: int
    ca: Decimal


class TopClient(BaseModel):
    client_id: int
    nom: str
    nb_ventes: int
    ca: Decimal


class TopBoutique(BaseModel):
    boutique_id: int
    nom: str
    nb_ventes: int
    ca: Decimal


class ModePaiement(BaseModel):
    mode: str
    label: str
    montant: Decimal
    count: int


class Alerte(BaseModel):
    type: str          # "stock_rupture" | "stock_alerte" | "creance" | "caisse" | etc.
    severity: str      # "error" | "warning" | "info"
    message: str
    count: int
    link: str | None   # URL frontend to navigate to


class ActiviteRecente(BaseModel):
    type: str          # "vente" | "retour" | "remboursement" | "client"
    reference: str
    montant: Decimal | None
    date: str
    link: str | None


class DashboardStats(BaseModel):
    kpi: DashboardKpi
    evolution_ventes: list[VenteEvolution]
    top_produits: list[TopProduit]
    top_clients: list[TopClient]
    # Only populated for the HQ (aggregated) view — empty for a single-store
    # view, since ranking one boutique against itself is meaningless.
    top_boutiques: list[TopBoutique]
    modes_paiement: list[ModePaiement]
    alertes: list[Alerte]
    activite_recente: list[ActiviteRecente]
