"""Declarative seed data: permissions, groups, group→permission map, settings.

Edit these structures to evolve the RBAC matrix; the seed runner is idempotent
and reconciles the database to match this file (creating what's missing).
"""

from app.database.enums import SettingType

# --- Permissions: (slug, module, name) ---------------------------------------
# Slugs follow the convention "<module>.<action>" and are the stable identifier.
PERMISSIONS: list[tuple[str, str, str]] = [
    # Dashboard
    ("dashboard.global.view", "dashboard", "Voir le tableau de bord global"),
    ("dashboard.store.view", "dashboard", "Voir le tableau de bord boutique"),
    # Users & access control
    ("users.view", "users", "Consulter les utilisateurs"),
    ("users.manage", "users", "Gérer les utilisateurs"),
    ("access.manage", "access", "Gérer les rôles, groupes et permissions"),
    # Stores
    ("stores.view", "stores", "Consulter les boutiques"),
    ("stores.manage", "stores", "Gérer les boutiques"),
    # Catalog
    ("products.view", "catalog", "Consulter les produits"),
    ("products.manage", "catalog", "Gérer les produits"),
    ("categories.manage", "catalog", "Gérer les catégories"),
    # Stock
    ("stock.view", "stock", "Consulter le stock"),
    ("stock.central.manage", "stock", "Gérer le stock central"),
    ("stock.store.manage", "stock", "Gérer le stock boutique"),
    # Commandes (réappro boutique → central)
    ("commandes.view", "commandes", "Consulter les commandes"),
    ("commandes.create", "commandes", "Passer une commande"),
    ("commandes.validate", "commandes", "Valider une commande"),
    (
        "commandes.approve_proforma",
        "commandes",
        "Valider ou rejeter une facture proforma (boutique)",
    ),
    ("commandes.prepare", "commandes", "Préparer une commande (magasinier central)"),
    ("commandes.ship", "commandes", "Expédier une commande (livreur)"),
    ("commandes.deliver", "commandes", "Marquer une commande comme livrée"),
    ("commandes.receive", "commandes", "Réceptionner une commande (boutique)"),
    # Ventes
    ("ventes.view", "ventes", "Consulter les ventes"),
    ("ventes.create", "ventes", "Effectuer une vente"),
    ("ventes.manage", "ventes", "Gérer les ventes"),
    ("ventes.annuler", "ventes", "Annuler une vente"),
    ("ventes.livrer", "ventes", "Confirmer la livraison d'une vente non livrée"),
    ("ventes.retourner", "ventes", "Retourner des produits vendus"),
    ("ventes.rembourser", "ventes", "Rembourser une vente"),
    ("ventes.imprimer", "ventes", "Imprimer un ticket de vente"),
    ("ventes.exporter", "ventes", "Exporter les ventes"),
    # Clients
    ("clients.view", "clients", "Consulter les clients"),
    ("clients.manage", "clients", "Gérer les clients"),
    # Créances & paiements
    ("creances.view", "creances", "Consulter les créances"),
    ("creances.manage", "creances", "Gérer les créances"),
    ("paiements.create", "creances", "Enregistrer un paiement"),
    # Fournisseurs & achats
    ("suppliers.view", "suppliers", "Consulter les fournisseurs"),
    ("suppliers.manage", "suppliers", "Gérer les fournisseurs"),
    ("purchases.view", "achat", "Consulter les achats"),
    ("purchases.manage", "achat", "Gérer les achats"),
    # Dépenses
    ("expenses.view", "expenses", "Consulter les dépenses"),
    ("expenses.manage", "expenses", "Gérer les dépenses"),
    ("expenses.exporter", "expenses", "Exporter les dépenses"),
    ("expenses.categories.manage", "expenses", "Gérer les catégories de dépenses"),
    # Caisse
    ("cash.view", "cash", "Consulter la caisse"),
    ("cash.manage", "cash", "Gérer la caisse (ouverture/fermeture)"),
    # Rapports
    ("reports.view", "reports", "Consulter les rapports"),
    # Notifications
    ("notifications.view", "notifications", "Consulter les notifications"),
    # Paramètres
    ("settings.manage", "settings", "Gérer les paramètres"),
]

# --- Groups: (slug, name, description) ---------------------------------------
GROUPS: list[tuple[str, str, str]] = [
    ("super-admin", "Super administrateur", "Accès complet à toute la plateforme"),
    ("fournisseur", "Fournisseur / Propriétaire", "Gère le central, les boutiques et le réseau"),
    ("gerant-boutique", "Gérant de boutique", "Gère une boutique et ses vendeurs"),
    ("vendeur-boutique", "Vendeur de boutique", "Effectue les ventes en boutique"),
    ("caissier", "Caissier", "Gère la caisse et les encaissements en boutique"),
    ("comptable", "Comptable", "Consulte les données financières et génère des rapports"),
    ("observateur", "Observateur", "Accès en lecture seule selon les permissions accordées"),
    (
        "magasinier-hq",
        "Magasinier (stock central)",
        "Prépare les commandes de réapprovisionnement au central",
    ),
    ("livreur", "Livreur", "Expédie et livre les commandes de réapprovisionnement"),
]

