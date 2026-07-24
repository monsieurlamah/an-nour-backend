"""HTTP-level authorization tests: RBAC enforcement + multi-store isolation.

Unlike the other test files (which call service classes directly), these
drive requests through the real FastAPI app + dependency graph via the
`client`/`login_as`/`rbac` fixtures (see conftest.py) — this is the only way
to actually exercise `require_permission`/`UserStoreScope`, since those are
FastAPI dependencies wired at the router layer, not the service layer.

Categories covered, per module: 401, 403 (missing permission), 404
(cross-store — resource exists but outside the caller's scope, both read and
write), insufficient-but-related permission, group revocation taking effect
without re-login, and a deactivated account.
"""

from decimal import Decimal

from app.database.enums import CashSessionStatus, StockLocationType
from app.modules.cash.models import CashSession
from app.modules.clients.models import Client
from app.modules.creances.models import Creance
from app.modules.stock.models import StockLocation
from tests.conftest import assign_group, link_store_user


async def _login_vendeur_store1(db, rbac, user, store, login_as):
    await assign_group(db, user, rbac["vendeur-boutique"])
    await link_store_user(db, store, user)
    login_as(user)


# ── 401: no / invalid credentials ───────────────────────────────────────────


async def test_no_token_is_401(client):
    resp = await client.get("/api/v1/users")
    assert resp.status_code == 401


async def test_garbage_token_is_401(client):
    resp = await client.get(
        "/api/v1/users", headers={"Authorization": "Bearer not-a-real-token"}
    )
    assert resp.status_code == 401


# ── 403: authenticated, zero permissions (the audit's escalation scenario) ──


async def test_zero_permission_user_cannot_list_users(client, db, rbac, user, login_as):
    login_as(user)  # no group assigned at all
    resp = await client.get("/api/v1/users")
    assert resp.status_code == 403


async def test_zero_permission_user_cannot_create_store(client, db, rbac, user, login_as):
    login_as(user)
    resp = await client.post("/api/v1/stores", json={"name": "HACKED", "devise": "GNF"})
    assert resp.status_code == 403


async def test_zero_permission_user_cannot_self_promote(client, db, rbac, user, login_as):
    """The exact escalation chain the audit found: a bare account granting
    itself super-admin via the group-assignment endpoint."""
    login_as(user)
    resp = await client.post(
        f"/api/v1/users/{user.id}/groups", params={"group_id": rbac["super-admin"].id}
    )
    assert resp.status_code == 403


async def test_zero_permission_user_cannot_create_permission(client, db, rbac, user, login_as):
    login_as(user)
    resp = await client.post(
        "/api/v1/access/permissions",
        json={"slug": "evil.x", "name": "Evil", "module": "evil"},
    )
    assert resp.status_code == 403


# ── 404: cross-store access is masked, not just denied ──────────────────────


async def test_vendeur_gets_404_reading_other_store_client(
    client, db, rbac, user, store, store2, login_as
):
    await _login_vendeur_store1(db, rbac, user, store, login_as)
    other_client = Client(store_id=store2.id, code_client="CLI-900001", name="ClientStore2")
    db.add(other_client)
    await db.commit()
    await db.refresh(other_client)

    resp = await client.get(f"/api/v1/clients/{other_client.id}")
    assert resp.status_code == 404


async def test_vendeur_gets_404_editing_other_store_client(
    client, db, rbac, user, store, store2, login_as
):
    await _login_vendeur_store1(db, rbac, user, store, login_as)
    other_client = Client(store_id=store2.id, code_client="CLI-900002", name="ClientStore2b")
    db.add(other_client)
    await db.commit()
    await db.refresh(other_client)

    resp = await client.patch(f"/api/v1/clients/{other_client.id}", json={"notes": "hacked"})
    assert resp.status_code == 404

    resp = await client.delete(f"/api/v1/clients/{other_client.id}")
    assert resp.status_code == 404


async def test_vendeur_cannot_create_client_in_other_store(
    client, db, rbac, user, store, store2, login_as
):
    await _login_vendeur_store1(db, rbac, user, store, login_as)
    resp = await client.post(
        "/api/v1/clients",
        json={"name": "Injected", "phone": "+224699999999", "store_id": store2.id},
    )
    assert resp.status_code == 403


async def test_vendeur_list_clients_never_sees_other_store(
    client, db, rbac, user, store, store2, login_as
):
    await _login_vendeur_store1(db, rbac, user, store, login_as)
    other_client = Client(store_id=store2.id, code_client="CLI-900003", name="ClientStore2c")
    db.add(other_client)
    await db.commit()

    resp = await client.get("/api/v1/clients", params={"store_id": store2.id})
    assert resp.status_code == 200
    assert resp.json() == []  # silently scoped out, not an error


