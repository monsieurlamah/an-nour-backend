"""Shared FastAPI dependencies (auth, current user)."""

from typing import Annotated

from fastapi import Depends, HTTPException, status
from fastapi.security import OAuth2PasswordBearer
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import settings
from app.core.i18n import t
from app.database.enums import UserStatus
from app.database.session import get_db
from app.modules.users.models import User
from app.modules.users.services import UserService
from app.security.jwt import ACCESS_TOKEN_TYPE, InvalidTokenError, decode_token

oauth2_scheme = OAuth2PasswordBearer(tokenUrl=f"{settings.API_V1_PREFIX}/auth/login")

DbSession = Annotated[AsyncSession, Depends(get_db)]

def _credentials_exception() -> HTTPException:
    return HTTPException(
        status_code=status.HTTP_401_UNAUTHORIZED,
        detail=t("invalid_credentials"),
        headers={"WWW-Authenticate": "Bearer"},
    )


async def get_current_user(
    token: Annotated[str, Depends(oauth2_scheme)],
    db: DbSession,
) -> User:
    try:
        payload = decode_token(token)
    except InvalidTokenError as exc:
        raise _credentials_exception() from exc

    if payload.get("type") != ACCESS_TOKEN_TYPE:
        raise _credentials_exception()

    subject = payload.get("sub")
    if subject is None:
        raise _credentials_exception()

    user = await UserService(db).get(int(subject))
    if user is None or user.deleted_at is not None:
        raise _credentials_exception()
    return user


async def get_current_active_user(
    current_user: Annotated[User, Depends(get_current_user)],
) -> User:
    if not current_user.is_activated or current_user.status != UserStatus.active:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN, detail=t("inactive_account")
        )
    return current_user


CurrentUser = Annotated[User, Depends(get_current_active_user)]
