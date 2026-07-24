"""Email delivery over SMTP.

Sending is blocking (smtplib), so it is executed in a worker thread via
``asyncio.to_thread`` to avoid blocking the event loop. Configuration comes from
the application settings (SMTP_HOST/PORT/SSL, EMAIL, EMAIL_PASS).
"""

import asyncio
import smtplib
import ssl
from email.message import EmailMessage
from email.utils import formataddr

from app.core.config import settings
from app.core.logging import get_logger

logger = get_logger("email")


def _send_sync(message: EmailMessage) -> None:
    if settings.SMTP_USE_SSL:
        context = ssl.create_default_context()
        with smtplib.SMTP_SSL(settings.SMTP_HOST, settings.SMTP_PORT, context=context) as server:
            server.login(settings.EMAIL, settings.EMAIL_PASS)
            server.send_message(message)
    else:
        with smtplib.SMTP(settings.SMTP_HOST, settings.SMTP_PORT) as server:
            if settings.SMTP_USE_TLS:
                server.starttls(context=ssl.create_default_context())
            server.login(settings.EMAIL, settings.EMAIL_PASS)
            server.send_message(message)


async def send_email(
    to: str,
    subject: str,
    html_body: str,
    text_body: str | None = None,
) -> bool:
    """Send an HTML email. Returns True on success, False on failure (logged)."""
    if not settings.SMTP_HOST or not settings.EMAIL:
        logger.warning("SMTP is not configured; skipping email to %s", to)
        return False

    message = EmailMessage()
    message["Subject"] = subject
    message["From"] = formataddr((settings.EMAIL_FROM_NAME, settings.EMAIL))
    message["To"] = to
    message.set_content(text_body or "Veuillez activer l'affichage HTML pour lire ce message.")
    message.add_alternative(html_body, subtype="html")

    try:
        await asyncio.to_thread(_send_sync, message)
        logger.info("Email sent to %s (%s)", to, subject)
        return True
    except Exception as exc:  # pragma: no cover - depends on SMTP availability
        logger.error("Failed to send email to %s: %s", to, exc)
        return False


def _otp_email_html(code: str, name: str | None) -> str:
    greeting = f"Bonjour {name}," if name else "Bonjour,"
    return f"""\
<!doctype html>
<html lang="fr">
  <body style="margin:0;background:#f4f4f7;font-family:Segoe UI,Roboto,Helvetica,Arial,sans-serif;">
    <div style="max-width:520px;margin:0 auto;padding:32px 16px;">
      <div style="background:#ffffff;border-radius:16px;padding:32px;border:1px solid #ececf1;">
        <h1 style="margin:0 0 8px;font-size:20px;color:#111827;">AN-NOUR</h1>
        <p style="margin:0 0 20px;color:#6b7280;font-size:14px;">
          Vérification de votre adresse e-mail
        </p>
        <p style="color:#374151;font-size:15px;">{greeting}</p>
        <p style="color:#374151;font-size:15px;">
          Voici votre code de vérification. Il expire dans
          {settings.OTP_EXPIRE_MINUTES} minutes :
        </p>
        <div style="text-align:center;margin:28px 0;">
          <span style="display:inline-block;font-size:34px;font-weight:700;letter-spacing:10px;
            color:#111827;background:#f3f4f6;border-radius:12px;padding:16px 24px;">{code}</span>
        </div>
        <p style="color:#6b7280;font-size:13px;">
          Si vous n'êtes pas à l'origine de cette demande, ignorez simplement cet e-mail.
        </p>
      </div>
      <p style="text-align:center;color:#9ca3af;font-size:12px;margin-top:16px;">
        © AN-NOUR — Commerce OS
      </p>
    </div>
  </body>
</html>"""


async def send_otp_email(to: str, code: str, name: str | None = None) -> bool:
    """Send the email-verification OTP to a user."""
    subject = "Votre code de vérification AN-NOUR"
    text = (
        f"Votre code de vérification AN-NOUR est : {code}\n"
        f"Il expire dans {settings.OTP_EXPIRE_MINUTES} minutes."
    )
    return await send_email(to, subject, _otp_email_html(code, name), text)


