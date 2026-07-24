"""Tests for the commandes (internal réappro) state machine — Phase 1.

Each test exercises ``CommandeService`` directly against the in-memory
SQLite session from ``conftest.py``, mirroring ``test_ventes_engine.py``'s
style: no HTTP layer, but the exact same service code the routes call.
"""

from decimal import Decimal

import pytest
import pytest_asyncio
from fastapi import HTTPException
from sqlalchemy import select

from app.database.enums import (
    CommandeAnomalieType,
    CommandeEvenementType,
    CommandeReceptionStatut,
    CommandeStatut,
    MovementReason,
    MovementType,
    StockLocationType,
)
from app.modules.commandes.models import CommandeAnomalie, CommandeEvenement
from app.modules.commandes.schemas import (
    CommandeAnomalieCreate,
    CommandeCreate,
    CommandeLigneCreate,
    CommandeLigneResolve,
    CommandeProformaReject,
    CommandeProformaRevise,
    CommandeReceptionCreate,
    CommandeRefuse,
    CommandeShip,
    CommandeValidate,
)
from app.modules.commandes.services import CommandeService
from app.modules.stock.models import ProductStock, StockLocation, StockMovement


@pytest_asyncio.fixture
async def central_location(db) -> StockLocation:
    loc = StockLocation(name="Central Test", type=StockLocationType.CENTRAL)
    db.add(loc)
    await db.commit()
    await db.refresh(loc)
    return loc


@pytest_asyncio.fixture
async def central_stock(db, product, central_location) -> ProductStock:
    ps = ProductStock(product_id=product.id, location_id=central_location.id, quantity=50)
    db.add(ps)
    await db.commit()
    await db.refresh(ps)
    return ps


def _payload(store, product, qty=10, price=Decimal("1000")) -> CommandeCreate:
    return CommandeCreate(
        boutique_id=store.id,
        lignes=[
            CommandeLigneCreate(produit_id=product.id, quantite_demandee=qty, prix_unitaire=price)
        ],
    )


async def _events_of(db, commande_id: int) -> list[CommandeEvenement]:
    rows = await db.execute(
        select(CommandeEvenement).where(CommandeEvenement.commande_id == commande_id)
    )
    return list(rows.scalars().all())


async def _stock_qty(db, product_id: int, location_id: int) -> int:
    row = (
        await db.execute(
            select(ProductStock).where(
                ProductStock.product_id == product_id, ProductStock.location_id == location_id
            )
        )
    ).scalar_one()
    return row.quantity


# --- Étape 1-2 : création + soumission -----------------------------------------


async def test_create_starts_as_brouillon(db, store, product, user):
    commande = await CommandeService(db).create(_payload(store, product), user, "127.0.0.1")
    assert commande.statut == CommandeStatut.brouillon
    assert commande.numero is None
    assert commande.montant_total == Decimal("10000")

    events = await _events_of(db, commande.id)
    assert len(events) == 1
    assert events[0].type_evenement == CommandeEvenementType.creation
    assert events[0].acteur_id == user.id
    assert events[0].ip_address == "127.0.0.1"


async def test_submit_assigns_numero_and_moves_to_en_attente(db, store, product, user):
    service = CommandeService(db)
    commande = await service.create(_payload(store, product), user, None)
    commande = await service.submit(commande, user, "10.0.0.1")

    assert commande.statut == CommandeStatut.en_attente
    assert commande.numero is not None
    assert commande.numero.startswith("DEM-")

    events = await _events_of(db, commande.id)
    assert [e.type_evenement for e in events] == [
        CommandeEvenementType.creation,
        CommandeEvenementType.soumission,
    ]


async def test_submit_rejects_non_brouillon(db, store, product, user):
    service = CommandeService(db)
    commande = await service.create(_payload(store, product), user, None)
    commande = await service.submit(commande, user, None)
    with pytest.raises(HTTPException) as exc:
        await service.submit(commande, user, None)
    assert exc.value.status_code == 409


async def test_submit_rejects_commande_without_lignes(db, store, user):
    service = CommandeService(db)
    commande = await service.create(CommandeCreate(boutique_id=store.id, lignes=[]), user, None)
    with pytest.raises(HTTPException) as exc:
        await service.submit(commande, user, None)
    assert exc.value.status_code == 422


# --- Étape 3 : décision HQ -------------------------------------------------------


