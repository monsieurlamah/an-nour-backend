"""Small, reusable helper functions."""

import re
import secrets
from datetime import UTC, datetime


def utcnow() -> datetime:
    """Timezone-aware current UTC datetime."""
    return datetime.now(UTC)


_SLUG_RE = re.compile(r"[^a-z0-9]+")


def slugify(value: str) -> str:
    """Turn a label into a URL-safe slug, e.g. 'Café Léon' -> 'cafe-leon'."""
    import unicodedata

    normalized = unicodedata.normalize("NFKD", value)
    ascii_only = normalized.encode("ascii", "ignore").decode("ascii")
    return _SLUG_RE.sub("-", ascii_only.strip().lower()).strip("-") or "n-a"


def generate_reference(prefix: str, length: int = 8) -> str:
    """Generate a short, human-readable reference like ``RC-9F3A2B71``."""
    token = secrets.token_hex(length // 2).upper()
    return f"{prefix}-{token}"


def normalize_email(email: str | None) -> str | None:
    """Lower-case and trim an email so case variants are never duplicated."""
    if email is None:
        return None
    cleaned = email.strip().lower()
    return cleaned or None


def normalize_phone(raw: str | None, default_country_code: str = "224") -> str | None:
    """Canonicalise a phone number to E.164-like form (e.g. ``+224620000000``).

    Guarantees that the same line typed in different ways collapses to one value
    so it can be enforced unique:
      ``+224 620 00 00 00`` / ``620000000`` / ``00224620000000`` / ``0620000000``
      all become ``+224620000000``.

    Numbers given in international form for another country (``+33...``) keep
    their own country code.
    """
    if raw is None:
        return None
    s = raw.strip()
    if not s:
        return None

    international = s.startswith("+") or s.startswith("00")
    digits = re.sub(r"\D", "", s)
    if s.startswith("00"):
        digits = digits[2:]  # drop the international call prefix (e.g. 00224 -> 224)
    if not digits:
        return None

    cc = default_country_code
    if international:
        if digits.startswith(cc):
            # Strip the default country code + any trunk '0' to get the canonical line.
            return f"+{cc}{digits[len(cc):].lstrip('0')}"
        # International number for another country: keep its own country code.
        return f"+{digits}"
    if digits.startswith(cc):
        return f"+{cc}{digits[len(cc):].lstrip('0')}"
    # National number (may carry a trunk '0').
    return f"+{cc}{digits.lstrip('0')}"