def _welcome_email_html(name: str, email: str, temp_password: str) -> str:
    login_url = f"{settings.FRONTEND_URL}/login"
    first_name = name.split()[0] if name else "là"
    return f"""\
<!doctype html>
<html lang="fr">
<head><meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1"></head>
<body style="margin:0;padding:0;background:#f0f2f5;
  font-family:-apple-system,BlinkMacSystemFont,'Segoe UI',Roboto,Helvetica,Arial,sans-serif;">
  <div style="max-width:600px;margin:0 auto;padding:40px 16px 24px;">

    <!-- Header brand -->
    <div style="background:linear-gradient(135deg,#6366f1 0%,#4f46e5 100%);
      border-radius:16px 16px 0 0;padding:36px 40px;">
      <table width="100%" cellpadding="0" cellspacing="0">
        <tr>
          <td>
            <div style="display:inline-block;background:rgba(255,255,255,0.18);
              border-radius:10px;padding:8px 14px;">
              <span style="color:#ffffff;font-size:17px;font-weight:800;letter-spacing:-0.5px;">
                AN-NOUR</span>
            </div>
            <p style="margin:6px 0 0;color:rgba(255,255,255,0.65);font-size:12px;
              letter-spacing:1.5px;text-transform:uppercase;">Commerce OS</p>
          </td>
          <td align="right" valign="middle">
            <span style="background:rgba(255,255,255,0.15);border-radius:20px;padding:5px 12px;
              color:rgba(255,255,255,0.85);font-size:12px;font-weight:600;">Nouveau compte</span>
          </td>
        </tr>
      </table>
    </div>

    <!-- Body -->
    <div style="background:#ffffff;border:1px solid #e5e7eb;border-top:0;padding:36px 40px;">

      <h1 style="margin:0 0 6px;font-size:22px;font-weight:700;color:#111827;">
        Bienvenue, {first_name} !</h1>
      <p style="margin:0 0 28px;color:#6b7280;font-size:14px;line-height:1.6;">
        Votre compte a été créé sur <strong style="color:#374151;">AN-NOUR</strong>.<br>
        Voici vos identifiants de connexion temporaires :
      </p>

      <!-- Credentials -->
      <div style="border:1px solid #e5e7eb;border-radius:12px;overflow:hidden;margin-bottom:24px;">
        <div style="background:#f9fafb;padding:16px 20px;border-bottom:1px solid #e5e7eb;">
          <p style="margin:0 0 3px;font-size:11px;font-weight:600;color:#9ca3af;
            text-transform:uppercase;letter-spacing:0.6px;">Email</p>
          <p style="margin:0;font-size:14px;font-weight:600;color:#111827;">{email}</p>
        </div>
        <div style="background:#ffffff;padding:16px 20px;">
          <p style="margin:0 0 6px;font-size:11px;font-weight:600;color:#9ca3af;
            text-transform:uppercase;letter-spacing:0.6px;">Mot de passe temporaire</p>
          <div style="display:inline-block;background:#f3f4f6;border:1px solid #e5e7eb;
            border-radius:8px;padding:8px 16px;">
            <span style="font-family:'Courier New',Courier,monospace;font-size:18px;
              font-weight:700;letter-spacing:3px;color:#1f2937;">{temp_password}</span>
          </div>
        </div>
      </div>

      <!-- Warning -->
      <div style="background:#fffbeb;border:1px solid #fde68a;border-radius:10px;
        padding:14px 18px;margin-bottom:32px;">
        <p style="margin:0;font-size:13px;color:#92400e;line-height:1.5;">
          <strong>&#9888;&#65039; Important :</strong> Ce mot de passe est temporaire.
          Vous devrez en définir un personnel dès votre première connexion.
        </p>
      </div>

      <!-- CTA -->
      <div style="text-align:center;margin-bottom:28px;">
        <a href="{login_url}"
           style="display:inline-block;background:linear-gradient(135deg,#6366f1,#4f46e5);
                  color:#ffffff;text-decoration:none;
                  padding:14px 36px;border-radius:10px;font-size:14px;font-weight:700;
                  letter-spacing:0.3px;">
          Accéder à mon compte &rarr;
        </a>
      </div>

      <p style="margin:0;color:#374151;font-size:14px;line-height:1.6;">
        Cordialement,<br>
        <strong>L'équipe AN-NOUR</strong>
      </p>
    </div>

    <!-- Footer -->
    <div style="background:#f9fafb;border:1px solid #e5e7eb;border-top:0;
      border-radius:0 0 16px 16px;padding:18px 40px;text-align:center;">
      <p style="margin:0;color:#9ca3af;font-size:12px;line-height:1.6;">
        Cet e-mail a été envoyé automatiquement &mdash; merci de ne pas répondre.<br>
        &copy; 2026 AN-NOUR &mdash; Commerce OS
      </p>
    </div>

  </div>
</body>
</html>"""


