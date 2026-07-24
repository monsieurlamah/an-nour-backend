"""FastAPI application factory and entrypoint."""

from contextlib import asynccontextmanager

from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware

from app.api.v1.router import api_router
from app.core.config import settings
from app.core.i18n import set_lang
from app.core.logging import get_logger, setup_logging
from app.database.session import check_connection, dispose_engine

logger = get_logger("main")

# Tag metadata controls the ordering and descriptions of module sections in /docs.
OPENAPI_TAGS = [
    {"name": "auth", "description": "Authentification : inscription, connexion, jetons JWT."},
    {"name": "users", "description": "Gestion des utilisateurs et profil courant."},
    {"name": "access", "description": "RBAC : rôles, groupes, permissions et assignations."},
    {"name": "catalog", "description": "Catalogue : catégories et produits, catégories boutiques."},
    {"name": "stores", "description": "Boutiques et affectation des utilisateurs aux boutiques."},
    {"name": "clients", "description": "Clients des boutiques."},
    {"name": "stock", "description": "Stock central, stock boutique et mouvements de stock."},
    {"name": "commandes", "description": "Commandes de réapprovisionnement boutique → central."},
    {"name": "achats", "description": "Fournisseurs et bons d'achat."},
    {"name": "ventes", "description": "Ventes en boutique et lignes de vente."},
    {"name": "creances", "description": "Créances clients et paiements."},
    {"name": "expenses", "description": "Catégories de dépenses et dépenses."},
    {"name": "cash", "description": "Sessions de caisse et mouvements de caisse."},
    {"name": "notifications", "description": "Notifications utilisateur."},
    {"name": "system", "description": "Paramètres, journaux d'activité et pièces jointes."},
    {"name": "health", "description": "Disponibilité de l'API et de la base de données."},
]


@asynccontextmanager
async def lifespan(_app: FastAPI):
    setup_logging()
    logger.info("Starting %s (%s)", settings.APP_NAME, settings.ENVIRONMENT)

    # Non-fatal DB check so the server still boots when MySQL is offline.
    # The schema is managed by Alembic migrations (`poetry run alembic upgrade head`),
    # so we no longer auto-create tables at startup.
    if await check_connection():
        logger.info("Database connection OK.")
    else:
        logger.warning(
            "Database unreachable at startup — the API is up but DB routes will fail "
            "until MySQL is available."
        )

    yield

    await dispose_engine()
    logger.info("Shutdown complete.")


def create_app() -> FastAPI:
    app = FastAPI(
        title=settings.APP_NAME,
        version=settings.APP_VERSION,
        description="API REST de AN-NOUR (Commerce OS) — gestion multi-boutiques.",
        debug=settings.DEBUG,
        openapi_url=f"{settings.API_V1_PREFIX}/openapi.json",
        openapi_tags=OPENAPI_TAGS,
        docs_url="/docs",
        redoc_url="/redoc",
        lifespan=lifespan,
    )

    if settings.BACKEND_CORS_ORIGINS:
        app.add_middleware(
            CORSMiddleware,
            allow_origins=settings.BACKEND_CORS_ORIGINS,
            allow_credentials=True,
            allow_methods=["*"],
            allow_headers=["*"],
        )

    @app.middleware("http")
    async def accept_language_middleware(request: Request, call_next):
        lang_header = request.headers.get("accept-language", "fr")
        set_lang("en" if lang_header.lower().startswith("en") else "fr")
        return await call_next(request)

    app.include_router(api_router, prefix=settings.API_V1_PREFIX)

    @app.get("/", tags=["health"])
    async def root() -> dict[str, str]:
        return {
            "name": settings.APP_NAME,
            "version": settings.APP_VERSION,
            "environment": settings.ENVIRONMENT,
            "docs": "/docs",
        }

    @app.get("/health", tags=["health"])
    async def health() -> dict[str, object]:
        return {"status": "ok", "database": await check_connection()}

    return app


app = create_app()
