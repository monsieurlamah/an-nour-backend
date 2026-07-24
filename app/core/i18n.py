"""Per-request i18n for backend error messages.

Usage:
    from app.core.i18n import t
    raise HTTPException(status_code=400, detail=t("email_taken"))

The current language is set per-request by the AcceptLanguageMiddleware in main.py.
Default is "fr" (French) when no header is present.
"""

import contextvars
from typing import Literal

Lang = Literal["fr", "en"]

_current_lang: contextvars.ContextVar[Lang] = contextvars.ContextVar("lang", default="fr")

MESSAGES: dict[str, dict[str, str]] = {
    # ── users ─────────────────────────────────────────────────────────────────
    "email_taken": {
        "en": "A user with this email already exists",
        "fr": "Un utilisateur avec cet e-mail existe déjà",
    },
    "phone_taken": {
        "en": "A user with this phone number already exists",
        "fr": "Un utilisateur avec ce numéro de téléphone existe déjà",
    },
    "user_not_found": {
        "en": "User not found",
        "fr": "Utilisateur introuvable",
    },
    # ── auth / credentials ────────────────────────────────────────────────────
    "invalid_credentials": {
        "en": "Could not validate credentials",
        "fr": "Identifiants non valides",
    },
    "incorrect_credentials": {
        "en": "Incorrect email or password",
        "fr": "E-mail ou mot de passe incorrect",
    },
    "incorrect_current_password": {
        "en": "Current password is incorrect",
        "fr": "Le mot de passe actuel est incorrect",
    },
    "inactive_account": {
        "en": "Inactive user account",
        "fr": "Compte utilisateur inactif",
    },
    "invalid_refresh_token": {
        "en": "Invalid refresh token",
        "fr": "Jeton de rafraîchissement invalide",
    },
    "invalid_token_type": {
        "en": "Invalid token type",
        "fr": "Type de jeton invalide",
    },
    "user_no_longer_valid": {
        "en": "User no longer valid",
        "fr": "Session invalide, veuillez vous reconnecter",
    },
    # ── email verification (OTP) ───────────────────────────────────────────────
    "email_already_verified": {
        "en": "Email already verified",
        "fr": "E-mail déjà vérifié",
    },
    "otp_expired": {
        "en": "Verification code expired or not found. Please request a new one.",
        "fr": "Code de vérification expiré ou introuvable. Veuillez en demander un nouveau.",
    },
    "too_many_attempts": {
        "en": "Too many attempts. Please request a new code.",
        "fr": "Trop de tentatives. Veuillez demander un nouveau code.",
    },
    "invalid_otp": {
        "en": "Invalid verification code",
        "fr": "Code de vérification invalide",
    },
    "otp_resend_wait": {
        "en": "Please wait {wait}s before requesting a new code.",
        "fr": "Veuillez patienter {wait}s avant de demander un nouveau code.",
    },
    # ── password reset ────────────────────────────────────────────────────────
    "password_reset_invalid": {
        "en": "This reset link is invalid or has expired. Please request a new one.",
        "fr": "Ce lien de réinitialisation est invalide ou a expiré. "
        "Veuillez en demander un nouveau.",
    },
    # ── clients ───────────────────────────────────────────────────────────────
    "client_not_found": {
        "en": "Client not found",
        "fr": "Client introuvable",
    },
    "client_phone_taken": {
        "en": "A client with this phone number already exists",
        "fr": "Un client avec ce numéro de téléphone existe déjà",
    },
    "client_email_taken": {
        "en": "A client with this email already exists",
        "fr": "Un client avec cet e-mail existe déjà",
    },
    "client_contact_required": {
        "en": "A phone number or email address is required",
        "fr": "Un numéro de téléphone ou une adresse e-mail est requis",
    },
    # ── authorization (RBAC / store scope) ──────────────────────────────────────
    "permission_denied": {
        "en": "You do not have permission to perform this action",
        "fr": "Vous n'avez pas la permission d'effectuer cette action",
    },
    "store_out_of_scope": {
        "en": "This action is outside the stores you are assigned to",
        "fr": "Cette action concerne une boutique en dehors de votre périmètre",
    },
    "store_id_required": {
        "en": "You belong to multiple stores — store_id must be specified",
        "fr": "Vous êtes rattaché à plusieurs boutiques — store_id doit être précisé",
    },
    "no_store_assigned": {
        "en": "Your account is not assigned to any store yet",
        "fr": "Votre compte n'est rattaché à aucune boutique pour le moment",
    },
}


def set_lang(lang: str) -> None:
    """Called by middleware once per request."""
    if lang in ("fr", "en"):
        _current_lang.set(lang)  # type: ignore[arg-type]


def get_lang() -> Lang:
    return _current_lang.get()


def t(key: str, **kwargs: object) -> str:
    """Return the localized message for *key* in the current request language.

    Falls back to French, then to the raw key if the message is missing.
    """
    lang = get_lang()
    entry = MESSAGES.get(key, {})
    msg: str = entry.get(lang) or entry.get("fr") or key
    return msg.format(**kwargs) if kwargs else msg
