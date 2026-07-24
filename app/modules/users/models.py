"""User ORM model."""

from datetime import datetime

from sqlalchemy import Boolean, DateTime, Enum, String
from sqlalchemy.orm import Mapped, mapped_column

from app.database.base import Entity
from app.database.enums import UserStatus


class User(Entity):
    __tablename__ = "users"

    lastname: Mapped[str] = mapped_column(String(120), nullable=False)
    firstname: Mapped[str] = mapped_column(String(120), nullable=False)
    phone: Mapped[str | None] = mapped_column(
        String(30), unique=True, index=True, nullable=True
    )
    email: Mapped[str] = mapped_column(String(255), unique=True, index=True, nullable=False)
    avatar: Mapped[str | None] = mapped_column(String(512), nullable=True)
    # Stores the bcrypt hash (never the plaintext).
    password: Mapped[str] = mapped_column(String(255), nullable=False)
    address: Mapped[str | None] = mapped_column(String(255), nullable=True)

    is_activated: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    email_verified: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    must_change_password: Mapped[bool] = mapped_column(
        Boolean, default=False, nullable=False
    )
    last_login_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)

    # Override the generic status with the user-specific lifecycle.
    status: Mapped[UserStatus] = mapped_column(
        Enum(UserStatus, native_enum=False, length=20, create_constraint=False),
        default=UserStatus.invited,
        nullable=False,
        index=True,
    )

    @property
    def full_name(self) -> str:
        return f"{self.firstname} {self.lastname}".strip()

    def __repr__(self) -> str:  # pragma: no cover
        return f"<User id={self.id} email={self.email!r}>"