async def test_validate_full_acceptance(db, store, product, user, other_user):
    service = CommandeService(db)
    commande = await service.create(
        _payload(store, product, qty=10, price=Decimal("1000")), user, None
    )
    commande = await service.submit(commande, user, None)

    commande = await service.validate(commande, CommandeValidate(), other_user, None)

    assert commande.statut == CommandeStatut.validee
    assert commande.lignes[0].quantite_validee == 10
    assert commande.montant_ht == Decimal("10000")
    assert commande.montant_ttc == Decimal("10000")
    assert commande.validated_by == other_user.id


async def test_validate_partial_acceptance_recomputes_amounts(db, store, product, user, other_user):
    service = CommandeService(db)
    commande = await service.create(
        _payload(store, product, qty=10, price=Decimal("1000")), user, None
    )
    commande = await service.submit(commande, user, None)
    ligne_id = commande.lignes[0].id

    commande = await service.validate(
        commande, CommandeValidate(quantites_validees={ligne_id: 4}, commentaire="stock limité"),
        other_user, None,
    )

    assert commande.statut == CommandeStatut.validee
    assert commande.lignes[0].quantite_validee == 4
    assert commande.montant_ht == Decimal("4000")

    events = await _events_of(db, commande.id)
    validation_event = next(
        e for e in events if e.type_evenement == CommandeEvenementType.validation
    )
    assert validation_event.extra["partiel"] is True
    assert validation_event.commentaire == "stock limité"


async def test_validate_rejects_non_en_attente(db, store, product, user, other_user):
    service = CommandeService(db)
    commande = await service.create(_payload(store, product), user, None)
    with pytest.raises(HTTPException) as exc:
        await service.validate(commande, CommandeValidate(), other_user, None)
    assert exc.value.status_code == 409


async def test_refuse_sets_motif_and_status(db, store, product, user, other_user):
    service = CommandeService(db)
    commande = await service.create(_payload(store, product), user, None)
    commande = await service.submit(commande, user, None)

    commande = await service.refuse(
        commande, CommandeRefuse(motif="Budget insuffisant ce mois-ci"), other_user, None
    )

    assert commande.statut == CommandeStatut.rejetee
    assert commande.refus_motif == "Budget insuffisant ce mois-ci"
    assert commande.refused_by == other_user.id
    assert commande.refused_at is not None


async def test_validate_notifies_the_gerant_who_submitted_it(db, store, product, user, other_user):
    from app.modules.notifications.models import Notification

    service = CommandeService(db)
    commande = await service.create(_payload(store, product), user, None)
    commande = await service.submit(commande, user, None)
    commande = await service.validate(commande, CommandeValidate(), other_user, None)

    notifs = (
        await db.execute(select(Notification).where(Notification.user_id == user.id))
    ).scalars().all()
    assert len(notifs) == 1
    assert commande.numero in notifs[0].title
    assert "approuvée" in notifs[0].title
    assert notifs[0].link == "/app/orders"


async def test_refuse_notifies_the_gerant_with_the_motif(db, store, product, user, other_user):
    from app.modules.notifications.models import Notification

    service = CommandeService(db)
    commande = await service.create(_payload(store, product), user, None)
    commande = await service.submit(commande, user, None)
    commande = await service.refuse(
        commande, CommandeRefuse(motif="Budget insuffisant ce mois-ci"), other_user, None
    )

    notifs = (
        await db.execute(select(Notification).where(Notification.user_id == user.id))
    ).scalars().all()
    assert len(notifs) == 1
    assert "refusée" in notifs[0].title
    assert notifs[0].message == "Budget insuffisant ce mois-ci"


# --- Étape 4-7 : documents + logistique ------------------------------------------


async def _validated_commande(service, store, product, user, other_user, qty=10):
    commande = await service.create(_payload(store, product, qty=qty), user, None)
    commande = await service.submit(commande, user, None)
    return await service.validate(commande, CommandeValidate(), other_user, None)


