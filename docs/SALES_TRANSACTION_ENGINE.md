# Moteur transactionnel des ventes (Ventes Engine)

Référence technique pour `app/modules/ventes/services.py::VenteService.create`
et les services qu'il orchestre. Document de référence pour tout
développement futur touchant aux ventes, paiements, créances, stock ou
caisse — à maintenir à jour si le comportement change.

**Statut** : Phase 1 — moteur backend stabilisé. Le frontend (POS, écrans
ventes) n'est **pas encore connecté** à ce moteur (cf. `app.pos.tsx`,
`app.sales.*.tsx`, qui restent sur `mock-data.ts`/`sales-store.ts`).

---

## 1. Vue d'ensemble

Une vente n'est pas une simple écriture en base : elle déclenche
automatiquement toute la chaîne métier d'un ERP — décrément de stock,
encaissement, créance éventuelle, mouvement de caisse — **dans une seule
transaction atomique**. Soit tout réussit, soit rien n'est écrit.

```
POST /ventes (VenteCreate)
        │
        ▼
VenteService.create()
        │
        ├─ 1. Validation
        ├─ 2. Contrôle de stock (lecture seule)
        ├─ 3. Création Vente + VenteLignes
        ├─ 4. Décrément stock + StockMovement (par ligne)
        ├─ 5. Création des Paiements (un par paiement reçu)
        ├─ 6. Création de la Creance si solde restant > 0
        ├─ 7. Création des CashMovement (un par paiement, jamais pour le solde)
        └─ 8. Rechargement des relations calculées (paiements, creance)
        │
        ▼
   Retour VenteRead (commit géré par get_db en fin de requête HTTP)
```

---

## 2. La transaction

Il n'y a **aucun `db.commit()` explicite** dans `VenteService`. Toute la
logique repose sur `app.database.session.get_db` :

```python
async def get_db():
    async with SessionLocal() as session:
        try:
            yield session
            await session.commit()      # uniquement si la route a réussi
        except Exception:
            await session.rollback()    # toute exception annule TOUT
            raise
```

Chaque appel de service (`self.db.add(...)`, `await self.db.flush()`) écrit
dans la transaction en cours mais ne la valide pas. Le commit final n'a lieu
qu'une fois la route FastAPI terminée sans exception. **Toute `HTTPException`
levée à n'importe quelle étape annule automatiquement tout ce qui a déjà été
flush — y compris les étapes déjà passées (vente créée, stock décrémenté,
etc.).** C'est ce qui garantit l'atomicité sans code de transaction explicite.

⚠️ Conséquence pour les développeurs futurs : **ne jamais appeler
`db.commit()` à l'intérieur d'un service**. Cela validerait prématurément une
transaction partielle et casserait le rollback en cas d'échec d'une étape
suivante.

---

## 3. Validations (étape 1)

Dans l'ordre, avant toute écriture :

| Règle | Où |
|---|---|
| Au moins une ligne | `VenteCreate.lignes` (`Field(min_length=1)`) + re-vérifié en service |
| Quantité ≥ 1, prix ≥ 0, remise ≥ 0 | `VenteLigneCreate` (Pydantic `Field`) |
| Montant de paiement > 0 | `VentePaiementCreate.montant` (`Field(gt=0)`) — aucun paiement négatif ou nul possible |
| Somme des paiements ≤ montant total | `VenteService.create`, sinon `422` |
| Client obligatoire si solde restant > 0 | `VenteService.create`, sinon `422` ("Un client est obligatoire…") |

Le **montant total** est calculé ligne par ligne :
`total_ligne = quantité × prix_unitaire − remise_ligne` (plancher à 0), puis
`montant_total = Σ(total_ligne) − remise_globale` (plancher à 0).

---

## 4. Stock (étapes 2 et 4)

**Principe : aucune logique de stock n'a été recréée.** Le moteur ventes
s'appuie sur une nouvelle classe `StockSaleService`
(`app/modules/stock/services.py`), elle-même construite sur les briques déjà
existantes : `ProductStockService`, `StockMovementService`,
`StockAlertService`.

