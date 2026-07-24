"""HTTP routes for the expenses module: categories and expenses."""

from datetime import date
from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, Query, status

from app.api.deps import CurrentUser, DbSession
from app.core.authz import UserStoreScope, require_permission
from app.modules.common.store_scope import (
    assert_creatable,
    in_scope,
    resolve_create_store_id,
    resolve_list_scope,
)
from app.modules.expenses.schemas import (
    ExpenseCategoryCreate,
    ExpenseCategoryRead,
    ExpenseCategoryUpdate,
    ExpenseCreate,
    ExpenseRead,
    ExpenseUpdate,
)
from app.modules.expenses.services import ExpenseCategoryService, ExpenseService

router = APIRouter(prefix="/expenses", tags=["expenses"])


# --- Categories (shared taxonomy, no store dimension — HQ only) --------------
# Deliberately gated by "expenses.categories.manage", NOT "expenses.manage":
# the latter is what lets a gérant record their own boutique's expenses, and
# must never also grant edit rights over the network-wide category taxonomy.
@router.get("/categories", response_model=list[ExpenseCategoryRead])
async def list_expense_categories(
    db: DbSession,
    _: CurrentUser,
    _perm: Annotated[None, Depends(require_permission("expenses.view"))],
    skip: int = Query(0, ge=0),
    limit: int = Query(100, ge=1, le=500),
) -> list[ExpenseCategoryRead]:
    return list(await ExpenseCategoryService(db).list(skip=skip, limit=limit))  # type: ignore[return-value]


@router.post(
    "/categories",
    response_model=ExpenseCategoryRead,
    status_code=status.HTTP_201_CREATED,
)
async def create_expense_category(
    payload: ExpenseCategoryCreate,
    db: DbSession,
    _: CurrentUser,
    _perm: Annotated[None, Depends(require_permission("expenses.categories.manage"))],
) -> ExpenseCategoryRead:
    service = ExpenseCategoryService(db)
    data = payload.model_dump()
    data["slug"] = payload.slug or await service.unique_slug(payload.name)
    return await service.create(data)  # type: ignore[return-value]


@router.patch("/categories/{category_id}", response_model=ExpenseCategoryRead)
async def update_expense_category(
    category_id: int,
    payload: ExpenseCategoryUpdate,
    db: DbSession,
    _: CurrentUser,
    _perm: Annotated[None, Depends(require_permission("expenses.categories.manage"))],
) -> ExpenseCategoryRead:
    service = ExpenseCategoryService(db)
    category = await service.get(category_id)
    if category is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Category not found")
    return await service.update(category, payload.model_dump(exclude_unset=True))  # type: ignore[return-value]


@router.delete("/categories/{category_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_expense_category(
    category_id: int,
    db: DbSession,
    _: CurrentUser,
    _perm: Annotated[None, Depends(require_permission("expenses.categories.manage"))],
) -> None:
    service = ExpenseCategoryService(db)
    category = await service.get(category_id)
    if category is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Category not found")
    await service.delete(category)


# --- Expenses ------------------------------------------------------------------
@router.get("", response_model=list[ExpenseRead])
async def list_expenses(
    db: DbSession,
    _: CurrentUser,
    _perm: Annotated[None, Depends(require_permission("expenses.view"))],
    scope: UserStoreScope,
    store_id: int | None = Query(default=None),
    category_id: int | None = Query(default=None),
    date_from: date | None = Query(default=None),
    date_to: date | None = Query(default=None),
    skip: int = Query(0, ge=0),
    limit: int = Query(100, ge=1, le=500),
) -> list[ExpenseRead]:
    return await ExpenseService(db).list_filtered_enriched(  # type: ignore[return-value]
        skip=skip, limit=limit,
        store_id=resolve_list_scope(store_id, scope), category_id=category_id,
        date_from=date_from, date_to=date_to,
    )


@router.get("/count")
async def count_expenses(
    db: DbSession,
    _: CurrentUser,
    _perm: Annotated[None, Depends(require_permission("expenses.view"))],
    scope: UserStoreScope,
    store_id: int | None = Query(default=None),
    category_id: int | None = Query(default=None),
    date_from: date | None = Query(default=None),
    date_to: date | None = Query(default=None),
) -> dict[str, int]:
    total = await ExpenseService(db).count_filtered(
        store_id=resolve_list_scope(store_id, scope), category_id=category_id,
        date_from=date_from, date_to=date_to,
    )
    return {"total": total}


@router.post("", response_model=ExpenseRead, status_code=status.HTTP_201_CREATED)
async def create_expense(
    payload: ExpenseCreate,
    db: DbSession,
    user: CurrentUser,
    _perm: Annotated[None, Depends(require_permission("expenses.manage"))],
    scope: UserStoreScope,
) -> ExpenseRead:
    store_id = resolve_create_store_id(payload.store_id, scope)
    assert_creatable(store_id, scope)
    data = payload.model_dump()
    data["store_id"] = store_id
    data["created_by"] = user.id
    service = ExpenseService(db)
    expense = await service.create(data)
    return await service.enrich(expense)  # type: ignore[return-value]


@router.get("/{expense_id}", response_model=ExpenseRead)
async def get_expense(
    expense_id: int,
    db: DbSession,
    _: CurrentUser,
    _perm: Annotated[None, Depends(require_permission("expenses.view"))],
    scope: UserStoreScope,
) -> ExpenseRead:
    service = ExpenseService(db)
    expense = await service.get(expense_id)
    if expense is None or not in_scope(expense.store_id, scope):  # type: ignore[attr-defined]
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Expense not found")
    return await service.enrich(expense)  # type: ignore[return-value]


@router.patch("/{expense_id}", response_model=ExpenseRead)
async def update_expense(
    expense_id: int,
    payload: ExpenseUpdate,
    db: DbSession,
    _: CurrentUser,
    _perm: Annotated[None, Depends(require_permission("expenses.manage"))],
    scope: UserStoreScope,
) -> ExpenseRead:
    service = ExpenseService(db)
    expense = await service.get(expense_id)
    if expense is None or not in_scope(expense.store_id, scope):  # type: ignore[attr-defined]
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Expense not found")
    updated = await service.update(expense, payload.model_dump(exclude_unset=True))
    return await service.enrich(updated)  # type: ignore[return-value]


@router.delete("/{expense_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_expense(
    expense_id: int,
    db: DbSession,
    _: CurrentUser,
    _perm: Annotated[None, Depends(require_permission("expenses.manage"))],
    scope: UserStoreScope,
) -> None:
    service = ExpenseService(db)
    expense = await service.get(expense_id)
    if expense is None or not in_scope(expense.store_id, scope):  # type: ignore[attr-defined]
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Expense not found")
    await service.delete(expense)