async def test_full_document_and_logistics_chain(db, store, product, user, other_user):
    service = CommandeService(db)
    commande = await _validated_commande(service, store, product, user, other_user)

    commande = await service.generate_proforma(commande, other_user, None)
    assert commande.statut == CommandeStatut.proforma_generee
    assert commande.numero_proforma.startswith("PRO-")

    commande = await service.approve_proforma(commande, other_user, None)
    assert commande.statut == CommandeStatut.facture_generee
    assert commande.numero_facture.startswith("FAC-")

    commande = await service.start_preparation(commande, other_user, None)
    assert commande.statut == CommandeStatut.en_preparation
    assert commande.livraison is not None
    assert commande.livraison.numero_bon_preparation.startswith("BP-")

    commande = await service.confirm_preparation(commande, other_user, None)
    assert commande.statut == CommandeStatut.pret_a_expedier
    assert commande.livraison.preparateur_id == other_user.id

    commande = await service.ship(
        commande, CommandeShip(transporteur="Transco", livreur_nom="Ibrahima"), other_user, None
    )
    assert commande.statut == CommandeStatut.expedie
    assert commande.livraison.numero_bon_livraison.startswith("BL-")
    assert commande.livraison.qr_content == commande.livraison.numero_bon_livraison
    assert commande.lignes[0].quantite_livree == commande.lignes[0].quantite_validee

    commande = await service.mark_delivered(commande, other_user, None)
    assert commande.statut == CommandeStatut.livree
    assert commande.livraison.date_livraison is not None


async def test_generate_proforma_rejects_wrong_status(db, store, product, user, other_user):
    service = CommandeService(db)
    commande = await service.create(_payload(store, product), user, None)
    with pytest.raises(HTTPException) as exc:
        await service.generate_proforma(commande, other_user, None)
    assert exc.value.status_code == 409


# --- Étape 5bis : décision du gérant sur la proforma -----------------------------


async def test_approve_proforma_rejects_wrong_status(db, store, product, user, other_user):
    service = CommandeService(db)
    commande = await _validated_commande(service, store, product, user, other_user)
    with pytest.raises(HTTPException) as exc:
        await service.approve_proforma(commande, other_user, None)
    assert exc.value.status_code == 409


async def test_reject_proforma_sets_status_and_notifies_boss(
    db, store, product, user, other_user, monkeypatch
):
    """`other_user` validated the demande (so it's the Boss on record via
    validated_by); `user` plays the boutique's gérant rejecting the proforma."""
    sent: list[dict] = []

    async def _fake_send_email(to, subject, html_body, text_body=None):
        sent.append({"to": to, "subject": subject})
        return True

    monkeypatch.setattr("app.utils.email.send_email", _fake_send_email)

    service = CommandeService(db)
    commande = await _validated_commande(service, store, product, user, other_user)
    commande = await service.generate_proforma(commande, other_user, None)

    commande = await service.reject_proforma(
        commande, CommandeProformaReject(motif="Prix trop élevé"), user, None
    )

    assert commande.statut == CommandeStatut.proforma_rejetee
    assert commande.proforma_refus_motif == "Prix trop élevé"
    assert commande.proforma_refused_by == user.id
    assert commande.proforma_refused_at is not None

    events = await _events_of(db, commande.id)
    assert any(e.type_evenement == CommandeEvenementType.proforma_rejetee for e in events)

    assert len(sent) == 1
    assert sent[0]["to"] == other_user.email


async def test_reject_proforma_rejects_wrong_status(db, store, product, user, other_user):
    service = CommandeService(db)
    commande = await _validated_commande(service, store, product, user, other_user)
    with pytest.raises(HTTPException) as exc:
        await service.reject_proforma(commande, CommandeProformaReject(motif="Non"), user, None)
    assert exc.value.status_code == 409


async def test_resubmit_proforma_updates_amounts_and_reopens_for_decision(
    db, store, product, user, other_user
):
    service = CommandeService(db)
    commande = await _validated_commande(service, store, product, user, other_user, qty=10)
    commande = await service.generate_proforma(commande, other_user, None)
    ligne_id = commande.lignes[0].id
    commande = await service.reject_proforma(
        commande, CommandeProformaReject(motif="Prix trop élevé"), user, None
    )

    commande = await service.resubmit_proforma(
        commande,
        CommandeProformaRevise(prix={ligne_id: Decimal("900")}, commentaire="Prix révisé"),
        other_user,
        None,
    )

    assert commande.statut == CommandeStatut.proforma_generee
    assert commande.lignes[0].prix_unitaire == Decimal("900")
    assert commande.lignes[0].produit_id == product.id  # Boss revises price/qty, never the product
    assert commande.montant_ht == Decimal("9000")
    assert commande.montant_ttc == commande.montant_ht

    events = await _events_of(db, commande.id)
    assert any(e.type_evenement == CommandeEvenementType.proforma_resoumise for e in events)

    # The gérant can now approve the revised proforma, completing the loop.
    commande = await service.approve_proforma(commande, user, None)
    assert commande.statut == CommandeStatut.facture_generee
    assert commande.lignes[0].produit_id == product.id


