"""
SynkDR Engine — WAHA (WhatsApp HTTP API) Channel Handler

Direct WhatsApp connection via WAHA on VPS.
Zero per-message cost. QR-code pairing.
Reuses the same WAHA instance from flow-bot (Laura/NexusRD).

WAHA instance: https://flowbot.trendygtm.com
"""

import os
import logging
import asyncio
import base64
from typing import Optional

import httpx

logger = logging.getLogger("synkdr.channels.waha")

# ── Config (reuse existing flow-bot WAHA on same VPS) ──
WAHA_BASE_URL = os.getenv("WAHA_BASE_URL", "https://flowbot.trendygtm.com")
WAHA_API_KEY = os.getenv("WAHA_API_KEY", "alveare_waha_secret_369")
WAHA_SESSION = os.getenv("WAHA_SESSION", "sofia")  # Dedicated session for Sofía
WAHA_WEBHOOK_URL = os.getenv("WAHA_WEBHOOK_URL", "")  # Set when deploying synkdr-bot


def _normalize_phone(phone: str) -> str:
    """Normalize phone to digits-only with country code."""
    clean = "".join(c for c in phone if c.isdigit())
    # Dominican numbers: 809/829/849 + 7 digits = 10 digits
    if len(clean) == 10 and clean[:3] in ("809", "829", "849"):
        clean = "1" + clean
    # Already has country code
    if len(clean) == 11 and clean.startswith("1"):
        return clean
    return clean


def _format_chat_id(phone: str) -> str:
    """Format phone to WAHA chatId (e.g. 18294554783@c.us)."""
    clean = _normalize_phone(phone)
    if not clean:
        return ""
    return f"{clean}@c.us"


_HEADERS = {
    "X-Api-Key": WAHA_API_KEY,
    "Content-Type": "application/json",
}


