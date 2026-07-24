"""Tests for StockAlertService.notify_store_adjustment — the Boss who
created a boutique gets emailed whenever its gérant validates a stock
adjustment (physical count) there."""

from app.modules.stock.alert_service import StockAlertService


async def _send_adjustment(db, *, location, product, gerant, before=10, after=16, notes=None):
    await StockAlertService(db).notify_store_adjustment(
        location=location,
        product_id=product.id,
        gerant=gerant,
        quantity_before=before,
        quantity_after=after,
        reason="INVENTORY",
        notes=notes,
    )


async def test_notifies_boss_who_created_the_boutique(
    db, store, store_location, product, user, other_user, monkeypatch
):
    sent: list[dict] = []

    async def _fake_send_email(to, subject, html_body, text_body=None):
        sent.append({"to": to, "subject": subject, "html": html_body})
        return True

    monkeypatch.setattr("app.utils.email.send_email", _fake_send_email)

    store.created_by = other_user.id
    db.add(store)
    await db.commit()

    await _send_adjustment(db, location=store_location, product=product, gerant=user)

    assert len(sent) == 1
    assert sent[0]["to"] == other_user.email
    assert store.name in sent[0]["subject"]
    assert product.name in sent[0]["html"]
    assert "10" in sent[0]["html"] and "16" in sent[0]["html"]


async def test_skips_when_boutique_has_no_creator(
    db, store, store_location, product, user, monkeypatch
):
    sent: list[dict] = []

    async def _fake_send_email(to, subject, html_body, text_body=None):
        sent.append({"to": to})
        return True

    monkeypatch.setattr("app.utils.email.send_email", _fake_send_email)

    assert store.created_by is None
    await _send_adjustment(db, location=store_location, product=product, gerant=user)

    assert sent == []


async def test_skips_self_notification_when_gerant_is_the_creator(
    db, store, store_location, product, user, monkeypatch
):
    sent: list[dict] = []

    async def _fake_send_email(to, subject, html_body, text_body=None):
        sent.append({"to": to})
        return True

    monkeypatch.setattr("app.utils.email.send_email", _fake_send_email)

    store.created_by = user.id
    db.add(store)
    await db.commit()

    await _send_adjustment(db, location=store_location, product=product, gerant=user)

    assert sent == []


async def test_never_raises_when_email_sending_fails(
    db, store, store_location, product, user, other_user, monkeypatch
):
    async def _boom(*args, **kwargs):
        raise RuntimeError("SMTP down")

    monkeypatch.setattr("app.utils.email.send_email", _boom)

    store.created_by = other_user.id
    db.add(store)
    await db.commit()

    # Should not raise despite the underlying send_email exploding.
    await _send_adjustment(db, location=store_location, product=product, gerant=user)


async def test_skips_when_location_has_no_store(db, product, user, other_user, monkeypatch):
    from app.database.enums import StockLocationType
    from app.modules.stock.models import StockLocation

    central = StockLocation(name="Central", type=StockLocationType.CENTRAL, store_id=None)
    db.add(central)
    await db.commit()
    await db.refresh(central)

    sent: list[dict] = []

    async def _fake_send_email(to, subject, html_body, text_body=None):
        sent.append({"to": to})
        return True

    monkeypatch.setattr("app.utils.email.send_email", _fake_send_email)

    await _send_adjustment(db, location=central, product=product, gerant=user)

    assert sent == []
