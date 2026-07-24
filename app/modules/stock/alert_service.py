"""Stock threshold alert service.

After every stock mutation, call ``StockAlertService(db).check_and_notify(stock)``
to detect LOW_STOCK / OUT_OF_STOCK conditions and dispatch emails. The check is
wrapped so that any failure is logged but never propagates to the caller.
"""

from datetime import date

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.logging import get_logger
from app.database.enums import NotificationType, StockAlertType, StockLocationType
from app.modules.access.models import Group, UserGroup
from app.modules.catalog.models import Product
from app.modules.notifications.schemas import NotificationCreate
from app.modules.notifications.services import NotificationService
from app.modules.stock.models import ProductStock, StockAlertLog, StockLocation
from app.modules.stores.models import Store
from app.modules.users.models import User
from app.utils.email import send_email, send_stock_adjustment_email

logger = get_logger("stock.alerts")


class StockAlertService:
    def __init__(self, db: AsyncSession) -> None:
        self.db = db

    async def notify_store_adjustment(
        self,
        *,
        location: StockLocation,
        product_id: int,
        gerant: User,
        quantity_before: int,
        quantity_after: int,
        reason: str,
        notes: str | None,
    ) -> None:
        """Best-effort email to the Boss who created this boutique, whenever
        its own gérant validates a stock adjustment (physical count) there.
        Never raises — logs internally on failure, mirrors check_and_notify.
        Only called for STORE locations; central adjustments are the Boss's
        own action and don't need to notify themselves."""
        try:
            if location.store_id is None:
                return
            store = await self.db.get(Store, location.store_id)
            if store is None or store.created_by is None or store.created_by == gerant.id:
                return
            boss = await self.db.get(User, store.created_by)
            if boss is None or not boss.email:
                return
            product = await self.db.get(Product, product_id)
            if product is None:
                return
            await send_stock_adjustment_email(
                to=boss.email,
                boss_name=f"{boss.firstname} {boss.lastname}",
                gerant_name=f"{gerant.firstname} {gerant.lastname}",
                boutique_name=store.name,
                product_name=product.name,
                quantity_before=quantity_before,
                quantity_after=quantity_after,
                reason=reason,
                notes=notes,
            )
        except Exception:
            logger.error(
                "Failed to send stock-adjustment email for location_id=%s product_id=%s",
                location.id,
                product_id,
                exc_info=True,
            )

    async def check_and_notify(self, stock: ProductStock) -> None:
        """Public entry point — never raises; logs any internal error."""
        try:
            await self._run(stock)
        except Exception as exc:
            logger.error(
                "Stock alert check failed for product_stock_id=%s: %s",
                stock.id,
                exc,
                exc_info=True,
            )

    # ── Private ────────────────────────────────────────────────────────────────

    async def _run(self, stock: ProductStock) -> None:
        # 1. Determine alert type
        if stock.quantity == 0:
            alert_type = StockAlertType.OUT_OF_STOCK
        elif stock.alert_threshold > 0 and stock.quantity <= stock.alert_threshold:
            alert_type = StockAlertType.LOW_STOCK
        else:
            return  # No alert needed

        # 2. Deduplicate: skip if same alert already sent today
        today = date.today()
        dup = await self.db.execute(
            select(StockAlertLog.id)
            .where(StockAlertLog.product_stock_id == stock.id)
            .where(StockAlertLog.alert_type == alert_type)
            .where(
                StockAlertLog.created_at >= today.strftime("%Y-%m-%d 00:00:00")
            )
            .limit(1)
        )
        if dup.scalar_one_or_none() is not None:
            logger.debug(
                "Alert already sent today for product_stock_id=%s type=%s — skipping",
                stock.id,
                alert_type,
            )
            return

        # 3. Load product
        product = await self.db.get(Product, stock.product_id)
        if product is None:
            logger.warning("Product %s not found, skipping stock alert", stock.product_id)
            return

        # 4. Load location
        location = await self.db.get(StockLocation, stock.location_id)
        if location is None:
            logger.warning("Location %s not found, skipping stock alert", stock.location_id)
            return

        # 5. Load store (for STORE locations)
        store: Store | None = None
        if location.store_id:
            store = await self.db.get(Store, location.store_id)

        # 6. Collect recipients — full User rows, since in-app notifications
        # need a user_id (email alone, used for the email side below, isn't enough).
        recipient_users: list[User] = await self._boss_users()

        if store and store.gerant_id:
            gerant = await self.db.get(User, store.gerant_id)
            if gerant and gerant.id not in {u.id for u in recipient_users}:
                recipient_users.append(gerant)

        if not recipient_users:
            logger.warning(
                "No recipients found for stock alert on product_stock_id=%s — skipping",
                stock.id,
            )
            return

        recipients: list[str] = [u.email for u in recipient_users if u.email]

        # 7. Build and send emails
        location_label = store.name if store else location.name
        if location.type == StockLocationType.CENTRAL:
            subject = "Alerte stock faible — Stock Central"
        else:
            subject = f"Alerte stock faible — Boutique {location_label}"

        if alert_type == StockAlertType.OUT_OF_STOCK:
            subject = subject.replace("stock faible", "rupture de stock")

        html_body = _build_html(
            product_name=product.name,
            location_label=location_label,
            location_type=str(location.type),
            quantity=stock.quantity,
            alert_threshold=stock.alert_threshold,
            alert_type=alert_type,
        )
        text_body = _build_text(
            product_name=product.name,
            location_label=location_label,
            quantity=stock.quantity,
            alert_threshold=stock.alert_threshold,
            alert_type=alert_type,
        )

        sent: list[str] = []
        for email in recipients:
            ok = await send_email(email, subject, html_body, text_body)
            if ok:
                sent.append(email)

        # In-app notification — one per recipient, regardless of whether their
        # email send succeeded. Best-effort per-recipient: one failure must
        # never block the others (mirrors the email loop just above).
        notif_title = f"{_STATUS_LABEL[alert_type]} : {product.name}"
        notif_message = (
            f"{location_label} est en rupture totale."
            if alert_type == StockAlertType.OUT_OF_STOCK
            else (
                f"{location_label} est sous le seuil de réappro "
                f"({stock.quantity} unité(s) restante(s))."
            )
        )
        notif_link = (
            "/app/inventory/central" if location.type == StockLocationType.CENTRAL
            else "/app/inventory/boutiques"
        )
        notif_service = NotificationService(self.db)
        for recipient_user in recipient_users:
            try:
                await notif_service.create(
                    NotificationCreate(
                        user_id=recipient_user.id,
                        title=notif_title,
                        message=notif_message,
                        type=NotificationType.stock,
                        link=notif_link,
                    )
                )
            except Exception:
                logger.error(
                    "Failed to create in-app stock notification for user_id=%s product_stock_id=%s",
                    recipient_user.id,
                    stock.id,
                    exc_info=True,
                )

        # Log regardless of send success (prevents retry storms on SMTP failure)
        log_entry = StockAlertLog(
            product_stock_id=stock.id,
            product_id=stock.product_id,
            stock_location_id=stock.location_id,
            alert_type=alert_type,
            quantity=stock.quantity,
            alert_threshold=stock.alert_threshold,
            sent_to=",".join(sent) if sent else ",".join(recipients) + " (échec SMTP)",
        )
        self.db.add(log_entry)
        await self.db.flush()

        logger.info(
            "Stock alert [%s] sent for product_stock_id=%s → %s",
            alert_type,
            stock.id,
            sent,
        )

    async def _boss_users(self) -> list[User]:
        """Return all active users in the super-admin group."""
        result = await self.db.execute(
            select(User)
            .join(UserGroup, UserGroup.user_id == User.id)
            .join(Group, Group.id == UserGroup.group_id)
            .where(Group.slug == "super-admin")
            .where(User.is_activated.is_(True))
        )
        return list(result.scalars().all())


