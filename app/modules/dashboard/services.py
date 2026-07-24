"""DashboardService — single-pass aggregation of all KPIs.

All queries use raw SQL via ``text()`` for maximum efficiency:
a single round-trip per logical group rather than dozens of ORM
select() calls. The schema of every table referenced here matches the
current Alembic HEAD migration.

Date filtering uses Python-computed ``datetime`` bounds (bind params) rather
than MySQL-only functions (``CURDATE()``/``MONTH()``/``YEAR()``/``DATE_SUB()``)
so the same SQL runs against SQLite in unit tests too, and so a caller-chosen
custom period (date_from/date_to) is just a different pair of bounds instead
of a second code path.
"""

from datetime import date, datetime, timedelta
from decimal import Decimal

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from app.modules.dashboard.schemas import (
    ActiviteRecente,
    Alerte,
    DashboardKpi,
    DashboardStats,
    ModePaiement,
    TopBoutique,
    TopClient,
    TopProduit,
    VenteEvolution,
)

MODE_LABELS = {
    "especes": "Espèces",
    "mobile_money": "Mobile Money",
    "carte": "Carte Bancaire",
    "virement": "Virement Bancaire",
    "cheque": "Chèque",
}

ZERO = Decimal("0")


def _day_bounds(d: date) -> tuple[datetime, datetime]:
    start = datetime(d.year, d.month, d.day)
    return start, start + timedelta(days=1)


def _month_to_date_bounds() -> tuple[datetime, datetime]:
    """[start, end) for the current calendar month up to now — the default
    period when the caller gives no explicit date_from/date_to."""
    today = date.today()
    start = datetime(today.year, today.month, 1)
    _, end = _day_bounds(today)
    return start, end


def _custom_bounds(date_from: date, date_to: date) -> tuple[datetime, datetime]:
    start = datetime(date_from.year, date_from.month, date_from.day)
    _, end = _day_bounds(date_to)
    return start, end


def _previous_period_bounds(start: datetime, end: datetime) -> tuple[datetime, datetime]:
    """The period of the same duration immediately preceding [start, end) —
    keeps the trend comparison meaningful for any custom range, not just a
    calendar month."""
    duration = end - start
    return start - duration, start


