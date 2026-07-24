"""HTTP routes for the stock module: locations, product stocks, movements, and operations."""

from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy import or_, select

from app.api.deps import CurrentUser, DbSession
from app.core.authz import StoreScope, UserStoreScope, require_any_permission, require_permission
from app.database.enums import MovementReason, MovementType, StockLocationType
from app.modules.common.store_scope import assert_creatable, in_scope, resolve_list_scope
from app.modules.stock.alert_service import StockAlertService
from app.modules.stock.models import StockLocation, StockMovement
from app.modules.stock.schemas import (
    AddStockRequest,
    AdjustStockRequest,
    ProductStockRead,
    ProductStockUpdate,
    StockLocationCreate,
    StockLocationRead,
    StockLocationUpdate,
    StockMovementRead,
    TransferStockRequest,
    TransferStockResult,
)
from app.modules.stock.services import (
    ProductStockService,
    StockLocationService,
    StockMovementService,
)

router = APIRouter(prefix="/stock", tags=["stock"])

_STOCK_MANAGE = require_any_permission("stock.store.manage", "stock.central.manage")


async def _accessible_location_ids(db, scope: StoreScope) -> list[int] | None:
    """None means unrestricted (HQ). Otherwise the ids of every StockLocation
    belonging to one of the caller's in-scope stores (never includes
    store_id=None central/warehouse locations for a boutique-scoped user)."""
    if scope == "hq":
        return None
    if not scope:
        return [-1]
    rows = await db.execute(
        select(StockLocation.id).where(
            StockLocation.store_id.in_(scope), StockLocation.deleted_at.is_(None)
        )
    )
    ids = rows.scalars().all()
    return list(ids) if ids else [-1]


async def _assert_location_in_scope(db, location_id: int, scope: StoreScope) -> StockLocation:
    loc = await StockLocationService(db).get(location_id)
    if loc is None or not in_scope(loc.store_id, scope):  # type: ignore[attr-defined]
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Location not found")
    return loc  # type: ignore[return-value]


# --- Stock locations ---------------------------------------------------------

@router.get("/locations", response_model=list[StockLocationRead])
async def list_locations(
    db: DbSession,
    _: CurrentUser,
    _perm: Annotated[None, Depends(require_permission("stock.view"))],
    scope: UserStoreScope,
    type: StockLocationType | None = Query(default=None),
    store_id: int | None = Query(default=None),
    skip: int = Query(0, ge=0),
    limit: int = Query(100, ge=1, le=500),
) -> list[StockLocationRead]:
    filters: dict = dict(skip=skip, limit=limit)
    if type is not None:
        filters["type"] = type
    scoped_store_id = resolve_list_scope(store_id, scope)
    if scoped_store_id is not None:
        filters["store_id"] = scoped_store_id
    items = await StockLocationService(db).list(**filters)
    return list(items)  # type: ignore[return-value]


@router.post("/locations", response_model=StockLocationRead, status_code=status.HTTP_201_CREATED)
async def create_location(
    payload: StockLocationCreate,
    db: DbSession,
    user: CurrentUser,
    _perm: Annotated[None, Depends(_STOCK_MANAGE)],
    scope: UserStoreScope,
) -> StockLocationRead:
    assert_creatable(payload.store_id, scope)
    data = payload.model_dump()
    data["created_by"] = user.id
    return await StockLocationService(db).create(data)  # type: ignore[return-value]


@router.get("/locations/{location_id}", response_model=StockLocationRead)
async def get_location(
    location_id: int,
    db: DbSession,
    _: CurrentUser,
    _perm: Annotated[None, Depends(require_permission("stock.view"))],
    scope: UserStoreScope,
) -> StockLocationRead:
    return await _assert_location_in_scope(db, location_id, scope)  # type: ignore[return-value]


@router.patch("/locations/{location_id}", response_model=StockLocationRead)
async def update_location(
    location_id: int,
    payload: StockLocationUpdate,
    db: DbSession,
    _: CurrentUser,
    _perm: Annotated[None, Depends(_STOCK_MANAGE)],
    scope: UserStoreScope,
) -> StockLocationRead:
    loc = await _assert_location_in_scope(db, location_id, scope)
    return await StockLocationService(db).update(loc, payload.model_dump(exclude_unset=True))  # type: ignore[return-value]


# --- Product stocks ------------------------------------------------------------

@router.get("/product-stocks", response_model=list[ProductStockRead])
async def list_product_stocks(
    db: DbSession,
    _: CurrentUser,
    _perm: Annotated[None, Depends(require_permission("stock.view"))],
    scope: UserStoreScope,
    product_id: int | None = Query(default=None),
    location_id: int | None = Query(default=None),
    skip: int = Query(0, ge=0),
    limit: int = Query(200, ge=1, le=1000),
) -> list[ProductStockRead]:
    if location_id is not None:
        await _assert_location_in_scope(db, location_id, scope)
    elif scope != "hq":
        location_id = await _accessible_location_ids(db, scope)  # type: ignore[assignment]
    items = await ProductStockService(db).list(
        skip=skip, limit=limit, product_id=product_id, location_id=location_id
    )
    return list(items)  # type: ignore[return-value]