async def test_resubmit_proforma_rejects_wrong_status(db, store, product, user, other_user):
    service = CommandeService(db)
    commande = await _validated_commande(service, store, product, user, other_user)
    commande = await service.generate_proforma(commande, other_user, None)
    with pytest.raises(HTTPException) as exc:
        await service.resubmit_proforma(commande, CommandeProformaRevise(), other_user, None)
    assert exc.value.status_code == 409


def test_commande_proforma_revise_schema_has_no_produit_id_field():
    """Locks in the invariant that the Boss can revise a proforma's quantities
    and prices but has no schema-level way to change WHICH product a line
    refers to — that choice belongs to the boutique's gérant alone."""
    assert "produit_id" not in CommandeProformaRevise.model_fields
    assert set(CommandeProformaRevise.model_fields) == {"quantites", "prix", "commentaire"}


async def test_produit_id_immutable_through_full_proforma_cycle(
    db, store, product, user, other_user
):
    """End-to-end guard: the produit_id the gérant picked at creation stays
    identical through validate → proforma → reject → resubmit → approve."""
    service = CommandeService(db)
    commande = await service.create(_payload(store, product, qty=5), user, None)
    original_produit_id = commande.lignes[0].produit_id
    assert original_produit_id == product.id

    commande = await service.submit(commande, user, None)
    commande = await service.validate(commande, CommandeValidate(), other_user, None)
    assert commande.lignes[0].produit_id == original_produit_id

    commande = await service.generate_proforma(commande, other_user, None)
    assert commande.lignes[0].produit_id == original_produit_id

    commande = await service.reject_proforma(
        commande, CommandeProformaReject(motif="Prix à revoir"), user, None
    )
    assert commande.lignes[0].produit_id == original_produit_id

    ligne_id = commande.lignes[0].id
    commande = await service.resubmit_proforma(
        commande,
        CommandeProformaRevise(quantites={ligne_id: 3}, prix={ligne_id: Decimal("500")}),
        other_user,
        None,
    )
    assert commande.lignes[0].produit_id == original_produit_id

    commande = await service.approve_proforma(commande, user, None)
    assert commande.lignes[0].produit_id == original_produit_id


async def test_confirm_preparation_requires_livraison_record(db, store, product, user, other_user):
    """start_preparation always creates the CommandeLivraison row — this test
    guards the defensive 409 in confirm_preparation if that invariant ever broke."""
    service = CommandeService(db)
    commande = await _validated_commande(service, store, product, user, other_user)
    commande = await service.generate_proforma(commande, other_user, None)
    commande = await service.approve_proforma(commande, other_user, None)
    commande = await service.start_preparation(commande, other_user, None)
    commande.livraison = None
    with pytest.raises(HTTPException) as exc:
        await service.confirm_preparation(commande, other_user, None)
    assert exc.value.status_code == 409


# --- Étape 8-9 : réception + mise à jour des stocks ------------------------------


async def _delivered_commande(service, store, product, user, other_user, qty=10):
    commande = await _validated_commande(service, store, product, user, other_user, qty=qty)
    commande = await service.generate_proforma(commande, other_user, None)
    commande = await service.approve_proforma(commande, other_user, None)
    commande = await service.start_preparation(commande, other_user, None)
    commande = await service.confirm_preparation(commande, other_user, None)
    commande = await service.ship(
        commande, CommandeShip(transporteur="Transco"), other_user, None
    )
    return await service.mark_delivered(commande, other_user, None)


async def test_confirm_reception_full_moves_stock_and_logs_movements(
    db, store, store_location, product, central_location, central_stock, user, other_user
):
    service = CommandeService(db)
    commande = await _delivered_commande(service, store, product, user, other_user, qty=10)
    ligne_id = commande.lignes[0].id

    commande = await service.confirm_reception(
        commande,
        CommandeReceptionCreate(
            statut_reception=CommandeReceptionStatut.accepte, lignes={ligne_id: 10}
        ),
        user,
        "41.2.3.4",
    )

    assert commande.statut == CommandeStatut.reception_confirmee
    assert commande.lignes[0].quantite_recue == 10

    assert await _stock_qty(db, product.id, central_location.id) == 40  # 50 - 10
    assert await _stock_qty(db, product.id, store_location.id) == 10  # 0 + 10

    movements = (
        await db.execute(
            select(StockMovement).where(
                StockMovement.product_id == product.id,
                StockMovement.reason == MovementReason.REAPPRO,
            )
        )
    ).scalars().all()
    assert len(movements) == 2
    out_move = next(m for m in movements if m.movement_type == MovementType.OUT)
    in_move = next(m for m in movements if m.movement_type == MovementType.IN)
    assert out_move.from_location_id == central_location.id
    assert out_move.quantity == 10
    assert in_move.to_location_id == store_location.id
    assert in_move.quantity == 10
    assert out_move.reference == f"COMMANDE-{commande.id}"

    events = await _events_of(db, commande.id)
    assert events[-1].type_evenement == CommandeEvenementType.reception
    assert events[-1].ip_address == "41.2.3.4"


