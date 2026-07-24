# Table des routes — permissions et scope (Sprint de Stabilisation)

Référence de conception pour le durcissement RBAC + isolation multi-boutiques. Chaque route liste la permission requise (slug de `app/seeds/data.py`), le(s) groupe(s) qui l'ont via le seed, et le scope (`HQ` = accès réseau entier ; `Boutique` = restreint aux boutiques affectées via `StoreUser` ; `Self` = restreint à l'appelant lui-même ; `Public` = aucune authentification).

Convention de statut : permission manquante → **403**. Ressource existante mais hors périmètre (autre boutique) → **404** (ne jamais confirmer l'existence d'une ressource hors scope).

## auth (`/api/v1/auth`)
| Méthode | Route | Permission | Scope |
|---|---|---|---|
| POST | /register | — | Public |
| POST | /verify-email | — | Public |
| POST | /resend-otp | — | Public |
| POST | /login | — | Public |
| POST | /refresh | — | Public |
| GET | /me | — (CurrentUser) | Self |
| GET | /me/groups | — (CurrentUser) | Self |

## users (`/api/v1/users`)
| Méthode | Route | Permission | Scope |
|---|---|---|---|
| GET | /me | — (CurrentUser) | Self |
| POST | /me/change-password | — (CurrentUser) | Self |
| GET | "" | `users.view` | HQ |
| POST | "" | `users.manage` | HQ |
| GET | /{id} | `users.view` | HQ |
| PATCH | /{id} | `users.manage` | HQ |
| DELETE | /{id} | `users.manage` | HQ |
| GET | /{id}/groups | `access.manage` | HQ |
| POST | /{id}/groups | `access.manage` | HQ |
| DELETE | /{id}/groups/{link_id} | `access.manage` | HQ |
| GET | /{id}/stores | `users.view` | HQ |
| POST | /{id}/send-credentials | `users.manage` | HQ |

## access (`/api/v1/access`) — administration RBAC, toujours HQ
| Méthode | Route | Permission | Scope |
|---|---|---|---|
| GET/POST | /roles | `access.manage` | HQ |
| GET/PATCH/DELETE | /roles/{id} | `access.manage` | HQ |
| GET/POST | /groups | `access.manage` | HQ |
| GET/PATCH/DELETE | /groups/{id} | `access.manage` | HQ |
| GET/POST | /permissions | `access.manage` | HQ |
| GET/PATCH/DELETE | /permissions/{id} | `access.manage` | HQ |
| GET/POST | /user-groups | `access.manage` | HQ |
| DELETE | /user-groups/{link_id} | `access.manage` | HQ |
| GET/POST | /group-permissions | `access.manage` | HQ |
| DELETE | /group-permissions/{link_id} | `access.manage` | HQ |
| GET/POST | /user-permissions | `access.manage` | HQ |
| DELETE | /user-permissions/{link_id} | `access.manage` | HQ |

*C'est la faille d'escalade de privilèges directe trouvée par l'audit (self-promotion via `POST /users/{id}/groups` et `POST /access/*`) — priorité 1 d'implémentation.*

