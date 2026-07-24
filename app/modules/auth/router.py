"""Authentication routes: register, verify-email, resend-otp, login, refresh, me."""

from typing import Annotated

from fastapi import APIRouter, Depends, status
from fastapi.security import OAuth2PasswordRequestForm
from sqlalchemy import select

from app.api.deps import CurrentUser, DbSession
from app.modules.access.models import Group, UserGroup
from app.modules.access.services import SUPER_ADMIN_SLUG, AccessService
from app.modules.auth.schemas import (
    ForgotPasswordRequest,
    MessageResponse,
    RegisterRequest,
    RegisterResponse,
    ResendOtpRequest,
    ResetPasswordConfirm,
    Token,
    TokenRefreshRequest,
    VerifyEmailRequest,
)
from app.modules.auth.services import AuthService
from app.modules.users.schemas import UserMeRead

router = APIRouter(prefix="/auth", tags=["auth"])


@router.post("/register", response_model=RegisterResponse, status_code=status.HTTP_201_CREATED)
async def register(payload: RegisterRequest, db: DbSession) -> RegisterResponse:
    user = await AuthService(db).register(payload)
    return RegisterResponse(
        message="Un code de vérification a été envoyé à votre adresse e-mail.",
        email=user.email,
    )


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
    # OAuth2 form uses ``username`` — we treat it as the email.
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