async def test_confirm_reception_partial_then_complement_no_double_credit(
    db, store, store_location, product, central_location, central_stock, user, other_user
):
    service = CommandeService(db)
    commande = await _delivered_commande(service, store, product, user, other_user, qty=10)
    ligne_id = commande.lignes[0].id

    commande = await service.confirm_reception(
        commande,
        CommandeReceptionCreate(
            statut_reception=CommandeReceptionStatut.partiel, lignes={ligne_id: 6}
        ),
        user,
        None,
    )
    assert commande.statut == CommandeStatut.partiellement_recu
    assert commande.lignes[0].quantite_recue == 6
    assert await _stock_qty(db, product.id, central_location.id) == 44  # 50 - 6
    assert await _stock_qty(db, product.id, store_location.id) == 6

    # Complement: only the remaining 4 units credited, never the cumulative 10.
    commande = await service.confirm_reception(
        commande,
        CommandeReceptionCreate(
            statut_reception=CommandeReceptionStatut.accepte, lignes={ligne_id: 4}
        ),
        user,
        None,
    )
    assert commande.statut == CommandeStatut.reception_confirmee
    assert commande.lignes[0].quantite_recue == 10
    assert await _stock_qty(db, product.id, central_location.id) == 40  # 50 - 10 total
    assert await _stock_qty(db, product.id, store_location.id) == 10

    receptions = await service.list_receptions(commande.id)
    assert len(receptions) == 2  # one row per delivery attempt, not merged


async def test_confirm_reception_with_anomaly_creates_anomalie_row(
    db, store, store_location, product, central_location, central_stock, user, other_user
):
    service = CommandeService(db)
    commande = await _delivered_commande(service, store, product, user, other_user, qty=10)
    ligne_id = commande.lignes[0].id

    commande = await service.confirm_reception(
        commande,
        CommandeReceptionCreate(
            statut_reception=CommandeReceptionStatut.partiel,
            commentaire="2 unités manquantes à l'arrivée",
            lignes={ligne_id: 8},
            anomalies=[
                CommandeAnomalieCreate(
                    ligne_id=ligne_id,
                    type_anomalie=CommandeAnomalieType.quantite_manquante,
                    quantite_ecart=2,
                    description="Colis ouvert, 2 unités manquantes",
                )
            ],
        ),
        user,
        None,
    )

    assert commande.statut == CommandeStatut.partiellement_recu
    anomalies = (
        await db.execute(
            select(CommandeAnomalie).where(CommandeAnomalie.commande_id == commande.id)
        )
    ).scalars().all()
    assert len(anomalies) == 1
    assert anomalies[0].quantite_ecart == 2
    assert anomalies[0].type_anomalie == CommandeAnomalieType.quantite_manquante

    events = await _events_of(db, commande.id)
    assert any(e.type_evenement == CommandeEvenementType.anomalie for e in events)


async def test_confirm_reception_rejects_qty_above_remaining(
    db, store, store_location, product, central_location, central_stock, user, other_user
):
    service = CommandeService(db)
    commande = await _delivered_commande(service, store, product, user, other_user, qty=10)
    ligne_id = commande.lignes[0].id

    with pytest.raises(HTTPException) as exc:
        await service.confirm_reception(
            commande,
            CommandeReceptionCreate(
                statut_reception=CommandeReceptionStatut.accepte, lignes={ligne_id: 999}
            ),
            user,
            None,
        )
    assert exc.value.status_code == 422


async def test_confirm_reception_rejects_wrong_status(db, store, product, user, other_user):
    service = CommandeService(db)
    commande = await service.create(_payload(store, product), user, None)
    with pytest.raises(HTTPException) as exc:
        await service.confirm_reception(
            commande,
            CommandeReceptionCreate(statut_reception=CommandeReceptionStatut.accepte),
            user,
            None,
        )
    assert exc.value.status_code == 409


