"""Pydantic schemas for the users module."""

from datetime import datetime

from pydantic import BaseModel, ConfigDict, EmailStr, Field, field_validator

from app.database.enums import UserStatus
from app.security.password import validate_password_strength


class UserBase(BaseModel):
    firstname: str = Field(min_length=1, max_length=120)
    lastname: str = Field(min_length=1, max_length=120)
    email: EmailStr
    phone: str | None = Field(default=None, max_length=30)
    address: str | None = Field(default=None, max_length=255)
    avatar: str | None = Field(default=None, max_length=512)


class UserCreate(UserBase):
    password: str = Field(min_length=8, max_length=128)
    status: UserStatus = UserStatus.active
    is_activated: bool = True
    # When True the router sends a welcome email with the plain-text password
    # and marks the account as must_change_password.
    send_credentials: bool = False

    @field_validator("password")
    @classmethod
    def _strong_password(cls, value: str) -> str:
        return validate_password_strength(value)


class UserUpdate(BaseModel):
    firstname: str | None = Field(default=None, min_length=1, max_length=120)
    lastname: str | None = Field(default=None, min_length=1, max_length=120)
    email: EmailStr | None = None
    phone: str | None = Field(default=None, max_length=30)
    address: str | None = Field(default=None, max_length=255)
    avatar: str | None = Field(default=None, max_length=512)
    password: str | None = Field(default=None, min_length=8, max_length=128)
    status: UserStatus | None = None
    is_activated: bool | None = None
    must_change_password: bool | None = None

    @field_validator("password")
    @classmethod
    def _strong_password(cls, value: str | None) -> str | None:
        return value if value is None else validate_password_strength(value)


class ChangePasswordRequest(BaseModel):
    # Optional: not required on the first-login flow, where the account is
    # flagged ``must_change_password`` and the user has just authenticated with
    # the temporary password. Required for a normal self-service change.
    current_password: str | None = Field(default=None, min_length=1)
    new_password: str = Field(min_length=8, max_length=128)

    @field_validator("new_password")
    @classmethod
    def _strong_password(cls, value: str) -> str:
        return validate_password_strength(value)


class UserRead(UserBase):
    model_config = ConfigDict(from_attributes=True)

    email: str  # override: no format validation on output (accepts internal domains like .local)
    id: int
    uuid: str
    status: UserStatus
    is_activated: bool
    email_verified: bool
    must_change_password: bool
    last_login_at: datetime | None
    created_at: datetime
    updated_at: datetime


class UserMeRead(UserRead):
    """Current-user profile enriched with the effective RBAC state."""

    groups: list[str] = []
    permissions: list[str] = []
    is_super_admin: bool = False
