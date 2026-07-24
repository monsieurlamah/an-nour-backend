"""StockAlertService.check_and_notify also creates in-app Notification rows
(one per recipient), alongside the pre-existing email alert — for the Boss
who created the boutique and its gérant."""

from sqlalchemy import select

from app.database.enums import NotificationType
from app.modules.notifications.models import Notification
from app.modules.stock.alert_service import StockAlertService
from app.modules.stock.models import ProductStock


async def _low_stock(db, *, product, location, quantity=5, threshold=10):
    ps = ProductStock(
        product_id=product.id, location_id=location.id,
        quantity=quantity, alert_threshold=threshold,
    )
    db.add(ps)
    await db.commit()
    await db.refresh(ps)
    return ps


async def test_low_stock_notifies_gerant_and_boss(
    db, store, store_location, product, user, other_user, rbac, monkeypatch
):
    async def _fake_send_email(*args, **kwargs):
        return True
    monkeypatch.setattr("app.modules.stock.alert_service.send_email", _fake_send_email)

    # user = gérant of the store; other_user = super-admin (the "Boss").
    store.gerant_id = user.id
    db.add(store)
    from tests.conftest import assign_group
    await assign_group(db, other_user, rbac["super-admin"])
    await db.commit()

    stock = await _low_stock(db, product=product, location=store_location)
    await StockAlertService(db).check_and_notify(stock)
    await db.commit()

    notifs = (await db.execute(select(Notification))).scalars().all()
    recipient_ids = {n.user_id for n in notifs}
    assert user.id in recipient_ids
    assert other_user.id in recipient_ids
    for n in notifs:
        assert n.type == NotificationType.stock
        assert product.name in n.title
        assert n.link == "/app/inventory/boutiques"


async def test_low_stock_notification_links_to_central_for_central_location(
    db, product, other_user, rbac, monkeypatch
):
    from app.database.enums import StockLocationType
    from app.modules.stock.models import StockLocation
    from tests.conftest import assign_group

    async def _fake_send_email(*args, **kwargs):
        return True
    monkeypatch.setattr("app.modules.stock.alert_service.send_email", _fake_send_email)

    await assign_group(db, other_user, rbac["super-admin"])
    central = StockLocation(name="Central", type=StockLocationType.CENTRAL, store_id=None)
    db.add(central)
    await db.commit()
    await db.refresh(central)

    stock = await _low_stock(db, product=product, location=central)
    await StockAlertService(db).check_and_notify(stock)
    await db.commit()

    notifs = (await db.execute(select(Notification))).scalars().all()
    assert len(notifs) == 1
    assert notifs[0].link == "/app/inventory/central"


async def test_check_and_notify_never_raises_when_notification_creation_fails(
    db, store, store_location, product, user, other_user, rbac, monkeypatch
):
    from tests.conftest import assign_group

    async def _fake_send_email(*args, **kwargs):
        return True
    monkeypatch.setattr("app.modules.stock.alert_service.send_email", _fake_send_email)

    async def _boom(*args, **kwargs):
        raise RuntimeError("DB down")
    monkeypatch.setattr(
        "app.modules.notifications.services.NotificationService.create", _boom
    )

    store.gerant_id = user.id
    db.add(store)
    await assign_group(db, other_user, rbac["super-admin"])
    await db.commit()

    stock = await _low_stock(db, product=product, location=store_location)
    # Should not raise despite every notification creation failing.
    await StockAlertService(db).check_and_notify(stock)