class WAHAChannel:
    """
    WAHA WhatsApp integration for SynkDR Engine (Sofía).

    Handles:
    - Sending text messages directly from server → customer phone
    - Receiving incoming messages via webhook
    - GPS location, audio, and image message parsing
    - QR code session management
    - Typing simulation for human-like behavior
    """

    def __init__(
        self,
        base_url: str = WAHA_BASE_URL,
        api_key: str = WAHA_API_KEY,
        session: str = WAHA_SESSION,
    ):
        self.base_url = base_url.rstrip("/")
        self.api_key = api_key
        self.session = session
        self.headers = {
            "X-Api-Key": api_key,
            "Content-Type": "application/json",
        }

    # ═══════════════════════════════════════════════════════════════
    # SESSION MANAGEMENT
    # ═══════════════════════════════════════════════════════════════

    async def get_status(self) -> dict:
        """Get connection status of the WAHA session."""
        try:
            async with httpx.AsyncClient(timeout=8) as client:
                res = await client.get(
                    f"{self.base_url}/api/sessions/{self.session}",
                    headers=self.headers,
                )
                if res.status_code == 200:
                    data = res.json()
                    status = data.get("status", "UNKNOWN")
                    me = data.get("me") or {}
                    phone = me.get("id", "").replace("@c.us", "") if me else None
                    return {
                        "status": status,
                        "connected": status == "WORKING",
                        "needs_qr": status == "SCAN_QR_CODE",
                        "phone": phone,
                        "name": me.get("pushName") or me.get("name") if me else None,
                        "session": self.session,
                    }
                elif res.status_code == 404:
                    return {
                        "status": "NOT_FOUND",
                        "connected": False,
                        "needs_qr": False,
                        "phone": None,
                        "session": self.session,
                    }
        except Exception as e:
            logger.warning(f"Error fetching WAHA status: {e}")

        return {
            "status": "OFFLINE",
            "connected": False,
            "needs_qr": False,
            "phone": None,
            "session": self.session,
        }

    async def start_session(self) -> bool:
        """Start or create WAHA session with webhook routing."""
        try:
            async with httpx.AsyncClient(timeout=10) as client:
                res = await client.post(
                    f"{self.base_url}/api/sessions/{self.session}/start",
                    headers=self.headers,
                )
                if res.status_code in (200, 201):
                    return True

                if res.status_code == 404:
                    webhook_config = []
                    if WAHA_WEBHOOK_URL:
                        webhook_config = [
                            {
                                "url": WAHA_WEBHOOK_URL,
                                "events": ["message", "message.any", "state.change"],
                            }
                        ]
                    res_create = await client.post(
                        f"{self.base_url}/api/sessions",
                        headers=self.headers,
                        json={
                            "name": self.session,
                            "config": {
                                "webhooks": webhook_config,
                                "noweb": {
                                    "store": {
                                        "enabled": True,
                                        "full_sync": True,
                                    }
                                },
                            },
                        },
                    )
                    if res_create.status_code in (200, 201):
                        await client.post(
                            f"{self.base_url}/api/sessions/{self.session}/start",
                            headers=self.headers,
                        )
                        return True
        except Exception as e:
            logger.warning(f"Error starting WAHA session '{self.session}': {e}")
        return False

    async def get_qr_base64(self) -> dict:
        """Fetch QR code as data:image/png;base64 string."""
        try:
            status_info = await self.get_status()
            current_status = status_info.get("status", "UNKNOWN")

            if current_status == "WORKING":
                return {
                    "success": False,
                    "qr_image": None,
                    "status": "WORKING",
                    "connected": True,
                    "session": self.session,
                }

            if current_status in ("STOPPED", "NOT_FOUND"):
                await self.start_session()
                await asyncio.sleep(1)

            async with httpx.AsyncClient(timeout=8) as client:
                res = await client.get(
                    f"{self.base_url}/api/{self.session}/auth/qr",
                    headers=self.headers,
                )
                if res.status_code == 200 and res.content:
                    b64 = base64.b64encode(res.content).decode("utf-8")
                    return {
                        "success": True,
                        "qr_image": f"data:image/png;base64,{b64}",
                        "status": "SCAN_QR_CODE",
                        "session": self.session,
                    }
        except Exception as e:
            logger.warning(f"Error fetching WAHA QR: {e}")

        return {
            "success": False,
            "qr_image": None,
            "status": "STARTING",
            "session": self.session,
        }

    # ═══════════════════════════════════════════════════════════════
    # PARSE INCOMING WEBHOOK
    # ═══════════════════════════════════════════════════════════════

    def parse_webhook(self, payload: dict) -> Optional[dict]:
        """
        Parse WAHA webhook payload into standard message format.

        Returns dict with: sender_phone, message_text, message_type, etc.
        Returns None if not a customer message.
        """
        try:
            event = payload.get("event", "")
            if event not in ("message", "message.any"):
                return None

            # Skip outgoing messages
            if payload.get("me", {}).get("id") == payload.get("payload", {}).get(
                "from", ""
            ):
                return None

            msg = payload.get("payload", {})
            if not msg:
                return None

            from_id = msg.get("from", "")
            if not from_id or not from_id.endswith("@c.us"):
                return None

            sender = from_id.replace("@c.us", "")
            if not sender:
                return None

            # Parse message by type
            msg_type = "text"
            text = ""
            audio_url = ""
            image_url = ""
            location_data = {}

            if msg.get("body"):
                text = msg["body"]
                msg_type = "text"

            if msg.get("hasMedia") and msg.get("mediaUrl"):
                media_type = msg.get("type", "")
                if media_type == "image" or "image" in msg.get("mimetype", ""):
                    msg_type = "image"
                    image_url = msg["mediaUrl"]
                    text = msg.get("body") or "[Imagen recibida]"
                elif media_type == "audio" or "audio" in msg.get("mimetype", ""):
                    msg_type = "audio"
                    audio_url = msg["mediaUrl"]
                    text = "[Audio recibido]"
                elif media_type == "ptt" or "ogg" in msg.get("mimetype", ""):
                    msg_type = "audio"
                    audio_url = msg["mediaUrl"]
                    text = "[Nota de voz recibida]"

            if msg.get("location"):
                loc = msg["location"]
                lat = loc.get("latitude")
                lon = loc.get("longitude")
                loc_name = loc.get("description", "")
                maps_url = (
                    f"https://www.google.com/maps?q={lat},{lon}"
                    if lat is not None and lon is not None
                    else ""
                )
                text = (
                    f"📍 {loc_name or 'Ubicación compartida'}: {maps_url}"
                    if maps_url
                    else "[Ubicación compartida]"
                )
                msg_type = "location"
                location_data = {
                    "latitude": lat,
                    "longitude": lon,
                    "name": loc_name,
                    "maps_url": maps_url,
                }

            if not text:
                return None

            return {
                "sender_phone": sender,
                "message_text": text,
                "message_type": msg_type,
                "message_id": msg.get("id", ""),
                "timestamp": msg.get("timestamp", ""),
                "whatsapp_name": msg.get("_data", {}).get("notifyName", "")
                or msg.get("notifyName", ""),
                "audio_url": audio_url,
                "image_url": image_url,
                "location": location_data,
            }

        except Exception as e:
            logger.error(f"Error parsing WAHA webhook: {e}")
            return None

    # ═══════════════════════════════════════════════════════════════
    # SEND MESSAGES
    # ═══════════════════════════════════════════════════════════════

    async def send_text(
        self,
        to: str,
        text: str,
        simulate_typing: bool = True,
        typing_seconds: int = 3,
    ) -> bool:
        """Send a text message via WAHA with typing simulation."""
        chat_id = _format_chat_id(to)
        if not chat_id:
            logger.error(f"Invalid phone number: {to}")
            return False

        try:
            async with httpx.AsyncClient(timeout=15) as client:
                # Simulate typing for human-like behavior
                if simulate_typing:
                    try:
                        await client.post(
                            f"{self.base_url}/api/startTyping",
                            headers=self.headers,
                            json={
                                "session": self.session,
                                "chatId": chat_id,
                            },
                        )
                        await asyncio.sleep(typing_seconds)
                        await client.post(
                            f"{self.base_url}/api/stopTyping",
                            headers=self.headers,
                            json={
                                "session": self.session,
                                "chatId": chat_id,
                            },
                        )
                    except Exception:
                        pass  # Typing simulation is best-effort

                # Send the message
                payload = {
                    "session": self.session,
                    "chatId": chat_id,
                    "text": text,
                }
                res = await client.post(
                    f"{self.base_url}/api/sendText",
                    headers=self.headers,
                    json=payload,
                )

                if res.status_code in (200, 201):
                    data = res.json()
                    msg_id = data.get("id")
                    logger.info(
                        f"✅ WAHA sent to {to} [Session: {self.session}] (ID: {msg_id})"
                    )
                    return True
                else:
                    logger.error(
                        f"❌ WAHA sendText error [{res.status_code}]: {res.text}"
                    )
                    return False

        except Exception as e:
            logger.error(f"❌ WAHA exception sending to {to}: {e}")
            return False

    async def send_image(
        self,
        to: str,
        image_url: str,
        caption: str = "",
    ) -> bool:
        """Send an image message via WAHA."""
        chat_id = _format_chat_id(to)
        if not chat_id:
            return False

        payload = {
            "session": self.session,
            "chatId": chat_id,
            "file": {"url": image_url},
            "caption": caption,
        }

        try:
            async with httpx.AsyncClient(timeout=20) as client:
                res = await client.post(
                    f"{self.base_url}/api/sendImage",
                    headers=self.headers,
                    json=payload,
                )
                if res.status_code in (200, 201):
                    logger.info(f"✅ WAHA image sent to {to}")
                    return True
                else:
                    logger.error(
                        f"❌ WAHA sendImage error [{res.status_code}]: {res.text}"
                    )
                    return False
        except Exception as e:
            logger.error(f"❌ WAHA image exception to {to}: {e}")
            return False

    async def send_template(
        self,
        to: str,
        template_name: str,
        language: str = "es",
        params: list = None,
    ) -> bool:
        """
        WAHA doesn't use Meta templates — send as plain text.
        This method exists for API compatibility with WhatsAppChannel.
        Falls back to send_text with the first param or template name.
        """
        if params:
            # Build a readable message from params
            text = " ".join(str(p) for p in params if p)
        else:
            text = f"[{template_name}]"

        logger.info(
            f"📨 WAHA template fallback → plain text to {to}: {text[:60]}..."
        )
        return await self.send_text(to, text, simulate_typing=False)
