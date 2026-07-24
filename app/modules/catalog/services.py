"""Business logic for the catalog module."""

from app.modules.catalog.models import CategoryProduct, CategoryStore, Product
from app.modules.common.crud import CRUDService


class CategoryProductService(CRUDService[CategoryProduct]):
    model = CategoryProduct


class ProductService(CRUDService[Product]):
    model = Product


class CategoryStoreService(CRUDService[CategoryStore]):
    model = CategoryStore
