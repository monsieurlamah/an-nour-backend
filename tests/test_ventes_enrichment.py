"""VenteService.list_enriched — denormalized store_name on each row of the
list endpoint, so the Boss can tell which boutique made a sale without a
second lookup per row (mirrors CreanceService's enrichment pattern). Only
the list endpoint enriches; get/create leave store_name unset since the
sale-detail page already resolves the store name itself."""

from decimal import Decimal

from app.modules.ventes.models import Vente
from tests.conftest import assign_group


async def _vente(db, store_id, montant=Decimal("10000")) -> Vente:
    v = Vente(boutique_id=store_id, montant_total=montant)
    db.add(v)
    await db.commit()
    await db.refresh(v)
    return v


async def test_boss_sees_store_name_on_each_vente_across_boutiques(
    client, db, rbac, user, store, store2, login_as
):
    await _vente(db, store.id)
    await _vente(db, store2.id)

    await assign_group(db, user, rbac["fournisseur"])
    login_as(user)

    resp = await client.get("/api/v1/ventes")
    assert resp.status_code == 200
    by_store = {v["boutique_id"]: v["store_name"] for v in resp.json()}
    assert by_store[store.id] == store.name
    assert by_store[store2.id] == store2.name


async def test_boss_can_filter_ventes_by_boutique(client, db, rbac, user, store, store2, login_as):
    v1 = await _vente(db, store.id)
    v2 = await _vente(db, store2.id)

    await assign_group(db, user, rbac["fournisseur"])
    login_as(user)

    resp = await client.get("/api/v1/ventes", params={"boutique_id": store.id})
    assert resp.status_code == 200
    ids = [v["id"] for v in resp.json()]
    assert v1.id in ids
    assert v2.id not in ids
