"""Tests for the expenses module: a gérant records/justifies expenses for
their own boutique, category taxonomy management is Boss-only, and the
date-range filter used by the export/print feature behaves correctly.

HTTP-level (client/login_as/rbac) since RBAC enforcement lives at the
router layer (require_permission/UserStoreScope), not the service layer.
"""

from datetime import datetime

from app.modules.expenses.models import Expense, ExpenseCategory
from tests.conftest import assign_group, link_store_user


async def _login_gerant_store1(db, rbac, user, store, login_as):
    await assign_group(db, user, rbac["gerant-boutique"])
    await link_store_user(db, store, user)
    login_as(user)


async def _make_category(db, name="Transport", slug="transport"):
    cat = ExpenseCategory(name=name, slug=slug)
    db.add(cat)
    await db.commit()
    await db.refresh(cat)
    return cat


# ── Recording + justification ────────────────────────────────────────────────


async def test_gerant_can_create_expense_for_own_store(client, db, rbac, user, store, login_as):
    await _login_gerant_store1(db, rbac, user, store, login_as)
    category = await _make_category(db)

    resp = await client.post(
        "/api/v1/expenses",
        json={
            "montant": "50000",
            "category_id": category.id,
            "description": "Achat de carburant pour la livraison",
            "payment_mode": "especes",
        },
    )
    assert resp.status_code == 201
    body = resp.json()
    assert body["store_id"] == store.id
    assert body["description"] == "Achat de carburant pour la livraison"
    assert body["receipt_url"] is None


async def test_expense_without_justification_is_rejected(client, db, rbac, user, store, login_as):
    await _login_gerant_store1(db, rbac, user, store, login_as)
    resp = await client.post(
        "/api/v1/expenses",
        json={"montant": "10000", "description": "", "payment_mode": "especes"},
    )
    assert resp.status_code == 422


async def test_expense_with_category_label_roundtrips(client, db, rbac, user, store, login_as):
    autre = await _make_category(db, name="Autre", slug="autre")
    await _login_gerant_store1(db, rbac, user, store, login_as)
    resp = await client.post(
        "/api/v1/expenses",
        json={
            "montant": "8000",
            "category_id": autre.id,
            "category_label": "Cadeau client fidèle",
            "description": "Petit geste commercial",
        },
    )
    assert resp.status_code == 201
    assert resp.json()["category_label"] == "Cadeau client fidèle"


async def test_expense_with_receipt_url_roundtrips(client, db, rbac, user, store, login_as):
    await _login_gerant_store1(db, rbac, user, store, login_as)
    resp = await client.post(
        "/api/v1/expenses",
        json={
            "montant": "12000",
            "description": "Réparation frigo",
            "payment_mode": "especes",
            "receipt_url": "https://res.cloudinary.com/demo/image/upload/receipt.jpg",
        },
    )
    assert resp.status_code == 201
    assert resp.json()["receipt_url"].endswith("receipt.jpg")


async def test_gerant_cannot_create_expense_for_other_store(
    client, db, rbac, user, store, store2, login_as
):
    await _login_gerant_store1(db, rbac, user, store, login_as)
    resp = await client.post(
        "/api/v1/expenses",
        json={
            "montant": "10000",
            "store_id": store2.id,
            "description": "Tentative hors périmètre",
        },
    )
    assert resp.status_code == 403


async def test_gerant_cannot_see_other_store_expense(
    client, db, rbac, user, store, store2, login_as
):
    other_expense = Expense(
        store_id=store2.id, montant=5000, description="Dépense boutique 2",
    )
    db.add(other_expense)
    await db.commit()
    await db.refresh(other_expense)

    await _login_gerant_store1(db, rbac, user, store, login_as)
    resp = await client.get(f"/api/v1/expenses/{other_expense.id}")
    assert resp.status_code == 404


# ── Category taxonomy: Boss-only, never the gérant ───────────────────────────


async def test_gerant_cannot_manage_expense_categories(client, db, rbac, user, store, login_as):
    await _login_gerant_store1(db, rbac, user, store, login_as)
    resp = await client.post(
        "/api/v1/expenses/categories", json={"name": "Catégorie pirate"},
    )
    assert resp.status_code == 403


async def test_boss_can_manage_expense_categories(client, db, rbac, user, store, login_as):
    await assign_group(db, user, rbac["fournisseur"])
    login_as(user)
    resp = await client.post(
        "/api/v1/expenses/categories", json={"name": "Nouvelle catégorie"},
    )
    assert resp.status_code == 201
    assert resp.json()["slug"] == "nouvelle-categorie"


async def test_gerant_can_still_view_categories(client, db, rbac, user, store, login_as):
    await _make_category(db)
    await _login_gerant_store1(db, rbac, user, store, login_as)
    resp = await client.get("/api/v1/expenses/categories")
    assert resp.status_code == 200
    assert len(resp.json()) == 1


# ── Date-range filter (powers the period export/print) ───────────────────────


async def test_date_range_filters_expenses_by_created_at(client, db, rbac, user, store, login_as):
    old = Expense(store_id=store.id, montant=1000, description="Ancienne dépense")
    recent = Expense(store_id=store.id, montant=2000, description="Dépense récente")
    db.add_all([old, recent])
    await db.commit()
    await db.refresh(old)
    await db.refresh(recent)

    old.created_at = datetime(2026, 1, 5)
    recent.created_at = datetime(2026, 7, 15)
    db.add_all([old, recent])
    await db.commit()

    await _login_gerant_store1(db, rbac, user, store, login_as)

    resp = await client.get(
        "/api/v1/expenses",
        params={"date_from": "2026-07-01", "date_to": "2026-07-31"},
    )
    assert resp.status_code == 200
    ids = [e["id"] for e in resp.json()]
    assert recent.id in ids
    assert old.id not in ids

    count_resp = await client.get(
        "/api/v1/expenses/count",
        params={"date_from": "2026-07-01", "date_to": "2026-07-31"},
    )
    assert count_resp.json() == {"total": 1}


# ── store_name enrichment (Boss overview across boutiques) ───────────────────


async def test_boss_sees_store_name_on_each_expense_across_boutiques(
    client, db, rbac, user, store, store2, login_as
):
    db.add_all([
        Expense(store_id=store.id, montant=1000, description="Dépense boutique 1"),
        Expense(store_id=store2.id, montant=2000, description="Dépense boutique 2"),
    ])
    await db.commit()

    await assign_group(db, user, rbac["fournisseur"])
    login_as(user)

    resp = await client.get("/api/v1/expenses")
    assert resp.status_code == 200
    by_store = {e["store_id"]: e["store_name"] for e in resp.json()}
    assert by_store[store.id] == store.name
    assert by_store[store2.id] == store2.name


async def test_expense_store_name_present_on_create_response(
    client, db, rbac, user, store, login_as
):
    await _login_gerant_store1(db, rbac, user, store, login_as)
    resp = await client.post(
        "/api/v1/expenses",
        json={"montant": "5000", "description": "Test enrichissement"},
    )
    assert resp.status_code == 201
    assert resp.json()["store_name"] == store.name
