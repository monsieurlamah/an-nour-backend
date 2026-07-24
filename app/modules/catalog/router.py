"""HTTP routes for the catalog module: product categories, products, store categories.

Catalog entities have no store dimension — they're shared across the whole
network — so only permission checks apply here, no store scope.
"""

from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, Query, status

from app.api.deps import CurrentUser, DbSession
from app.core.authz import require_permission
from app.modules.catalog.schemas import (
    CategoryProductCreate,
    CategoryProductRead,
    CategoryProductUpdate,
    CategoryStoreCreate,
    CategoryStoreRead,
    CategoryStoreUpdate,
    ProductCreate,
    ProductRead,
    ProductUpdate,
)
from app.modules.catalog.services import (
    CategoryProductService,
    CategoryStoreService,
    ProductService,
)

router = APIRouter(prefix="/catalog", tags=["catalog"])


# --- Product categories ------------------------------------------------------
@router.get("/product-categories", response_model=list[CategoryProductRead])
async def list_product_categories(
    db: DbSession,
    _: CurrentUser,
    _perm: Annotated[None, Depends(require_permission("products.view"))],
    skip: int = Query(0, ge=0),
    limit: int = Query(100, ge=1, le=500),
) -> list[CategoryProductRead]:
    return list(await CategoryProductService(db).list(skip=skip, limit=limit))  # type: ignore[return-value]


@router.post(
    "/product-categories",
    response_model=CategoryProductRead,
    status_code=status.HTTP_201_CREATED,
)
async def create_product_category(
    payload: CategoryProductCreate,
    db: DbSession,
    user: CurrentUser,
    _perm: Annotated[None, Depends(require_permission("categories.manage"))],
) -> CategoryProductRead:
    service = CategoryProductService(db)
    data = payload.model_dump()
    data["slug"] = payload.slug or await service.unique_slug(payload.name)
    data["created_by"] = user.id
    return await service.create(data)  # type: ignore[return-value]


@router.get("/product-categories/{category_id}", response_model=CategoryProductRead)
async def get_product_category(
    category_id: int,
    db: DbSession,
    _: CurrentUser,
    _perm: Annotated[None, Depends(require_permission("products.view"))],
) -> CategoryProductRead:
    category = await CategoryProductService(db).get(category_id)
    if category is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Category not found")
    return category  # type: ignore[return-value]


@router.patch("/product-categories/{category_id}", response_model=CategoryProductRead)
async def update_product_category(
    category_id: int,
    payload: CategoryProductUpdate,
    db: DbSession,
    _: CurrentUser,
    _perm: Annotated[None, Depends(require_permission("categories.manage"))],
) -> CategoryProductRead:
    service = CategoryProductService(db)
    category = await service.get(category_id)
    if category is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Category not found")
    return await service.update(category, payload.model_dump(exclude_unset=True))  # type: ignore[return-value]


@router.delete("/product-categories/{category_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_product_category(
    category_id: int,
    db: DbSession,
    _: CurrentUser,
    _perm: Annotated[None, Depends(require_permission("categories.manage"))],
) -> None:
    service = CategoryProductService(db)
    category = await service.get(category_id)
    if category is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Category not found")
    await service.delete(category)


# --- Products ----------------------------------------------------------------
@router.get("/products", response_model=list[ProductRead])
async def list_products(
    db: DbSession,
    _: CurrentUser,
    _perm: Annotated[None, Depends(require_permission("products.view"))],
    category_product_id: int | None = Query(default=None),
    skip: int = Query(0, ge=0),
    limit: int = Query(100, ge=1, le=1000),
) -> list[ProductRead]:
    items = await ProductService(db).list(
        skip=skip, limit=limit, category_product_id=category_product_id
    )
    return list(items)  # type: ignore[return-value]


@router.post("/products", response_model=ProductRead, status_code=status.HTTP_201_CREATED)
async def create_product(
    payload: ProductCreate,
    db: DbSession,
    user: CurrentUser,
    _perm: Annotated[None, Depends(require_permission("products.manage"))],
) -> ProductRead:
    service = ProductService(db)
    data = payload.model_dump()
    data["slug"] = payload.slug or await service.unique_slug(payload.name)
    data["created_by"] = user.id
    return await service.create(data)  # type: ignore[return-value]


