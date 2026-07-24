"""Pydantic schemas for the stores module."""

from pydantic import BaseModel, Field

from app.modules.common.schemas import EntityRead


class StoreCreate(BaseModel):
    name: str = Field(min_length=1, max_length=200)
    slug: str | None = Field(default=None, max_length=200)
    code: str | None = Field(default=None, max_length=50)
    description: str | None = None
    logo: str | None = Field(default=None, max_length=512)
    address: str | None = Field(default=None, max_length=255)
    city: str | None = Field(default=None, max_length=100)
    timezone: str = Field(default="Africa/Conakry", max_length=50)
    devise: str = Field(default="GNF", max_length=10)
    gerant_id: int | None = None
    category_store_id: int | None = None


class StoreUpdate(BaseModel):
    name: str | None = Field(default=None, min_length=1, max_length=200)
    code: str | None = Field(default=None, max_length=50)
    description: str | None = None
    logo: str | None = Field(default=None, max_length=512)
    address: str | None = Field(default=None, max_length=255)
    city: str | None = Field(default=None, max_length=100)
    timezone: str | None = Field(default=None, max_length=50)
    devise: str | None = Field(default=None, max_length=10)
    gerant_id: int | None = None
    category_store_id: int | None = None


class StoreRead(EntityRead):
    name: str
    slug: str
    code: str | None
    description: str | None
    logo: str | None
    address: str | None
    city: str | None
    timezone: str
    devise: str
    gerant_id: int | None
    category_store_id: int | None
    created_by: int | None


class StoreUserCreate(BaseModel):
    store_id: int
    user_id: int
    role_id: int | None = None


class StoreUserRead(EntityRead):
    store_id: int
    user_id: int
    role_id: int | None
