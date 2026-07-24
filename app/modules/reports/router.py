"""HTTP routes for the Reports module."""

from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, Query, status

from app.api.deps import CurrentUser, DbSession
from app.core.authz import UserStoreScope, require_permission
from app.core.i18n import t
from app.modules.common.store_scope import in_scope, resolve_create_store_id
from app.modules.reports.schemas import ReportsData
from app.modules.reports.services import ReportsService

router = APIRouter(prefix="/reports", tags=["reports"])


@router.get("/data", response_model=ReportsData)
async def get_reports_data(
    db: DbSession,
    _: CurrentUser,
    _perm: Annotated[None, Depends(require_permission("reports.view"))],
    scope: UserStoreScope,
    boutique_id: int | None = Query(default=None),
) -> ReportsData:
    """Single aggregated payload for the "Rapports & Analyses" page.

    ``boutique_id=None`` returns the HQ-wide view across every boutique —
    only reachable for a caller whose scope is ``"hq"``. A store-scoped
    caller is always pinned to (one of) their own store(s), same rule as
    ``GET /dashboard/stats``.
    """
    if scope == "hq":
        return await ReportsService(db).get_data(boutique_id)

    resolved = resolve_create_store_id(boutique_id, scope)
    if resolved is None or not in_scope(resolved, scope):
        raise HTTPException(status.HTTP_403_FORBIDDEN, detail=t("store_out_of_scope"))
    return await ReportsService(db).get_data(resolved)