async def test_vendeur_gets_404_on_other_store_vente_and_creance(
    client, db, rbac, user, store, store2, login_as
):
    await _login_vendeur_store1(db, rbac, user, store, login_as)
    other_client = Client(store_id=store2.id, code_client="CLI-900004", name="ClientStore2d")
    db.add(other_client)
    await db.commit()
    await db.refresh(other_client)
    other_creance = Creance(
        client_id=other_client.id,
        boutique_id=store2.id,
        montant_initial=Decimal("50000"),
        montant_restant=Decimal("50000"),
    )
    db.add(other_creance)
    await db.commit()
    await db.refresh(other_creance)

    resp = await client.get(f"/api/v1/creances/{other_creance.id}")
    assert resp.status_code == 404

    resp = await client.get("/api/v1/ventes/999999")
    assert resp.status_code == 404


# ── Insufficient permission: right group, wrong specific action ────────────


async def test_vendeur_has_stock_view_but_not_stock_manage(
    client, db, rbac, user, store, login_as
):
    """vendeur-boutique can see stock (stock.view) but the seed does not
    grant it stock.store.manage/stock.central.manage — POST /stock/add must
    be rejected even though the user is legitimately authenticated and does
    hold *some* stock permission."""
    await _login_vendeur_store1(db, rbac, user, store, login_as)

    loc = StockLocation(name=store.name, type=StockLocationType.STORE, store_id=store.id)
    db.add(loc)
    await db.commit()
    await db.refresh(loc)

    resp = await client.get("/api/v1/stock/locations")
    assert resp.status_code == 200  # stock.view: allowed

    resp = await client.post(
        "/api/v1/stock/add",
        json={
            "product_id": 1,
            "location_id": loc.id,
            "quantity": 5,
            "reason": "achat",
            "alert_threshold": 0,
        },
    )
    assert resp.status_code == 403  # stock.store.manage: not granted


# ── Group revocation takes effect immediately, without re-login ─────────────


async def test_revoking_group_denies_access_on_next_request_same_session(
    client, db, rbac, user, login_as
):
    from sqlalchemy import delete

    from app.modules.access.models import UserGroup

    await assign_group(db, user, rbac["super-admin"])
    login_as(user)

    resp = await client.get("/api/v1/users")
    assert resp.status_code == 200

    await db.execute(delete(UserGroup).where(UserGroup.user_id == user.id))
    await db.commit()

    # Same "session" (login_as override untouched) — no re-login performed.
    resp = await client.get("/api/v1/users")
    assert resp.status_code == 403


# ── Deactivated account: rejected before permissions are even checked ───────


async def test_suspended_user_is_rejected_even_with_full_permissions(
    client, db, rbac, user, login_as
):
    from app.database.enums import UserStatus

    await assign_group(db, user, rbac["super-admin"])
    user.status = UserStatus.suspended
    db.add(user)
    await db.commit()
    login_as(user)

    resp = await client.get("/api/v1/users")
    assert resp.status_code == 403


# ── Positive control: a correctly-permissioned request still works ─────────


async def test_super_admin_passes_every_check(client, db, rbac, user, login_as):
    await assign_group(db, user, rbac["super-admin"])
    login_as(user)

    assert (await client.get("/api/v1/users")).status_code == 200
    assert (await client.get("/api/v1/stores")).status_code == 200
    assert (await client.get("/api/v1/access/permissions")).status_code == 200


async def test_gerant_can_manage_own_store_client(client, db, rbac, user, store, login_as):
    await assign_group(db, user, rbac["gerant-boutique"])
    await link_store_user(db, store, user)
    login_as(user)

    resp = await client.post(
        "/api/v1/clients",
        json={"name": "Client Local", "phone": "+224611112222"},
    )
    assert resp.status_code == 201
    body = resp.json()
    assert body["store_id"] == store.id  # auto-filled: exactly one store in scope

    resp = await client.get(f"/api/v1/clients/{body['id']}")
    assert resp.status_code == 200


async def test_hq_scope_sees_across_stores(client, db, rbac, user, store, store2, login_as):
    """fournisseur (Boss) has stores.manage -> resolves to \"hq\" scope and
    is not restricted to any single store."""
    await assign_group(db, user, rbac["fournisseur"])
    login_as(user)

    other_client = Client(store_id=store2.id, code_client="CLI-900005", name="ClientStore2e")
    db.add(other_client)
    await db.commit()
    await db.refresh(other_client)

    resp = await client.get(f"/api/v1/clients/{other_client.id}")
    assert resp.status_code == 200


# ── Cash session: cross-store isolation on a required (non-nullable) field ──


async def test_vendeur_cannot_open_cash_session_for_other_store(
    client, db, rbac, user, store, store2, login_as
):
    await _login_vendeur_store1(db, rbac, user, store, login_as)
    resp = await client.post(
        "/api/v1/cash/sessions", json={"store_id": store2.id, "opening_amount": "0"}
    )
    assert resp.status_code == 403


async def test_vendeur_gets_404_on_other_store_cash_session(
    client, db, rbac, user, store, store2, login_as
):
    await _login_vendeur_store1(db, rbac, user, store, login_as)
    other_session = CashSession(
        store_id=store2.id, opening_amount=Decimal("0"), status=CashSessionStatus.ouverte
    )
    db.add(other_session)
    await db.commit()
    await db.refresh(other_session)

    resp = await client.get(f"/api/v1/cash/sessions/{other_session.id}")
    assert resp.status_code == 404
