"""Business logic for the stores module."""

from sqlalchemy import select

from app.modules.common.crud import CRUDService
from app.modules.stores.models import Store, StoreUser
from app.utils.helpers import utcnow


class StoreService(CRUDService[Store]):
    model = Store

    async def sync_gerant_link(
        self,
        store_id: int,
        gerant_id: int | None,
        previous_gerant_id: int | None = None,
    ) -> None:
        """Keep ``stores.gerant_id`` and ``store_users`` consistent.

        The whole RBAC store-scope system (``get_user_store_scope``) and the
        frontend's "my stores" list both read from ``StoreUser`` rows — not
        from ``stores.gerant_id``. Setting a gérant on the boutique form must
        therefore also create the matching ``StoreUser`` row, or that gérant
        ends up assigned on paper but with an empty scope (403 on every
        store-scoped page). A replaced gérant's link is soft-deleted.
        """
        if previous_gerant_id is not None and previous_gerant_id != gerant_id:
            rows = (
                await self.db.execute(
                    select(StoreUser).where(
                        StoreUser.store_id == store_id,
                        StoreUser.user_id == previous_gerant_id,
                        StoreUser.deleted_at.is_(None),
                    )
                )
            ).scalars().all()
            for row in rows:
                row.deleted_at = utcnow()
                self.db.add(row)

        if gerant_id is not None:
            existing = (
                await self.db.execute(
                    select(StoreUser).where(
                        StoreUser.store_id == store_id,
                        StoreUser.user_id == gerant_id,
                    )
                )
            ).scalars().first()
            if existing is None:
                self.db.add(StoreUser(store_id=store_id, user_id=gerant_id))
            elif existing.deleted_at is not None:
                existing.deleted_at = None
                self.db.add(existing)

        await self.db.flush()


class StoreUserService(CRUDService[StoreUser]):
    model = StoreUser
