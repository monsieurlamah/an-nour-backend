"""Password hashing utilities using bcrypt directly (no passlib dependency)."""

import re

import bcrypt

# bcrypt truncates silently beyond 72 bytes; we guard explicitly.
_MAX_PASSWORD_BYTES = 72

# Strong-password policy.
PASSWORD_MIN_LENGTH = 8
PASSWORD_MAX_LENGTH = 128
_SYMBOL_RE = re.compile(r"[^A-Za-z0-9]")


def validate_password_strength(password: str) -> str:
    """Ensure a password is robust. Returns it unchanged or raises ``ValueError``.

    Policy: 8–128 chars, with at least one lowercase letter, one uppercase
    letter, one digit and one symbol — and no whitespace.
    """
    if password is None or len(password) < PASSWORD_MIN_LENGTH:
        raise ValueError(
            f"Le mot de passe doit contenir au moins {PASSWORD_MIN_LENGTH} caractères."
        )
    if len(password) > PASSWORD_MAX_LENGTH:
        raise ValueError(
            f"Le mot de passe ne doit pas dépasser {PASSWORD_MAX_LENGTH} caractères."
        )
    if re.search(r"\s", password):
        raise ValueError("Le mot de passe ne doit pas contenir d'espaces.")
    if not re.search(r"[a-z]", password):
        raise ValueError("Le mot de passe doit contenir au moins une minuscule.")
    if not re.search(r"[A-Z]", password):
        raise ValueError("Le mot de passe doit contenir au moins une majuscule.")
    if not re.search(r"[0-9]", password):
        raise ValueError("Le mot de passe doit contenir au moins un chiffre.")
    if not _SYMBOL_RE.search(password):
        raise ValueError("Le mot de passe doit contenir au moins un symbole.")
    return password


def _truncate(password: str) -> bytes:
    return password.encode("utf-8")[:_MAX_PASSWORD_BYTES]


def hash_password(password: str) -> str:
    """Return a salted bcrypt hash for the given plain password."""
    hashed = bcrypt.hashpw(_truncate(password), bcrypt.gensalt(rounds=12))
    return hashed.decode("utf-8")


def verify_password(plain_password: str, hashed_password: str) -> bool:
    """Check a plain password against a stored bcrypt hash."""
    try:
        return bcrypt.checkpw(_truncate(plain_password), hashed_password.encode("utf-8"))
    except (ValueError, TypeError):
        return False
