"""HTTP routes for the access (RBAC) module: roles, groups, permissions, links.

Every route here manages the RBAC model itself (who can do what) — the most
sensitive module in the platform. All of it requires ``access.manage``,
enforced once at the router level rather than repeated per route.
"""

from fastapi import APIRouter, Depends, HTTPException, Query, status

from app.api.deps import CurrentUser, DbSession
from app.core.authz import require_permission
from app.modules.access.schemas import (
    GroupCreate,
    GroupPermissionCreate,
    GroupPermissionRead,
    GroupRead,
    GroupUpdate,
    PermissionCreate,
    PermissionRead,
    PermissionUpdate,
    RoleCreate,
    RoleRead,
    RoleUpdate,
    UserGroupCreate,
    UserGroupRead,
    UserPermissionCreate,
    UserPermissionRead,
)
from app.modules.access.services import (
    GroupPermissionService,
    GroupService,
    PermissionService,
    RoleService,
    UserGroupService,
    UserPermissionService,
)

router = APIRouter(
    prefix="/access",
    tags=["access"],
    dependencies=[Depends(require_permission("access.manage"))],
)


# --- Roles -------------------------------------------------------------------
@router.get("/roles", response_model=list[RoleRead])
async def list_roles(
    db: DbSession,
    _: CurrentUser,
    skip: int = Query(0, ge=0),
    limit: int = Query(100, ge=1, le=500),
) -> list[RoleRead]:
    return list(await RoleService(db).list(skip=skip, limit=limit))  # type: ignore[return-value]


@router.post("/roles", response_model=RoleRead, status_code=status.HTTP_201_CREATED)
async def create_role(payload: RoleCreate, db: DbSession, user: CurrentUser) -> RoleRead:
    service = RoleService(db)
    slug = payload.slug or await service.unique_slug(payload.name)
    return await service.create(  # type: ignore[return-value]
        {
            "name": payload.name,
            "slug": slug,
            "description": payload.description,
            "created_by": user.id,
        }
    )


@router.get("/roles/{role_id}", response_model=RoleRead)
async def get_role(role_id: int, db: DbSession, _: CurrentUser) -> RoleRead:
    role = await RoleService(db).get(role_id)
    if role is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Role not found")
    return role  # type: ignore[return-value]


@router.patch("/roles/{role_id}", response_model=RoleRead)
async def update_role(
    role_id: int, payload: RoleUpdate, db: DbSession, _: CurrentUser
) -> RoleRead:
    service = RoleService(db)
    role = await service.get(role_id)
    if role is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Role not found")
    return await service.update(role, payload.model_dump(exclude_unset=True))  # type: ignore[return-value]


