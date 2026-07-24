"""Pydantic schemas for the access (RBAC) module."""

from pydantic import BaseModel, Field

from app.modules.common.schemas import EntityRead


# --- Roles -------------------------------------------------------------------
class RoleCreate(BaseModel):
    name: str = Field(min_length=1, max_length=120)
    slug: str | None = Field(default=None, max_length=120)
    description: str | None = None


class RoleUpdate(BaseModel):
    name: str | None = Field(default=None, min_length=1, max_length=120)
    description: str | None = None


class RoleRead(EntityRead):
    name: str
    slug: str
    description: str | None
    created_by: int | None


# --- Groups ------------------------------------------------------------------
class GroupCreate(BaseModel):
    name: str = Field(min_length=1, max_length=120)
    slug: str | None = Field(default=None, max_length=120)
    description: str | None = None


class GroupUpdate(BaseModel):
    name: str | None = Field(default=None, min_length=1, max_length=120)
    description: str | None = None


class GroupRead(EntityRead):
    name: str
    slug: str
    description: str | None


# --- Permissions -------------------------------------------------------------
class PermissionCreate(BaseModel):
    name: str = Field(min_length=1, max_length=150)
    slug: str = Field(min_length=1, max_length=150)
    module: str = Field(min_length=1, max_length=80)
    description: str | None = None


class PermissionUpdate(BaseModel):
    name: str | None = Field(default=None, min_length=1, max_length=150)
    module: str | None = Field(default=None, min_length=1, max_length=80)
    description: str | None = None


class PermissionRead(EntityRead):
    name: str
    slug: str
    module: str
    description: str | None


# --- Assignments -------------------------------------------------------------
class UserGroupCreate(BaseModel):
    user_id: int
    group_id: int


class UserGroupRead(EntityRead):
    user_id: int
    group_id: int


class GroupPermissionCreate(BaseModel):
    group_id: int
    permission_id: int
    allowed: bool = True


class GroupPermissionRead(EntityRead):
    group_id: int
    permission_id: int
    allowed: bool


class UserPermissionCreate(BaseModel):
    user_id: int
    permission_id: int
    store_id: int | None = None
    allowed: bool = True


class UserPermissionRead(EntityRead):
    user_id: int
    permission_id: int
    store_id: int | None
    allowed: bool