def _password_reset_email_html(reset_url: str, name: str | None) -> str:
    greeting = f"Bonjour {name}," if name else "Bonjour,"
    return f"""\
<!doctype html>
<html lang="fr">
  <body style="margin:0;background:#f4f4f7;font-family:Segoe UI,Roboto,Helvetica,Arial,sans-serif;">
    <div style="max-width:520px;margin:0 auto;padding:32px 16px;">
      <div style="background:#ffffff;border-radius:16px;padding:32px;border:1px solid #ececf1;">
        <h1 style="margin:0 0 8px;font-size:20px;color:#111827;">AN-NOUR</h1>
        <p style="margin:0 0 20px;color:#6b7280;font-size:14px;">
          Réinitialisation de votre mot de passe
        </p>
        <p style="color:#374151;font-size:15px;">{greeting}</p>
        <p style="color:#374151;font-size:15px;">
          Vous avez demandé la réinitialisation de votre mot de passe AN-NOUR.
          Ce lien expire dans {settings.PASSWORD_RESET_EXPIRE_MINUTES} minutes :
        </p>
        <div style="text-align:center;margin:28px 0;">
          <a href="{reset_url}"
             style="display:inline-block;background:linear-gradient(135deg,#6366f1,#4f46e5);
                    color:#ffffff;text-decoration:none;
                    padding:14px 36px;border-radius:10px;font-size:14px;font-weight:700;
                    letter-spacing:0.3px;">
            Réinitialiser mon mot de passe &rarr;
          </a>
        </div>
        <p style="color:#6b7280;font-size:13px;">
          Si vous n'êtes pas à l'origine de cette demande, ignorez simplement cet e-mail —
          votre mot de passe restera inchangé.
        </p>
      </div>
      <p style="text-align:center;color:#9ca3af;font-size:12px;margin-top:16px;">
        © AN-NOUR — Commerce OS
      </p>
    </div>
  </body>
</html>"""


async def send_password_reset_email(to: str, reset_url: str, name: str | None = None) -> bool:
    """Send the password-reset link to a user."""
    subject = "Réinitialisation de votre mot de passe AN-NOUR"
    text = (
        f"Pour réinitialiser votre mot de passe AN-NOUR, ouvrez ce lien : {reset_url}\n"
        f"Il expire dans {settings.PASSWORD_RESET_EXPIRE_MINUTES} minutes.\n"
        "Si vous n'êtes pas à l'origine de cette demande, ignorez cet e-mail."
    )
    return await send_email(to, subject, _password_reset_email_html(reset_url, name), text)


