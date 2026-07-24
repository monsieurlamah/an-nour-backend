"""HTTP routes for the system module: settings, activity logs, attachments."""

from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, Query, status

from app.api.deps import CurrentUser, DbSession
from app.core.authz import require_permission
from app.database.enums import ReferenceType
from app.modules.system.schemas import (
    ActivityLogCreate,
    ActivityLogRead,
    AttachmentCreate,
    AttachmentRead,
    SettingCreate,
    SettingRead,
    SettingUpdate,
)
from app.modules.system.services import (
    ActivityLogService,
    AttachmentService,
    SettingService,
)

router = APIRouter(prefix="/system", tags=["system"])


# --- Settings ------------------------------------------------------------------
@router.get("/settings", response_model=list[SettingRead])
async def list_settings(
    db: DbSession,
    _: CurrentUser,
    _perm: Annotated[None, Depends(require_permission("settings.manage"))],
    group_name: str | None = Query(default=None),
) -> list[SettingRead]:
    return list(await SettingService(db).list(group_name=group_name))  # type: ignore[return-value]


@router.post("/settings", response_model=SettingRead, status_code=status.HTTP_201_CREATED)
async def create_setting(
    payload: SettingCreate,
    db: DbSession,
    _: CurrentUser,
    _perm: Annotated[None, Depends(require_permission("settings.manage"))],
) -> SettingRead:
    service = SettingService(db)
    if await service.get_by_key(payload.key):
        raise HTTPException(status.HTTP_409_CONFLICT, "A setting with this key already exists")
    return await service.create(payload)  # type: ignore[return-value]


@router.get("/settings/{key}", response_model=SettingRead)
async def get_setting(
    key: str,
    db: DbSession,
    _: CurrentUser,
    _perm: Annotated[None, Depends(require_permission("settings.manage"))],
) -> SettingRead:
    setting = await SettingService(db).get_by_key(key)
    if setting is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Setting not found")
    return setting  # type: ignore[return-value]


@router.patch("/settings/{setting_id}", response_model=SettingRead)
async def update_setting(
    setting_id: int,
    payload: SettingUpdate,
    db: DbSession,
    _: CurrentUser,
    _perm: Annotated[None, Depends(require_permission("settings.manage"))],
) -> SettingRead:
    service = SettingService(db)
    setting = await service.get(setting_id)
    if setting is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Setting not found")
    return await service.update(setting, payload.model_dump(exclude_unset=True))  # type: ignore[return-value]


@router.delete("/settings/{setting_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_setting(
    setting_id: int,
    db: DbSession,
    _: CurrentUser,
    _perm: Annotated[None, Depends(require_permission("settings.manage"))],
) -> None:
    service = SettingService(db)
    setting = await service.get(setting_id)
    if setting is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Setting not found")
    await service.delete(setting)


# --- Activity logs ---------------------------------------------------------------
@router.get("/activity-logs", response_model=list[ActivityLogRead])
async def list_activity_logs(
    db: DbSession,
    _: CurrentUser,
    _perm: Annotated[None, Depends(require_permission("settings.manage"))],
    user_id: int | None = Query(default=None),
    module: str | None = Query(default=None),
    skip: int = Query(0, ge=0),
    limit: int = Query(100, ge=1, le=500),
) -> list[ActivityLogRead]:
    items = await ActivityLogService(db).list(
        skip=skip, limit=limit, user_id=user_id, module=module
    )
    return list(items)  # type: ignore[return-value]


@router.post("/activity-logs", response_model=ActivityLogRead, status_code=status.HTTP_201_CREATED)
async def create_activity_log(
    payload: ActivityLogCreate, db: DbSession, user: CurrentUser
) -> ActivityLogRead:
    # Any authenticated user may log their own activity — this is a write
    # sink, not a sensitive read; no permission required.
    return await ActivityLogService(db).create(payload, user)  # type: ignore[return-value]


# --- Attachments -----------------------------------------------------------------
@router.get("/attachments", response_model=list[AttachmentRead])
async def list_attachments(
    db: DbSession,
    _: CurrentUser,
    _perm: Annotated[None, Depends(require_permission("settings.manage"))],
    reference_type: ReferenceType | None = Query(default=None),
    reference_id: int | None = Query(default=None),
    skip: int = Query(0, ge=0),
    limit: int = Query(100, ge=1, le=500),
) -> list[AttachmentRead]:
    items = await AttachmentService(db).list(
        skip=skip, limit=limit, reference_type=reference_type, reference_id=reference_id
    )
    return list(items)  # type: ignore[return-value]


@router.post("/attachments", response_model=AttachmentRead, status_code=status.HTTP_201_CREATED)
async def create_attachment(
    payload: AttachmentCreate,
    db: DbSession,
    user: CurrentUser,
    _perm: Annotated[None, Depends(require_permission("settings.manage"))],
) -> AttachmentRead:
    return await AttachmentService(db).create(payload, user)  # type: ignore[return-value]


@router.delete("/attachments/{attachment_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_attachment(
    attachment_id: int,
    db: DbSession,
    _: CurrentUser,
    _perm: Annotated[None, Depends(require_permission("settings.manage"))],
) -> None:
    service = AttachmentService(db)
    attachment = await service.get(attachment_id)
    if attachment is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Attachment not found")
    await service.delete(attachment)
