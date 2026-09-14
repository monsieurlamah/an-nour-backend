"""Pydantic schemas for the system module: settings, activity logs, attachments."""

from datetime import datetime

from pydantic import BaseModel, Field

from app.database.enums import ReferenceType, SettingType
from app.modules.common.schemas import LogRead, ORMModel


# --- Settings ----------------------------------------------------------------
class SettingCreate(BaseModel):
    key: str = Field(min_length=1, max_length=150)
    value: str | None = None
    value_type: SettingType = SettingType.string
    group_name: str | None = Field(default=None, max_length=80)


class SettingUpdate(BaseModel):
    value: str | None = None
    value_type: SettingType | None = None
    group_name: str | None = Field(default=None, max_length=80)


class SettingRead(ORMModel):
    id: int
    uuid: str
    key: str
    value: str | None
    value_type: SettingType
    group_name: str | None
    created_at: datetime
    updated_at: datetime


# --- Activity logs -----------------------------------------------------------
class ActivityLogCreate(BaseModel):
    action: str = Field(min_length=1, max_length=150)
    module: str | None = Field(default=None, max_length=80)
    reference_type: ReferenceType | None = None
    reference_id: int | None = None
    boutique_id: int | None = None
    ip_address: str | None = Field(default=None, max_length=45)
    user_agent: str | None = Field(default=None, max_length=512)


class ActivityLogRead(LogRead):
    user_id: int | None
    action: str
    module: str | None
    reference_type: ReferenceType | None
    reference_id: int | None
    boutique_id: int | None = None
    ip_address: str | None
    user_agent: str | None
    # Denormalized for the frontend Journal page — never persisted, filled
    # in by the router from a bulk user lookup (same pattern as
    # CreanceService.list_enriched) so it doesn't need its own join per row.
    user_name: str | None = None


# --- Attachments -------------------------------------------------------------
class AttachmentCreate(BaseModel):
    file_url: str = Field(min_length=1, max_length=512)
    file_type: str | None = Field(default=None, max_length=80)
    file_name: str | None = Field(default=None, max_length=255)
    reference_type: ReferenceType | None = None
    reference_id: int | None = None


class AttachmentRead(LogRead):
    reference_type: ReferenceType | None
    reference_id: int | None
    file_url: str
    file_type: str | None
    file_name: str | None
    created_by: int | None