def _proforma_rejected_email_html(
    boss_name: str,
    gerant_name: str,
    boutique_name: str,
    numero: str,
    numero_proforma: str,
    motif: str,
) -> str:
    first_name = boss_name.split()[0] if boss_name else "là"
    return f"""\
<!doctype html>
<html lang="fr">
  <body style="margin:0;background:#f4f4f7;font-family:Segoe UI,Roboto,Helvetica,Arial,sans-serif;">
    <div style="max-width:560px;margin:0 auto;padding:32px 16px;">
      <div style="background:#ffffff;border-radius:16px;padding:32px;border:1px solid #ececf1;">
        <h1 style="margin:0 0 4px;font-size:20px;color:#111827;">AN-NOUR</h1>
        <p style="margin:0 0 24px;color:#6b7280;font-size:13px;">Commerce OS — Approvisionnement</p>

        <div style="background:#fef2f2;border-left:4px solid #dc2626;border-radius:8px;
                    padding:14px 16px;margin-bottom:24px;">
          <p style="margin:0;font-size:15px;font-weight:700;color:#dc2626;">
            Facture proforma rejetée
          </p>
          <p style="margin:4px 0 0;font-size:13px;color:#b91c1cCC;">
            Le gérant de la boutique a rejeté la facture proforma soumise.
          </p>
        </div>

        <p style="color:#374151;font-size:15px;">Bonjour {first_name},</p>

        <table style="width:100%;border-collapse:collapse;border-radius:8px;
                      overflow:hidden;border:1px solid #e5e7eb;margin:16px 0;">
          <tr style="background:#f9fafb;">
            <td style="padding:8px 12px;color:#6b7280;font-size:14px;">Demande</td>
            <td style="padding:8px 12px;font-size:14px;font-weight:600;">{numero}</td>
          </tr>
          <tr>
            <td style="padding:8px 12px;color:#6b7280;font-size:14px;">Proforma</td>
            <td style="padding:8px 12px;font-size:14px;font-weight:600;">{numero_proforma}</td>
          </tr>
          <tr style="background:#f9fafb;">
            <td style="padding:8px 12px;color:#6b7280;font-size:14px;">Boutique</td>
            <td style="padding:8px 12px;font-size:14px;font-weight:600;">{boutique_name}</td>
          </tr>
          <tr>
            <td style="padding:8px 12px;color:#6b7280;font-size:14px;">Rejetée par</td>
            <td style="padding:8px 12px;font-size:14px;font-weight:600;">{gerant_name}</td>
          </tr>
        </table>

        <div style="background:#fffbeb;border:1px solid #fde68a;border-radius:10px;
                    padding:14px 18px;margin-bottom:8px;">
          <p style="margin:0 0 4px;font-size:12px;font-weight:700;color:#92400e;
                    text-transform:uppercase;letter-spacing:0.5px;">Motif du rejet</p>
          <p style="margin:0;font-size:14px;color:#92400e;">{motif}</p>
        </div>

        <p style="margin-top:20px;color:#374151;font-size:14px;line-height:1.6;">
          Vous pouvez modifier les quantités/prix et resoumettre la proforma pour une
          nouvelle décision du gérant.
        </p>

        <p style="margin-top:20px;color:#374151;font-size:14px;">
          Cordialement,<br>
          <strong>AN-NOUR — Commerce OS</strong>
        </p>
      </div>
      <p style="text-align:center;color:#9ca3af;font-size:12px;margin-top:16px;">
        © AN-NOUR — Commerce OS
      </p>
    </div>
  </body>
</html>"""


async def send_proforma_rejected_email(
    to: str,
    boss_name: str,
    gerant_name: str,
    boutique_name: str,
    numero: str,
    numero_proforma: str,
    motif: str,
) -> bool:
    """Notify the Boss/HQ user that a boutique gérant rejected a proforma."""
    subject = f"Proforma rejetée — {boutique_name} ({numero})"
    text = (
        f"Bonjour {boss_name},\n\n"
        f"Le gérant {gerant_name} a rejeté la facture proforma {numero_proforma} "
        f"de la demande {numero} (boutique {boutique_name}).\n\n"
        f"Motif : {motif}\n\n"
        "Vous pouvez modifier les quantités/prix et resoumettre la proforma.\n\n"
        "Cordialement,\nAN-NOUR"
    )
    html = _proforma_rejected_email_html(
        boss_name, gerant_name, boutique_name, numero, numero_proforma, motif
    )
    return await send_email(to, subject, html, text)


