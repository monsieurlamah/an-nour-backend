"""Shared Pydantic base schemas."""

from datetime import datetime

from pydantic import BaseModel, ConfigDict

from app.database.enums import RecordStatus


class ORMModel(BaseModel):
    """Base read model reading attributes directly from ORM objects."""

    model_config = ConfigDict(from_attributes=True)


class EntityRead(ORMModel):
    """Common fields exposed by every ``Entity``-based resource."""

    id: int
    uuid: str
    status: RecordStatus
    created_at: datetime
    updated_at: datetime


class LogRead(ORMModel):
    """Common fields exposed by append-only (``LogEntity``) resources."""

    id: int
    uuid: str
    created_at: datetime
