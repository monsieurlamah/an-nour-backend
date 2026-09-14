"""Tests for the Vente proforma (devis) lifecycle — cahier des charges
§9.1-§9.3: create_proforma → update_proforma / reject_proforma →
transform_to_facture, additive on top of the existing direct-sale engine
(see test_ventes_engine.py, which must keep passing unchanged)."""

from datetime import timedelta
from decimal import Decimal

import pytest
from fastapi import HTTPException
from sqlalchemy import select

from app.database.enums import VenteLivraisonStatut, VenteStatut
from app.modules.creances.models import Paiement
from app.modules.stock.models import ProductStock
from app.modules.ventes.schemas import (
    VenteLigneCreate,
    VentePaiementCreate,
    VenteProformaCreate,
    VenteProformaReject,
    VenteProformaUpdate,
    VenteTransformRequest,
)
from app.modules.ventes.services import VenteService
from app.utils.helpers import utcnow


def _ligne(product, qty=2, price=Decimal("100000")) -> VenteLigneCreate:
    return VenteLigneCreate(produit_id=product.id, quantite=qty, prix_unitaire=price)


async def _stock_qty(db, product_id: int, location_id: int) -> int:
    row = (
        await db.execute(
            select(ProductStock).where(
                ProductStock.product_id == product_id, ProductStock.location_id == location_id
            )
        )
    ).scalar_one()
    return row.quantity


# ── Creating a proforma never touches stock, payments or créance ────────────


async def test_create_proforma_no_stock_no_payment(
    db, store, store_location, stocked_product, user
):
    payload = VenteProformaCreate(
        boutique_id=store.id,
        lignes=[_ligne(stocked_product, qty=3, price=Decimal("50000"))],
    )
    vente = await VenteService(db).create_proforma(payload, user)

    assert vente.statut == VenteStatut.proforma
    assert vente.numero_proforma is not None and vente.numero_proforma.startswith("PRO-")
    assert vente.numero_facture is None
    assert vente.montant_total == Decimal("150000")
    assert vente.montant_paye == Decimal("0")
    assert vente.creance is None
    assert vente.paiements == []
    assert (await _stock_qty(db, stocked_product.id, store_location.id)) == 10  # untouched


async def test_create_proforma_applies_global_remise(db, store, stocked_product, user):
    payload = VenteProformaCreate(
        boutique_id=store.id,
        remise=Decimal("10000"),
        lignes=[_ligne(stocked_product, qty=2, price=Decimal("100000"))],
    )
    vente = await VenteService(db).create_proforma(payload, user)
    assert vente.montant_total == Decimal("190000")


async def test_create_proforma_sets_default_validity(db, store, stocked_product, user):
    before = utcnow().replace(tzinfo=None)  # DATETIME columns round-trip naive
    payload = VenteProformaCreate(
        boutique_id=store.id, lignes=[_ligne(stocked_product)], validite_jours=7
    )
    vente = await VenteService(db).create_proforma(payload, user)
    assert vente.proforma_valide_jusquau is not None
    delta = vente.proforma_valide_jusquau - before
    assert timedelta(days=6, hours=23) < delta < timedelta(days=7, hours=1)


async def test_create_proforma_is_not_marked_delivered(db, store, stocked_product, user):
    """A proforma "n'impacte pas le stock" (§9.1) — it must not inherit the
    `livre` column default, or the UI would wrongly claim delivery before
    any transform ever happened."""
    payload = VenteProformaCreate(boutique_id=store.id, lignes=[_ligne(stocked_product)])
    vente = await VenteService(db).create_proforma(payload, user)
    assert vente.livraison_statut == VenteLivraisonStatut.non_livre


# ── Negotiation: update / reject ────────────────────────────────────────────


async def test_update_proforma_reprices_lines(db, store, stocked_product, user):
    payload = VenteProformaCreate(boutique_id=store.id, lignes=[_ligne(stocked_product, qty=2)])
    vente = await VenteService(db).create_proforma(payload, user)

    updated = await VenteService(db).update_proforma(
        vente,
        VenteProformaUpdate(remise=Decimal("20000"), lignes=[_ligne(stocked_product, qty=4)]),
        user,
    )
    assert updated.montant_total == Decimal("380000")  # 4*100000 - 20000
    assert len(updated.lignes) == 1
    assert updated.lignes[0].quantite == 4


async def test_reject_proforma_records_motif(db, store, stocked_product, user):
    payload = VenteProformaCreate(boutique_id=store.id, lignes=[_ligne(stocked_product)])
    vente = await VenteService(db).create_proforma(payload, user)

    rejected = await VenteService(db).reject_proforma(
        vente, VenteProformaReject(motif="Prix trop élevé"), user
    )
    assert rejected.statut == VenteStatut.proforma_rejetee
    assert rejected.proforma_refus_motif == "Prix trop élevé"
    assert rejected.proforma_refused_by == user.id


async def test_update_rejected_proforma_fails(db, store, stocked_product, user):
    payload = VenteProformaCreate(boutique_id=store.id, lignes=[_ligne(stocked_product)])
    vente = await VenteService(db).create_proforma(payload, user)
    await VenteService(db).reject_proforma(vente, VenteProformaReject(motif="non"), user)

    with pytest.raises(HTTPException) as exc:
        await VenteService(db).update_proforma(
            vente, VenteProformaUpdate(remise=Decimal("0")), user
        )
    assert exc.value.status_code == 409


# ── Transformation: the pivot into a real facture ───────────────────────────


