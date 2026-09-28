"""
SynkDR Engine — Notification System

Sends real-time notifications when escalation happens.
Supports: Telegram, Email (via Supabase Edge Function).
"""

import logging
import httpx
from typing import Optional

logger = logging.getLogger("synkdr.notifications")


class NotificationSender:
    """
    Sends escalation notifications to the store owner.
    
    Channels:
    - Telegram Bot API (primary)
    - Fallback: logs to DB for admin dashboard alert
    """

    def __init__(
        self,
        telegram_token: str = "",
        telegram_chat_id: str = "",
        owner_name: str = "Howard",
    ):
        self.telegram_token = telegram_token
        self.telegram_chat_id = telegram_chat_id
        self.owner_name = owner_name
        self._enabled = bool(telegram_token and telegram_chat_id)
        if self._enabled:
            logger.info("✅ Telegram notifications enabled")
        else:
            logger.warning("⚠️ Telegram not configured — notifications will only appear in HQ dashboard")

    @property
    def is_enabled(self) -> bool:
        return self._enabled

    async def notify_escalation(
        self,
        customer_id: str,
        reason: str,
        level: int,
        last_message: str = "",
        channel: str = "webchat",
    ) -> bool:
        """
        Send escalation notification to owner via Telegram.
        
        Returns True if notification was sent successfully.
        """
        emoji = {1: "⚠️", 2: "🟠", 3: "🚨"}.get(level, "⚠️")
        
        text = (
            f"{emoji} *ESCALACIÓN Nivel {level}*\n\n"
            f"👤 Cliente: `{customer_id}`\n"
            f"📱 Canal: {channel}\n"
            f"📋 Razón: {reason}\n"
        )
        if last_message:
            # Sanitize for Telegram MarkdownV2
            safe_msg = last_message[:200].replace("_", "\\_").replace("*", "\\*").replace("`", "\\`")
            text += f"💬 Último mensaje: _{safe_msg}_\n"
        
        text += f"\n🔗 [Abrir SynkDR Dashboard](https://synkdr.com/admin)"

        return await self._send_telegram(text)

    async def notify_new_conversation(self, customer_id: str, channel: str) -> bool:
        """Notify owner of a new conversation (optional — can be noisy)."""
        text = (
            f"🆕 *Nueva conversación*\n\n"
            f"👤 Cliente: `{customer_id}`\n"
            f"📱 Canal: {channel}\n"
            f"\n🔗 [Abrir SynkDR Dashboard](https://synkdr.com/admin)"
        )
        return await self._send_telegram(text)

    async def send_daily_summary(self, stats: dict) -> bool:
        """Send daily analytics summary to owner."""
        text = (
            f"📊 *Resumen del día — SynkDR AI*\n\n"
            f"💬 Conversaciones: {stats.get('conversations_started', 0)}\n"
            f"✅ Resueltas: {stats.get('conversations_resolved', 0)}\n"
            f"🚨 Escaladas: {stats.get('conversations_escalated', 0)}\n"
            f"📈 Tasa resolución: {stats.get('resolution_rate_pct', 0)}%\n"
            f"⚡ Respuesta promedio: {stats.get('avg_response_ms', 0)}ms\n"
            f"📨 Mensajes totales: {stats.get('messages_total', 0)}\n"
        )
        return await self._send_telegram(text)

    async def notify_low_stock(self, low_stock_products: list) -> bool:
        """
        Send low-stock alert to owner via Telegram.
        
        Args:
            low_stock_products: List of dicts with keys: name, total_qty, variants_detail
        
        Returns True if notification was sent.
        """
        if not low_stock_products:
            return False

        lines = []
        critical = [p for p in low_stock_products if p["total_qty"] <= 3]
        warning = [p for p in low_stock_products if p["total_qty"] > 3]

        if critical:
            lines.append("🔴 *CRÍTICO (≤3 unidades):*")
            for p in critical:
                lines.append(f"  • {p['name']} — *{p['total_qty']}* restantes")

        if warning:
            lines.append("🟡 *BAJO (≤10 unidades):*")
            for p in warning:
                lines.append(f"  • {p['name']} — {p['total_qty']} restantes")

        text = (
            f"📦 *Alerta de Inventario*\n\n"
            f"{chr(10).join(lines)}\n\n"
            f"🔗 [Abrir SynkDR Dashboard](https://synkdr.com/admin)"
        )
        return await self._send_telegram(text)

    async def send(self, text: str) -> bool:
        """Generic Telegram message (used for order confirmations, etc.)."""
        return await self._send_telegram(text)

    async def notify_out_of_stock_demand(
        self,
        customer_id: str,
        product_name: str,
        variant_title: str = "",
        channel: str = "webchat",
    ) -> bool:
        """
        Notify owner when a customer asks about a variant that doesn't exist
        or is out of stock. Signals real demand the owner should act on.
        """
        variant_str = f" — variante: *{variant_title}*" if variant_title else ""
        text = (
            f"🛍️ *Demanda no satisfecha*\n\n"
            f"👤 Cliente: `{customer_id}`\n"
            f"📦 Producto: *{product_name}*{variant_str}\n"
            f"📱 Canal: {channel}\n"
            f"💡 _El cliente preguntó por algo que no tenemos. Considera agregarlo._\n\n"
            f"🔗 [Abrir SynkDR Dashboard](https://synkdr.com/admin)"
        )
        return await self._send_telegram(text)

    async def notify_restock_alert(
        self,
        customer_id: str,
        product_name: str,
        variant_title: str,
        product_url: str = "",
    ) -> bool:
        """
        Notify a customer (via the dashboard log) that their wished product is back.
        Actual WhatsApp message is sent by the restock scheduler.
        """
        text = (
            f"🔔 *Restock disponible para cliente*\n\n"
            f"👤 Cliente: `{customer_id}`\n"
            f"📦 *{product_name}* ({variant_title}) está disponible otra vez\n"
            f"💡 _El cliente fue agregado a la lista de notificación automática._"
        )
        if product_url:
            text += f"\n🔗 {product_url}"
        return await self._send_telegram(text)

    async def _send_telegram(self, text: str) -> bool:
        """Send a message via Telegram Bot API."""
        if not self._enabled:
            logger.info(f"📩 [Notification not sent — Telegram not configured] {text[:100]}...")
            return False

        url = f"https://api.telegram.org/bot{self.telegram_token}/sendMessage"
        payload = {
            "chat_id": self.telegram_chat_id,
            "text": text,
            "parse_mode": "Markdown",
            "disable_web_page_preview": True,
        }

        try:
            async with httpx.AsyncClient(timeout=10) as client:
                response = await client.post(url, json=payload)
                if response.status_code == 200:
                    logger.info(f"✅ Telegram notification sent to {self.telegram_chat_id}")
                    return True
                else:
                    logger.error(f"❌ Telegram API error: {response.status_code} — {response.text}")
                    return False
        except Exception as e:
            logger.error(f"❌ Telegram send failed: {e}")
            return False
