"""Business logic for the stock module."""

from fastapi import HTTPException, status
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.logging import get_logger
from app.database.enums import MovementReason, MovementType, StockLocationType
from app.modules.common.crud import CRUDService
from app.modules.stock.alert_service import StockAlertService
from app.modules.stock.models import ProductStock, StockLocation, StockMovement

logger = get_logger("stock")


class StockLocationService(CRUDService[StockLocation]):
    model = StockLocation


class ProductStockService(CRUDService[ProductStock]):
    model = ProductStock


class StockMovementService(CRUDService[StockMovement]):
    model = StockMovement


class StockSaleService:
    """Atomic stock consumption for the sales (ventes) workflow.

    Built on top of ``ProductStockService`` / ``StockMovementService`` /
    ``StockAlertService`` — the same primitives used by the manual
    add/adjust/transfer endpoints in ``stock/router.py`` — rather than
    re-implementing quantity bookkeeping from scratch.
    """

    def __init__(self, db: AsyncSession) -> None:
        self.db = db
        self.stocks = ProductStockService(db)
        self.movements = StockMovementService(db)
        self.alerts = StockAlertService(db)

    async def get_central_location(self) -> StockLocation:
        """Resolve the CENTRAL stock location. Uniqueness of a single CENTRAL
        row isn't enforced at the DB level (see StockLocation), so this picks
        the oldest non-deleted one deterministically and logs a warning if
        more than one exists rather than failing outright."""
        result = await self.db.execute(
            select(StockLocation)
            .where(
                StockLocation.type == StockLocationType.CENTRAL,
                StockLocation.deleted_at.is_(None),
            )
            .order_by(StockLocation.id)
        )
        locations = result.scalars().all()
        if not locations:
            raise HTTPException(
                status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
                detail=(
                    "Aucun emplacement de stock central configuré — "
                    "impossible de réceptionner tant qu'un emplacement de type CENTRAL "
                    "n'est pas créé."
                ),
            )
        if len(locations) > 1:
            logger.warning(
                "stock.central_location.ambiguous count=%d using_id=%d",
                len(locations), locations[0].id,
            )
        return locations[0]

    async def get_store_location(self, store_id: int) -> StockLocation:
        """Resolve the single STORE-type stock location for a boutique."""
        result = await self.db.execute(
            select(StockLocation).where(
                StockLocation.store_id == store_id,
                StockLocation.type == StockLocationType.STORE,
                StockLocation.deleted_at.is_(None),
            )
        )
        location = result.scalars().first()
        if location is None:
            raise HTTPException(
                status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
                detail=(
                    f"Aucun emplacement de stock configuré pour la boutique #{store_id} — "
                    "impossible de vendre tant qu'un emplacement de type STORE n'est pas créé."
                ),
            )
        return location

    async def check_available(
        self, product_id: int, location_id: int, quantity: int
    ) -> ProductStock:
        """Raise 422 if the location doesn't hold enough of the product."""
        existing = await self.stocks.list(product_id=product_id, location_id=location_id, limit=1)
        stock = existing[0] if existing else None
        available = stock.quantity if stock else 0
        if available < quantity:
            raise HTTPException(
                status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
                detail=(
                    f"Stock insuffisant pour le produit #{product_id} : "
                    f"disponible={available}, demandé={quantity}"
                ),
            )
        return stock  # type: ignore[return-value]

    async def consume(
        self,
        *,
        product_id: int,
        location_id: int,
        quantity: int,
        reference: str | None,
        created_by: int | None,
    ) -> StockMovement:
        """Decrement stock and log a SALE/OUT movement. Caller must have already
        validated sufficient availability via ``check_available`` (re-checked
        here defensively against the same in-transaction row)."""
        stock = await self.check_available(product_id, location_id, quantity)
        qty_before = stock.quantity
        qty_after = qty_before - quantity
        if qty_after < 0:
            # Defensive — should be unreachable given check_available above.
            raise HTTPException(
                status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
                detail=f"Stock insuffisant pour le produit #{product_id}.",
            )

        stock = await self.stocks.update(stock, {"quantity": qty_after})

        movement = await self.movements.create({
            "product_id": product_id,
            "from_location_id": location_id,
            "movement_type": MovementType.OUT,
            "reason": MovementReason.SALE,
            "quantity": quantity,
            "quantity_before": qty_before,
            "quantity_after": qty_after,
            "reference": reference,
            "created_by": created_by,
        })

        # Best-effort: never raises, logs internally on failure.
        await self.alerts.check_and_notify(stock)
        return movement

    async def restore(
        self,
        *,
        product_id: int,
        location_id: int,
        quantity: int,
        reference: str | None,
        created_by: int | None,
    ) -> StockMovement:
        """Re-integrate returned goods: increment stock and log an IN/RETURN
        movement. Mirrors ``consume`` exactly in reverse direction."""
        existing = await self.stocks.list(product_id=product_id, location_id=location_id, limit=1)
        if existing:
            stock = existing[0]
            qty_before = stock.quantity
            qty_after = qty_before + quantity
            stock = await self.stocks.update(stock, {"quantity": qty_after})
        else:
            # Edge case: the product was never stocked here — create the row.
            stock = await self.stocks.create({
                "product_id": product_id,
                "location_id": location_id,
                "quantity": quantity,
                "alert_threshold": 0,
            })
            qty_before = 0
            qty_after = quantity

        movement = await self.movements.create({
            "product_id": product_id,
            "to_location_id": location_id,
            "movement_type": MovementType.IN,
            "reason": MovementReason.RETURN,
            "quantity": quantity,
            "quantity_before": qty_before,
            "quantity_after": qty_after,
            "reference": reference,
            "created_by": created_by,
        })
        return movement

    async def receive_transfer(
        self,
        *,
        product_id: int,
        central_location_id: int,
        store_location_id: int,
        quantity: int,
        reference: str | None,
        created_by: int | None,
    ) -> tuple[StockMovement, StockMovement]:
        """Atomically move ``quantity`` units of ``product_id`` from the
        central warehouse to a boutique's own location — the ONLY place
        stock actually changes for the internal réappro workflow, called
        exclusively from ``CommandeService.confirm_reception`` once the
        boutique has confirmed receipt of (all or part of) a delivery.

        Locks both ``ProductStock`` rows for the duration of the update
        (``SELECT ... FOR UPDATE``) — the one place in this codebase that
        needs it, since two boutiques can plausibly confirm receipt of the
        same product from the same central stock at the same moment.
        """
        if quantity <= 0:
            raise HTTPException(
                status.HTTP_422_UNPROCESSABLE_ENTITY, "La quantité reçue doit être positive."
            )

        central_result = await self.db.execute(
            select(ProductStock)
            .where(
                ProductStock.product_id == product_id,
                ProductStock.location_id == central_location_id,
            )
            .with_for_update()
        )
        central_stock = central_result.scalars().first()
        central_available = central_stock.quantity if central_stock else 0
        if central_available < quantity:
            raise HTTPException(
                status.HTTP_422_UNPROCESSABLE_ENTITY,
                f"Stock central insuffisant pour le produit #{product_id} : "
                f"disponible={central_available}, requis={quantity}",
            )

        store_result = await self.db.execute(
            select(ProductStock)
            .where(
                ProductStock.product_id == product_id,
                ProductStock.location_id == store_location_id,
            )
            .with_for_update()
        )
        store_stock = store_result.scalars().first()

        central_qty_before = central_stock.quantity  # type: ignore[union-attr]
        central_qty_after = central_qty_before - quantity
        central_stock = await self.stocks.update(central_stock, {"quantity": central_qty_after})  # type: ignore[arg-type]

        if store_stock:
            store_qty_before = store_stock.quantity
            store_qty_after = store_qty_before + quantity
            store_stock = await self.stocks.update(store_stock, {"quantity": store_qty_after})
        else:
            store_qty_before = 0
            store_qty_after = quantity
            store_stock = await self.stocks.create({
                "product_id": product_id,
                "location_id": store_location_id,
                "quantity": quantity,
                "alert_threshold": 0,
            })

        out_movement = await self.movements.create({
            "product_id": product_id,
            "from_location_id": central_location_id,
            "movement_type": MovementType.OUT,
            "reason": MovementReason.REAPPRO,
            "quantity": quantity,
            "quantity_before": central_qty_before,
            "quantity_after": central_qty_after,
            "reference": reference,
            "created_by": created_by,
        })
        in_movement = await self.movements.create({
            "product_id": product_id,
            "to_location_id": store_location_id,
            "movement_type": MovementType.IN,
            "reason": MovementReason.REAPPRO,
            "quantity": quantity,
            "quantity_before": store_qty_before,
            "quantity_after": store_qty_after,
            "reference": reference,
            "created_by": created_by,
        })

        # Best-effort: never raises, logs internally on failure.
        await self.alerts.check_and_notify(central_stock)
        await self.alerts.check_and_notify(store_stock)
        return out_movement, in_movement
