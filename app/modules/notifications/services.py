"""Business logic for the notifications module."""

from collections.abc import Sequence

from sqlalchemy import select, update
from sqlalchemy.ext.asyncio import AsyncSession

from app.modules.notifications.models import Notification
from app.modules.notifications.schemas import NotificationCreate
from app.utils.helpers import utcnow


class NotificationService:
    def __init__(self, db: AsyncSession) -> None:
        self.db = db

    async def get(self, notification_id: int) -> Notification | None:
        return await self.db.get(Notification, notification_id)

    async def list(
        self,
        user_id: int,
        skip: int = 0,
        limit: int = 100,
        is_read: bool | None = None,
    ) -> Sequence[Notification]:
        stmt = select(Notification).where(Notification.user_id == user_id)
        if is_read is not None:
            stmt = stmt.where(Notification.is_read == is_read)
        stmt = stmt.order_by(Notification.id.desc()).offset(skip).limit(limit)
        return (await self.db.execute(stmt)).scalars().all()

    async def create(self, payload: NotificationCreate) -> Notification:
        notification = Notification(**payload.model_dump())
        self.db.add(notification)
        await self.db.flush()
        await self.db.refresh(notification)
        return notification

    async def mark_read(self, notification: Notification) -> Notification:
        notification.is_read = True
        notification.read_at = utcnow()
        self.db.add(notification)
        await self.db.flush()
        await self.db.refresh(notification)
        return notification

    async def mark_all_read(self, user_id: int) -> int:
        result = await self.db.execute(
            update(Notification)
            .where(Notification.user_id == user_id, Notification.is_read.is_(False))
            .values(is_read=True, read_at=utcnow())
        )
        await self.db.flush()
        return result.rowcount or 0
