"""Aggregates all v1 module routers under a single API router."""

from fastapi import APIRouter

from app.modules.access.router import router as access_router
from app.modules.achat.router import router as achat_router
from app.modules.auth.router import router as auth_router
from app.modules.cash.router import router as cash_router
from app.modules.catalog.router import router as catalog_router
from app.modules.clients.router import router as clients_router
from app.modules.commandes.router import router as commandes_router
from app.modules.creances.router import router as creances_router
from app.modules.dashboard.router import router as dashboard_router
from app.modules.expenses.router import router as expenses_router
from app.modules.notifications.router import router as notifications_router
from app.modules.reports.router import router as reports_router
from app.modules.stock.router import router as stock_router
from app.modules.stores.router import router as stores_router
from app.modules.system.router import router as system_router
from app.modules.upload.router import router as upload_router
from app.modules.users.router import router as users_router
from app.modules.ventes.router import router as ventes_router

api_router = APIRouter()

# Auth & identity
api_router.include_router(auth_router)
api_router.include_router(users_router)
api_router.include_router(access_router)

# Catalog & network
api_router.include_router(catalog_router)
api_router.include_router(stores_router)
api_router.include_router(clients_router)

# Inventory & supply
api_router.include_router(stock_router)
api_router.include_router(commandes_router)
api_router.include_router(achat_router)

# Sales & finance
api_router.include_router(ventes_router)
api_router.include_router(creances_router)
api_router.include_router(expenses_router)
api_router.include_router(cash_router)

# Platform
api_router.include_router(notifications_router)
api_router.include_router(system_router)
api_router.include_router(upload_router)
api_router.include_router(dashboard_router)
api_router.include_router(reports_router)
