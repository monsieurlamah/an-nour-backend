"""HTTP routes for the notifications module."""

from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, Query, status

from app.api.deps import CurrentUser, DbSession
from app.core.authz import require_permission
from app.modules.notifications.schemas import NotificationCreate, NotificationRead
from app.modules.notifications.services import NotificationService

router = APIRouter(prefix="/notifications", tags=["notifications"])


@router.get("", response_model=list[NotificationRead])
async def list_my_notifications(
    db: DbSession,
    user: CurrentUser,
    is_read: bool | None = Query(default=None),
    skip: int = Query(0, ge=0),
    limit: int = Query(100, ge=1, le=500),
) -> list[NotificationRead]:
    # Self-scoped by construction (user_id=user.id) — no extra permission needed.
    items = await NotificationService(db).list(
        user_id=user.id, skip=skip, limit=limit, is_read=is_read
    )
    return list(items)  # type: ignore[return-value]


@router.post("", response_model=NotificationRead, status_code=status.HTTP_201_CREATED)
async def create_notification(
    payload: NotificationCreate,
    db: DbSession,
    _: CurrentUser,
    # Pushing a notification to an arbitrary user is an admin action; there's
    # no dedicated "notifications.manage" slug in the seed, so this reuses
    # users.manage rather than inventing a new permission for one route.
    _perm: Annotated[None, Depends(require_permission("users.manage"))],
) -> NotificationRead:
    return await NotificationService(db).create(payload)  # type: ignore[return-value]


@router.post("/{notification_id}/read", response_model=NotificationRead)
async def mark_notification_read(
    notification_id: int, db: DbSession, user: CurrentUser
) -> NotificationRead:
    service = NotificationService(db)
    notification = await service.get(notification_id)
    if notification is None or notification.user_id != user.id:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Notification not found")
    return await service.mark_read(notification)  # type: ignore[return-value]


@router.post("/read-all")
async def mark_all_notifications_read(db: DbSession, user: CurrentUser) -> dict[str, int]:
    updated = await NotificationService(db).mark_all_read(user.id)
    return {"updated": updated}
