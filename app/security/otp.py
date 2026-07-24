"""One-time password (OTP) generation and verification.

Codes are never stored in clear text: only a keyed HMAC-SHA256 digest is kept,
so a database leak does not expose valid codes. Verification is constant-time.
"""

import hashlib
import hmac
import secrets

from app.core.config import settings


def generate_otp(length: int | None = None) -> str:
    """Return a numeric OTP of the configured length (cryptographically secure)."""
    n = length or settings.OTP_LENGTH
    # secrets.randbelow keeps a uniform distribution; zero-pad to fixed width.
    upper = 10**n
    return str(secrets.randbelow(upper)).zfill(n)


def hash_otp(code: str) -> str:
    """Return a keyed HMAC-SHA256 hex digest of the code (salted by SECRET_KEY)."""
    return hmac.new(
        settings.SECRET_KEY.encode("utf-8"),
        code.encode("utf-8"),
        hashlib.sha256,
    ).hexdigest()


def verify_otp(code: str, hashed: str) -> bool:
    """Constant-time comparison of a candidate code against a stored digest."""
    return hmac.compare_digest(hash_otp(code), hashed)