- `get_store_location(store_id)` — résout l'unique `StockLocation` de type
  `STORE` rattachée à la boutique. Si elle n'existe pas → `422`
  ("Aucun emplacement de stock configuré pour la boutique…").
- `check_available(product_id, location_id, quantity)` — lève `422`
  ("Stock insuffisant…") si la quantité demandée dépasse le disponible.
  Appelée une fois en lecture pure pour **chaque ligne avant toute écriture**
  (étape 2 — échec rapide), puis ré-appelée par sécurité dans `consume()`.
- `consume(...)` — décrémente `ProductStock.quantity`, crée un
  `StockMovement` (`movement_type=OUT`, `reason=SALE`, `reference="VENTE-{id}"`),
  puis appelle `StockAlertService.check_and_notify()` — **les alertes de
  seuil existantes continuent de fonctionner automatiquement**, sans aucune
  modification.

Le stock n'est jamais négatif : `check_available` bloque en amont, et
`consume` revérifie par défense en profondeur.

---

## 5. Paiements (étape 5)

`VenteCreate.paiements: list[VentePaiementCreate]` — une vente peut recevoir
**zéro, un ou plusieurs paiements** (`mode`, `montant`, `reference?`).

Règle fondamentale : **un paiement représente uniquement un montant
réellement encaissé.** La part non couverte par les paiements n'est jamais un
`Paiement` — elle devient une `Creance` (section suivante). Exemple de
l'énoncé original :

```
Total : 1 000 000
Paiements envoyés : 300 000 (espèces) + 200 000 (mobile_money)
→ 2 enregistrements Paiement (300 000 et 200 000)
→ 1 Creance de 500 000 (le reste, jamais un "paiement crédit")
```