## stores (`/api/v1/stores`)
| Méthode | Route | Permission | Scope |
|---|---|---|---|
| GET | "" | `stores.view` | Boutique (liste filtrée à ses boutiques ; HQ voit tout) |
| POST | "" | `stores.manage` | HQ |
| GET | /{id} | `stores.view` | Boutique (get_scoped) |
| PATCH | /{id} | `stores.manage` | HQ |
| DELETE | /{id} | `stores.manage` | HQ |
| GET | /{id}/users | `stores.view` | Boutique (get_scoped sur la boutique) |
| POST | /{id}/users | `stores.manage` | HQ *(affectation d'équipe = action sensible, cf. note ci-dessous)* |
| DELETE | /users/{link_id} | `stores.manage` | HQ |

*Note de conception : `POST /{id}/users` (affecter un utilisateur+rôle à une boutique) est restreint à HQ plutôt qu'ouvert au gérant de la boutique elle-même — choix conservateur par défaut vu l'absence de permission plus fine dans le seed actuel ; à revisiter si les gérants doivent pouvoir ajouter eux-mêmes leurs vendeurs.*

## catalog (`/api/v1/catalog`) — pas de dimension boutique (catalogue partagé réseau)
| Méthode | Route | Permission | Scope |
|---|---|---|---|
| GET | /product-categories | `products.view` | HQ |
| POST/PATCH/DELETE | /product-categories(/{id}) | `categories.manage` | HQ |
| GET | /products, /products/by-uuid/{uuid}, /products/{id} | `products.view` | HQ |
| POST/PATCH/DELETE | /products(/{id}) | `products.manage` | HQ |
| GET | /store-categories | `stores.view` | HQ |
| POST/PATCH/DELETE | /store-categories(/{id}) | `stores.manage` | HQ |

## clients (`/api/v1/clients`)
| Méthode | Route | Permission | Scope |
|---|---|---|---|
| GET | "" | `clients.view` | Boutique |
| POST | "" | `clients.manage` | Boutique |
| GET | /{id} | `clients.view` | Boutique (get_scoped → 404 hors scope) |
| PATCH | /{id} | `clients.manage` | Boutique |
| DELETE | /{id} | `clients.manage` | Boutique |

## commandes (`/api/v1/commandes`) — réappro boutique → central
| Méthode | Route | Permission | Scope |
|---|---|---|---|
| GET | "" | `commandes.view` | Boutique |
| POST | "" | `commandes.create` | Boutique |
| GET | /{id} | `commandes.view` | Boutique |
| POST | /{id}/validate | `commandes.validate` | HQ *(le validateur n'a pas besoin d'appartenir à la boutique émettrice)* |
| PATCH | /{id}/status | `commandes.validate` | HQ |
| DELETE | /{id} | `commandes.create` | Boutique *(annuler sa propre commande)* |

## creances (`/api/v1/creances`)
| Méthode | Route | Permission | Scope |
|---|---|---|---|
| GET | "" | `creances.view` | Boutique |
| POST | "" | `creances.manage` | Boutique |
| GET | /{id} | `creances.view` | Boutique |
| PATCH | /{id} | `creances.manage` | Boutique |
| GET | /payments/list | `creances.view` | Boutique |
| POST | /payments | `paiements.create` | Boutique |

## cash (`/api/v1/cash`)
| Méthode | Route | Permission | Scope |
|---|---|---|---|
| GET | /sessions | `cash.view` | Boutique |
| POST | /sessions | `cash.manage` | Boutique |
| GET | /sessions/{id} | `cash.view` | Boutique |
| POST | /sessions/{id}/close | `cash.manage` | Boutique |
| GET | /movements | `cash.view` | Boutique (via la session) |
| POST | /movements | `cash.manage` | Boutique |

## stock (`/api/v1/stock`)
| Méthode | Route | Permission | Scope |
|---|---|---|---|
| GET | /locations | `stock.view` | Boutique (locations sans store_id = HQ uniquement) |
| POST | /locations | `stock.central.manage` | HQ |
| GET | /locations/{id} | `stock.view` | Boutique |
| PATCH | /locations/{id} | `stock.store.manage` | Boutique |
| GET | /product-stocks | `stock.view` | Boutique (via la location) |
| PATCH | /product-stocks/{id} | `stock.store.manage` | Boutique |
| POST | /add, /adjust | `stock.store.manage` OU `stock.central.manage` | Boutique (les deux emplacements doivent être dans le scope) |
| POST | /transfer | `stock.store.manage` OU `stock.central.manage` | Boutique (from **et** to dans le scope, sinon HQ requis) |
| GET | /movements | `stock.view` | Boutique |

## achat (`/api/v1/achats`) — central/HQ, aucune dimension boutique
| Méthode | Route | Permission | Scope |
|---|---|---|---|
| GET | /suppliers | `suppliers.view` | HQ |
| POST/PATCH/DELETE | /suppliers(/{id}) | `suppliers.manage` | HQ |
| GET | "" | `purchases.view` | HQ |
| POST | "" | `purchases.manage` | HQ |
| GET | /{id} | `purchases.view` | HQ |
| PATCH | /{id}/status | `purchases.manage` | HQ |
| DELETE | /{id} | `purchases.manage` | HQ |

## expenses (`/api/v1/expenses`)
| Méthode | Route | Permission | Scope |
|---|---|---|---|
| GET | /categories | `expenses.view` | HQ *(taxonomie partagée, pas de store_id)* |
| POST/PATCH/DELETE | /categories(/{id}) | `expenses.categories.manage` | HQ — Boss uniquement (`fournisseur`, `super-admin`), jamais `gerant-boutique` |
| GET | "" | `expenses.view` | Boutique — `date_from`/`date_to` filtrent sur `created_at` |
| GET | /count | `expenses.view` | Boutique |
| POST | "" | `expenses.manage` | Boutique |
| GET | /{id} | `expenses.view` | Boutique |
| PATCH/DELETE | /{id} | `expenses.manage` | Boutique |

`expenses.exporter` gate l'export (Excel/CSV/PDF) côté frontend uniquement (aucune route dédiée) — accordé à `gerant-boutique`, `comptable`, `fournisseur`.

## ventes (`/api/v1/ventes`)
| Méthode | Route | Permission | Scope |
|---|---|---|---|
| GET | /count, "" | `ventes.view` | Boutique |
| POST | "" | `ventes.create` | Boutique |
| GET | /{id} | `ventes.view` | Boutique (get_scoped) |
| POST | /{id}/void | `ventes.annuler` | Boutique |
| DELETE | /{id} | `ventes.manage` | Boutique |
| GET | /{id}/retours | `ventes.view` | Boutique (hérite du scope de la vente) |
| POST | /{id}/return | `ventes.retourner` | Boutique |
| GET | /{id}/remboursements | `ventes.view` | Boutique |
| POST | /{id}/refund | `ventes.rembourser` | Boutique |

## dashboard (`/api/v1/dashboard`)
| Méthode | Route | Permission | Scope |
|---|---|---|---|
| GET | /stats | `dashboard.global.view` OU `dashboard.store.view` | `boutique_id=None` → HQ uniquement ; sinon Boutique |

## reports (`/api/v1/reports`)
| Méthode | Route | Permission | Scope |
|---|---|---|---|
| GET | /data | `reports.view` | `boutique_id=None` → HQ uniquement ; sinon Boutique |

## notifications (`/api/v1/notifications`)
| Méthode | Route | Permission | Scope |
|---|---|---|---|
| GET | "" | — (CurrentUser) | Self *(déjà filtré par `user.id`)* |
| POST | "" | `users.manage` | HQ *(pousser une notif à un tiers = action admin ; pas de slug dédié dans le seed)* |
| POST | /{id}/read | — (CurrentUser) | Self *(check d'ownership déjà existant)* |
| POST | /read-all | — (CurrentUser) | Self |

## system (`/api/v1/system`)
| Méthode | Route | Permission | Scope |
|---|---|---|---|
| GET/POST/PATCH/DELETE | /settings(/{key\|id}) | `settings.manage` | HQ |
| GET | /activity-logs | `settings.manage` | HQ |
| POST | /activity-logs | — (CurrentUser) | Self *(sink de log, chaque utilisateur loggue sa propre activité)* |
| GET/POST/DELETE | /attachments(/{id}) | `settings.manage` | HQ |

## upload (`/api/v1/upload`)
| Méthode | Route | Permission | Scope |
|---|---|---|---|
| POST | /image | — (CurrentUser) | Self *(utilitaire générique réutilisé par plusieurs modules, pas de contexte propre)* |

---

## Décisions de conception notables (à valider dans la durée, pas bloquantes pour ce sprint)
- **`commandes`** : la granularité du seed (`view`/`create`/`validate`, pas de `manage`) force `validate`+`status` en scope HQ et `delete` en scope Boutique via la permission `create` — cohérent avec "Boss valide les commandes" mais mérite un slug `commandes.manage` dédié à terme.
- **`stores.POST /{id}/users`** restreint à HQ par défaut (pas de permission "gérer son équipe boutique" dédiée) — un gérant ne peut donc pas encore ajouter lui-même un vendeur à sa boutique via l'API tant que ce choix n'est pas révisé.
- **`notifications.POST` et `system settings/attachments`** réutilisent des slugs existants (`users.manage`/`settings.manage`) faute de slug dédié — pas de nouveau slug inventé pour rester minimal, conformément à la consigne "aucun nouveau développement fonctionnel."
- **Dérive de permissions pré-existante non corrigée dans ce sprint** (trouvée par le script de vérification seed↔DB) : les groupes `fournisseur`, `gerant-boutique` et `vendeur-boutique` ont en base plus de permissions que ce que `app/seeds/data.py` déclare (ex. `vendeur-boutique` a `stores.manage`, `users.view`, `expenses.manage` en trop). Ces permissions en trop sont **conservées telles quelles** (retrait délibérément hors périmètre de ce sprint — un retrait pourrait casser un usage réel non documenté) ; elles élargissent l'accès de ces groupes au-delà de l'intention du seed mais ne cassent rien. Recommandation séparée : décider explicitement, permission par permission, si chaque écart doit être ajouté au seed (intentionnel) ou révoqué (dérive accidentelle).