@router.delete("/roles/{role_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_role(role_id: int, db: DbSession, _: CurrentUser) -> None:
    service = RoleService(db)
    role = await service.get(role_id)
    if role is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Role not found")
    await service.delete(role)


# --- Groups ------------------------------------------------------------------
@router.get("/groups", response_model=list[GroupRead])
async def list_groups(
    db: DbSession,
    _: CurrentUser,
    skip: int = Query(0, ge=0),
    limit: int = Query(100, ge=1, le=500),
) -> list[GroupRead]:
    return list(await GroupService(db).list(skip=skip, limit=limit))  # type: ignore[return-value]


@router.post("/groups", response_model=GroupRead, status_code=status.HTTP_201_CREATED)
async def create_group(payload: GroupCreate, db: DbSession, _: CurrentUser) -> GroupRead:
    service = GroupService(db)
    slug = payload.slug or await service.unique_slug(payload.name)
    return await service.create(  # type: ignore[return-value]
        {"name": payload.name, "slug": slug, "description": payload.description}
    )


@router.get("/groups/{group_id}", response_model=GroupRead)
async def get_group(group_id: int, db: DbSession, _: CurrentUser) -> GroupRead:
    group = await GroupService(db).get(group_id)
    if group is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Group not found")
    return group  # type: ignore[return-value]


@router.patch("/groups/{group_id}", response_model=GroupRead)
async def update_group(
    group_id: int, payload: GroupUpdate, db: DbSession, _: CurrentUser
) -> GroupRead:
    service = GroupService(db)
    group = await service.get(group_id)
    if group is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Group not found")
    return await service.update(group, payload.model_dump(exclude_unset=True))  # type: ignore[return-value]


@router.delete("/groups/{group_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_group(group_id: int, db: DbSession, _: CurrentUser) -> None:
    service = GroupService(db)
    group = await service.get(group_id)
    if group is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Group not found")
    await service.delete(group)


# --- Permissions -------------------------------------------------------------
@router.get("/permissions", response_model=list[PermissionRead])
async def list_permissions(
    db: DbSession,
    _: CurrentUser,
    module: str | None = Query(default=None),
    skip: int = Query(0, ge=0),
    limit: int = Query(200, ge=1, le=500),
) -> list[PermissionRead]:
    items = await PermissionService(db).list(skip=skip, limit=limit, module=module)
    return list(items)  # type: ignore[return-value]


@router.post("/permissions", response_model=PermissionRead, status_code=status.HTTP_201_CREATED)
async def create_permission(
    payload: PermissionCreate, db: DbSession, _: CurrentUser
) -> PermissionRead:
    return await PermissionService(db).create(payload.model_dump())  # type: ignore[return-value]


@router.get("/permissions/{permission_id}", response_model=PermissionRead)
async def get_permission(permission_id: int, db: DbSession, _: CurrentUser) -> PermissionRead:
    permission = await PermissionService(db).get(permission_id)
    if permission is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Permission not found")
    return permission  # type: ignore[return-value]


@router.patch("/permissions/{permission_id}", response_model=PermissionRead)
async def update_permission(
    permission_id: int, payload: PermissionUpdate, db: DbSession, _: CurrentUser
) -> PermissionRead:
    service = PermissionService(db)
    permission = await service.get(permission_id)
    if permission is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Permission not found")
    return await service.update(permission, payload.model_dump(exclude_unset=True))  # type: ignore[return-value]


@router.delete("/permissions/{permission_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_permission(permission_id: int, db: DbSession, _: CurrentUser) -> None:
    service = PermissionService(db)
    permission = await service.get(permission_id)
    if permission is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Permission not found")
    await service.delete(permission)


# --- User ↔ Group ------------------------------------------------------------
@router.get("/user-groups", response_model=list[UserGroupRead])
async def list_user_groups(
    db: DbSession,
    _: CurrentUser,
    user_id: int | None = Query(default=None),
    group_id: int | None = Query(default=None),
) -> list[UserGroupRead]:
    items = await UserGroupService(db).list(user_id=user_id, group_id=group_id, limit=500)
    return list(items)  # type: ignore[return-value]


@router.post("/user-groups", response_model=UserGroupRead, status_code=status.HTTP_201_CREATED)
async def assign_user_group(
    payload: UserGroupCreate, db: DbSession, _: CurrentUser
) -> UserGroupRead:
    return await UserGroupService(db).create(payload.model_dump())  # type: ignore[return-value]


@router.delete("/user-groups/{link_id}", status_code=status.HTTP_204_NO_CONTENT)
async def remove_user_group(link_id: int, db: DbSession, _: CurrentUser) -> None:
    service = UserGroupService(db)
    link = await service.get(link_id)
    if link is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Assignment not found")
    await service.delete(link)


# --- Group ↔ Permission ------------------------------------------------------
@router.get("/group-permissions", response_model=list[GroupPermissionRead])
async def list_group_permissions(
    db: DbSession,
    _: CurrentUser,
    group_id: int | None = Query(default=None),
) -> list[GroupPermissionRead]:
    items = await GroupPermissionService(db).list(group_id=group_id, limit=500)
    return list(items)  # type: ignore[return-value]


@router.post(
    "/group-permissions",
    response_model=GroupPermissionRead,
    status_code=status.HTTP_201_CREATED,
)
async def assign_group_permission(
    payload: GroupPermissionCreate, db: DbSession, _: CurrentUser
) -> GroupPermissionRead:
    return await GroupPermissionService(db).create(payload.model_dump())  # type: ignore[return-value]


@router.delete("/group-permissions/{link_id}", status_code=status.HTTP_204_NO_CONTENT)
async def remove_group_permission(link_id: int, db: DbSession, _: CurrentUser) -> None:
    service = GroupPermissionService(db)
    link = await service.get(link_id)
    if link is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Assignment not found")
    await service.delete(link)


# --- User ↔ Permission (per-store override) ----------------------------------
@router.get("/user-permissions", response_model=list[UserPermissionRead])
async def list_user_permissions(
    db: DbSession,
    _: CurrentUser,
    user_id: int | None = Query(default=None),
    store_id: int | None = Query(default=None),
) -> list[UserPermissionRead]:
    items = await UserPermissionService(db).list(user_id=user_id, store_id=store_id, limit=500)
    return list(items)  # type: ignore[return-value]


@router.post(
    "/user-permissions",
    response_model=UserPermissionRead,
    status_code=status.HTTP_201_CREATED,
)
async def assign_user_permission(
    payload: UserPermissionCreate, db: DbSession, _: CurrentUser
) -> UserPermissionRead:
    return await UserPermissionService(db).create(payload.model_dump())  # type: ignore[return-value]


@router.delete("/user-permissions/{link_id}", status_code=status.HTTP_204_NO_CONTENT)
async def remove_user_permission(link_id: int, db: DbSession, _: CurrentUser) -> None:
    service = UserPermissionService(db)
    link = await service.get(link_id)
    if link is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Assignment not found")
    await service.delete(link)