Chaque `Paiement` est créé via `PaiementService.create()` (réutilisé depuis
`app.modules.creances.services`), avec `vente_id` renseigné et `creance_id`
laissé à `None` (ce ne sont pas des remboursements d'une créance existante,
mais l'encaissement initial de la vente).

---

## 6. Créances (étape 6)

**Nouvelle règle métier (Phase 1) : une `Creance` n'est jamais créée
directement par un appelant.** Elle est uniquement un sous-produit
automatique de `VenteService.create`, calculé ainsi :

```python
montant_restant = montant_total - montant_paye
if montant_restant > 0:
    creance = CreanceService.create_creance(CreanceCreate(
        client_id=payload.client_id,   # obligatoire, validé à l'étape 1
        boutique_id=payload.boutique_id,
        vente_id=vente.id,
        montant_initial=montant_restant,
    ))
```

Si `montant_paye >= montant_total` → **aucune créance**, `vente.creance is
None`. Le champ `type_vente` (`directe`/`credit`) reste informatif : c'est la
**comparaison des montants**, pas ce champ, qui décide de la créance.

`CreanceService.create_creance` initialise `montant_restant = montant_initial`
et `statut = active` (logique déjà existante, non modifiée).

---

## 7. Statut de la vente

Calculé par `VenteService._resolve_statut` à partir des montants, **jamais**
à partir de `type_vente` :

| Condition | Statut |
|---|---|
| `montant_total <= 0` ou `montant_paye >= montant_total` | `completee` |
| `montant_paye <= 0` | `impayee` |
| sinon (`0 < montant_paye < montant_total`) | `partiellement_payee` |

---

## 8. Caisse (étape 7)

Pour **chaque paiement reçu** (jamais pour la part impayée), un
`CashMovement` (`type=entree`, `reference_type=VENTE`,
`reference_id=vente.id`) est créé sur la **session de caisse actuellement
ouverte** pour la boutique (`CashSession.status == ouverte`, la plus récente
si plusieurs).

- S'il n'y a **aucun paiement** (vente 100 % à crédit) → aucune session de
  caisse n'est même requise, aucun `CashMovement` n'est créé.
- S'il y a au moins un paiement et **aucune session ouverte** pour la
  boutique → `422` ("Aucune session de caisse ouverte…"). C'est une étape
  *tardive* du flux (après création de la vente et décrément du stock) :
  c'est précisément le scénario qui prouve que le rollback défait bien tout
  ce qui précède (voir tests).

Réutilise `CashMovementService.create()` (`app.modules.cash.services`), déjà
existant et non modifié.

---

## 9. Annulation (`void`) — non implémentée en Phase 1

`VenteService.void()` ne fait aujourd'hui que passer `statut = annulee`. Les
effets de bord ne sont **pas** inversés — ne pas l'exposer comme une
opération sûre côté frontend avant que les TODO suivants (présents dans le
docstring du code) soient traités :

- `TODO(annulation)` : remettre en stock chaque ligne (mouvement IN/RETURN
  inverse via `StockSaleService`).
- `TODO(annulation)` : annuler/rembourser les `Paiement` liés.
- `TODO(annulation)` : recalculer/annuler la `Creance` liée (`statut ->
  annulee`, `montant_restant -> 0`) plutôt que la laisser active.
- `TODO(annulation)` : créer un `CashMovement` "sortie" inverse pour chaque
  encaissement déjà comptabilisé, sur la session de caisse **ouverte
  courante** (pas l'originale, qui peut être fermée).

---

## 10. Schéma de réponse (`VenteRead`)

En plus des champs déjà existants, `VenteRead` expose désormais :

| Champ | Calcul |
|---|---|
| `montant_paye` | `Vente.montant_paye` (propriété Python : somme des `paiements`) |
| `montant_restant` | `Vente.montant_restant` (propriété Python : `montant_total - montant_paye`, plancher 0) |
| `paiements` | Relation `viewonly`, `lazy="selectin"` vers `Paiement.vente_id` |
| `creance` | Relation `viewonly`, `uselist=False`, `lazy="selectin"` vers `Creance.vente_id` |

Ces relations sont en lecture seule côté modèle `Vente` — elles ne servent
qu'à l'affichage, jamais à la mutation (toute écriture passe par
`PaiementService`/`CreanceService`).

---

## 11. Logging

Chaque étape majeure logue sous le logger `app.ventes.service` :
`vente.create.start` → `validated` → `stock_checked` → `vente_created` →
`stock_consumed` → `paiements_created` → `creance_created`/`no_creance` →
`cash_movements_created`/`no_cash_movement` → `ready_to_commit`. Un échec à
n'importe quelle étape interrompt la séquence (l'exception remonte, pas de
log de "commit" puisqu'il n'y en a pas eu).

---

## 12. Tests

| Fichier | Cible | Commande |
|---|---|---|
| `tests/test_ventes_engine.py` | SQLite en mémoire, rapide, isolé | `poetry run pytest tests/test_ventes_engine.py` |
| `tests/test_ventes_engine_mysql.py` | Vraie base MySQL de dev (marqueur `mysql`), auto-skip si injoignable | `poetry run pytest tests/test_ventes_engine_mysql.py` |
| `poetry run qa` | Lint + tous les tests + compileall, résumé | voir `app/cli.py::qa` |

Les tests MySQL n'utilisent **jamais `commit()`** — uniquement `flush()` —
et la session est explicitement annulée (`rollback()`) en fin de test, quel
que soit le résultat. Aucune donnée de test ne persiste dans la base de
développement partagée.

---

## 13. Ce qui n'est PAS dans cette phase

- Frontend (POS, écrans ventes) — toujours sur données mock, non connecté.
- Annulation complète (`void`) — statut uniquement, voir section 9.
- Vérification de permission côté serveur (`ventes.create`/`manage`, etc.) —
  problème transversal à tout le backend, hors périmètre de ce moteur.
- Distinction fine des opérateurs mobile money (Orange Money / MTN MoMo) —
  un seul mode générique `mobile_money` existe dans `PaiementMode`.
- Coût unitaire figé sur `VenteLigne` au moment de la vente (nécessaire pour
  des marges historiques fiables si `prix_achat` du produit change ensuite).