# --- Group → permission slugs. "*" grants every permission. ------------------
GROUP_PERMISSIONS: dict[str, list[str]] = {
    "super-admin": ["*"],
    "fournisseur": [
        "dashboard.global.view",
        "users.view",
        "users.manage",
        "access.manage",
        "stores.view",
        "stores.manage",
        "products.view",
        "products.manage",
        "categories.manage",
        "stock.view",
        "stock.central.manage",
        "commandes.view",
        "commandes.validate",
        "suppliers.view",
        "suppliers.manage",
        "purchases.view",
        "purchases.manage",
        "ventes.view",
        "clients.view",
        "creances.view",
        "expenses.view",
        "expenses.exporter",
        "expenses.categories.manage",
        "reports.view",
        "notifications.view",
        "settings.manage",
    ],
    "gerant-boutique": [
        "dashboard.store.view",
        "users.view",
        "stores.view",
        "products.view",
        "stock.view",
        "stock.store.manage",
        "commandes.view",
        "commandes.create",
        "commandes.approve_proforma",
        "commandes.receive",
        "ventes.view",
        "ventes.create",
        "ventes.manage",
        "ventes.livrer",
        "clients.view",
        "clients.manage",
        "creances.view",
        "creances.manage",
        "paiements.create",
        "expenses.view",
        "expenses.manage",
        "expenses.exporter",
        "cash.view",
        "cash.manage",
        "reports.view",
        "notifications.view",
    ],
    "vendeur-boutique": [
        "dashboard.store.view",
        "products.view",
        "stock.view",
        "ventes.view",
        "ventes.create",
        "ventes.livrer",
        "clients.view",
        "clients.manage",
        "creances.view",
        "paiements.create",
        "cash.view",
        "notifications.view",
    ],
    "caissier": [
        "dashboard.store.view",
        "products.view",
        "stock.view",
        "ventes.view",
        "ventes.create",
        "ventes.livrer",
        "clients.view",
        "creances.view",
        "paiements.create",
        "cash.view",
        "cash.manage",
        "notifications.view",
    ],
    "comptable": [
        "dashboard.global.view",
        "dashboard.store.view",
        "stores.view",
        "products.view",
        "stock.view",
        "ventes.view",
        "clients.view",
        "creances.view",
        # Le module Fournisseurs (achats/suppliers) est réservé au Boss —
        # le Comptable n'y a plus accès (suppliers.view/purchases.view retirés).
        "expenses.view",
        "expenses.exporter",
        "cash.view",
        "reports.view",
        "notifications.view",
    ],
    "observateur": [
        "dashboard.store.view",
        "products.view",
        "stock.view",
        "ventes.view",
        "clients.view",
        "notifications.view",
    ],
    "magasinier-hq": [
        "commandes.view",
        "commandes.prepare",
        "products.view",
        "stock.view",
        "notifications.view",
    ],
    "livreur": [
        "commandes.view",
        "commandes.ship",
        "commandes.deliver",
        "notifications.view",
    ],
}

# --- Base settings: (key, value, value_type, group_name) ---------------------
SETTINGS: list[tuple[str, str, SettingType, str]] = [
    ("company.name", "Business Flow Suite", SettingType.string, "general"),
    ("company.fiscal_id", "", SettingType.string, "general"),
    ("company.phone", "", SettingType.string, "general"),
    ("company.email", "", SettingType.string, "general"),
    ("company.currency", "GNF", SettingType.string, "general"),
    ("company.timezone", "Africa/Conakry", SettingType.string, "general"),
    ("company.tax_rate", "19.25", SettingType.number, "general"),
    ("locale.default", "fr", SettingType.string, "general"),
    ("stock.low_threshold", "10", SettingType.number, "stock"),
]

# --- Expense categories: (name, slug, description) ----------------------------
EXPENSE_CATEGORIES: list[tuple[str, str, str | None]] = [
    ("Loyer", "loyer", "Loyer de la boutique ou de l'entrepôt"),
    ("Électricité & eau", "electricite-eau", "Factures d'électricité et d'eau"),
    ("Transport", "transport", "Carburant, livraison, déplacements"),
    (
        "Fournitures & consommables",
        "fournitures-consommables",
        "Emballages, papeterie, consommables divers",
    ),
    ("Salaires & primes", "salaires-primes", "Rémunération du personnel hors paie officielle"),
    ("Entretien & réparations", "entretien-reparations", "Maintenance des locaux et du matériel"),
    ("Communication & internet", "communication-internet", "Téléphone, internet, forfaits"),
    ("Marketing & publicité", "marketing-publicite", "Communication commerciale, promotions"),
    ("Taxes & impôts", "taxes-impots", "Taxes locales et obligations fiscales"),
    ("Autre", "autre", "Dépense ne correspondant à aucune autre catégorie"),
]
