"""GET /stock/movements — regression test for a bug where the store-scoped
(non-HQ) query path filtered on `StockMovement.deleted_at`, a column that
doesn't exist: StockMovement is a LogEntity (append-only audit log), not a
soft-deletable Entity. A gérant hitting this endpoint got a 500
AttributeError; only the HQ path (which goes through the generic
CRUDService, and correctly skips the filter via a hasattr check) worked."""

from app.database.enums import MovementType
from app.modules.stock.models import StockMovement
from tests.conftest import assign_group, link_store_user


async def _movement(db, product_id, location_id) -> StockMovement:
    m = StockMovement(
        product_id=product_id, to_location_id=location_id,
        movement_type=MovementType.IN, quantity=5,
        quantity_before=0, quantity_after=5,
    )
    db.add(m)
    await db.commit()
    await db.refresh(m)
    return m


async def test_gerant_can_list_store_scoped_movements(
    client, db, rbac, user, store, store_location, product, login_as
):
    await _movement(db, product.id, store_location.id)

    await assign_group(db, user, rbac["gerant-boutique"])
    await link_store_user(db, store, user)
    login_as(user)

    resp = await client.get("/api/v1/stock/movements")
    assert resp.status_code == 200
    assert len(resp.json()) == 1


async def test_boss_can_list_all_movements(
    db, rbac, user, store, store_location, product, login_as, client
):
    await _movement(db, product.id, store_location.id)

    await assign_group(db, user, rbac["fournisseur"])
    login_as(user)

    resp = await client.get("/api/v1/stock/movements")
    assert resp.status_code == 200
    assert len(resp.json()) == 1
