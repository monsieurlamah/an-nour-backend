"""ReportsService — aggregations for the "Rapports & Analyses" page.

Same style as ``app.modules.dashboard.services.DashboardService``: raw SQL
via ``text()``, one query per logical group, boutique scope injected as an
f-string filter fragment + bound params.

Date filtering uses Python-computed ``datetime`` bounds (bind params) rather
than MySQL-only functions (``CURDATE()``/``MONTH()``/``YEAR()``/``DATE_SUB()``/
``DATEDIFF()``) so the exact same SQL runs against SQLite in unit tests too —
month/week bucketing that MySQL would do in-query is done in Python instead
(see ``_as_date``, used because a raw ``text()`` query isn't type-decorated:
MySQL's driver returns real ``datetime`` objects, SQLite's returns ISO
strings, but both stringify with "YYYY-MM-DD" first, which ``_as_date``
relies on).
"""

from datetime import date, datetime, timedelta
from decimal import Decimal

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from app.modules.reports.schemas import (
    CollectionWeekPoint,
    ReportsData,
    ReportsKpi,
    RevenueMonthPoint,
    SellerRevenue,
    StockCategoryValue,
    StoreRevenue,
)

ZERO = Decimal("0")

MONTH_LABELS_FR = [
    "Jan", "Fév", "Mars", "Avr", "Mai", "Juin",
    "Juil", "Août", "Sept", "Oct", "Nov", "Déc",
]


def _month_bounds(offset: int = 0) -> tuple[datetime, datetime]:
    """[start, end) bounds for "this month" (offset=0) or an earlier one
    (offset=1 -> previous month, etc.)."""
    today = date.today()
    year, month = today.year, today.month
    for _ in range(offset):
        month -= 1
        if month == 0:
            month, year = 12, year - 1
    start = datetime(year, month, 1)
    end = datetime(year + 1, 1, 1) if month == 12 else datetime(year, month + 1, 1)
    return start, end


def _year_bounds() -> tuple[datetime, datetime]:
    year = date.today().year
    return datetime(year, 1, 1), datetime(year + 1, 1, 1)


def _as_date(value: object) -> date:
    """Normalize a raw ``text()`` query's created_at value to a ``date``,
    regardless of whether the driver returned a native ``datetime``/``date``
    (MySQL) or an ISO string (SQLite)."""
    if isinstance(value, datetime):
        return value.date()
    if isinstance(value, date):
        return value
    return date.fromisoformat(str(value)[:10])


