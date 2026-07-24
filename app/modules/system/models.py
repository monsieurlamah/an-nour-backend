"""System ORM models: activity logs, settings, attachments."""

from sqlalchemy import Enum, ForeignKey, Integer, String, Text
from sqlalchemy.orm import Mapped, mapped_column

from app.database.base import Base, LogEntity
from app.database.enums import ReferenceType, SettingType
from app.database.mixins import IDMixin, TimestampMixin, UUIDMixin


class ActivityLog(LogEntity):
    __tablename__ = "activity_logs"

    user_id: Mapped[int | None] = mapped_column(
        ForeignKey("users.id", ondelete="SET NULL"), nullable=True, index=True
    )
    action: Mapped[str] = mapped_column(String(150), nullable=False, index=True)
    module: Mapped[str | None] = mapped_column(String(80), index=True, nullable=True)
    reference_type: Mapped[ReferenceType | None] = mapped_column(
        Enum(ReferenceType, native_enum=False, length=30, create_constraint=False),
        nullable=True,
    )
    reference_id: Mapped[int | None] = mapped_column(Integer, nullable=True)
    ip_address: Mapped[str | None] = mapped_column(String(45), nullable=True)
    user_agent: Mapped[str | None] = mapped_column(String(512), nullable=True)


class Setting(Base, IDMixin, UUIDMixin, TimestampMixin):
    __tablename__ = "settings"

    # ``key``/``group`` are reserved SQL words; ``type`` is renamed for clarity.
    key: Mapped[str] = mapped_column(String(150), unique=True, index=True, nullable=False)
    value: Mapped[str | None] = mapped_column(Text, nullable=True)
    value_type: Mapped[SettingType] = mapped_column(
        Enum(SettingType, native_enum=False, length=20, create_constraint=False),
        default=SettingType.string,
        nullable=False,
    )
    group_name: Mapped[str | None] = mapped_column(String(80), index=True, nullable=True)


class Attachment(LogEntity):
    __tablename__ = "attachments"

    reference_type: Mapped[ReferenceType | None] = mapped_column(
        Enum(ReferenceType, native_enum=False, length=30, create_constraint=False),
        nullable=True,
        index=True,
    )
    reference_id: Mapped[int | None] = mapped_column(Integer, nullable=True, index=True)
    file_url: Mapped[str] = mapped_column(String(512), nullable=False)
    file_type: Mapped[str | None] = mapped_column(String(80), nullable=True)
    file_name: Mapped[str | None] = mapped_column(String(255), nullable=True)
    created_by: Mapped[int | None] = mapped_column(
        ForeignKey("users.id", ondelete="SET NULL"), nullable=True
    )
