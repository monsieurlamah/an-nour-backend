"""CreanceService.flag_overdue — the one-time transition to EN_RETARD, run
on a schedule (poetry run check-overdue-creances), plus its notifications
to the boutique's gérant and the Boss who created it."""

from datetime import UTC, datetime, timedelta
from decimal import Decimal

from sqlalchemy import select

from app.database.enums import CreanceStatut, NotificationType
from app.modules.creances.models import Creance
from app.modules.creances.services import CreanceService
from app.modules.notifications.models import Notification


def _past(days: int) -> datetime:
    return (datetime.now(UTC) - timedelta(days=days)).replace(tzinfo=None)


async def test_flags_overdue_creance_and_notifies_gerant_and_boss(
    db, store, client_, user, other_user
):
    store.gerant_id = user.id
    store.created_by = other_user.id
    db.add(store)

    creance = Creance(
        client_id=client_.id, boutique_id=store.id,
        montant_initial=Decimal("100000"), montant_restant=Decimal("60000"),
        date_echeance=_past(3), statut=CreanceStatut.partiellement_payee,
    )
    db.add(creance)
    await db.commit()

    service = CreanceService(db)
    overdue_count, notified = await service.flag_overdue()
    await db.commit()

    assert overdue_count == 1
    assert notified == 2  # gérant + boss
    await db.refresh(creance)
    assert creance.statut == CreanceStatut.en_retard

    notifs = (await db.execute(select(Notification))).scalars().all()
    recipient_ids = {n.user_id for n in notifs}
    assert recipient_ids == {user.id, other_user.id}
    for n in notifs:
        assert n.type == NotificationType.creance
        assert client_.name in n.title
        assert "60 000 GNF" in n.message
        assert n.link == "/app/debts"


async def test_flag_overdue_skips_creance_not_yet_due(db, store, client_, user):
    store.gerant_id = user.id
    db.add(store)
    creance = Creance(
        client_id=client_.id, boutique_id=store.id,
        montant_initial=Decimal("50000"), montant_restant=Decimal("50000"),
        date_echeance=(datetime.now(UTC) + timedelta(days=5)).replace(tzinfo=None),
        statut=CreanceStatut.active,
    )
    db.add(creance)
    await db.commit()

    overdue_count, notified = await CreanceService(db).flag_overdue()
    assert overdue_count == 0
    assert notified == 0


async def test_flag_overdue_skips_creance_already_settled(db, store, client_, user):
    store.gerant_id = user.id
    db.add(store)
    creance = Creance(
        client_id=client_.id, boutique_id=store.id,
        montant_initial=Decimal("50000"), montant_restant=Decimal("0"),
        date_echeance=_past(10), statut=CreanceStatut.soldee,
    )
    db.add(creance)
    await db.commit()

    overdue_count, notified = await CreanceService(db).flag_overdue()
    assert overdue_count == 0
    assert notified == 0


async def test_flag_overdue_is_idempotent_across_runs(db, store, client_, user):
    store.gerant_id = user.id
    db.add(store)
    creance = Creance(
        client_id=client_.id, boutique_id=store.id,
        montant_initial=Decimal("50000"), montant_restant=Decimal("50000"),
        date_echeance=_past(1), statut=CreanceStatut.active,
    )
    db.add(creance)
    await db.commit()

    service = CreanceService(db)
    first_count, first_notified = await service.flag_overdue()
    await db.commit()
    assert first_count == 1
    assert first_notified == 1

    # Second run — the créance is already EN_RETARD, so no re-notification.
    second_count, second_notified = await service.flag_overdue()
    assert second_count == 0
    assert second_notified == 0