@router.patch("/product-stocks/{stock_id}", response_model=ProductStockRead)
async def update_product_stock(
    stock_id: int,
    payload: ProductStockUpdate,
    db: DbSession,
    _: CurrentUser,
    _perm: Annotated[None, Depends(_STOCK_MANAGE)],
    scope: UserStoreScope,
) -> ProductStockRead:
    svc = ProductStockService(db)
    stock = await svc.get(stock_id)
    if stock is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Stock entry not found")
    await _assert_location_in_scope(db, stock.location_id, scope)  # type: ignore[attr-defined]
    return await svc.update(stock, payload.model_dump(exclude_unset=True))  # type: ignore[return-value]


# --- Atomic stock operations ---------------------------------------------------

@router.post("/add", response_model=ProductStockRead, status_code=status.HTTP_201_CREATED)
async def add_stock(
    payload: AddStockRequest,
    db: DbSession,
    user: CurrentUser,
    _perm: Annotated[None, Depends(_STOCK_MANAGE)],
    scope: UserStoreScope,
) -> ProductStockRead:
    """Add stock to a location. Creates the ProductStock entry if it doesn't exist yet."""
    await _assert_location_in_scope(db, payload.location_id, scope)
    svc = ProductStockService(db)
    existing = await svc.list(
        product_id=payload.product_id, location_id=payload.location_id, limit=1
    )
    stock = existing[0] if existing else None

    qty_before = stock.quantity if stock else 0
    qty_after = qty_before + payload.quantity

    if stock:
        update: dict = {"quantity": qty_after}
        if payload.alert_threshold != stock.alert_threshold:
            update["alert_threshold"] = payload.alert_threshold
        stock = await svc.update(stock, update)
    else:
        stock = await svc.create({
            "product_id": payload.product_id,
            "location_id": payload.location_id,
            "quantity": qty_after,
            "alert_threshold": payload.alert_threshold,
        })

    total_cost = (payload.unit_cost * payload.quantity) if payload.unit_cost else None
    await StockMovementService(db).create({
        "product_id": payload.product_id,
        "to_location_id": payload.location_id,
        "movement_type": MovementType.IN,
        "reason": payload.reason,
        "quantity": payload.quantity,
        "quantity_before": qty_before,
        "quantity_after": qty_after,
        "unit_cost": payload.unit_cost,
        "total_cost": total_cost,
        "reference": payload.reference,
        "notes": payload.notes,
        "created_by": user.id,
    })

    await StockAlertService(db).check_and_notify(stock)  # type: ignore[arg-type]
    return stock  # type: ignore[return-value]


@router.post("/adjust", response_model=ProductStockRead)
async def adjust_stock(
    payload: AdjustStockRequest,
    db: DbSession,
    user: CurrentUser,
    _perm: Annotated[None, Depends(_STOCK_MANAGE)],
    scope: UserStoreScope,
) -> ProductStockRead:
    """Set a location's stock to a physical count. Creates a movement even when delta is zero."""
    location = await _assert_location_in_scope(db, payload.location_id, scope)
    svc = ProductStockService(db)
    existing = await svc.list(
        product_id=payload.product_id, location_id=payload.location_id, limit=1
    )
    stock = existing[0] if existing else None

    qty_before = stock.quantity if stock else 0
    qty_after = payload.physical_count
    delta = abs(qty_after - qty_before)

    if stock:
        adj_update: dict = {"quantity": qty_after}
        if payload.alert_threshold is not None and payload.alert_threshold != stock.alert_threshold:
            adj_update["alert_threshold"] = payload.alert_threshold
        stock = await svc.update(stock, adj_update)
    else:
        stock = await svc.create({
            "product_id": payload.product_id,
            "location_id": payload.location_id,
            "quantity": qty_after,
            "alert_threshold": (
                payload.alert_threshold if payload.alert_threshold is not None else 0
            ),
        })

    if qty_before != qty_after:
        await StockMovementService(db).create({
            "product_id": payload.product_id,
            "to_location_id": payload.location_id if qty_after > qty_before else None,
            "from_location_id": payload.location_id if qty_after < qty_before else None,
            "movement_type": MovementType.ADJUSTMENT,
            "reason": payload.reason,
            "quantity": delta,
            "quantity_before": qty_before,
            "quantity_after": qty_after,
            "notes": payload.notes,
            "created_by": user.id,
        })

        # A gérant (never HQ) validating a physical count in their own
        # boutique — notify the Boss who created that boutique. Central
        # adjustments (done by HQ itself) don't need to self-notify.
        if location.type == StockLocationType.STORE and scope != "hq":  # type: ignore[attr-defined]
            await StockAlertService(db).notify_store_adjustment(
                location=location,
                product_id=payload.product_id,
                gerant=user,
                quantity_before=qty_before,
                quantity_after=qty_after,
                reason=payload.reason.value,
                notes=payload.notes,
            )

    await StockAlertService(db).check_and_notify(stock)  # type: ignore[arg-type]
    return stock  # type: ignore[return-value]