# --- Annulation --------------------------------------------------------------------


async def test_cancel_allowed_before_expedition(db, store, product, user, other_user):
    service = CommandeService(db)
    commande = await _validated_commande(service, store, product, user, other_user)
    commande = await service.cancel(commande, user, None, "Erreur de saisie")
    assert commande.statut == CommandeStatut.annulee


async def test_cancel_rejected_after_shipment(db, store, product, user, other_user):
    service = CommandeService(db)
    commande = await _validated_commande(service, store, product, user, other_user)
    commande = await service.generate_proforma(commande, other_user, None)
    commande = await service.approve_proforma(commande, other_user, None)
    commande = await service.start_preparation(commande, other_user, None)
    commande = await service.confirm_preparation(commande, other_user, None)
    commande = await service.ship(commande, CommandeShip(transporteur="Transco"), other_user, None)

    with pytest.raises(HTTPException) as exc:
        await service.cancel(commande, other_user, None, "Trop tard")
    assert exc.value.status_code == 409


# --- Produit non catalogué (nom_libre) --------------------------------------------


def _payload_with_free_text(store, nom="Jus Fanta 1L", qty=12) -> CommandeCreate:
    return CommandeCreate(
        boutique_id=store.id,
        lignes=[CommandeLigneCreate(nom_libre=nom, quantite_demandee=qty)],
    )


def test_ligne_create_requires_exactly_one_of_produit_id_or_nom_libre(product):
    with pytest.raises(ValueError):
        CommandeLigneCreate(quantite_demandee=1)
    with pytest.raises(ValueError):
        CommandeLigneCreate(produit_id=product.id, nom_libre="Doublon", quantite_demandee=1)


async def test_create_accepts_free_text_line(db, store, user):
    commande = await CommandeService(db).create(_payload_with_free_text(store), user, None)
    assert commande.lignes[0].produit_id is None
    assert commande.lignes[0].nom_libre == "Jus Fanta 1L"


async def test_validate_rejects_commande_with_unresolved_line(db, store, user, other_user):
    service = CommandeService(db)
    commande = await service.create(_payload_with_free_text(store), user, None)
    commande = await service.submit(commande, user, None)

    with pytest.raises(HTTPException) as exc:
        await service.validate(commande, CommandeValidate(), other_user, None)
    assert exc.value.status_code == 409
    assert "Jus Fanta 1L" in exc.value.detail


async def test_resolve_ligne_attaches_product_and_allows_validation(
    db, store, product, user, other_user
):
    service = CommandeService(db)
    commande = await service.create(_payload_with_free_text(store), user, None)
    commande = await service.submit(commande, user, None)
    ligne_id = commande.lignes[0].id

    commande = await service.resolve_ligne(
        commande, ligne_id, CommandeLigneResolve(produit_id=product.id), other_user, "9.9.9.9"
    )
    assert commande.lignes[0].produit_id == product.id
    assert commande.lignes[0].nom_libre == "Jus Fanta 1L"  # kept for audit history

    events = await _events_of(db, commande.id)
    resolve_event = next(
        e for e in events if e.type_evenement == CommandeEvenementType.produit_resolu
    )
    assert resolve_event.ip_address == "9.9.9.9"
    assert resolve_event.extra["produit_id"] == product.id

    # Now validation succeeds since every line is resolved.
    commande = await service.validate(commande, CommandeValidate(), other_user, None)
    assert commande.statut == CommandeStatut.validee


async def test_resolve_ligne_rejects_already_resolved(db, store, product, user, other_user):
    service = CommandeService(db)
    commande = await service.create(_payload(store, product), user, None)
    commande = await service.submit(commande, user, None)
    ligne_id = commande.lignes[0].id

    with pytest.raises(HTTPException) as exc:
        await service.resolve_ligne(
            commande, ligne_id, CommandeLigneResolve(produit_id=product.id), other_user, None
        )
    assert exc.value.status_code == 409


async def test_resolve_ligne_rejects_unknown_ligne_id(db, store, product, user, other_user):
    service = CommandeService(db)
    commande = await service.create(_payload_with_free_text(store), user, None)
    commande = await service.submit(commande, user, None)

    with pytest.raises(HTTPException) as exc:
        await service.resolve_ligne(
            commande, 999999, CommandeLigneResolve(produit_id=product.id), other_user, None
        )
    assert exc.value.status_code == 404