# ── Email templates ─────────────────────────────────────────────────────────────

_STATUS_LABEL = {
    StockAlertType.LOW_STOCK: "Stock faible",
    StockAlertType.OUT_OF_STOCK: "Rupture de stock",
}

_STATUS_COLOR = {
    StockAlertType.LOW_STOCK: "#d97706",    # amber
    StockAlertType.OUT_OF_STOCK: "#dc2626", # red
}

_RECO = {
    StockLocationType.CENTRAL: (
        "Veuillez réapprovisionner le stock central auprès de vos fournisseurs."
    ),
    StockLocationType.STORE: (
        "Veuillez effectuer ou demander un transfert de stock depuis le stock central."
    ),
    StockLocationType.WAREHOUSE: "Veuillez réapprovisionner cet entrepôt.",
}


def _build_html(
    product_name: str,
    location_label: str,
    location_type: str,
    quantity: int,
    alert_threshold: int,
    alert_type: StockAlertType,
) -> str:
    status_label = _STATUS_LABEL[alert_type]
    status_color = _STATUS_COLOR[alert_type]
    reco = _RECO.get(location_type, _RECO[StockLocationType.CENTRAL])  # type: ignore[call-overload]
    date_str = date.today().strftime("%d/%m/%Y")

    threshold_row = (
        f"""<tr>
              <td style="padding:8px 12px;color:#6b7280;font-size:14px;">Seuil d'alerte</td>
              <td style="padding:8px 12px;font-size:14px;font-weight:600;">{alert_threshold}</td>
            </tr>"""
        if alert_threshold > 0
        else ""
    )

    return f"""\
<!doctype html>
<html lang="fr">
<body style="margin:0;background:#f4f4f7;font-family:Segoe UI,Roboto,Helvetica,Arial,sans-serif;">
  <div style="max-width:560px;margin:0 auto;padding:32px 16px;">
    <div style="background:#fff;border-radius:16px;padding:32px;border:1px solid #ececf1;">

      <h1 style="margin:0 0 4px;font-size:20px;color:#111827;">AN-NOUR</h1>
      <p style="margin:0 0 24px;color:#6b7280;font-size:13px;">Commerce OS — Alerte automatique</p>

      <div style="background:{status_color}15;border-left:4px solid {status_color};
                  border-radius:8px;padding:14px 16px;margin-bottom:24px;">
        <p style="margin:0;font-size:15px;font-weight:700;color:{status_color};">
          {status_label}
        </p>
        <p style="margin:4px 0 0;font-size:13px;color:{status_color}cc;">
          Une alerte de stock a été détectée sur votre système.
        </p>
      </div>

      <table style="width:100%;border-collapse:collapse;border-radius:8px;
                    overflow:hidden;border:1px solid #e5e7eb;">
        <tr style="background:#f9fafb;">
          <td style="padding:8px 12px;color:#6b7280;font-size:14px;">Produit</td>
          <td style="padding:8px 12px;font-size:14px;font-weight:600;">{product_name}</td>
        </tr>
        <tr>
          <td style="padding:8px 12px;color:#6b7280;font-size:14px;">Emplacement</td>
          <td style="padding:8px 12px;font-size:14px;font-weight:600;">{location_label}</td>
        </tr>
        <tr style="background:#f9fafb;">
          <td style="padding:8px 12px;color:#6b7280;font-size:14px;">Quantité actuelle</td>
          <td style="padding:8px 12px;font-size:14px;font-weight:700;color:{status_color};">
            {quantity}
          </td>
        </tr>
        {threshold_row}
        <tr style="background:#f9fafb;">
          <td style="padding:8px 12px;color:#6b7280;font-size:14px;">Statut</td>
          <td style="padding:8px 12px;">
            <span style="display:inline-block;background:{status_color}20;color:{status_color};
                         font-size:12px;font-weight:700;padding:3px 10px;border-radius:99px;">
              {status_label}
            </span>
          </td>
        </tr>
        <tr>
          <td style="padding:8px 12px;color:#6b7280;font-size:14px;">Date</td>
          <td style="padding:8px 12px;font-size:14px;">{date_str}</td>
        </tr>
      </table>

      <div style="background:#eff6ff;border-radius:8px;padding:14px 16px;margin-top:20px;">
        <p style="margin:0;font-size:13px;color:#1d4ed8;">
          <strong>Recommandation :</strong> {reco}
        </p>
      </div>

      <p style="margin-top:24px;color:#374151;font-size:14px;">
        Cordialement,<br>
        <strong>AN-NOUR — Commerce OS</strong>
      </p>
    </div>
    <p style="text-align:center;color:#9ca3af;font-size:12px;margin-top:16px;">
      Cet email a été envoyé automatiquement. Ne pas répondre.
    </p>
  </div>
</body>
</html>"""


def _build_text(
    product_name: str,
    location_label: str,
    quantity: int,
    alert_threshold: int,
    alert_type: StockAlertType,
) -> str:
    status_label = _STATUS_LABEL[alert_type]
    date_str = date.today().strftime("%d/%m/%Y")
    threshold_line = f"Seuil d'alerte : {alert_threshold}\n" if alert_threshold > 0 else ""
    return (
        f"Alerte de stock — {status_label}\n\n"
        f"Produit        : {product_name}\n"
        f"Emplacement    : {location_label}\n"
        f"Quantité       : {quantity}\n"
        f"{threshold_line}"
        f"Date           : {date_str}\n\n"
        "Veuillez prendre les dispositions nécessaires pour éviter une rupture.\n\n"
        "Cordialement,\nAN-NOUR"
    )
