"""HTTP routes for the achat module: suppliers and purchases.

Central/HQ procurement — no store dimension on this module at all, only
permission checks apply.
"""

from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, Query, status

from app.api.deps import CurrentUser, DbSession
from app.core.authz import require_permission
from app.database.enums import PurchaseStatut
from app.modules.achat.schemas import (
    PurchaseCreate,
    PurchaseRead,
    PurchaseStatusUpdate,
    SupplierCreate,
    SupplierRead,
    SupplierUpdate,
)
from app.modules.achat.services import PurchaseService, SupplierService

router = APIRouter(prefix="/achats", tags=["achats"])


# --- Suppliers ---------------------------------------------------------------
@router.get("/suppliers", response_model=list[SupplierRead])
async def list_suppliers(
    db: DbSession,
    _: CurrentUser,
    _perm: Annotated[None, Depends(require_permission("suppliers.view"))],
    skip: int = Query(0, ge=0),
    limit: int = Query(100, ge=1, le=500),
) -> list[SupplierRead]:
    return list(await SupplierService(db).list(skip=skip, limit=limit))  # type: ignore[return-value]


@router.post("/suppliers", response_model=SupplierRead, status_code=status.HTTP_201_CREATED)
async def create_supplier(
    payload: SupplierCreate,
    db: DbSession,
    _: CurrentUser,
    _perm: Annotated[None, Depends(require_permission("suppliers.manage"))],
) -> SupplierRead:
    data = payload.model_dump()
    if data.get("email") is not None:
        data["email"] = str(data["email"])
    return await SupplierService(db).create(data)  # type: ignore[return-value]


@router.get("/suppliers/{supplier_id}", response_model=SupplierRead)
async def get_supplier(
    supplier_id: int,
    db: DbSession,
    _: CurrentUser,
    _perm: Annotated[None, Depends(require_permission("suppliers.view"))],
) -> SupplierRead:
    supplier = await SupplierService(db).get(supplier_id)
    if supplier is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Supplier not found")
    return supplier  # type: ignore[return-value]


@router.patch("/suppliers/{supplier_id}", response_model=SupplierRead)
async def update_supplier(
    supplier_id: int,
    payload: SupplierUpdate,
    db: DbSession,
    _: CurrentUser,
    _perm: Annotated[None, Depends(require_permission("suppliers.manage"))],
) -> SupplierRead:
    service = SupplierService(db)
    supplier = await service.get(supplier_id)
    if supplier is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Supplier not found")
    data = payload.model_dump(exclude_unset=True)
    if data.get("email") is not None:
        data["email"] = str(data["email"])
    return await service.update(supplier, data)  # type: ignore[return-value]


@router.delete("/suppliers/{supplier_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_supplier(
    supplier_id: int,
    db: DbSession,
    _: CurrentUser,
    _perm: Annotated[None, Depends(require_permission("suppliers.manage"))],
) -> None:
    service = SupplierService(db)
    supplier = await service.get(supplier_id)
    if supplier is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Supplier not found")
    await service.delete(supplier)


# --- Purchases -----------------------------------------------------------------
@router.get("", response_model=list[PurchaseRead])
async def list_purchases(
    db: DbSession,
    _: CurrentUser,
    _perm: Annotated[None, Depends(require_permission("purchases.view"))],
    supplier_id: int | None = Query(default=None),
    statut: PurchaseStatut | None = Query(default=None),
    skip: int = Query(0, ge=0),
    limit: int = Query(100, ge=1, le=500),
) -> list[PurchaseRead]:
    items = await PurchaseService(db).list(
        skip=skip, limit=limit, supplier_id=supplier_id, statut=statut
    )
    return list(items)  # type: ignore[return-value]


@router.post("", response_model=PurchaseRead, status_code=status.HTTP_201_CREATED)
async def create_purchase(
    payload: PurchaseCreate,
    db: DbSession,
    user: CurrentUser,
    _perm: Annotated[None, Depends(require_permission("purchases.manage"))],
) -> PurchaseRead:
    return await PurchaseService(db).create(payload, user)  # type: ignore[return-value]


@router.get("/{purchase_id}", response_model=PurchaseRead)
async def get_purchase(
    purchase_id: int,
    db: DbSession,
    _: CurrentUser,
    _perm: Annotated[None, Depends(require_permission("purchases.view"))],
) -> PurchaseRead:
    purchase = await PurchaseService(db).get(purchase_id)
    if purchase is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Purchase not found")
    return purchase  # type: ignore[return-value]


@router.patch("/{purchase_id}/status", response_model=PurchaseRead)
async def update_purchase_status(
    purchase_id: int,
    payload: PurchaseStatusUpdate,
    db: DbSession,
    _: CurrentUser,
    _perm: Annotated[None, Depends(require_permission("purchases.manage"))],
) -> PurchaseRead:
    service = PurchaseService(db)
    purchase = await service.get(purchase_id)
    if purchase is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Purchase not found")
    return await service.update_status(purchase, payload.statut)  # type: ignore[return-value]


@router.delete("/{purchase_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_purchase(
    purchase_id: int,
    db: DbSession,
    _: CurrentUser,
    _perm: Annotated[None, Depends(require_permission("purchases.manage"))],
) -> None:
    service = PurchaseService(db)
    purchase = await service.get(purchase_id)
    if purchase is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Purchase not found")
    await service.soft_delete(purchase)
