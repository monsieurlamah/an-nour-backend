"""Business logic for the system module."""
from __future__ import annotations

from collections.abc import Sequence
from datetime import datetime

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.logging import get_logger
from app.database.enums import ReferenceType
from app.modules.system.models import ActivityLog, Attachment, Setting
from app.modules.system.schemas import (
    ActivityLogCreate,
    AttachmentCreate,
    SettingCreate,
)
from app.modules.users.models import User

_activity_logger = get_logger("system.activity_log")


class SettingService:
    def __init__(self, db: AsyncSession) -> None:
        self.db = db

    async def get(self, setting_id: int) -> Setting | None:
        return await self.db.get(Setting, setting_id)

    async def get_by_key(self, key: str) -> Setting | None:
        result = await self.db.execute(select(Setting).where(Setting.key == key))
        return result.scalar_one_or_none()

    async def list(self, group_name: str | None = None) -> Sequence[Setting]:
        stmt = select(Setting)
        if group_name is not None:
            stmt = stmt.where(Setting.group_name == group_name)
        return (await self.db.execute(stmt.order_by(Setting.key))).scalars().all()

    async def create(self, payload: SettingCreate) -> Setting:
        setting = Setting(**payload.model_dump())
        self.db.add(setting)
        await self.db.flush()
        await self.db.refresh(setting)
        return setting

    async def update(self, setting: Setting, data: dict) -> Setting:
        for field, value in data.items():
            setattr(setting, field, value)
        self.db.add(setting)
        await self.db.flush()
        await self.db.refresh(setting)
        return setting

    async def delete(self, setting: Setting) -> None:
        await self.db.delete(setting)
        await self.db.flush()


class ActivityLogService:
    def __init__(self, db: AsyncSession) -> None:
        self.db = db

    async def list(
        self,
        skip: int = 0,
        limit: int = 100,
        user_id: int | None = None,
        module: str | None = None,
        boutique_id: int | list[int] | None = None,
        date_from: datetime | None = None,
        date_to: datetime | None = None,
    ) -> Sequence[ActivityLog]:
        stmt = select(ActivityLog)
        if user_id is not None:
            stmt = stmt.where(ActivityLog.user_id == user_id)
        if module is not None:
            stmt = stmt.where(ActivityLog.module == module)
        if isinstance(boutique_id, (list, set, frozenset)):
            stmt = stmt.where(ActivityLog.boutique_id.in_(boutique_id))
        elif boutique_id is not None:
            stmt = stmt.where(ActivityLog.boutique_id == boutique_id)
        if date_from is not None:
            stmt = stmt.where(ActivityLog.created_at >= date_from)
        if date_to is not None:
            stmt = stmt.where(ActivityLog.created_at <= date_to)
        stmt = stmt.order_by(ActivityLog.id.desc()).offset(skip).limit(limit)
        return (await self.db.execute(stmt)).scalars().all()

    async def create(self, payload: ActivityLogCreate, user: User) -> ActivityLog:
        log = ActivityLog(**payload.model_dump(), user_id=user.id)
        self.db.add(log)
        await self.db.flush()
        await self.db.refresh(log)
        return log

    async def list_enriched(self, **filters) -> list[dict]:
        """Same as list(), each row denormalized with the actor's display
        name — the frontend Journal page has no other way to resolve it
        (users.view is a separate permission a gérant may not even hold)."""
        logs = await self.list(**filters)
        user_ids = {log.user_id for log in logs if log.user_id is not None}
        users: dict[int, User] = {}
        if user_ids:
            result = await self.db.execute(select(User).where(User.id.in_(user_ids)))
            users = {u.id: u for u in result.scalars().all()}
        rows = []
        for log in logs:
            u = users.get(log.user_id) if log.user_id else None
            rows.append({
                "id": log.id, "uuid": log.uuid, "created_at": log.created_at,
                "user_id": log.user_id, "action": log.action, "module": log.module,
                "reference_type": log.reference_type, "reference_id": log.reference_id,
                "boutique_id": log.boutique_id, "ip_address": log.ip_address,
                "user_agent": log.user_agent,
                "user_name": f"{u.firstname} {u.lastname}" if u else None,
            })
        return rows


async def log_activity(
    db: AsyncSession,
    user: User | int | None,
    action: str,
    module: str,
    *,
    reference_type: ReferenceType | None = None,
    reference_id: int | None = None,
    boutique_id: int | None = None,
    ip_address: str | None = None,
) -> None:
    """Cahier des charges §14 — the one call site every module uses to write
    to the append-only journal (mouvements de stock, documents commerciaux,
    opérations de caisse, actions d'administration). Never raises — a
    logging failure must never roll back or block the business operation it
    describes, mirroring the existing best-effort pattern for stock-alert
    emails (see stock/alert_service.py).

    ``user`` accepts either a loaded ``User`` (the common case) or a bare
    user id (e.g. ``Commande.created_by``/``CommandeEvenement.acteur_id`` —
    an int the caller already has, with no need to load the full row just to
    log against it) — or ``None`` for a system-triggered event (e.g. the
    overdue-créances cron), which leaves the row's ``user_id`` null rather
    than skip logging entirely: an automatic action is still worth a line in
    the journal, just not attributable to a person.
    """
    user_id = user.id if isinstance(user, User) else user
    try:
        db.add(
            ActivityLog(
                user_id=user_id,
                action=action,
                module=module,
                reference_type=reference_type,
                reference_id=reference_id,
                boutique_id=boutique_id,
                ip_address=ip_address,
            )
        )
        await db.flush()
    except Exception:
        _activity_logger.error(
            "Failed to write activity log action=%s module=%s reference_id=%s",
            action, module, reference_id, exc_info=True,
        )


class AttachmentService:
    def __init__(self, db: AsyncSession) -> None:
        self.db = db

    async def get(self, attachment_id: int) -> Attachment | None:
        return await self.db.get(Attachment, attachment_id)

    async def list(
        self,
        skip: int = 0,
        limit: int = 100,
        reference_type: ReferenceType | None = None,
        reference_id: int | None = None,
    ) -> Sequence[Attachment]:
        stmt = select(Attachment)
        if reference_type is not None:
            stmt = stmt.where(Attachment.reference_type == reference_type)
        if reference_id is not None:
            stmt = stmt.where(Attachment.reference_id == reference_id)
        stmt = stmt.order_by(Attachment.id.desc()).offset(skip).limit(limit)
        return (await self.db.execute(stmt)).scalars().all()

    async def create(self, payload: AttachmentCreate, user: User) -> Attachment:
        attachment = Attachment(**payload.model_dump(), created_by=user.id)
        self.db.add(attachment)
        await self.db.flush()
        await self.db.refresh(attachment)
        return attachment

    async def delete(self, attachment: Attachment) -> None:
        await self.db.delete(attachment)
        await self.db.flush()
