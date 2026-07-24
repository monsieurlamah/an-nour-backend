"""Business logic for the system module."""

from collections.abc import Sequence

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.database.enums import ReferenceType
from app.modules.system.models import ActivityLog, Attachment, Setting
from app.modules.system.schemas import (
    ActivityLogCreate,
    AttachmentCreate,
    SettingCreate,
)
from app.modules.users.models import User


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
    ) -> Sequence[ActivityLog]:
        stmt = select(ActivityLog)
        if user_id is not None:
            stmt = stmt.where(ActivityLog.user_id == user_id)
        if module is not None:
            stmt = stmt.where(ActivityLog.module == module)
        stmt = stmt.order_by(ActivityLog.id.desc()).offset(skip).limit(limit)
        return (await self.db.execute(stmt)).scalars().all()

    async def create(self, payload: ActivityLogCreate, user: User) -> ActivityLog:
        log = ActivityLog(**payload.model_dump(), user_id=user.id)
        self.db.add(log)
        await self.db.flush()
        await self.db.refresh(log)
        return log


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