class ReportsService:
    def __init__(self, db: AsyncSession) -> None:
        self.db = db

    # ── helpers ────────────────────────────────────────────────────────────

    async def _q(self, sql: str, params: dict | None = None):
        return await self.db.execute(text(sql), params or {})

    def _scalar(self, row) -> Decimal:
        v = row[0] if row else None
        return Decimal(str(v)) if v is not None else ZERO

    def _int(self, row) -> int:
        v = row[0] if row else None
        return int(v) if v is not None else 0

    @staticmethod
    def _pct(numerator: Decimal, denominator: Decimal) -> Decimal:
        if denominator == 0:
            return ZERO
        return (numerator / denominator * 100).quantize(Decimal("0.1"))

    # ── KPIs ───────────────────────────────────────────────────────────────

    async def _kpi(
        self, boutique_filter_nv: str, boutique_filter_v: str, params: dict
    ) -> ReportsKpi:
        async def ca_and_cost(month_offset: int) -> tuple[Decimal, Decimal, int]:
            """CA, coût d'achat et nb de ventes pour le mois courant (0) ou
            un mois antérieur (1 = mois précédent)."""
            start, end = _month_bounds(month_offset)
            period_params = {**params, "period_start": start, "period_end": end}

            r = (await self._q(
                f"SELECT COALESCE(SUM(montant_total),0), COUNT(*) FROM ventes "
                f"WHERE created_at >= :period_start AND created_at < :period_end "
                f"AND statut NOT IN ('annulee') AND deleted_at IS NULL {boutique_filter_nv} ",
                period_params,
            )).fetchone()
            ca = Decimal(str(r[0])) if r and r[0] else ZERO
            ventes = int(r[1]) if r else 0

            r2 = (await self._q(
                f"SELECT COALESCE(SUM(vl.quantite * p.prix_achat),0) "
                f"FROM vente_lignes vl "
                f"JOIN ventes v ON v.id=vl.vente_id "
                f"JOIN products p ON p.id=vl.produit_id AND p.deleted_at IS NULL "
                f"WHERE v.statut NOT IN ('annulee') AND v.deleted_at IS NULL "
                f"AND v.created_at >= :period_start AND v.created_at < :period_end "
                f"{boutique_filter_v}",
                period_params,
            )).fetchone()
            cost = Decimal(str(r2[0])) if r2 and r2[0] else ZERO
            return ca, cost, ventes

        ca_mois, cost_mois, ventes_mois = await ca_and_cost(0)
        ca_prec, cost_prec, ventes_prec = await ca_and_cost(1)

        marge_pct = self._pct(ca_mois - cost_mois, ca_mois)
        marge_pct_precedent = self._pct(ca_prec - cost_prec, ca_prec)

        # Recouvrement global (toutes créances non annulées, tous statuts) —
        # ratio cumulatif, pas de comparaison mensuelle : une créance vieille
        # de 6 mois recouvrée ce mois-ci ne "appartient" à aucun mois en
        # particulier pour cette mesure.
        r = (await self._q(
            f"SELECT COALESCE(SUM(montant_initial),0), COALESCE(SUM(montant_restant),0) "
            f"FROM creances WHERE statut != 'annulee' AND deleted_at IS NULL {boutique_filter_nv}",
            params,
        )).fetchone()
        initial = Decimal(str(r[0])) if r and r[0] else ZERO
        restant = Decimal(str(r[1])) if r and r[1] else ZERO
        recouvrement_pct = self._pct(initial - restant, initial)

        return ReportsKpi(
            ca_mois=ca_mois, ca_mois_precedent=ca_prec,
            ventes_mois=ventes_mois, ventes_mois_precedent=ventes_prec,
            marge_pct=marge_pct, marge_pct_precedent=marge_pct_precedent,
            recouvrement_pct=recouvrement_pct,
        )

    # ── Évolution du CA sur l'année civile (Jan → Déc) ──────────────────────

    async def _revenue_trend(
        self, boutique_filter_nv: str, params: dict
    ) -> list[RevenueMonthPoint]:
        year_start, year_end = _year_bounds()
        rows = (await self._q(
            f"SELECT created_at, montant_total FROM ventes "
            f"WHERE created_at >= :year_start AND created_at < :year_end "
            f"AND statut NOT IN ('annulee') AND deleted_at IS NULL {boutique_filter_nv}",
            {**params, "year_start": year_start, "year_end": year_end},
        )).fetchall()
        by_month: dict[int, tuple[Decimal, int]] = {}
        for created_at, montant in rows:
            m = _as_date(created_at).month
            ca, cnt = by_month.get(m, (ZERO, 0))
            by_month[m] = (ca + Decimal(str(montant)), cnt + 1)
        return [
            RevenueMonthPoint(
                month=f"{m:02d}", label=MONTH_LABELS_FR[m - 1],
                ca=by_month.get(m, (ZERO, 0))[0], ventes=by_month.get(m, (ZERO, 0))[1],
            )
            for m in range(1, 13)
        ]

    # ── Valeur du stock par catégorie (central + boutiques) ─────────────────

    async def _stock_by_category(self, loc_filter: str, params: dict) -> list[StockCategoryValue]:
        rows = (await self._q(
            f"SELECT COALESCE(cp.name, 'Sans catégorie') as category, "
            f"COALESCE(SUM(ps.quantity * p.prix_achat),0) as valeur "
            f"FROM product_stocks ps "
            f"JOIN products p ON p.id=ps.product_id AND p.deleted_at IS NULL "
            f"JOIN stock_locations sl ON sl.id=ps.location_id AND sl.deleted_at IS NULL "
            f"LEFT JOIN category_products cp "
            f"  ON cp.id=p.category_product_id AND cp.deleted_at IS NULL "
            f"WHERE 1=1 {loc_filter} "
            f"GROUP BY cp.id, cp.name "
            f"HAVING valeur > 0 "
            f"ORDER BY valeur DESC",
            params,
        )).fetchall()
        return [
            StockCategoryValue(category=str(r[0]), valeur=Decimal(str(r[1])))
            for r in rows
        ]

    # ── Créances : encaissé vs nouvelles dettes, 8 dernières semaines ───────

    async def _collection_trend(
        self, boutique_filter_nv: str, boutique_filter_v: str, params: dict
    ) -> list[CollectionWeekPoint]:
        today = date.today()
        window_start = datetime(today.year, today.month, today.day) - timedelta(weeks=8)
        window_params = {**params, "window_start": window_start}

        collected_rows = (await self._q(
            f"SELECT p.created_at, p.montant "
            f"FROM paiements p "
            f"JOIN ventes v ON v.id=p.vente_id "
            f"WHERE p.creance_id IS NOT NULL AND p.deleted_at IS NULL AND v.deleted_at IS NULL "
            f"AND p.created_at >= :window_start "
            f"{boutique_filter_v}",
            window_params,
        )).fetchall()
        collected_by_bucket: dict[int, Decimal] = {}
        for created_at, montant in collected_rows:
            bucket = (today - _as_date(created_at)).days // 7
            collected_by_bucket[bucket] = (
                collected_by_bucket.get(bucket, ZERO) + Decimal(str(montant))
            )

        outstanding_rows = (await self._q(
            f"SELECT created_at, montant_initial "
            f"FROM creances "
            f"WHERE deleted_at IS NULL AND statut != 'annulee' "
            f"AND created_at >= :window_start "
            f"{boutique_filter_nv}",
            window_params,
        )).fetchall()
        outstanding_by_bucket: dict[int, Decimal] = {}
        for created_at, montant in outstanding_rows:
            bucket = (today - _as_date(created_at)).days // 7
            outstanding_by_bucket[bucket] = (
                outstanding_by_bucket.get(bucket, ZERO) + Decimal(str(montant))
            )

        # bucket 7 = il y a 7 semaines (le plus ancien) -> S1 ; bucket 0 = cette semaine -> S8.
        return [
            CollectionWeekPoint(
                week=f"S{8 - bucket}",
                collected=collected_by_bucket.get(bucket, ZERO),
                outstanding=outstanding_by_bucket.get(bucket, ZERO),
            )
            for bucket in range(7, -1, -1)
        ]

    # ── CA du mois par boutique ──────────────────────────────────────────────

    async def _store_revenue(self, boutique_filter_v: str, params: dict) -> list[StoreRevenue]:
        start, end = _month_bounds(0)
        rows = (await self._q(
            f"SELECT v.boutique_id, s.name, COALESCE(SUM(v.montant_total),0) as ca "
            f"FROM ventes v "
            f"JOIN stores s ON s.id=v.boutique_id AND s.deleted_at IS NULL "
            f"WHERE v.statut NOT IN ('annulee') AND v.deleted_at IS NULL "
            f"AND v.created_at >= :period_start AND v.created_at < :period_end "
            f"{boutique_filter_v} "
            f"GROUP BY v.boutique_id, s.name ORDER BY ca DESC",
            {**params, "period_start": start, "period_end": end},
        )).fetchall()
        return [
            StoreRevenue(store_id=int(r[0]), nom=str(r[1]), ca=Decimal(str(r[2])))
            for r in rows
        ]

    # ── Ventes du mois par vendeur ────────────────────────────────────────────

    async def _seller_revenue(self, boutique_filter_v: str, params: dict) -> list[SellerRevenue]:
        start, end = _month_bounds(0)
        rows = (await self._q(
            f"SELECT v.vendeur_id, CONCAT(u.firstname,' ',u.lastname) as nom, "
            f"COUNT(*) as nb, COALESCE(SUM(v.montant_total),0) as ca "
            f"FROM ventes v "
            f"JOIN users u ON u.id=v.vendeur_id AND u.deleted_at IS NULL "
            f"WHERE v.vendeur_id IS NOT NULL AND v.statut NOT IN ('annulee') "
            f"AND v.deleted_at IS NULL "
            f"AND v.created_at >= :period_start AND v.created_at < :period_end "
            f"{boutique_filter_v} "
            f"GROUP BY v.vendeur_id, nom ORDER BY ca DESC LIMIT 15",
            {**params, "period_start": start, "period_end": end},
        )).fetchall()
        return [
            SellerRevenue(
                vendeur_id=int(r[0]), nom=str(r[1]), ventes=int(r[2]), ca=Decimal(str(r[3]))
            )
            for r in rows
        ]

    # ── Public method ─────────────────────────────────────────────────────────

    async def get_data(self, boutique_id: int | None) -> ReportsData:
        """``boutique_id=None`` = vue HQ agrégée sur tout le réseau."""
        if boutique_id is not None:
            boutique_filter_v = "AND v.boutique_id = :boutique_id"
            boutique_filter_nv = "AND boutique_id = :boutique_id"
            loc_filter = "AND sl.store_id = :boutique_id"
            params: dict = {"boutique_id": boutique_id}
        else:
            boutique_filter_v = ""
            boutique_filter_nv = ""
            loc_filter = ""
            params = {}

        kpi = await self._kpi(boutique_filter_nv, boutique_filter_v, params)
        revenue_trend = await self._revenue_trend(boutique_filter_nv, params)
        stock_by_category = await self._stock_by_category(loc_filter, params)
        collection_trend = await self._collection_trend(
            boutique_filter_nv, boutique_filter_v, params
        )
        store_revenue = await self._store_revenue(boutique_filter_v, params)
        seller_revenue = await self._seller_revenue(boutique_filter_v, params)

        return ReportsData(
            kpi=kpi,
            revenue_trend=revenue_trend,
            stock_by_category=stock_by_category,
            collection_trend=collection_trend,
            store_revenue=store_revenue,
            seller_revenue=seller_revenue,
        )
