"""Tests for the transferts module — cahier des charges §7.4/§12: a transfer
between any two boutiques (including the boutique principale) is independent
of the réapprovisionnement circuit (commandes)."""

import pytest
import pytest_asyncio
from fastapi import HTTPException
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.database.enums import StockLocationType, TransfertStatut
from app.modules.stock.models import ProductStock, StockLocation
from app.modules.transferts.schemas import (
    TransfertCancel,
    TransfertCreate,
    TransfertLigneCreate,
    TransfertReceive,
    TransfertReceptionLigne,
)
from app.modules.transferts.services import TransfertService


@pytest_asyncio.fixture
async def store2_location(db: AsyncSession, store2) -> StockLocation:
    loc = StockLocation(name="Boutique 2", type=StockLocationType.STORE, store_id=store2.id)
    db.add(loc)
    await db.commit()
    await db.refresh(loc)
    return loc


@pytest_asyncio.fixture
async def central_location(db: AsyncSession) -> StockLocation:
    loc = StockLocation(name="Central", type=StockLocationType.CENTRAL)
    db.add(loc)
    await db.commit()
    await db.refresh(loc)
    return loc


async def _qty(db, product_id: int, location_id: int) -> int:
    row = (
        await db.execute(
            select(ProductStock).where(
                ProductStock.product_id == product_id, ProductStock.location_id == location_id
            )
        )
    ).scalar_one_or_none()
    return row.quantity if row else 0


# ── Store -> store ───────────────────────────────────────────────────────────


async def test_create_decrements_source_immediately(
    db, store, store2, store_location, store2_location, stocked_product, user
):
    payload = TransfertCreate(
        boutique_source_id=store.id,
        boutique_destination_id=store2.id,
        motif="Rééquilibrage stock",
        lignes=[TransfertLigneCreate(produit_id=stocked_product.id, quantite=4)],
    )
    transfert = await TransfertService(db).create(payload, user)

    assert transfert.statut == TransfertStatut.en_transit
    assert transfert.numero is not None and transfert.numero.startswith("TRF-")
    assert (await _qty(db, stocked_product.id, store_location.id)) == 6  # 10 - 4
    assert (await _qty(db, stocked_product.id, store2_location.id)) == 0  # not credited yet


async def test_create_rejects_insufficient_stock(
    db, store, store2, store_location, store2_location, stocked_product, user
):
    payload = TransfertCreate(
        boutique_source_id=store.id,
        boutique_destination_id=store2.id,
        lignes=[TransfertLigneCreate(produit_id=stocked_product.id, quantite=999)],
    )
    with pytest.raises(HTTPException) as exc:
        await TransfertService(db).create(payload, user)
    assert exc.value.status_code == 422
    assert (await _qty(db, stocked_product.id, store_location.id)) == 10  # untouched


async def test_receive_exact_quantity_no_ecart(
    db, store, store2, store_location, store2_location, stocked_product, user, other_user
):
    service = TransfertService(db)
    transfert = await service.create(
        TransfertCreate(
            boutique_source_id=store.id, boutique_destination_id=store2.id,
            lignes=[TransfertLigneCreate(produit_id=stocked_product.id, quantite=4)],
        ),
        user,
    )
    ligne_id = transfert.lignes[0].id

    received = await service.receive(
        transfert,
        TransfertReceive(lignes=[TransfertReceptionLigne(ligne_id=ligne_id, quantite_recue=4)]),
        other_user,
    )

    assert received.statut == TransfertStatut.receptionne
    assert received.receptionne_par == other_user.id
    assert (await _qty(db, stocked_product.id, store2_location.id)) == 4


async def test_receive_with_ecart(
    db, store, store2, store_location, store2_location, stocked_product, user, other_user
):
    service = TransfertService(db)
    transfert = await service.create(
        TransfertCreate(
            boutique_source_id=store.id, boutique_destination_id=store2.id,
            lignes=[TransfertLigneCreate(produit_id=stocked_product.id, quantite=4)],
        ),
        user,
    )
    ligne_id = transfert.lignes[0].id

    received = await service.receive(
        transfert,
        TransfertReceive(
            lignes=[
                TransfertReceptionLigne(
                    ligne_id=ligne_id, quantite_recue=3, observation="1 carton cassé"
                )
            ]
        ),
        other_user,
    )

    assert received.statut == TransfertStatut.receptionne_avec_ecart
    assert (await _qty(db, stocked_product.id, store2_location.id)) == 3
    assert received.lignes[0].quantite_recue == 3
    assert received.lignes[0].observation == "1 carton cassé"


