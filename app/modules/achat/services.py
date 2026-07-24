"""Business logic for the achat module."""

from collections.abc import Sequence
from decimal import Decimal

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.database.enums import PurchaseStatut
from app.modules.achat.models import Purchase, PurchaseLine, Supplier
from app.modules.achat.schemas import PurchaseCreate
from app.modules.common.crud import CRUDService
from app.modules.users.models import User


class SupplierService(CRUDService[Supplier]):
    model = Supplier


class PurchaseService:
    def __init__(self, db: AsyncSession) -> None:
        self.db = db

    async def get(self, purchase_id: int) -> Purchase | None:
        purchase = await self.db.get(Purchase, purchase_id)
        if purchase is None or purchase.deleted_at is not None:
            return None
        return purchase

    async def list(
        self,
        skip: int = 0,
        limit: int = 100,
        supplier_id: int | None = None,
        statut: PurchaseStatut | None = None,
    ) -> Sequence[Purchase]:
        stmt = select(Purchase).where(Purchase.deleted_at.is_(None))
        if supplier_id is not None:
            stmt = stmt.where(Purchase.supplier_id == supplier_id)
        if statut is not None:
            stmt = stmt.where(Purchase.statut == statut)
        stmt = stmt.order_by(Purchase.id.desc()).offset(skip).limit(limit)
        return (await self.db.execute(stmt)).scalars().all()

    async def create(self, payload: PurchaseCreate, user: User) -> Purchase:
        purchase = Purchase(
            supplier_id=payload.supplier_id,
            statut=payload.statut,
            created_by=user.id,
        )
        total = Decimal("0")
        for line in payload.lignes:
            line_total = Decimal(line.quantity) * line.prix_unitaire
            total += line_total
            purchase.lignes.append(
                PurchaseLine(
                    product_id=line.product_id,
                    quantity=line.quantity,
                    prix_unitaire=line.prix_unitaire,
                    total_ligne=line_total,
                )
            )
        purchase.montant_total = total
        self.db.add(purchase)
        await self.db.flush()
        await self.db.refresh(purchase)
        return purchase

    async def update_status(self, purchase: Purchase, statut: PurchaseStatut) -> Purchase:
        purchase.statut = statut
        self.db.add(purchase)
        await self.db.flush()
        await self.db.refresh(purchase)
        return purchase

    async def soft_delete(self, purchase: Purchase) -> None:
        from app.utils.helpers import utcnow

        purchase.deleted_at = utcnow()
        self.db.add(purchase)
        await self.db.flush()
