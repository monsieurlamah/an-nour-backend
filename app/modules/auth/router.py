"""Authentication routes: register, verify-email, resend-otp, login, refresh, me."""
from __future__ import annotations

from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, status
from fastapi.security import OAuth2PasswordRequestForm
from sqlalchemy import select

from app.api.deps import CurrentUser, DbSession
from app.core.i18n import t
from app.modules.access.models import Group, UserGroup
from app.modules.access.services import SUPER_ADMIN_SLUG, AccessService
from app.modules.auth.schemas import (
    ForgotPasswordRequest,
    MessageResponse,
    ResendOtpRequest,
    ResetPasswordConfirm,
    Token,
    TokenRefreshRequest,
    VerifyEmailRequest,
)
from app.modules.auth.services import AuthService
from app.modules.users.schemas import UserMeRead

router = APIRouter(prefix="/auth", tags=["auth"])


@router.post("/register")
async def register() -> None:
    """Self-registration is disabled — only a super-admin can create user
    accounts (POST /users). Kept as a stub, rather than removed, so the
    route can be re-enabled later without a client-facing API change."""
    raise HTTPException(status.HTTP_403_FORBIDDEN, detail=t("self_registration_disabled"))


@router.post("/verify-email", response_model=Token)
async def verify_email(payload: VerifyEmailRequest, db: DbSession) -> Token:
    return await AuthService(db).verify_email(str(payload.email), payload.code)


@router.post("/resend-otp", response_model=MessageResponse)
async def resend_otp(payload: ResendOtpRequest, db: DbSession) -> MessageResponse:
    message = await AuthService(db).resend_otp(str(payload.email))
    return MessageResponse(message=message)


@router.post("/forgot-password", response_model=MessageResponse)
async def forgot_password(payload: ForgotPasswordRequest, db: DbSession) -> MessageResponse:
    message = await AuthService(db).forgot_password(str(payload.email))
    return MessageResponse(message=message)


@router.post("/reset-password", status_code=status.HTTP_204_NO_CONTENT)
async def reset_password(payload: ResetPasswordConfirm, db: DbSession) -> None:
    await AuthService(db).reset_password(payload.token, payload.new_password)


@router.post("/login", response_model=Token)
async def login(
    db: DbSession,
    form_data: Annotated[OAuth2PasswordRequestForm, Depends()],
) -> Token:
    # OAuth2 form uses ``username`` — we accept either the email or the
    # identifiant there (AuthService.authenticate resolves whichever it is).
    return await AuthService(db).login(form_data.username, form_data.password)


@router.post("/refresh", response_model=Token)
async def refresh(payload: TokenRefreshRequest, db: DbSession) -> Token:
    return await AuthService(db).refresh(payload.refresh_token)


@router.get("/me", response_model=UserMeRead)
async def me(current_user: CurrentUser, db: DbSession) -> UserMeRead:
    access = AccessService(db)
    groups = await access.get_group_slugs(current_user.id)
    data = UserMeRead.model_validate(current_user)
    data.groups = groups
    data.permissions = await access.get_effective_permission_slugs(current_user.id)
    data.is_super_admin = SUPER_ADMIN_SLUG in groups
    return data


@router.get("/me/groups", response_model=list[str])
async def me_groups(current_user: CurrentUser, db: DbSession) -> list[str]:
    """Return the group slugs the current user belongs to."""
    result = await db.execute(
        select(Group.slug)
        .join(UserGroup, UserGroup.group_id == Group.id)
        .where(
            UserGroup.user_id == current_user.id,
            UserGroup.deleted_at.is_(None),
        )
    )
    return list(result.scalars().all())