@router.post("/transfer", response_model=TransferStockResult)
async def transfer_stock(
    payload: TransferStockRequest,
    db: DbSession,
    user: CurrentUser,
    _perm: Annotated[None, Depends(_STOCK_MANAGE)],
    scope: UserStoreScope,
) -> TransferStockResult:
    """Move stock atomically from one location to another. Rejects if source is insufficient.

    Both ends must be in the caller's scope (a store-scoped user may only
    transfer within their own store(s); moving to/from a different store or
    the central warehouse requires HQ scope)."""
    if payload.from_location_id == payload.to_location_id:
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_ENTITY, "Locations must be different")

    await _assert_location_in_scope(db, payload.from_location_id, scope)
    await _assert_location_in_scope(db, payload.to_location_id, scope)

    svc = ProductStockService(db)

    from_list = await svc.list(
        product_id=payload.product_id, location_id=payload.from_location_id, limit=1
    )
    from_stock = from_list[0] if from_list else None

    if not from_stock or from_stock.quantity < payload.quantity:
        available = from_stock.quantity if from_stock else 0
        raise HTTPException(
            status.HTTP_422_UNPROCESSABLE_ENTITY,
            f"Stock insuffisant : disponible={available}, demandé={payload.quantity}",
        )

    to_list = await svc.list(
        product_id=payload.product_id, location_id=payload.to_location_id, limit=1
    )
    to_stock = to_list[0] if to_list else None

    from_qty_before = from_stock.quantity
    to_qty_before = to_stock.quantity if to_stock else 0

    from_stock = await svc.update(from_stock, {"quantity": from_qty_before - payload.quantity})
    if to_stock:
        to_update: dict = {"quantity": to_qty_before + payload.quantity}
        threshold_changed = (
            payload.dest_alert_threshold is not None
            and payload.dest_alert_threshold != to_stock.alert_threshold
        )
        if threshold_changed:
            to_update["alert_threshold"] = payload.dest_alert_threshold
        to_stock = await svc.update(to_stock, to_update)
    else:
        to_stock = await svc.create({
            "product_id": payload.product_id,
            "location_id": payload.to_location_id,
            "quantity": payload.quantity,
            "alert_threshold": (
                payload.dest_alert_threshold if payload.dest_alert_threshold is not None else 0
            ),
        })

    await StockMovementService(db).create({
        "product_id": payload.product_id,
        "from_location_id": payload.from_location_id,
        "to_location_id": payload.to_location_id,
        "movement_type": MovementType.TRANSFER,
        "reason": MovementReason.OTHER,
        "quantity": payload.quantity,
        "quantity_before": from_qty_before,
        "quantity_after": from_qty_before - payload.quantity,
        "notes": payload.notes,
        "created_by": user.id,
    })

    # Check both sides: source may have dropped below threshold after transfer
    await StockAlertService(db).check_and_notify(from_stock)  # type: ignore[arg-type]
    await StockAlertService(db).check_and_notify(to_stock)  # type: ignore[arg-type]
    return TransferStockResult(from_stock=from_stock, to_stock=to_stock)  # type: ignore[arg-type]


# --- Movements (read-only audit log) -------------------------------------------

@router.get("/movements", response_model=list[StockMovementRead])
async def list_movements(
    db: DbSession,
    _: CurrentUser,
    _perm: Annotated[None, Depends(require_permission("stock.view"))],
    scope: UserStoreScope,
    product_id: int | None = Query(default=None),
    movement_type: MovementType | None = Query(default=None),
    skip: int = Query(0, ge=0),
    limit: int = Query(100, ge=1, le=1000),
) -> list[StockMovementRead]:
    if scope == "hq":
        items = await StockMovementService(db).list(
            skip=skip, limit=limit, order_desc=True,
            product_id=product_id, movement_type=movement_type,
        )
        return list(items)  # type: ignore[return-value]

    # No generic IN-on-either-of-two-columns filter exists on CRUDService,
    # so a movement touching an in-scope location (as source OR destination)
    # is queried directly here rather than growing the generic filter API
    # for one caller.
    location_ids = await _accessible_location_ids(db, scope)
    stmt = (
        select(StockMovement)
        .where(
            or_(
                StockMovement.from_location_id.in_(location_ids),
                StockMovement.to_location_id.in_(location_ids),
            ),
        )
        .order_by(StockMovement.id.desc())
        .offset(skip)
        .limit(limit)
    )
    if product_id is not None:
        stmt = stmt.where(StockMovement.product_id == product_id)
    if movement_type is not None:
        stmt = stmt.where(StockMovement.movement_type == movement_type)
    result = await db.execute(stmt)
    return list(result.scalars().all())  # type: ignore[return-value]
