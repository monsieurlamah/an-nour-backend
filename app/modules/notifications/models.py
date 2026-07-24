"""Notification ORM model."""

from datetime import datetime

from sqlalchemy import Boolean, DateTime, Enum, ForeignKey, String, Text
from sqlalchemy.orm import Mapped, mapped_column

from app.database.base import LogEntity
from app.database.enums import NotificationType


class Notification(LogEntity):
    __tablename__ = "notifications"

    user_id: Mapped[int] = mapped_column(
        ForeignKey("users.id", ondelete="CASCADE"), nullable=False, index=True
    )
    title: Mapped[str] = mapped_column(String(255), nullable=False)
    message: Mapped[str | None] = mapped_column(Text, nullable=True)
    type: Mapped[NotificationType] = mapped_column(
        Enum(NotificationType, native_enum=False, length=20, create_constraint=False),
        default=NotificationType.systeme,
        nullable=False,
        index=True,
    )
    is_read: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False, index=True)
    read_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    # Deep-link for click-to-navigate — same shape/nullability as the
    # frontend's existing DashboardAlerte.link (frontend/src/lib/api.ts).
    link: Mapped[str | None] = mapped_column(String(255), nullable=True)
