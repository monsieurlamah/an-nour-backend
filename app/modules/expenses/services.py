"""Business logic for the expenses module."""

from collections.abc import Sequence
from datetime import date, datetime, timedelta

from sqlalchemy import Select, func, select

from app.modules.common.crud import CRUDService
from app.modules.expenses.models import Expense, ExpenseCategory
from app.modules.stores.models import Store


def _apply_filters(
    stmt: Select,
    store_id: int | list[int] | None,
    category_id: int | None,
    date_from: date | None,
    date_to: date | None,
) -> Select:
    """Shared WHERE-building for list_filtered/count_filtered — a plain
    equality filter can't express "between", so date range bypasses the
    generic CRUDService.list() filter loop entirely."""
    if store_id is not None:
        stmt = (
            stmt.where(Expense.store_id.in_(store_id))
            if isinstance(store_id, (list, set, frozenset))
            else stmt.where(Expense.store_id == store_id)
        )
    if category_id is not None:
        stmt = stmt.where(Expense.category_id == category_id)
    if date_from is not None:
        start = datetime(date_from.year, date_from.month, date_from.day)
        stmt = stmt.where(Expense.created_at >= start)
    if date_to is not None:
        end = datetime(date_to.year, date_to.month, date_to.day) + timedelta(days=1)
        stmt = stmt.where(Expense.created_at < end)
    return stmt


class ExpenseCategoryService(CRUDService[ExpenseCategory]):
    model = ExpenseCategory


class ExpenseService(CRUDService[Expense]):
    model = Expense

    _READ_FIELDS = (
        "id", "uuid", "status", "created_at", "updated_at",
        "store_id", "category_id", "category_label", "montant",
        "description", "payment_mode", "receipt_url", "created_by",
    )

    @staticmethod
    def _to_dict(expense: Expense, store: Store | None) -> dict:
        return {
            **{k: getattr(expense, k) for k in ExpenseService._READ_FIELDS},
            "store_name": store.name if store else (
                f"Boutique #{expense.store_id}" if expense.store_id is not None else None
            ),
        }

    async def enrich(self, expense: Expense) -> dict:
        """Attach store_name for a single expense — bypasses the soft-delete
        filter on the store lookup, same rationale as CreanceService.enrich:
        an expense must still show which boutique spent it even if that
        boutique was later deleted."""
        store = await self.db.get(Store, expense.store_id) if expense.store_id is not None else None
        return self._to_dict(expense, store)

    async def list_filtered_enriched(
        self,
        skip: int = 0,
        limit: int = 100,
        store_id: int | list[int] | None = None,
        category_id: int | None = None,
        date_from: date | None = None,
        date_to: date | None = None,
    ) -> list[dict]:
        expenses = await self.list_filtered(
            skip=skip, limit=limit, store_id=store_id,
            category_id=category_id, date_from=date_from, date_to=date_to,
        )
        ids = {e.store_id for e in expenses if e.store_id is not None}
        stores: dict[int, Store] = {}
        if ids:
            result = await self.db.execute(select(Store).where(Store.id.in_(ids)))
            stores = {s.id: s for s in result.scalars().all()}
        return [
            self._to_dict(e, stores.get(e.store_id) if e.store_id is not None else None)
            for e in expenses
        ]

    async def list_filtered(
        self,
        skip: int = 0,
        limit: int = 100,
        store_id: int | list[int] | None = None,
        category_id: int | None = None,
        date_from: date | None = None,
        date_to: date | None = None,
    ) -> Sequence[Expense]:
        stmt = _apply_filters(
            select(Expense).where(Expense.deleted_at.is_(None)),
            store_id, category_id, date_from, date_to,
        )
        stmt = stmt.order_by(Expense.id.desc()).offset(skip).limit(limit)
        return (await self.db.execute(stmt)).scalars().all()

    async def count_filtered(
        self,
        store_id: int | list[int] | None = None,
        category_id: int | None = None,
        date_from: date | None = None,
        date_to: date | None = None,
    ) -> int:
        stmt = _apply_filters(
            select(func.count()).select_from(Expense).where(Expense.deleted_at.is_(None)),
            store_id, category_id, date_from, date_to,
        )
        return (await self.db.execute(stmt)).scalar_one()
