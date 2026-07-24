# e-Boutique — Backend API

API REST de **e-Boutique** (Commerce OS), construite avec
**FastAPI**, **MySQL**, **SQLAlchemy 2.0 (async)** et **Poetry**.

## Stack

- **FastAPI** — framework web ASGI
- **SQLAlchemy 2.0** (async) + **aiomysql** — ORM et accès MySQL
- **Pydantic v2** / **pydantic-settings** — validation et configuration
- **PyJWT** + **bcrypt** — authentification JWT et hachage des mots de passe
- **Alembic** — migrations de base de données (async)
- **Uvicorn** — serveur ASGI
- **Poetry** — gestion des dépendances et scripts

## Structure

```
backend/
├── app/
│   ├── main.py              # Création de l'app FastAPI + lifespan + health
│   ├── cli.py               # Entrées Poetry : `dev`, `start`
│   ├── core/                # config, settings, logging
│   ├── api/
│   │   ├── deps.py          # Dépendances partagées (auth, current user, rôles)
│   │   └── v1/router.py     # Agrégation des routers de modules
│   ├── modules/             # Un dossier par fonctionnalité
│   │   ├── auth/            # models · schemas · services · router
│   │   ├── users/
│   │   ├── ventes/
│   │   └── achat/
│   ├── database/            # base déclarative + session async
│   ├── security/            # jwt + password
│   ├── seeds/               # données initiales (RBAC, settings, super-admin)
│   └── utils/               # helpers
├── alembic/                 # migrations (env.py + versions/)
├── alembic.ini
├── pyproject.toml
├── .env.example
└── README.md
```

Chaque module suit la même convention : `models.py`, `schemas.py`,
`services.py`, `router.py`.

## Démarrage

### 1. Configuration

```bash
cd backend
cp .env.example .env
# Éditez .env : identifiants MySQL et SECRET_KEY
```

Générer une clé secrète robuste :

```bash
python -c "import secrets; print(secrets.token_urlsafe(64))"
```

### 2. Base de données MySQL

Créez la base (le serveur démarre même si MySQL est indisponible, mais les
routes DB échoueront tant qu'il ne l'est pas) :

```sql
CREATE DATABASE business_flow_suite CHARACTER SET utf8mb4 COLLATE utf8mb4_unicode_ci;
```

Le schéma est géré par **Alembic** (plus de `create_all` au démarrage).

### 3. Installation

```bash
poetry install
```

### 4. Migrations (Alembic)

```bash
poetry run alembic upgrade head          # appliquer les migrations
poetry run alembic revision --autogenerate -m "message"   # générer une migration
poetry run alembic downgrade -1          # revenir d'un cran
poetry run alembic current               # révision appliquée
poetry run alembic check                 # détecter une divergence modèles/schéma
```

### 5. Données initiales (seed)

Crée les permissions, groupes (super-admin, fournisseur, gérant, vendeur), leurs
associations, les paramètres de base et le premier super-admin (identifiants
définis par `FIRST_SUPERADMIN_*` dans `.env`). Idempotent.

```bash
poetry run seed
```

### 6. Lancement

```bash
poetry run dev
```

- API : http://localhost:8000
- Documentation Swagger : http://localhost:8000/docs
- Documentation ReDoc : http://localhost:8000/redoc
- Santé : http://localhost:8000/health

## Modules et endpoints (v1)

Préfixe : `/api/v1`

| Module | Endpoints principaux |
|--------|----------------------|
| `auth` | `POST /auth/register`, `POST /auth/login`, `POST /auth/refresh`, `GET /auth/me` |
| `users` | `GET/POST /users`, `GET/PATCH/DELETE /users/{id}`, `GET /users/me` |
| `access` | `roles`, `groups`, `permissions`, `user-groups`, `group-permissions`, `user-permissions` |
| `catalog` | `product-categories`, `products`, `store-categories` |
| `stores` | `GET/POST /stores`, `GET/PATCH/DELETE /stores/{id}`, `stores/{id}/users` |
| `clients` | `GET/POST /clients`, `GET/PATCH/DELETE /clients/{id}` |
| `stock` | `stock/central`, `stock/boutique`, `stock/movements` |
| `commandes` | `GET/POST /commandes`, `POST /commandes/{id}/validate`, `PATCH /commandes/{id}/status` |
| `achats` | `achats/suppliers`, `GET/POST /achats`, `PATCH /achats/{id}/status` |
| `ventes` | `GET/POST /ventes`, `GET /ventes/{id}`, `POST /ventes/{id}/void` |
| `creances` | `GET/POST /creances`, `POST /creances/payments` |
| `expenses` | `expenses/categories`, `GET/POST /expenses` |
| `cash` | `cash/sessions` (open/close), `cash/movements` |
| `notifications` | `GET/POST /notifications`, `POST /notifications/{id}/read`, `read-all` |
| `system` | `system/settings`, `system/activity-logs`, `system/attachments` |

La documentation interactive complète (tous les modules) est disponible sur `/docs`.

## Authentification

Flux OAuth2 « password » : `POST /api/v1/auth/login` (champs `username` =
email, `password`) renvoie `access_token` + `refresh_token`. Passez ensuite
l'en-tête `Authorization: Bearer <access_token>`.

Le contrôle d'accès (RBAC) repose sur des **groupes** (`super-admin`,
`fournisseur`, `gerant-boutique`, `vendeur-boutique`) porteurs de **permissions**,
initialisés par `poetry run seed`.

## Scripts Poetry

- `poetry run dev` — serveur de développement avec rechargement à chaud
- `poetry run start` — serveur de production (sans reload)
- `poetry run seed` — initialise les données (RBAC, settings, super-admin)
- `poetry run alembic ...` — gestion des migrations
