"""Tests for the achat module: suppliers and purchases are Boss-only (the
"fournisseur" group — Propriétaire/Owner — not to be confused with the
Supplier entities themselves). The Comptable role lost suppliers.view/
purchases.view in this change; the Gérant never had them."""

from app.modules.achat.models import Purchase, Supplier
from tests.conftest import assign_group


async def _login_boss(db, rbac, user, login_as):
    await assign_group(db, user, rbac["fournisseur"])
    login_as(user)


# ── RBAC ──────────────────────────────────────────────────────────────────


async def test_boss_can_view_and_manage_suppliers(client, db, rbac, user, login_as):
    await _login_boss(db, rbac, user, login_as)
    resp = await client.post(
        "/api/v1/achats/suppliers",
        json={"name": "Grossiste Conakry", "phone": "+224600000001"},
    )
    assert resp.status_code == 201

    resp = await client.get("/api/v1/achats/suppliers")
    assert resp.status_code == 200
    assert len(resp.json()) == 1


async def test_comptable_no_longer_has_supplier_access(client, db, rbac, user, login_as):
    await assign_group(db, user, rbac["comptable"])
    login_as(user)
    resp = await client.get("/api/v1/achats/suppliers")
    assert resp.status_code == 403

    resp = await client.get("/api/v1/achats")
    assert resp.status_code == 403


async def test_gerant_has_no_supplier_access(client, db, rbac, user, store, login_as):
    from tests.conftest import link_store_user

    await assign_group(db, user, rbac["gerant-boutique"])
    await link_store_user(db, store, user)
    login_as(user)
    resp = await client.get("/api/v1/achats/suppliers")
    assert resp.status_code == 403


# ── Supplier CRUD ─────────────────────────────────────────────────────────


async def test_supplier_update_and_status_toggle(client, db, rbac, user, login_as):
    await _login_boss(db, rbac, user, login_as)
    create_resp = await client.post(
        "/api/v1/achats/suppliers", json={"name": "Fournisseur A"},
    )
    supplier_id = create_resp.json()["id"]

    resp = await client.patch(
        f"/api/v1/achats/suppliers/{supplier_id}",
        json={"phone": "+224611111111", "status": "inactive"},
    )
    assert resp.status_code == 200
    body = resp.json()
    assert body["phone"] == "+224611111111"
    assert body["status"] == "inactive"


async def test_supplier_soft_delete_excludes_from_list(client, db, rbac, user, login_as):
    await _login_boss(db, rbac, user, login_as)
    create_resp = await client.post("/api/v1/achats/suppliers", json={"name": "À supprimer"})
    supplier_id = create_resp.json()["id"]

    del_resp = await client.delete(f"/api/v1/achats/suppliers/{supplier_id}")
    assert del_resp.status_code == 204

    list_resp = await client.get("/api/v1/achats/suppliers")
    assert all(s["id"] != supplier_id for s in list_resp.json())


# ── Purchases ─────────────────────────────────────────────────────────────


async def test_create_purchase_computes_total_from_lines(client, db, rbac, user, product, login_as):
    await _login_boss(db, rbac, user, login_as)
    supplier = Supplier(name="Fournisseur B")
    db.add(supplier)
    await db.commit()
    await db.refresh(supplier)

    resp = await client.post(
        "/api/v1/achats",
        json={
            "supplier_id": supplier.id,
            "lignes": [
                {"product_id": product.id, "quantity": 5, "prix_unitaire": "70000"},
                {"product_id": product.id, "quantity": 2, "prix_unitaire": "70000"},
            ],
        },
    )
    assert resp.status_code == 201
    body = resp.json()
    assert body["montant_total"] == "490000.00"
    assert body["statut"] == "brouillon"
    assert len(body["lignes"]) == 2


async def test_purchase_status_transition(client, db, rbac, user, product, login_as):
    await _login_boss(db, rbac, user, login_as)
    supplier = Supplier(name="Fournisseur C")
    db.add(supplier)
    await db.commit()
    await db.refresh(supplier)

    create_resp = await client.post(
        "/api/v1/achats",
        json={
            "supplier_id": supplier.id,
            "lignes": [{"product_id": product.id, "quantity": 1, "prix_unitaire": "70000"}],
        },
    )
    purchase_id = create_resp.json()["id"]

    resp = await client.patch(
        f"/api/v1/achats/{purchase_id}/status", json={"statut": "commandee"},
    )
    assert resp.status_code == 200
    assert resp.json()["statut"] == "commandee"


async def test_list_purchases_filters_by_supplier(client, db, rbac, user, product, login_as):
    await _login_boss(db, rbac, user, login_as)
    s1 = Supplier(name="Fournisseur D")
    s2 = Supplier(name="Fournisseur E")
    db.add_all([s1, s2])
    await db.commit()
    await db.refresh(s1)
    await db.refresh(s2)

    for supplier in (s1, s2):
        p = Purchase(supplier_id=supplier.id, montant_total=1000)
        db.add(p)
    await db.commit()

    resp = await client.get("/api/v1/achats", params={"supplier_id": s1.id})
    assert resp.status_code == 200
    body = resp.json()
    assert len(body) == 1
    assert body[0]["supplier_id"] == s1.id
