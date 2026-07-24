"""Pydantic schemas for the Reports module."""

from decimal import Decimal

from pydantic import BaseModel


class ReportsKpi(BaseModel):
    ca_mois: Decimal
    ca_mois_precedent: Decimal
    ventes_mois: int
    ventes_mois_precedent: int
    # Marge = (CA - coût d'achat des lignes vendues) / CA, en %.
    marge_pct: Decimal
    marge_pct_precedent: Decimal
    # Recouvrement = (initial - restant) / initial sur toutes les créances
    # non annulées, tous statuts confondus — ratio global, pas de tendance
    # mensuelle associée (voir ReportsService docstring).
    recouvrement_pct: Decimal


class RevenueMonthPoint(BaseModel):
    month: str   # "2026-01"
    label: str   # "Jan"
    ca: Decimal
    ventes: int


class StockCategoryValue(BaseModel):
    category: str
    valeur: Decimal


class CollectionWeekPoint(BaseModel):
    week: str          # "S1", "S2", ...
    collected: Decimal  # paiements de créances encaissés cette semaine
    outstanding: Decimal  # nouvelles créances nées cette semaine


class StoreRevenue(BaseModel):
    store_id: int
    nom: str
    ca: Decimal


class SellerRevenue(BaseModel):
    vendeur_id: int
    nom: str
    ventes: int
    ca: Decimal


class ReportsData(BaseModel):
    kpi: ReportsKpi
    revenue_trend: list[RevenueMonthPoint]
    stock_by_category: list[StockCategoryValue]
    collection_trend: list[CollectionWeekPoint]
    store_revenue: list[StoreRevenue]
    seller_revenue: list[SellerRevenue]