async def test_transform_to_facture_consumes_stock_and_pays(
    db, store, store_location, stocked_product, user, open_cash_session
):
    payload = VenteProformaCreate(
        boutique_id=store.id, lignes=[_ligne(stocked_product, qty=2, price=Decimal("100000"))]
    )
    vente = await VenteService(db).create_proforma(payload, user)
    assert (await _stock_qty(db, stocked_product.id, store_location.id)) == 10

    facture = await VenteService(db).transform_to_facture(
        vente,
        VenteTransformRequest(
            paiements=[VentePaiementCreate(mode="especes", montant=Decimal("200000"))]
        ),
        user,
    )

    assert facture.statut == VenteStatut.completee
    assert facture.numero_facture is not None and facture.numero_facture.startswith("FAC-")
    assert facture.numero_proforma == vente.numero_proforma  # same dossier
    assert facture.montant_paye == Decimal("200000")
    assert facture.creance is None
    assert facture.facture_by == user.id
    assert (await _stock_qty(db, stocked_product.id, store_location.id)) == 8

    paiements = (
        await db.execute(select(Paiement).where(Paiement.vente_id == facture.id))
    ).scalars().all()
    assert len(paiements) == 1


async def test_transform_without_payment_creates_full_creance(
    db, store, stocked_product, user, client_
):
    payload = VenteProformaCreate(
        boutique_id=store.id, client_id=client_.id,
        lignes=[_ligne(stocked_product, qty=1, price=Decimal("75000"))],
    )
    vente = await VenteService(db).create_proforma(payload, user)

    facture = await VenteService(db).transform_to_facture(
        vente, VenteTransformRequest(paiements=[]), user
    )
    assert facture.statut == VenteStatut.impayee
    assert facture.creance is not None
    assert facture.montant_restant == Decimal("75000")


async def test_transform_without_payment_and_without_client_rejected(
    db, store, stocked_product, user
):
    payload = VenteProformaCreate(boutique_id=store.id, lignes=[_ligne(stocked_product)])
    vente = await VenteService(db).create_proforma(payload, user)

    with pytest.raises(HTTPException) as exc:
        await VenteService(db).transform_to_facture(
            vente, VenteTransformRequest(paiements=[]), user
        )
    assert exc.value.status_code == 422


async def test_transform_non_livre_defers_stock(
    db, store, store_location, stocked_product, user, client_
):
    payload = VenteProformaCreate(
        boutique_id=store.id, client_id=client_.id, lignes=[_ligne(stocked_product, qty=2)]
    )
    vente = await VenteService(db).create_proforma(payload, user)

    facture = await VenteService(db).transform_to_facture(
        vente,
        VenteTransformRequest(paiements=[], livraison_statut=VenteLivraisonStatut.non_livre),
        user,
    )
    assert facture.livraison_statut == VenteLivraisonStatut.non_livre
    assert facture.numero_bon_livraison is None
    assert (await _stock_qty(db, stocked_product.id, store_location.id)) == 10  # untouched yet


async def test_transform_already_facture_rejected(
    db, store, stocked_product, user, open_cash_session
):
    payload = VenteProformaCreate(boutique_id=store.id, lignes=[_ligne(stocked_product, qty=1)])
    vente = await VenteService(db).create_proforma(payload, user)
    await VenteService(db).transform_to_facture(
        vente,
        VenteTransformRequest(
            paiements=[VentePaiementCreate(mode="especes", montant=Decimal("100000"))]
        ),
        user,
    )

    with pytest.raises(HTTPException) as exc:
        await VenteService(db).transform_to_facture(
            vente, VenteTransformRequest(paiements=[]), user
        )
    assert exc.value.status_code == 409


# ── Expiry (lazy, on read) ───────────────────────────────────────────────────


async def test_expired_proforma_flips_on_read(db, store, stocked_product, user):
    payload = VenteProformaCreate(boutique_id=store.id, lignes=[_ligne(stocked_product)])
    vente = await VenteService(db).create_proforma(payload, user)

    # Simulate time passing: back-date the validity window directly.
    vente.proforma_valide_jusquau = utcnow() - timedelta(days=1)
    db.add(vente)
    await db.flush()

    reloaded = await VenteService(db).get(vente.id)
    assert reloaded.statut == VenteStatut.proforma_expiree


async def test_transform_expired_proforma_rejected(db, store, stocked_product, user):
    payload = VenteProformaCreate(boutique_id=store.id, lignes=[_ligne(stocked_product)])
    vente = await VenteService(db).create_proforma(payload, user)
    vente.proforma_valide_jusquau = utcnow() - timedelta(days=1)
    db.add(vente)
    await db.flush()

    vente = await VenteService(db).get(vente.id)  # triggers the lazy flip
    with pytest.raises(HTTPException) as exc:
        await VenteService(db).transform_to_facture(
            vente, VenteTransformRequest(paiements=[]), user
        )
    assert exc.value.status_code == 422


# ── A direct sale (create()) now also gets a numero_facture ────────────────


async def test_direct_sale_also_gets_numero_facture(
    db, store, stocked_product, user, open_cash_session
):
    from app.modules.ventes.schemas import VenteCreate

    payload = VenteCreate(
        boutique_id=store.id,
        lignes=[_ligne(stocked_product, qty=1, price=Decimal("100000"))],
        paiements=[VentePaiementCreate(mode="especes", montant=Decimal("100000"))],
    )
    vente = await VenteService(db).create(payload, user)
    assert vente.numero_facture is not None and vente.numero_facture.startswith("FAC-")
    assert vente.numero_proforma is None
    assert vente.facture_by == user.id
