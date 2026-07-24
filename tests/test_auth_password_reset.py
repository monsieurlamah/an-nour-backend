"""Tests for the "mot de passe oublié" flow — AuthService.forgot_password /
reset_password. Email sending is monkeypatched (no real SMTP calls); the
reset token is captured from the URL passed to the (mocked) email sender,
mirroring how a user would actually receive and click it.
"""

import re
from datetime import UTC, datetime, timedelta

import pytest
from fastapi import HTTPException
from pydantic import ValidationError
from sqlalchemy import select

from app.modules.auth.models import EmailVerification
from app.modules.auth.schemas import ResetPasswordConfirm
from app.modules.auth.services import AuthService
from app.security.password import verify_password


@pytest.fixture
def sent_emails(monkeypatch):
    """Capture every call to the low-level send_email instead of hitting SMTP."""
    calls: list[dict] = []

    async def _fake_send_email(to, subject, html_body, text_body=None):
        calls.append({"to": to, "subject": subject, "html": html_body, "text": text_body})
        return True

    monkeypatch.setattr("app.utils.email.send_email", _fake_send_email)
    return calls


def _extract_token(html: str) -> str:
    # secrets.token_urlsafe() output is base64url: letters, digits, "-" and "_".
    match = re.search(r"token=([A-Za-z0-9_-]+)", html)
    assert match is not None, "reset token not found in email HTML"
    return match.group(1)


async def test_forgot_password_sends_email_and_creates_verification_row(db, user, sent_emails):
    message = await AuthService(db).forgot_password(user.email)

    assert "réinitialisation" in message.lower()
    assert len(sent_emails) == 1
    assert "/reset-password?token=" in sent_emails[0]["html"]

    rows = (
        await db.execute(
            select(EmailVerification).where(
                EmailVerification.user_id == user.id,
                EmailVerification.purpose == "password_reset",
            )
        )
    ).scalars().all()
    assert len(rows) == 1
    assert rows[0].consumed_at is None


async def test_forgot_password_unknown_email_is_generic_and_silent(db, sent_emails):
    message = await AuthService(db).forgot_password("nobody@nowhere.test")
    assert "réinitialisation" in message.lower()
    assert len(sent_emails) == 0  # never reveals whether the account exists


async def test_forgot_password_respects_cooldown(db, user, sent_emails):
    await AuthService(db).forgot_password(user.email)
    with pytest.raises(HTTPException) as exc:
        await AuthService(db).forgot_password(user.email)
    assert exc.value.status_code == 429
    assert len(sent_emails) == 1  # second call never sent


async def test_reset_password_with_valid_token_changes_password(db, user, sent_emails):
    await AuthService(db).forgot_password(user.email)
    token = _extract_token(sent_emails[0]["html"])

    await AuthService(db).reset_password(token, "NewStrongP@ss1")

    await db.refresh(user)
    assert verify_password("NewStrongP@ss1", user.password)
    assert user.must_change_password is False


async def test_reset_password_token_is_single_use(db, user, sent_emails):
    await AuthService(db).forgot_password(user.email)
    token = _extract_token(sent_emails[0]["html"])

    await AuthService(db).reset_password(token, "NewStrongP@ss1")
    with pytest.raises(HTTPException) as exc:
        await AuthService(db).reset_password(token, "AnotherP@ss2")
    assert exc.value.status_code == 400


async def test_reset_password_rejects_unknown_token(db):
    with pytest.raises(HTTPException) as exc:
        await AuthService(db).reset_password("not-a-real-token", "NewStrongP@ss1")
    assert exc.value.status_code == 400


async def test_reset_password_rejects_expired_token(db, user, sent_emails):
    await AuthService(db).forgot_password(user.email)
    token = _extract_token(sent_emails[0]["html"])

    rows = (
        await db.execute(
            select(EmailVerification).where(
                EmailVerification.user_id == user.id,
                EmailVerification.purpose == "password_reset",
            )
        )
    ).scalars().all()
    rows[0].expires_at = datetime.now(UTC).replace(tzinfo=None) - timedelta(minutes=1)
    db.add(rows[0])
    await db.commit()

    with pytest.raises(HTTPException) as exc:
        await AuthService(db).reset_password(token, "NewStrongP@ss1")
    assert exc.value.status_code == 400


def test_reset_password_schema_rejects_weak_password():
    with pytest.raises(ValidationError):
        ResetPasswordConfirm(token="x" * 20, new_password="weak")
