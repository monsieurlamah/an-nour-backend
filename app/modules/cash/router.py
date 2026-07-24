"""HTTP routes for the cash module: sessions and movements."""

from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, Query, status

from app.api.deps import CurrentUser, DbSession
from app.core.authz import UserStoreScope, require_permission
from app.database.enums import CashSessionStatus
from app.modules.cash.schemas import (
    CashMovementCreate,
    CashMovementRead,
    CashSessionClose,
    CashSessionOpen,
    CashSessionRead,
)
from app.modules.cash.services import CashMovementService, CashSessionService
from app.modules.common.store_scope import assert_creatable, in_scope, resolve_list_scope

router = APIRouter(prefix="/cash", tags=["cash"])


# --- Sessions ----------------------------------------------------------------
@router.get("/sessions", response_model=list[CashSessionRead])
async def list_cash_sessions(
    db: DbSession,
    _: CurrentUser,
    _perm: Annotated[None, Depends(require_permission("cash.view"))],
    scope: UserStoreScope,
    store_id: int | None = Query(default=None),
    session_status: CashSessionStatus | None = Query(default=None),
    skip: int = Query(0, ge=0),
    limit: int = Query(100, ge=1, le=500),
) -> list[CashSessionRead]:
    items = await CashSessionService(db).list(
        skip=skip, limit=limit, store_id=resolve_list_scope(store_id, scope), status=session_status
    )
    return list(items)  # type: ignore[return-value]


@router.post("/sessions", response_model=CashSessionRead, status_code=status.HTTP_201_CREATED)
async def open_cash_session(
    payload: CashSessionOpen,
    db: DbSession,
    user: CurrentUser,
    _perm: Annotated[None, Depends(require_permission("cash.manage"))],
    scope: UserStoreScope,
) -> CashSessionRead:
    assert_creatable(payload.store_id, scope)
    return await CashSessionService(db).open(payload, user)  # type: ignore[return-value]


@router.get("/sessions/{session_id}", response_model=CashSessionRead)
async def get_cash_session(
    session_id: int,
    db: DbSession,
    _: CurrentUser,
    _perm: Annotated[None, Depends(require_permission("cash.view"))],
    scope: UserStoreScope,
) -> CashSessionRead:
    session = await CashSessionService(db).get(session_id)
    if session is None or not in_scope(session.store_id, scope):  # type: ignore[attr-defined]
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Cash session not found")
    return session  # type: ignore[return-value]


@router.post("/sessions/{session_id}/close", response_model=CashSessionRead)
async def close_cash_session(
    session_id: int,
    payload: CashSessionClose,
    db: DbSession,
    user: CurrentUser,
    _perm: Annotated[None, Depends(require_permission("cash.manage"))],
    scope: UserStoreScope,
) -> CashSessionRead:
    service = CashSessionService(db)
    session = await service.get(session_id)
    if session is None or not in_scope(session.store_id, scope):  # type: ignore[attr-defined]
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Cash session not found")
    if session.status == CashSessionStatus.fermee:
        raise HTTPException(status.HTTP_409_CONFLICT, "Cash session already closed")
    return await service.close(session, payload, user)  # type: ignore[return-value]


# --- Movements ---------------------------------------------------------------
@router.get("/movements", response_model=list[CashMovementRead])
async def list_cash_movements(
    db: DbSession,
    _: CurrentUser,
    _perm: Annotated[None, Depends(require_permission("cash.view"))],
    scope: UserStoreScope,
    cash_session_id: int | None = Query(default=None),
    skip: int = Query(0, ge=0),
    limit: int = Query(100, ge=1, le=500),
) -> list[CashMovementRead]:
    if scope != "hq":
        if cash_session_id is None:
            return []  # no target to scope against -> don't leak every store's movements
        session = await CashSessionService(db).get(cash_session_id)
        if session is None or not in_scope(session.store_id, scope):  # type: ignore[attr-defined]
            raise HTTPException(status.HTTP_404_NOT_FOUND, "Cash session not found")
    items = await CashMovementService(db).list(
        skip=skip, limit=limit, cash_session_id=cash_session_id
    )
    return list(items)  # type: ignore[return-value]


@router.post("/movements", response_model=CashMovementRead, status_code=status.HTTP_201_CREATED)
async def create_cash_movement(
    payload: CashMovementCreate,
    db: DbSession,
    user: CurrentUser,
    _perm: Annotated[None, Depends(require_permission("cash.manage"))],
    scope: UserStoreScope,
) -> CashMovementRead:
    if scope != "hq":
        session = await CashSessionService(db).get(payload.cash_session_id)
        if session is None or not in_scope(session.store_id, scope):  # type: ignore[attr-defined]
            raise HTTPException(status.HTTP_404_NOT_FOUND, "Cash session not found")
    return await CashMovementService(db).create(payload, user)  # type: ignore[return-value]
