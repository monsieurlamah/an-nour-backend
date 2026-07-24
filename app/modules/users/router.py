"""HTTP routes for the users module."""

import secrets
import string
from typing import Annotated

from fastapi import APIRouter, BackgroundTasks, Depends, HTTPException, Query, status

from app.api.deps import CurrentUser, DbSession
from app.core.authz import UserStoreScope, require_permission
from app.core.i18n import t
from app.core.logging import get_logger
from app.modules.access.schemas import UserGroupRead
from app.modules.access.services import UserGroupService
from app.modules.common.store_scope import resolve_list_scope
from app.modules.stores.schemas import StoreUserRead
from app.modules.stores.services import StoreUserService
from app.modules.users.schemas import ChangePasswordRequest, UserCreate, UserRead, UserUpdate
from app.modules.users.services import UserService
from app.security.password import hash_password
from app.utils.email import send_welcome_email

logger = get_logger("users.router")

router = APIRouter(prefix="/users", tags=["users"])

_TEMP_ALPHABET = string.ascii_letters + string.digits


def _temp_password(length: int = 12) -> str:
    return "".join(secrets.choice(_TEMP_ALPHABET) for _ in range(length))


@router.get("/me", response_model=UserRead)
async def read_me(current_user: CurrentUser) -> UserRead:
    return current_user  # type: ignore[return-value]


@router.post("/me/change-password", status_code=status.HTTP_204_NO_CONTENT)
async def change_my_password(
    payload: ChangePasswordRequest, db: DbSession, current_user: CurrentUser
) -> None:
    await UserService(db).change_own_password(current_user, payload)


@router.get("", response_model=list[UserRead])
async def list_users(
    db: DbSession,
    _: CurrentUser,
    _perm: Annotated[None, Depends(require_permission("users.view"))],
    scope: UserStoreScope,
    skip: int = Query(0, ge=0),
    limit: int = Query(100, ge=1, le=500),
    group_id: int | None = Query(default=None),
    search: str | None = Query(default=None, max_length=100),
) -> list[UserRead]:
    # HQ-capable roles (super-admin, fournisseur) see the whole network; a
    # store-scoped caller (e.g. gérant-boutique) only ever sees users linked
    # to their own store(s) — never every user across the network.
    store_id = resolve_list_scope(None, scope)
    users = await UserService(db).list(
        skip=skip, limit=limit, group_id=group_id, search=search, store_id=store_id
    )
    return list(users)  # type: ignore[return-value]


@router.post("", response_model=UserRead, status_code=status.HTTP_201_CREATED)
async def create_user(
    payload: UserCreate,
    background_tasks: BackgroundTasks,
    db: DbSession,
    _: CurrentUser,
    _perm: Annotated[None, Depends(require_permission("users.manage"))],
) -> UserRead:
    plain_pw = payload.password  # capture before the service hashes it
    user = await UserService(db).create(payload)

    # Admin-created accounts: the admin vouches for the email address, so skip OTP.
    # When credentials are sent, force a password change on first login.
    user.email_verified = True
    user.must_change_password = payload.send_credentials
    db.add(user)
    await db.flush()
    await db.refresh(user)

    if payload.send_credentials:
        # Fire-and-forget: email is sent after the response is returned so the
        # creation endpoint remains fast even when SMTP is slow.
        email_to = user.email
        full_name = user.full_name
        logger.info("Queuing welcome email to %s", email_to)
        background_tasks.add_task(
            send_welcome_email,
            to=email_to,
            name=full_name,
            temp_password=plain_pw,
        )

    return user  # type: ignore[return-value]


@router.get("/{user_id}", response_model=UserRead)
async def get_user(
    user_id: int,
    db: DbSession,
    _: CurrentUser,
    _perm: Annotated[None, Depends(require_permission("users.view"))],
) -> UserRead:
    user = await UserService(db).get(user_id)
    if user is None or user.deleted_at is not None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=t("user_not_found"))
    return user  # type: ignore[return-value]


@router.patch("/{user_id}", response_model=UserRead)
async def update_user(
    user_id: int,
    payload: UserUpdate,
    db: DbSession,
    _: CurrentUser,
    _perm: Annotated[None, Depends(require_permission("users.manage"))],
) -> UserRead:
    service = UserService(db)
    user = await service.get(user_id)
    if user is None or user.deleted_at is not None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=t("user_not_found"))
    return await service.update(user, payload)  # type: ignore[return-value]


@router.delete("/{user_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_user(
    user_id: int,
    db: DbSession,
    _: CurrentUser,
    _perm: Annotated[None, Depends(require_permission("users.manage"))],
) -> None:
    service = UserService(db)
    user = await service.get(user_id)
    if user is None or user.deleted_at is not None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=t("user_not_found"))
    await service.soft_delete(user)


# --- User ↔ Group (shorthand on /users path) ---------------------------------
# Assigning/removing a group is an RBAC administration action -> access.manage.

@router.get("/{user_id}/groups", response_model=list[UserGroupRead])
async def get_user_groups(
    user_id: int,
    db: DbSession,
    _: CurrentUser,
    _perm: Annotated[None, Depends(require_permission("access.manage"))],
) -> list[UserGroupRead]:
    items = await UserGroupService(db).list(user_id=user_id, limit=50)
    return list(items)  # type: ignore[return-value]


@router.post("/{user_id}/groups", response_model=UserGroupRead, status_code=status.HTTP_201_CREATED)
async def assign_user_group(
    user_id: int,
    db: DbSession,
    _: CurrentUser,
    _perm: Annotated[None, Depends(require_permission("access.manage"))],
    group_id: int = Query(...),
) -> UserGroupRead:
    return await UserGroupService(db).create({"user_id": user_id, "group_id": group_id})  # type: ignore[return-value]


@router.delete("/{user_id}/groups/{link_id}", status_code=status.HTTP_204_NO_CONTENT)
async def remove_user_group(
    user_id: int,
    link_id: int,
    db: DbSession,
    _: CurrentUser,
    _perm: Annotated[None, Depends(require_permission("access.manage"))],
) -> None:
    svc = UserGroupService(db)
    link = await svc.get(link_id)
    if link is None or link.user_id != user_id:  # type: ignore[attr-defined]
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Group assignment not found")
    await svc.delete(link)


# --- User ↔ Store (read-only view of assignments) ----------------------------

@router.get("/{user_id}/stores", response_model=list[StoreUserRead])
async def get_user_stores(
    user_id: int,
    db: DbSession,
    _: CurrentUser,
    _perm: Annotated[None, Depends(require_permission("users.view"))],
) -> list[StoreUserRead]:
    items = await StoreUserService(db).list(user_id=user_id, limit=100)
    return list(items)  # type: ignore[return-value]


# --- Send credentials --------------------------------------------------------

@router.post("/{user_id}/send-credentials", status_code=status.HTTP_204_NO_CONTENT)
async def send_user_credentials(
    user_id: int,
    background_tasks: BackgroundTasks,
    db: DbSession,
    _: CurrentUser,
    _perm: Annotated[None, Depends(require_permission("users.manage"))],
) -> None:
    """Generate a new temp password, update the account, and email it to the user."""
    user = await UserService(db).get(user_id)
    if user is None or user.deleted_at is not None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, t("user_not_found"))

    temp_pw = _temp_password()
    user.password = hash_password(temp_pw)
    user.must_change_password = True
    db.add(user)
    await db.flush()

    logger.info("Queuing resend-credentials email to %s", user.email)
    background_tasks.add_task(
        send_welcome_email,
        to=user.email,
        name=user.full_name,
        temp_password=temp_pw,
    )