@router.get("/products/by-uuid/{uuid}", response_model=ProductRead)
async def get_product_by_uuid(
    uuid: str,
    db: DbSession,
    _: CurrentUser,
    _perm: Annotated[None, Depends(require_permission("products.view"))],
) -> ProductRead:
    from sqlalchemy import select as sa_select

    from app.modules.catalog.models import Product as ProductModel
    result = await db.execute(sa_select(ProductModel).where(ProductModel.uuid == uuid))
    product = result.scalar_one_or_none()
    if product is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Product not found")
    return product  # type: ignore[return-value]


@router.get("/products/{product_id}", response_model=ProductRead)
async def get_product(
    product_id: int,
    db: DbSession,
    _: CurrentUser,
    _perm: Annotated[None, Depends(require_permission("products.view"))],
) -> ProductRead:
    product = await ProductService(db).get(product_id)
    if product is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Product not found")
    return product  # type: ignore[return-value]


@router.patch("/products/{product_id}", response_model=ProductRead)
async def update_product(
    product_id: int,
    payload: ProductUpdate,
    db: DbSession,
    _: CurrentUser,
    _perm: Annotated[None, Depends(require_permission("products.manage"))],
) -> ProductRead:
    service = ProductService(db)
    product = await service.get(product_id)
    if product is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Product not found")
    return await service.update(product, payload.model_dump(exclude_unset=True))  # type: ignore[return-value]


@router.delete("/products/{product_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_product(
    product_id: int,
    db: DbSession,
    _: CurrentUser,
    _perm: Annotated[None, Depends(require_permission("products.manage"))],
) -> None:
    service = ProductService(db)
    product = await service.get(product_id)
    if product is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Product not found")
    await service.delete(product)


# --- Store categories ----------------------------------------------------------
@router.get("/store-categories", response_model=list[CategoryStoreRead])
async def list_store_categories(
    db: DbSession,
    _: CurrentUser,
    _perm: Annotated[None, Depends(require_permission("stores.view"))],
    skip: int = Query(0, ge=0),
    limit: int = Query(100, ge=1, le=500),
) -> list[CategoryStoreRead]:
    return list(await CategoryStoreService(db).list(skip=skip, limit=limit))  # type: ignore[return-value]


@router.post(
    "/store-categories",
    response_model=CategoryStoreRead,
    status_code=status.HTTP_201_CREATED,
)
async def create_store_category(
    payload: CategoryStoreCreate,
    db: DbSession,
    user: CurrentUser,
    _perm: Annotated[None, Depends(require_permission("stores.manage"))],
) -> CategoryStoreRead:
    service = CategoryStoreService(db)
    data = payload.model_dump()
    data["slug"] = payload.slug or await service.unique_slug(payload.name)
    data["created_by"] = user.id
    return await service.create(data)  # type: ignore[return-value]


@router.get("/store-categories/{category_id}", response_model=CategoryStoreRead)
async def get_store_category(
    category_id: int,
    db: DbSession,
    _: CurrentUser,
    _perm: Annotated[None, Depends(require_permission("stores.view"))],
) -> CategoryStoreRead:
    category = await CategoryStoreService(db).get(category_id)
    if category is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Category not found")
    return category  # type: ignore[return-value]


@router.patch("/store-categories/{category_id}", response_model=CategoryStoreRead)
async def update_store_category(
    category_id: int,
    payload: CategoryStoreUpdate,
    db: DbSession,
    _: CurrentUser,
    _perm: Annotated[None, Depends(require_permission("stores.manage"))],
) -> CategoryStoreRead:
    service = CategoryStoreService(db)
    category = await service.get(category_id)
    if category is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Category not found")
    return await service.update(category, payload.model_dump(exclude_unset=True))  # type: ignore[return-value]


@router.delete("/store-categories/{category_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_store_category(
    category_id: int,
    db: DbSession,
    _: CurrentUser,
    _perm: Annotated[None, Depends(require_permission("stores.manage"))],
) -> None:
    service = CategoryStoreService(db)
    category = await service.get(category_id)
    if category is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Category not found")
    await service.delete(category)
