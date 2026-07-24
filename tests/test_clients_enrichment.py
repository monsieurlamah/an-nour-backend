"""ClientService.list_enriched/enrich — denormalized store_name on each
client, so the Boss can tell which boutique a client belongs to without a
second lookup per row (mirrors CreanceService's enrichment pattern)."""

from app.modules.clients.models import Client
from tests.conftest import assign_group


async def test_boss_sees_store_name_on_each_client_across_boutiques(
    client, db, rbac, user, store, store2, login_as
):
    db.add_all([
        Client(code_client="CLI-100001", name="Diallo", phone="+224600000010", store_id=store.id),
        Client(code_client="CLI-100002", name="Barry", phone="+224600000020", store_id=store2.id),
    ])
    await db.commit()

    await assign_group(db, user, rbac["fournisseur"])
    login_as(user)

    resp = await client.get("/api/v1/clients")
    assert resp.status_code == 200
    by_store = {c["store_id"]: c["store_name"] for c in resp.json()}
    assert by_store[store.id] == store.name
    assert by_store[store2.id] == store2.name


async def test_client_store_name_present_on_create_response(
    client, db, rbac, user, store, login_as
):
    await assign_group(db, user, rbac["gerant-boutique"])
    from tests.conftest import link_store_user
    await link_store_user(db, store, user)
    login_as(user)

    resp = await client.post(
        "/api/v1/clients",
        json={"name": "Nouveau client", "phone": "+224600000099"},
    )
    assert resp.status_code == 201
    assert resp.json()["store_name"] == store.name


async def test_client_without_store_has_no_store_name(client, db, rbac, user, login_as):
    c = Client(code_client="CLI-100003", name="Sans boutique", phone="+224600000030")
    db.add(c)
    await db.commit()

    await assign_group(db, user, rbac["fournisseur"])
    login_as(user)

    resp = await client.get("/api/v1/clients")
    assert resp.status_code == 200
    row = next(r for r in resp.json() if r["id"] == c.id)
    assert row["store_name"] is None
