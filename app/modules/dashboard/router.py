"""HTTP routes for the Dashboard module."""

from datetime import date
from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, Query, status

from app.api.deps import CurrentUser, DbSession
from app.core.authz import UserStoreScope, require_any_permission
from app.core.i18n import t
from app.modules.common.store_scope import (
    assert_scope_nonempty,
    in_scope,
    resolve_create_store_id,
)
from app.modules.dashboard.schemas import DashboardStats
from app.modules.dashboard.services import DashboardService

router = APIRouter(prefix="/dashboard", tags=["dashboard"])


@router.get("/stats", response_model=DashboardStats)
async def get_dashboard_stats(
    db: DbSession,
    _: CurrentUser,
    _perm: Annotated[
        None, Depends(require_any_permission("dashboard.global.view", "dashboard.store.view"))
    ],
    scope: UserStoreScope,
    boutique_id: int | None = Query(default=None),
    date_from: date | None = Query(default=None),
    date_to: date | None = Query(default=None),
) -> DashboardStats:
    """Single endpoint returning all dashboard KPIs, charts and alerts.

    Designed for one API call per dashboard load — no waterfalling.
    ``boutique_id=None`` returns an aggregated HQ view across all boutiques
    — only reachable by a caller whose scope is ``"hq"``. A store-scoped
    caller is always pinned to (one of) their own store(s).

    ``date_from``/``date_to`` select a custom period for the period-based
    figures (both required together — a lone one is ignored, falling back
    to the default "month to date").
    """
    period = (date_from, date_to) if date_from is not None and date_to is not None else (None, None)

    if scope == "hq":
        return await DashboardService(db).get_stats(boutique_id, *period)

    # A store-scoped account with zero assigned boutiques: give the specific
    # "not assigned to any store" message, not a generic scope/permission
    # error the frontend can't distinguish from a real 403.
    assert_scope_nonempty(scope)

    resolved = resolve_create_store_id(boutique_id, scope)
    if resolved is None or not in_scope(resolved, scope):
        raise HTTPException(status.HTTP_403_FORBIDDEN, detail=t("store_out_of_scope"))
    return await DashboardService(db).get_stats(resolved, *period)