class DashboardService:
    def __init__(self, db: AsyncSession) -> None:
        self.db = db

    # ── helpers ────────────────────────────────────────────────────────────

    async def _q(self, sql: str, params: dict | None = None):
        return (await self.db.execute(text(sql), params or {}))

    def _scalar(self, row) -> Decimal:
        v = row[0] if row else None
        return Decimal(str(v)) if v is not None else ZERO

    def _int(self, row) -> int:
        v = row[0] if row else None
        return int(v) if v is not None else 0

    # ── KPIs ───────────────────────────────────────────────────────────────

    async def _kpi(
        self,
        boutique_filter: str,
        boutique_filter_v: str,
        loc_filter: str,
        params: dict,
        period_params: dict,
        prev_period_params: dict,
        today_params: dict,
        boutique_id: int | None,
    ) -> DashboardKpi:
        # CA du jour (toujours "aujourd'hui", indépendant de la période choisie)
        r = (await self._q(
            f"SELECT COALESCE(SUM(montant_total),0) FROM ventes "
            f"WHERE created_at >= :period_start AND created_at < :period_end "
            f"AND statut NOT IN ('annulee') AND deleted_at IS NULL {boutique_filter}",
            today_params,
        )).fetchone()
        ca_jour = self._scalar(r)

        # CA de la période sélectionnée
        r = (await self._q(
            f"SELECT COALESCE(SUM(montant_total),0) FROM ventes "
            f"WHERE created_at >= :period_start AND created_at < :period_end "
            f"AND statut NOT IN ('annulee') AND deleted_at IS NULL {boutique_filter}",
            period_params,
        )).fetchone()
        ca_mois = self._scalar(r)

        # CA période précédente (même durée) — pour la tendance
        r = (await self._q(
            f"SELECT COALESCE(SUM(montant_total),0) FROM ventes "
            f"WHERE created_at >= :period_start AND created_at < :period_end "
            f"AND statut NOT IN ('annulee') AND deleted_at IS NULL {boutique_filter}",
            prev_period_params,
        )).fetchone()
        ca_mois_precedent = self._scalar(r)

        # Ventes du jour
        r = (await self._q(
            f"SELECT COUNT(*) FROM ventes "
            f"WHERE created_at >= :period_start AND created_at < :period_end "
            f"AND statut NOT IN ('annulee') AND deleted_at IS NULL {boutique_filter}",
            today_params,
        )).fetchone()
        ventes_jour = self._int(r)

        # Ventes de la période
        r = (await self._q(
            f"SELECT COUNT(*) FROM ventes "
            f"WHERE created_at >= :period_start AND created_at < :period_end "
            f"AND statut NOT IN ('annulee') AND deleted_at IS NULL {boutique_filter}",
            period_params,
        )).fetchone()
        ventes_mois = self._int(r)

        # Ventes période précédente
        r = (await self._q(
            f"SELECT COUNT(*) FROM ventes "
            f"WHERE created_at >= :period_start AND created_at < :period_end "
            f"AND statut NOT IN ('annulee') AND deleted_at IS NULL {boutique_filter}",
            prev_period_params,
        )).fetchone()
        ventes_mois_precedent = self._int(r)

        # Produits vendus (quantité) sur la période — distinct de ventes_mois
        # (nombre de transactions, pas d'unités).
        r = (await self._q(
            f"SELECT COALESCE(SUM(vl.quantite),0) FROM vente_lignes vl "
            f"JOIN ventes v ON v.id=vl.vente_id "
            f"WHERE v.statut NOT IN ('annulee') AND v.deleted_at IS NULL "
            f"AND v.created_at >= :period_start AND v.created_at < :period_end "
            f"{boutique_filter_v}",
            period_params,
        )).fetchone()
        produits_vendus = self._int(r)

        # Clients total (global — not filtered by boutique)
        r = (await self._q(
            "SELECT COUNT(*) FROM clients WHERE deleted_at IS NULL", {}
        )).fetchone()
        clients_total = self._int(r)

        # Nouveaux clients sur la période
        r = (await self._q(
            "SELECT COUNT(*) FROM clients "
            "WHERE created_at >= :period_start AND created_at < :period_end "
            "AND deleted_at IS NULL",
            period_params,
        )).fetchone()
        clients_mois = self._int(r)

        # Stock valeur (coût d'achat × quantité) — solde instantané
        r = (await self._q(
            f"SELECT COALESCE(SUM(ps.quantity * p.prix_achat),0) "
            f"FROM product_stocks ps "
            f"JOIN products p ON p.id=ps.product_id "
            f"JOIN stock_locations sl ON sl.id=ps.location_id "
            f"WHERE p.deleted_at IS NULL {loc_filter}", params
        )).fetchone()
        stock_valeur = self._scalar(r)

        # Rupture totale
        r = (await self._q(
            f"SELECT COUNT(*) FROM product_stocks ps "
            f"JOIN stock_locations sl ON sl.id=ps.location_id AND sl.deleted_at IS NULL "
            f"JOIN products p ON p.id=ps.product_id AND p.deleted_at IS NULL "
            f"WHERE ps.quantity=0 {loc_filter}", params
        )).fetchone()
        stock_rupture = self._int(r)

        # Sous seuil d'alerte
        r = (await self._q(
            f"SELECT COUNT(*) FROM product_stocks ps "
            f"JOIN stock_locations sl ON sl.id=ps.location_id AND sl.deleted_at IS NULL "
            f"JOIN products p ON p.id=ps.product_id AND p.deleted_at IS NULL "
            f"WHERE ps.quantity>0 AND ps.quantity<=ps.alert_threshold "
            f"AND ps.alert_threshold>0 {loc_filter}", params
        )).fetchone()
        stock_alerte = self._int(r)

        # Créances actives — solde instantané, pas lié à la période
        r = (await self._q(
            f"SELECT COUNT(*), COALESCE(SUM(montant_restant),0) FROM creances "
            f"WHERE statut IN ('active','partiellement_payee') "
            f"AND deleted_at IS NULL {boutique_filter}", params
        )).fetchone()
        creances_actives = self._int((r[0],)) if r else 0
        creances_montant = Decimal(str(r[1])) if r and r[1] else ZERO

        # Encaissements du jour
        r = (await self._q(
            f"SELECT COALESCE(SUM(p.montant),0) FROM paiements p "
            f"JOIN ventes v ON v.id=p.vente_id "
            f"WHERE p.created_at >= :period_start AND p.created_at < :period_end "
            f"AND v.deleted_at IS NULL {boutique_filter_v}",
            today_params,
        )).fetchone()
        encaissements_jour = self._scalar(r)

        # Remboursements du jour
        r = (await self._q(
            f"SELECT COALESCE(SUM(vr.montant),0) FROM vente_remboursements vr "
            f"JOIN ventes v ON v.id=vr.vente_id "
            f"WHERE vr.created_at >= :period_start AND vr.created_at < :period_end "
            f"AND vr.deleted_at IS NULL AND v.deleted_at IS NULL {boutique_filter_v}",
            today_params,
        )).fetchone()
        remboursements_jour = self._scalar(r)

        # Total décaissement (sorties de caisse) sur la période sélectionnée —
        # dépenses, remboursements en espèces, retraits... tout ce qui sort
        # physiquement de la caisse, quelle qu'en soit la raison.
        store_filter = "AND cs.store_id = :boutique_id" if boutique_id is not None else ""
        r = (await self._q(
            f"SELECT COALESCE(SUM(cm.amount),0) FROM cash_movements cm "
            f"JOIN cash_sessions cs ON cs.id = cm.cash_session_id "
            f"WHERE cm.type = 'sortie' "
            f"AND cm.created_at >= :period_start AND cm.created_at < :period_end "
            f"{store_filter}",
            period_params,
        )).fetchone()
        total_decaissement = self._scalar(r)

        # Solde de la caisse actuellement ouverte — un solde instantané
        # (montant d'ouverture + entrées - sorties de la session en cours),
        # jamais un cumul sur la période. Uniquement pour une vue boutique.
        caisse_solde: Decimal | None = None
        caisse_ouverte = False
        if boutique_id is not None:
            session_row = (await self._q(
                "SELECT id, opening_amount FROM cash_sessions "
                "WHERE store_id = :boutique_id AND status = 'ouverte' "
                "ORDER BY opened_at DESC LIMIT 1",
                {"boutique_id": boutique_id},
            )).fetchone()
            if session_row is not None:
                caisse_ouverte = True
                session_id = session_row[0]
                opening_amount = Decimal(str(session_row[1]))
                mv = (await self._q(
                    "SELECT COALESCE(SUM(CASE WHEN type='entree' THEN amount ELSE -amount END),0) "
                    "FROM cash_movements WHERE cash_session_id = :session_id",
                    {"session_id": session_id},
                )).fetchone()
                movements_sum = Decimal(str(mv[0])) if mv and mv[0] is not None else ZERO
                caisse_solde = opening_amount + movements_sum

        # Boutiques
        r = (await self._q(
            "SELECT COUNT(*), SUM(CASE WHEN status='active' THEN 1 ELSE 0 END) "
            "FROM stores WHERE deleted_at IS NULL", {}
        )).fetchone()
        boutiques_total = self._int((r[0],)) if r else 0
        boutiques_actives = int(r[1]) if r and r[1] else 0

        return DashboardKpi(
            ca_jour=ca_jour, ca_mois=ca_mois, ca_mois_precedent=ca_mois_precedent,
            ventes_jour=ventes_jour, ventes_mois=ventes_mois,
            ventes_mois_precedent=ventes_mois_precedent,
            produits_vendus=produits_vendus,
            clients_total=clients_total, clients_mois=clients_mois,
            stock_valeur=stock_valeur, stock_rupture=stock_rupture, stock_alerte=stock_alerte,
            creances_actives=creances_actives, creances_montant=creances_montant,
            encaissements_jour=encaissements_jour, remboursements_jour=remboursements_jour,
            total_decaissement=total_decaissement,
            caisse_solde=caisse_solde, caisse_ouverte=caisse_ouverte,
            boutiques_total=boutiques_total, boutiques_actives=boutiques_actives,
        )

    # ── Évolution sur la période sélectionnée ───────────────────────────────

    async def _evolution(
        self, boutique_filter: str, period_params: dict
    ) -> list[VenteEvolution]:
        rows = (await self._q(
            f"SELECT created_at, montant_total FROM ventes "
            f"WHERE created_at >= :period_start AND created_at < :period_end "
            f"AND statut NOT IN ('annulee') AND deleted_at IS NULL {boutique_filter}",
            period_params,
        )).fetchall()
        by_day: dict[str, tuple[int, Decimal]] = {}
        for created_at, montant in rows:
            day_key = str(created_at)[:10]
            cnt, ca = by_day.get(day_key, (0, ZERO))
            by_day[day_key] = (cnt + 1, ca + Decimal(str(montant)))

        start: datetime = period_params["period_start"]
        end: datetime = period_params["period_end"]
        days = []
        cursor = start.date() if isinstance(start, datetime) else start
        end_date = (end.date() if isinstance(end, datetime) else end)
        while cursor < end_date:
            key = cursor.isoformat()
            cnt, ca = by_day.get(key, (0, ZERO))
            days.append(VenteEvolution(date=key, count=cnt, ca=ca))
            cursor += timedelta(days=1)
        return days

    # ── Top produits ───────────────────────────────────────────────────────

    async def _top_produits(
        self, boutique_filter: str, period_params: dict
    ) -> list[TopProduit]:
        rows = (await self._q(
            f"SELECT vl.produit_id, p.name, COALESCE(SUM(vl.quantite),0) as qty, "
            f"COALESCE(SUM(vl.total_ligne),0) as ca "
            f"FROM vente_lignes vl "
            f"JOIN ventes v ON v.id=vl.vente_id "
            f"JOIN products p ON p.id=vl.produit_id "
            f"WHERE v.statut NOT IN ('annulee') AND v.deleted_at IS NULL AND p.deleted_at IS NULL "
            f"AND v.created_at >= :period_start AND v.created_at < :period_end "
            f"{boutique_filter} "
            f"GROUP BY vl.produit_id, p.name ORDER BY qty DESC LIMIT 10",
            period_params,
        )).fetchall()
        return [
            TopProduit(produit_id=int(r[0]), nom=str(r[1]), quantite=int(r[2]),
                       ca=Decimal(str(r[3])))
            for r in rows
        ]

    # ── Top clients ────────────────────────────────────────────────────────

    async def _top_clients(
        self, boutique_filter: str, period_params: dict
    ) -> list[TopClient]:
        rows = (await self._q(
            f"SELECT v.client_id, CONCAT(c.name, COALESCE(CONCAT(' ', c.prenom), '')) as nom, "
            f"COUNT(*) as nb, COALESCE(SUM(v.montant_total),0) as ca "
            f"FROM ventes v "
            f"JOIN clients c ON c.id=v.client_id "
            f"WHERE v.client_id IS NOT NULL AND v.statut NOT IN ('annulee') "
            f"AND v.deleted_at IS NULL AND c.deleted_at IS NULL "
            f"AND v.created_at >= :period_start AND v.created_at < :period_end "
            f"{boutique_filter} "
            f"GROUP BY v.client_id, nom ORDER BY ca DESC LIMIT 10",
            period_params,
        )).fetchall()
        return [
            TopClient(client_id=int(r[0]), nom=str(r[1]), nb_ventes=int(r[2]),
                       ca=Decimal(str(r[3])))
            for r in rows
        ]

    # ── Top boutiques ──────────────────────────────────────────────────────
    # HQ-only ranking — never called with a boutique_filter (a single store
    # ranked against itself is meaningless), so no boutique_filter param here.

    async def _top_boutiques(self, period_params: dict) -> list[TopBoutique]:
        rows = (await self._q(
            "SELECT v.boutique_id, s.name, COUNT(*) as nb, "
            "COALESCE(SUM(v.montant_total),0) as ca "
            "FROM ventes v "
            "JOIN stores s ON s.id=v.boutique_id "
            "WHERE v.statut NOT IN ('annulee') AND v.deleted_at IS NULL "
            "AND v.created_at >= :period_start AND v.created_at < :period_end "
            "GROUP BY v.boutique_id, s.name ORDER BY ca DESC LIMIT 10",
            period_params,
        )).fetchall()
        return [
            TopBoutique(boutique_id=int(r[0]), nom=str(r[1]), nb_ventes=int(r[2]),
                        ca=Decimal(str(r[3])))
            for r in rows
        ]

    # ── Modes de paiement ─────────────────────────────────────────────────

    async def _modes_paiement(
        self, boutique_filter: str, period_params: dict
    ) -> list[ModePaiement]:
        rows = (await self._q(
            f"SELECT p.mode, COUNT(*) as cnt, COALESCE(SUM(p.montant),0) as total "
            f"FROM paiements p "
            f"JOIN ventes v ON v.id=p.vente_id "
            f"WHERE v.statut NOT IN ('annulee') AND v.deleted_at IS NULL "
            f"AND v.created_at >= :period_start AND v.created_at < :period_end "
            f"{boutique_filter} "
            f"GROUP BY p.mode ORDER BY total DESC",
            period_params,
        )).fetchall()
        return [
            ModePaiement(
                mode=str(r[0]),
                label=MODE_LABELS.get(str(r[0]), str(r[0])),
                count=int(r[1]),
                montant=Decimal(str(r[2])),
            )
            for r in rows
        ]

    # ── Alertes ────────────────────────────────────────────────────────────

    async def _alertes(
        self, boutique_filter: str, loc_filter: str, params: dict, today_params: dict
    ) -> list[Alerte]:
        alertes: list[Alerte] = []

        # Rupture stock — compte central ET boutiques confondus, donc le lien
        # doit pointer vers la Vue d'ensemble (qui montre les deux), pas
        # l'onglet "Stock boutiques" seul (qui ne montre qu'une partie du
        # compte et fait croire à un chiffre erroné).
        r = (await self._q(
            f"SELECT COUNT(*) FROM product_stocks ps "
            f"JOIN stock_locations sl ON sl.id=ps.location_id AND sl.deleted_at IS NULL "
            f"JOIN products p ON p.id=ps.product_id AND p.deleted_at IS NULL "
            f"WHERE ps.quantity=0 {loc_filter}", params
        )).fetchone()
        n = self._int(r)
        if n > 0:
            alertes.append(Alerte(
                type="stock_rupture", severity="error",
                message=f"{n} produit(s) en rupture totale",
                count=n, link="/app/inventory",
            ))

        # Sous seuil
        r = (await self._q(
            f"SELECT COUNT(*) FROM product_stocks ps "
            f"JOIN stock_locations sl ON sl.id=ps.location_id "
            f"WHERE ps.quantity>0 AND ps.quantity<=ps.alert_threshold "
            f"AND ps.alert_threshold>0 {loc_filter}", params
        )).fetchone()
        n = self._int(r)
        if n > 0:
            alertes.append(Alerte(
                type="stock_alerte", severity="warning",
                message=f"{n} produit(s) sous le seuil d'alerte",
                count=n, link="/app/inventory/boutiques",
            ))

        # Créances en retard
        r = (await self._q(
            f"SELECT COUNT(*) FROM creances "
            f"WHERE statut IN ('active','partiellement_payee') "
            f"AND date_echeance IS NOT NULL AND date_echeance < :today "
            f"AND deleted_at IS NULL {boutique_filter}",
            {**params, "today": today_params["period_start"]},
        )).fetchone()
        n = self._int(r)
        if n > 0:
            alertes.append(Alerte(
                type="creance_retard", severity="error",
                message=f"{n} créance(s) en retard",
                count=n, link="/app/debts",
            ))

        # Ventes annulées aujourd'hui
        r = (await self._q(
            f"SELECT COUNT(*) FROM ventes "
            f"WHERE created_at >= :period_start AND created_at < :period_end "
            f"AND statut='annulee' AND deleted_at IS NULL {boutique_filter}",
            today_params,
        )).fetchone()
        n = self._int(r)
        if n > 0:
            alertes.append(Alerte(
                type="ventes_annulees", severity="warning",
                message=f"{n} vente(s) annulée(s) aujourd'hui",
                count=n, link="/app/sales",
            ))

        # Caisse non ouverte pour boutiques actives — scoped to this boutique
        # only when a boutique_id is active (boutique_filter non-empty),
        # otherwise network-wide (HQ view). Never mix the two: a store-scoped
        # user must never learn how many OTHER boutiques have no open caisse.
        store_filter = "AND s.id = :boutique_id" if boutique_filter else ""
        r = (await self._q(
            "SELECT COUNT(*) FROM stores s "
            "WHERE s.status='active' AND s.deleted_at IS NULL "
            f"{store_filter} "
            "AND NOT EXISTS ("
            "  SELECT 1 FROM cash_sessions cs "
            "  WHERE cs.store_id=s.id AND cs.status='ouverte'"
            ")", params
        )).fetchone()
        n = self._int(r)
        if n > 0:
            message = (
                "Aucune caisse ouverte pour cette boutique"
                if boutique_filter
                else f"{n} boutique(s) sans caisse ouverte"
            )
            alertes.append(Alerte(
                type="caisse_fermee", severity="info",
                message=message,
                count=n, link="/app/stores",
            ))

        return alertes

    # ── Activité récente ───────────────────────────────────────────────────

    async def _activite(
        self, boutique_filter: str, boutique_filter_v: str, params: dict
    ) -> list[ActiviteRecente]:
        activites: list[ActiviteRecente] = []

        # Dernières ventes
        rows = (await self._q(
            f"SELECT id, montant_total, created_at FROM ventes "
            f"WHERE deleted_at IS NULL {boutique_filter} "
            f"ORDER BY id DESC LIMIT 5", params
        )).fetchall()
        for r in rows:
            activites.append(ActiviteRecente(
                type="vente", reference=f"VENTE-{r[0]}",
                montant=Decimal(str(r[1])), date=str(r[2]),
                link=f"/app/sales/{r[0]}",
            ))

        # Derniers remboursements
        rows = (await self._q(
            f"SELECT vr.id, vr.montant, vr.created_at, vr.vente_id FROM vente_remboursements vr "
            f"JOIN ventes v ON v.id=vr.vente_id "
            f"WHERE vr.deleted_at IS NULL {boutique_filter_v} "
            f"ORDER BY vr.id DESC LIMIT 3", params
        )).fetchall()
        for r in rows:
            activites.append(ActiviteRecente(
                type="remboursement", reference=f"REMB-{r[0]}",
                montant=Decimal(str(r[1])), date=str(r[2]),
                link=f"/app/sales/{r[3]}",
            ))

        # Derniers clients
        rows = (await self._q(
            "SELECT id, name, created_at FROM clients "
            "WHERE deleted_at IS NULL ORDER BY id DESC LIMIT 3", {}
        )).fetchall()
        for r in rows:
            activites.append(ActiviteRecente(
                type="client", reference=str(r[1]),
                montant=None, date=str(r[2]),
                link="/app/customers",
            ))

        activites.sort(key=lambda a: a.date, reverse=True)
        return activites[:15]

    # ── Public method ───────────────────────────────────────────────────────

    async def get_stats(
        self,
        boutique_id: int | None,
        date_from: date | None = None,
        date_to: date | None = None,
    ) -> DashboardStats:
        """Compute all dashboard data in one aggregated service call.

        ``boutique_id=None`` means HQ view (all boutiques). ``date_from``/
        ``date_to`` select a custom period for every period-based figure
        (CA, ventes, produits vendus, top produits/clients, modes de
        paiement, décaissements, évolution) — defaulting to "month to date"
        when omitted. "Aujourd'hui"-labelled figures and instantaneous
        balances (stock, créances, caisse) always mean today / right now,
        regardless of the selected period.
        """
        if date_from is not None and date_to is not None:
            start, end = _custom_bounds(date_from, date_to)
        else:
            start, end = _month_to_date_bounds()
        prev_start, prev_end = _previous_period_bounds(start, end)
        today_start, today_end = _day_bounds(date.today())

        if boutique_id is not None:
            # bf = filter when ventes has no alias (direct FROM ventes WHERE ...)
            boutique_filter = "AND boutique_id = :boutique_id"
            boutique_filter_v = "AND v.boutique_id = :boutique_id"
            boutique_filter_nv = "AND boutique_id = :boutique_id"
            loc_filter = "AND sl.store_id = :boutique_id"
            params: dict = {"boutique_id": boutique_id}
        else:
            boutique_filter = ""
            boutique_filter_v = ""
            boutique_filter_nv = ""
            loc_filter = ""
            params = {}

        period_params = {**params, "period_start": start, "period_end": end}
        prev_period_params = {**params, "period_start": prev_start, "period_end": prev_end}
        today_params = {**params, "period_start": today_start, "period_end": today_end}

        kpi = await self._kpi(
            boutique_filter, boutique_filter_v, loc_filter, params,
            period_params, prev_period_params, today_params, boutique_id,
        )
        evolution = await self._evolution(boutique_filter, period_params)
        top_produits = await self._top_produits(boutique_filter_v, period_params)
        top_clients = await self._top_clients(boutique_filter_v, period_params)
        top_boutiques = await self._top_boutiques(period_params) if boutique_id is None else []
        modes = await self._modes_paiement(boutique_filter_v, period_params)
        alertes = await self._alertes(boutique_filter_nv, loc_filter, params, today_params)
        activite = await self._activite(boutique_filter, boutique_filter_v, params)

        return DashboardStats(
            kpi=kpi,
            evolution_ventes=evolution,
            top_produits=top_produits,
            top_clients=top_clients,
            top_boutiques=top_boutiques,
            modes_paiement=modes,
            alertes=alertes,
            activite_recente=activite,
        )
