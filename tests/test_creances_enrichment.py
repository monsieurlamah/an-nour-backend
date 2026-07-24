"""CreanceService.list_enriched/enrich — denormalized client_name/store_name
on every créance, including when the client was since soft-deleted (a real
production scenario found via live testing: the client row still exists with
its name, just deleted_at set, and the frontend's normally-scoped client list
would never surface it)."""

from decimal import Decimal

from app.database.enums import CreanceStatut
from app.modules.creances.models import Creance
from app.modules.creances.services import CreanceService
from app.utils.helpers import utcnow


async def _creance(db, *, client_id, boutique_id, restant=Decimal("50000")):
    c = Creance(
        client_id=client_id, boutique_id=boutique_id,
        montant_initial=restant, montant_restant=restant,
        statut=CreanceStatut.active,
    )
    db.add(c)
    await db.commit()
    await db.refresh(c)
    return c


async def test_list_enriched_resolves_client_and_store_names(db, store, client_):
    await _creance(db, client_id=client_.id, boutique_id=store.id)

    rows = await CreanceService(db).list_enriched()
    assert len(rows) == 1
    assert rows[0]["client_name"] == f"{client_.name} {client_.prenom or ''}".strip()
    assert rows[0]["store_name"] == store.name
    assert rows[0]["client_phone"] == client_.phone


async def test_list_enriched_still_names_a_soft_deleted_client(db, store, client_):
    await _creance(db, client_id=client_.id, boutique_id=store.id)
    client_.deleted_at = utcnow()
    db.add(client_)
    await db.commit()

    # The regular, scope-respecting client list would never return this
    # client anymore — but the créance must still show who owes the debt.
    rows = await CreanceService(db).list_enriched()
    assert rows[0]["client_name"] == f"{client_.name} {client_.prenom or ''}".strip()
    assert rows[0]["client_name"] != f"Client #{client_.id}"


async def test_enrich_single_creance_matches_list_enriched(db, store, client_):
    creance = await _creance(db, client_id=client_.id, boutique_id=store.id)

    single = await CreanceService(db).enrich(creance)
    assert single["client_name"] == f"{client_.name} {client_.prenom or ''}".strip()
    assert single["store_name"] == store.name


async def test_list_enriched_respects_boutique_filter(db, store, store2, client_):
    await _creance(db, client_id=client_.id, boutique_id=store.id)
    await _creance(db, client_id=client_.id, boutique_id=store2.id)

    rows = await CreanceService(db).list_enriched(boutique_id=store.id)
    assert len(rows) == 1
    assert rows[0]["store_name"] == store.name
