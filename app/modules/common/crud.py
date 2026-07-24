"""Generic async CRUD service reused by the domain modules.

Subclass it and set ``model`` to get list/get/create/update/delete for free,
with automatic soft-delete handling when the model exposes ``deleted_at``.
"""

from collections.abc import Sequence
from typing import Any, Generic, TypeVar

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.utils.helpers import generate_reference, slugify

ModelT = TypeVar("ModelT")


class CRUDService(Generic[ModelT]):
    model: type[ModelT]

    def __init__(self, db: AsyncSession) -> None:
        self.db = db

    @property
    def _soft_delete(self) -> bool:
        return hasattr(self.model, "deleted_at")

    async def get(self, obj_id: int) -> ModelT | None:
        obj = await self.db.get(self.model, obj_id)
        if obj is None:
            return None
        if self._soft_delete and obj.deleted_at is not None:
            return None
        return obj

    async def list(
        self,
        skip: int = 0,
        limit: int = 100,
        order_desc: bool = False,
        **filters: Any,
    ) -> Sequence[ModelT]:
        stmt = select(self.model)
        if self._soft_delete:
            stmt = stmt.where(self.model.deleted_at.is_(None))
        for field, value in filters.items():
            if value is None or not hasattr(self.model, field):
                continue
            col = getattr(self.model, field)
            # A list/set/frozenset filter means "any of these" (used for
            # store-scope enforcement — a user linked to several stores);
            # every existing caller passes a scalar, so behavior for them
            # is unchanged.
            if isinstance(value, (list, set, frozenset)):
                stmt = stmt.where(col.in_(value))
            else:
                stmt = stmt.where(col == value)
        order_col = self.model.id
        stmt = stmt.order_by(order_col.desc() if order_desc else order_col)
        result = await self.db.execute(stmt.offset(skip).limit(limit))
        return result.scalars().all()

    async def create(self, data: dict[str, Any]) -> ModelT:
        obj = self.model(**data)
        self.db.add(obj)
        await self.db.flush()
        await self.db.refresh(obj)
        return obj

    async def update(self, obj: ModelT, data: dict[str, Any]) -> ModelT:
        for field, value in data.items():
            setattr(obj, field, value)
        self.db.add(obj)
        await self.db.flush()
        await self.db.refresh(obj)
        return obj

    async def delete(self, obj: ModelT) -> None:
        if self._soft_delete:
            from app.utils.helpers import utcnow

            obj.deleted_at = utcnow()
            self.db.add(obj)
            await self.db.flush()
        else:
            await self.db.delete(obj)
            await self.db.flush()

    async def unique_slug(self, name: str) -> str:
        """Return a slug for ``name`` that is unique on ``model.slug``."""
        base = slugify(name)
        candidate = base
        while True:
            existing = await self.db.execute(
                select(self.model).where(self.model.slug == candidate)
            )
            if existing.scalar_one_or_none() is None:
                return candidate
            candidate = f"{base}-{generate_reference('', 4).strip('-').lower()}"
