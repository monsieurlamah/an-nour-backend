"""Authentication business logic (with email-OTP verification)."""

import secrets
from datetime import UTC, datetime, timedelta

from fastapi import HTTPException, status
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import settings
from app.core.i18n import t
from app.core.logging import get_logger
from app.database.enums import UserStatus
from app.modules.auth.models import EmailVerification
from app.modules.auth.schemas import RegisterRequest, Token
from app.modules.users.models import User
from app.modules.users.schemas import UserCreate
from app.modules.users.services import UserService
from app.security.jwt import (
    REFRESH_TOKEN_TYPE,
    InvalidTokenError,
    create_access_token,
    create_refresh_token,
    decode_token,
)
from app.security.otp import generate_otp, hash_otp, verify_otp
from app.security.password import hash_password, verify_password
from app.utils.email import send_otp_email, send_password_reset_email
from app.utils.helpers import utcnow

logger = get_logger("auth")

# Machine-readable error code the frontend can branch on.
EMAIL_NOT_VERIFIED = "EMAIL_NOT_VERIFIED"


def _naive_utcnow() -> datetime:
    """Naive UTC datetime (matches the DB's tz-naive DATETIME columns)."""
    return datetime.now(UTC).replace(tzinfo=None)


class AuthService:
    def __init__(self, db: AsyncSession) -> None:
        self.db = db
        self.users = UserService(db)

    # ----------------------------- helpers ---------------------------------
    async def _latest_verification(
        self, user_id: int, purpose: str = "email_verification"
    ) -> EmailVerification | None:
        result = await self.db.execute(
            select(EmailVerification)
            .where(EmailVerification.user_id == user_id, EmailVerification.purpose == purpose)
            .order_by(EmailVerification.id.desc())
            .limit(1)
        )
        return result.scalar_one_or_none()

    async def _issue_otp(self, user: User) -> None:
        """Invalidate any pending code, create a fresh one and email it."""
        # Invalidate previous active codes.
        previous = await self.db.execute(
            select(EmailVerification).where(
                EmailVerification.user_id == user.id,
                EmailVerification.consumed_at.is_(None),
            )
        )
        now = _naive_utcnow()
        for row in previous.scalars():
            row.consumed_at = now
            self.db.add(row)

        code = generate_otp()
        verification = EmailVerification(
            user_id=user.id,
            code_hash=hash_otp(code),
            expires_at=now + timedelta(minutes=settings.OTP_EXPIRE_MINUTES),
        )
        self.db.add(verification)
        await self.db.flush()

        # In development, log the code so the flow can be tested without SMTP.
        if settings.ENVIRONMENT == "development":
            logger.info("DEV OTP for %s: %s", user.email, code)

        await send_otp_email(user.email, code, name=user.firstname)

    # ----------------------------- register --------------------------------
    async def register(self, payload: RegisterRequest) -> User:
        # Uniqueness of email AND phone is enforced by UserService.create
        # (with phone normalisation, so +224 / local variants never duplicate).
        user = await self.users.create(
            UserCreate(
                firstname=payload.firstname,
                lastname=payload.lastname,
                email=payload.email,
                password=payload.password,
                phone=payload.phone,
                status=UserStatus.invited,
                is_activated=False,
            )
        )
        await self._issue_otp(user)
        return user

    # ----------------------------- verify ----------------------------------
    async def verify_email(self, email: str, code: str) -> Token:
        user = await self.users.get_by_email(email)
        if user is None or user.deleted_at is not None:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND, detail=t("user_not_found")
            )
        if user.email_verified:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST, detail=t("email_already_verified")
            )

        verification = await self._latest_verification(user.id)
        now = _naive_utcnow()
        if (
            verification is None
            or verification.consumed_at is not None
            or verification.expires_at < now
        ):
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail=t("otp_expired"),
            )
        if verification.attempts >= settings.OTP_MAX_ATTEMPTS:
            raise HTTPException(
                status_code=status.HTTP_429_TOO_MANY_REQUESTS,
                detail=t("too_many_attempts"),
            )

        verification.attempts += 1
        if not verify_otp(code, verification.code_hash):
            self.db.add(verification)
            await self.db.flush()
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST, detail=t("invalid_otp")
            )

        # Success: consume the code and activate the account.
        verification.consumed_at = now
        user.email_verified = True
        user.is_activated = True
        user.status = UserStatus.active
        user.last_login_at = utcnow()
        self.db.add_all([verification, user])
        await self.db.flush()
        return self.issue_tokens(user)

    # ----------------------------- resend ----------------------------------
    async def resend_otp(self, email: str) -> str:
        """(Re)send a verification code. Generic response to avoid enumeration."""
        generic = "If the account exists and is not verified, a code has been sent."
        user = await self.users.get_by_email(email)
        if user is None or user.deleted_at is not None or user.email_verified:
            return generic

        latest = await self._latest_verification(user.id)
        if latest is not None:
            elapsed = (_naive_utcnow() - latest.created_at).total_seconds()
            if elapsed < settings.OTP_RESEND_COOLDOWN_SECONDS:
                wait = int(settings.OTP_RESEND_COOLDOWN_SECONDS - elapsed)
                raise HTTPException(
                    status_code=status.HTTP_429_TOO_MANY_REQUESTS,
                    detail=t("otp_resend_wait", wait=wait),
                )

        await self._issue_otp(user)
        return generic

    # ----------------------------- password reset ---------------------------
    async def forgot_password(self, email: str) -> str:
        """Email a password-reset link. Generic response to avoid enumeration."""
        generic = (
            "Si un compte existe avec cette adresse, un e-mail de "
            "réinitialisation a été envoyé."
        )
        user = await self.users.get_by_email(email)
        if user is None or user.deleted_at is not None:
            return generic

        latest = await self._latest_verification(user.id, purpose="password_reset")
        now = _naive_utcnow()
        if latest is not None and latest.consumed_at is None:
            elapsed = (now - latest.created_at).total_seconds()
            if elapsed < settings.PASSWORD_RESET_RESEND_COOLDOWN_SECONDS:
                wait = int(settings.PASSWORD_RESET_RESEND_COOLDOWN_SECONDS - elapsed)
                raise HTTPException(
                    status_code=status.HTTP_429_TOO_MANY_REQUESTS,
                    detail=t("otp_resend_wait", wait=wait),
                )
            latest.consumed_at = now
            self.db.add(latest)

        token = secrets.token_urlsafe(32)
        verification = EmailVerification(
            user_id=user.id,
            code_hash=hash_otp(token),
            purpose="password_reset",
            expires_at=now + timedelta(minutes=settings.PASSWORD_RESET_EXPIRE_MINUTES),
        )
        self.db.add(verification)
        await self.db.flush()

        if settings.ENVIRONMENT == "development":
            logger.info("DEV password reset token for %s: %s", user.email, token)

        reset_url = f"{settings.FRONTEND_URL}/reset-password?token={token}"
        await send_password_reset_email(user.email, reset_url, name=user.firstname)
        return generic

    async def reset_password(self, token: str, new_password: str) -> None:
        result = await self.db.execute(
            select(EmailVerification).where(
                EmailVerification.purpose == "password_reset",
                EmailVerification.code_hash == hash_otp(token),
            )
        )
        verification = result.scalar_one_or_none()
        now = _naive_utcnow()
        if (
            verification is None
            or verification.consumed_at is not None
            or verification.expires_at < now
        ):
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST, detail=t("password_reset_invalid")
            )

        user = await self.users.get(verification.user_id)
        if user is None or user.deleted_at is not None:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST, detail=t("password_reset_invalid")
            )

        verification.consumed_at = now
        user.password = hash_password(new_password)
        user.must_change_password = False
        self.db.add_all([verification, user])
        await self.db.flush()

    # ----------------------------- login -----------------------------------
    async def authenticate(self, email: str, password: str) -> User:
        user = await self.users.get_by_email(email)
        if (
            user is None
            or user.deleted_at is not None
            or not verify_password(password, user.password)
        ):
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED,
                detail=t("incorrect_credentials"),
                headers={"WWW-Authenticate": "Bearer"},
            )
        if not user.email_verified:
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN, detail=EMAIL_NOT_VERIFIED
            )
        if not user.is_activated or user.status != UserStatus.active:
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN, detail=t("inactive_account")
            )
        return user

    @staticmethod
    def issue_tokens(user: User) -> Token:
        claims = {"email": user.email}
        return Token(
            access_token=create_access_token(user.id, extra_claims=claims),
            refresh_token=create_refresh_token(user.id),
        )

    async def login(self, email: str, password: str) -> Token:
        user = await self.authenticate(email, password)
        user.last_login_at = utcnow()
        self.db.add(user)
        await self.db.flush()
        return self.issue_tokens(user)

    # ----------------------------- refresh ---------------------------------
    async def refresh(self, refresh_token: str) -> Token:
        try:
            payload = decode_token(refresh_token)
        except InvalidTokenError as exc:
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED,
                detail=t("invalid_refresh_token"),
            ) from exc

        if payload.get("type") != REFRESH_TOKEN_TYPE:
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED, detail=t("invalid_token_type")
            )

        subject = payload.get("sub")
        user = await self.users.get(int(subject)) if subject is not None else None
        if user is None or user.deleted_at is not None:
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED, detail=t("user_no_longer_valid")
            )
        return self.issue_tokens(user)