def _stock_adjustment_email_html(
    boss_name: str,
    gerant_name: str,
    boutique_name: str,
    product_name: str,
    quantity_before: int,
    quantity_after: int,
    reason: str,
    notes: str | None,
) -> str:
    first_name = boss_name.split()[0] if boss_name else "là"
    delta = quantity_after - quantity_before
    delta_label = f"+{delta}" if delta >= 0 else str(delta)
    delta_color = "#059669" if delta >= 0 else "#dc2626"
    notes_row = (
        f"""<tr>
              <td style="padding:8px 12px;color:#6b7280;font-size:14px;">Note</td>
              <td style="padding:8px 12px;font-size:14px;">{notes}</td>
            </tr>"""
        if notes
        else ""
    )
    return f"""\
<!doctype html>
<html lang="fr">
  <body style="margin:0;background:#f4f4f7;font-family:Segoe UI,Roboto,Helvetica,Arial,sans-serif;">
    <div style="max-width:560px;margin:0 auto;padding:32px 16px;">
      <div style="background:#ffffff;border-radius:16px;padding:32px;border:1px solid #ececf1;">
        <h1 style="margin:0 0 4px;font-size:20px;color:#111827;">AN-NOUR</h1>
        <p style="margin:0 0 24px;color:#6b7280;font-size:13px;">Commerce OS — Stock boutique</p>

        <div style="background:#eff6ff;border-left:4px solid #2563eb;border-radius:8px;
                    padding:14px 16px;margin-bottom:24px;">
          <p style="margin:0;font-size:15px;font-weight:700;color:#2563eb;">
            Réajustement de stock
          </p>
          <p style="margin:4px 0 0;font-size:13px;color:#1d4ed8cc;">
            Le gérant a validé un réajustement de stock dans sa boutique.
          </p>
        </div>

        <p style="color:#374151;font-size:15px;">Bonjour {first_name},</p>

        <table style="width:100%;border-collapse:collapse;border-radius:8px;
                      overflow:hidden;border:1px solid #e5e7eb;margin:16px 0;">
          <tr style="background:#f9fafb;">
            <td style="padding:8px 12px;color:#6b7280;font-size:14px;">Boutique</td>
            <td style="padding:8px 12px;font-size:14px;font-weight:600;">{boutique_name}</td>
          </tr>
          <tr>
            <td style="padding:8px 12px;color:#6b7280;font-size:14px;">Réajusté par</td>
            <td style="padding:8px 12px;font-size:14px;font-weight:600;">{gerant_name}</td>
          </tr>
          <tr style="background:#f9fafb;">
            <td style="padding:8px 12px;color:#6b7280;font-size:14px;">Produit</td>
            <td style="padding:8px 12px;font-size:14px;font-weight:600;">{product_name}</td>
          </tr>
          <tr>
            <td style="padding:8px 12px;color:#6b7280;font-size:14px;">Quantité</td>
            <td style="padding:8px 12px;font-size:14px;">
              {quantity_before} &rarr; {quantity_after}
              <span style="color:{delta_color};font-weight:700;">({delta_label})</span>
            </td>
          </tr>
          <tr style="background:#f9fafb;">
            <td style="padding:8px 12px;color:#6b7280;font-size:14px;">Motif</td>
            <td style="padding:8px 12px;font-size:14px;">{reason}</td>
          </tr>
          {notes_row}
        </table>

        <p style="margin-top:20px;color:#374151;font-size:14px;line-height:1.6;">
          Vous pouvez consulter l'historique complet des mouvements de stock de cette
          boutique depuis sa fiche.
        </p>

        <p style="margin-top:20px;color:#374151;font-size:14px;">
          Cordialement,<br>
          <strong>AN-NOUR — Commerce OS</strong>
        </p>
      </div>
      <p style="text-align:center;color:#9ca3af;font-size:12px;margin-top:16px;">
        © AN-NOUR — Commerce OS
      </p>
    </div>
  </body>
</html>"""


async def send_stock_adjustment_email(
    to: str,
    boss_name: str,
    gerant_name: str,
    boutique_name: str,
    product_name: str,
    quantity_before: int,
    quantity_after: int,
    reason: str,
    notes: str | None = None,
) -> bool:
    """Notify the Boss who created a boutique that its gérant validated a
    stock adjustment (physical count) on a product in that boutique."""
    subject = f"Réajustement de stock — {boutique_name} ({product_name})"
    delta = quantity_after - quantity_before
    text = (
        f"Bonjour {boss_name},\n\n"
        f"Le gérant {gerant_name} a validé un réajustement de stock dans la boutique "
        f"{boutique_name}.\n\n"
        f"Produit : {product_name}\n"
        f"Quantité : {quantity_before} -> {quantity_after} ({'+' if delta >= 0 else ''}{delta})\n"
        f"Motif : {reason}\n"
        + (f"Note : {notes}\n" if notes else "")
        + "\nCordialement,\nAN-NOUR"
    )
    html = _stock_adjustment_email_html(
        boss_name, gerant_name, boutique_name, product_name, quantity_before, quantity_after,
        reason, notes,
    )
    return await send_email(to, subject, html, text)


async def send_welcome_email(to: str, name: str, temp_password: str) -> bool:
    """Send account credentials to a newly created user."""
    subject = "Bienvenue sur AN-NOUR — vos accès"
    text = (
        f"Bonjour {name},\n\n"
        f"Votre compte AN-NOUR a été créé.\n"
        f"Email : {to}\n"
        f"Mot de passe temporaire : {temp_password}\n\n"
        "Veuillez changer ce mot de passe à votre première connexion.\n\n"
        "Cordialement,\nAN-NOUR"
    )
    return await send_email(to, subject, _welcome_email_html(name, to, temp_password), text)
