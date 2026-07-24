"""Pydantic schemas for the notifications module."""

from datetime import datetime

from pydantic import BaseModel, Field

from app.database.enums import NotificationType
from app.modules.common.schemas import LogRead


class NotificationCreate(BaseModel):
    user_id: int
    title: str = Field(min_length=1, max_length=255)
    message: str | None = None
    type: NotificationType = NotificationType.systeme
    link: str | None = None


class NotificationRead(LogRead):
    user_id: int
    title: str
    message: str | None
    type: NotificationType
    is_read: bool
    read_at: datetime | None
    link: str | None