async def test_receive_twice_rejected(
    db, store, store2, store_location, store2_location, stocked_product, user, other_user
):
    service = TransfertService(db)
    transfert = await service.create(
        TransfertCreate(
            boutique_source_id=store.id, boutique_destination_id=store2.id,
            lignes=[TransfertLigneCreate(produit_id=stocked_product.id, quantite=4)],
        ),
        user,
    )
    ligne_id = transfert.lignes[0].id
    await service.receive(
        transfert,
        TransfertReceive(lignes=[TransfertReceptionLigne(ligne_id=ligne_id, quantite_recue=4)]),
        other_user,
    )

    with pytest.raises(HTTPException) as exc:
        await service.receive(
            transfert,
            TransfertReceive(
                lignes=[TransfertReceptionLigne(ligne_id=ligne_id, quantite_recue=4)]
            ),
            other_user,
        )
    assert exc.value.status_code == 409


async def test_cancel_restores_source_stock(
    db, store, store2, store_location, store2_location, stocked_product, user
):
    service = TransfertService(db)
    transfert = await service.create(
        TransfertCreate(
            boutique_source_id=store.id, boutique_destination_id=store2.id,
            lignes=[TransfertLigneCreate(produit_id=stocked_product.id, quantite=4)],
        ),
        user,
    )
    assert (await _qty(db, stocked_product.id, store_location.id)) == 6

    cancelled = await service.cancel(
        transfert, TransfertCancel(motif="Erreur de saisie"), user
    )

    assert cancelled.statut == TransfertStatut.annule
    assert cancelled.annule_motif == "Erreur de saisie"
    assert (await _qty(db, stocked_product.id, store_location.id)) == 10  # fully restored


async def test_cancel_after_receive_rejected(
    db, store, store2, store_location, store2_location, stocked_product, user, other_user
):
    service = TransfertService(db)
    transfert = await service.create(
        TransfertCreate(
            boutique_source_id=store.id, boutique_destination_id=store2.id,
            lignes=[TransfertLigneCreate(produit_id=stocked_product.id, quantite=4)],
        ),
        user,
    )
    ligne_id = transfert.lignes[0].id
    await service.receive(
        transfert,
        TransfertReceive(lignes=[TransfertReceptionLigne(ligne_id=ligne_id, quantite_recue=4)]),
        other_user,
    )

    with pytest.raises(HTTPException) as exc:
        await service.cancel(transfert, TransfertCancel(motif="Trop tard"), user)
    assert exc.value.status_code == 409


# ── Boutique principale (central) as an endpoint ────────────────────────────


async def test_transfer_from_central_to_store(
    db, store, store_location, central_location, stocked_product, user
):
    # Move the test stock to the central location instead, to simulate the
    # principale shipping OUT to a boutique.
    central_stock = ProductStock(
        product_id=stocked_product.id, location_id=central_location.id, quantity=20
    )
    db.add(central_stock)
    await db.commit()

    service = TransfertService(db)
    transfert = await service.create(
        TransfertCreate(
            source_est_principale=True,
            boutique_destination_id=store.id,
            lignes=[TransfertLigneCreate(produit_id=stocked_product.id, quantite=5)],
        ),
        user,
    )
    assert transfert.boutique_source_id is None
    assert (await _qty(db, stocked_product.id, central_location.id)) == 15
    # unaffected until réception
    assert (await _qty(db, stocked_product.id, store_location.id)) == 10

    ligne_id = transfert.lignes[0].id
    received = await service.receive(
        transfert,
        TransfertReceive(lignes=[TransfertReceptionLigne(ligne_id=ligne_id, quantite_recue=5)]),
        user,
    )
    assert received.statut == TransfertStatut.receptionne
    assert (await _qty(db, stocked_product.id, store_location.id)) == 15  # 10 + 5


async def test_source_and_destination_both_principale_rejected():
    with pytest.raises(ValueError):
        TransfertCreate(
            source_est_principale=True,
            destination_est_principale=True,
            lignes=[TransfertLigneCreate(produit_id=1, quantite=1)],
        )


async def test_same_source_and_destination_rejected():
    with pytest.raises(ValueError):
        TransfertCreate(
            boutique_source_id=1,
            boutique_destination_id=1,
            lignes=[TransfertLigneCreate(produit_id=1, quantite=1)],
        )


# ── enrich() denormalization ─────────────────────────────────────────────────


async def test_enrich_names_principale_when_endpoint_is_central(
    db, store, store_location, central_location, stocked_product, user
):
    central_stock = ProductStock(
        product_id=stocked_product.id, location_id=central_location.id, quantity=20
    )
    db.add(central_stock)
    await db.commit()

    service = TransfertService(db)
    transfert = await service.create(
        TransfertCreate(
            source_est_principale=True, boutique_destination_id=store.id,
            lignes=[TransfertLigneCreate(produit_id=stocked_product.id, quantite=2)],
        ),
        user,
    )
    enriched = await service.enrich(transfert)
    assert "principale" in enriched["boutique_source_name"].lower()
    assert enriched["boutique_destination_name"] == store.name
