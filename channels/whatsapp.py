"""
SynkDR Engine — WhatsApp Channel Handler

Handles incoming WhatsApp messages via YCloud webhook.
This is the PLUGGABLE channel layer — swap YCloud for Twilio, etc.
"""

import logging
import httpx
import hmac
import hashlib
from typing import Optional

logger = logging.getLogger("synkdr.channels.whatsapp")


class WhatsAppChannel:
    """
    YCloud WhatsApp integration for SynkDR Engine.
    
    Handles:
    - Receiving incoming messages via webhook
    - Sending replies via YCloud API
    - Message type parsing (text, image, etc.)
    """

    YCLOUD_API_BASE = "https://api.ycloud.com/v2"

    def __init__(self, api_key: str, from_number: str, webhook_secret: str = ""):
        self.api_key = api_key
        self.from_number = from_number
        self.webhook_secret = webhook_secret
        self.headers = {
            "X-API-Key": api_key,
            "Content-Type": "application/json",
        }

    # ═══════════════════════════════════════════════════════════════
    # PARSE INCOMING WEBHOOK
    # ═══════════════════════════════════════════════════════════════

    def parse_webhook(self, payload: dict) -> Optional[dict]:
        """
        Parse YCloud webhook payload into a standard message format.
        
        Returns dict with: sender_phone, message_text, message_type, message_id, timestamp
        Returns None if the payload is not a customer message (e.g., status update).
        """
        try:
            event_type = payload.get("type", "")
            
            # Only process incoming messages
            if event_type != "whatsapp.inbound_message.received":
                logger.debug(f"Ignoring event type: {event_type}")
                return None

            msg = payload.get("whatsappInboundMessage", {})
            if not msg:
                logger.warning("No whatsappInboundMessage in payload")
                return None

            # Get sender info
            sender = msg.get("from", "")
            if not sender:
                return None

            # Parse message content based on type
            msg_type = msg.get("type", "text")
            text = ""
            audio_url = ""
            image_url = ""

            if msg_type == "text":
                text = msg.get("text", {}).get("body", "")
            elif msg_type == "image":
                image_caption = msg.get("image", {}).get("caption", "")
                text = image_caption if image_caption else "[Imagen recibida]"
                image_url = msg.get("image", {}).get("link", "")
            elif msg_type == "audio":
                text = "[Audio recibido]"
                audio_url = msg.get("audio", {}).get("link", "")
            elif msg_type == "document":
                text = "[Documento recibido]"
            elif msg_type == "location":
                text = "[Ubicación compartida]"
            elif msg_type == "button":
                text = msg.get("button", {}).get("text", "")
            elif msg_type == "interactive":
                interactive = msg.get("interactive", {})
                if interactive.get("type") == "button_reply":
                    text = interactive.get("button_reply", {}).get("title", "")
                elif interactive.get("type") == "list_reply":
                    text = interactive.get("list_reply", {}).get("title", "")
            else:
                text = f"[Mensaje tipo: {msg_type}]"

            if not text:
                return None

            # Click-to-WhatsApp ad referral (only present on the FIRST message after an ad click)
            referral = msg.get("referral", {}) or {}

            return {
                "sender_phone": sender,
                "message_text": text,
                "message_type": msg_type,
                "message_id": msg.get("id", ""),
                "timestamp": msg.get("timestamp", ""),
                "whatsapp_name": msg.get("customerProfile", {}).get("name", ""),
                "audio_url": audio_url if msg_type == "audio" else "",
                "image_url": image_url if msg_type == "image" else "",
                "referral_source_id": referral.get("source_id", ""),
                "referral_headline": referral.get("headline", ""),
                "referral_source_url": referral.get("source_url", ""),
            }

        except Exception as e:
            logger.error(f"Error parsing webhook: {e}")
            return None

    # ═══════════════════════════════════════════════════════════════
    # SEND MESSAGES
    # ═══════════════════════════════════════════════════════════════

    async def send_text(self, to: str, text: str) -> bool:
        """Send a text message via YCloud WhatsApp API."""
        payload = {
            "from": self.from_number,
            "to": to,
            "type": "text",
            "text": {"body": text},
        }

        try:
            async with httpx.AsyncClient(timeout=15) as client:
                response = await client.post(
                    f"{self.YCLOUD_API_BASE}/whatsapp/messages",
                    json=payload,
                    headers=self.headers,
                )

                if response.status_code in (200, 201):
                    data = response.json()
                    logger.info(f"✅ Sent to {to}: {text[:50]}...")
                    return True
                else:
                    logger.error(
                        f"❌ YCloud send failed [{response.status_code}]: {response.text}"
                    )
                    return False

        except Exception as e:
            logger.error(f"❌ Error sending WhatsApp: {e}")
            return False

    async def send_template(
        self, to: str, template_name: str, language: str = "es", params: list = None
    ) -> bool:
        """Send a template message via YCloud (for first-contact or notifications)."""
        payload = {
            "from": self.from_number,
            "to": to,
            "type": "template",
            "template": {
                "name": template_name,
                "language": {"code": language},
            },
        }

        if params:
            payload["template"]["components"] = [
                {
                    "type": "body",
                    "parameters": [{"type": "text", "text": p} for p in params],
                }
            ]

        try:
            async with httpx.AsyncClient(timeout=15) as client:
                response = await client.post(
                    f"{self.YCLOUD_API_BASE}/whatsapp/messages",
                    json=payload,
                    headers=self.headers,
                )
                if response.status_code in (200, 201):
                    logger.info(f"✅ Template '{template_name}' sent to {to}")
                    return True
                else:
                    logger.error(f"❌ Template send failed: {response.text}")
                    return False
        except Exception as e:
            logger.error(f"❌ Error sending template: {e}")
            return False

    # ═══════════════════════════════════════════════════════════════
    # SEND AUDIO — Voice Notes
    # ═══════════════════════════════════════════════════════════════

    async def upload_media(self, file_path: str, mime_type: str = "audio/ogg") -> Optional[str]:
        """Upload a media file to YCloud and return the media ID."""
        try:
            import os
            waba_id = os.getenv("YCLOUD_WABA_ID", "")
            if not waba_id:
                logger.error("❌ YCLOUD_WABA_ID not set — cannot upload media")
                return None

            async with httpx.AsyncClient(timeout=30) as client:
                with open(file_path, "rb") as f:
                    response = await client.post(
                        f"{self.YCLOUD_API_BASE}/whatsapp/media/upload",
                        params={"wabaId": waba_id},
                        files={"file": (file_path.split("\\")[-1].split("/")[-1], f, mime_type)},
                        headers={"X-API-Key": self.api_key},
                    )

                if response.status_code in (200, 201):
                    data = response.json()
                    media_id = data.get("id", "")
                    logger.info(f"✅ Media uploaded: {media_id}")
                    return media_id
                else:
                    logger.error(f"❌ Media upload failed [{response.status_code}]: {response.text}")
                    return None

        except Exception as e:
            logger.error(f"❌ Media upload error: {e}")
            return None

    async def send_audio(self, to: str, file_path: str, mime_type: str = "audio/ogg") -> bool:
        """
        Upload audio file to YCloud and send as voice message.
        
        Args:
            to: Recipient phone number
            file_path: Path to audio file (OGG Opus preferred)
            mime_type: MIME type of the audio file
        """
        media_id = await self.upload_media(file_path, mime_type)
        if not media_id:
            return False

        payload = {
            "from": self.from_number,
            "to": to,
            "type": "audio",
            "audio": {"id": media_id},
        }

        try:
            async with httpx.AsyncClient(timeout=15) as client:
                response = await client.post(
                    f"{self.YCLOUD_API_BASE}/whatsapp/messages",
                    json=payload,
                    headers=self.headers,
                )
                if response.status_code in (200, 201):
                    logger.info(f"✅ Audio sent to {to}")
                    return True
                else:
                    logger.error(f"❌ Audio send failed [{response.status_code}]: {response.text}")
                    return False
        except Exception as e:
            logger.error(f"❌ Error sending audio: {e}")
            return False

    # ═══════════════════════════════════════════════════════════════
    # WEBHOOK VERIFICATION
    # ═══════════════════════════════════════════════════════════════

    def verify_signature(self, payload_body: bytes, signature: str) -> bool:
        """Verify YCloud webhook signature for security."""
        if not self.webhook_secret:
            return True  # Skip if no secret configured (dev mode)

        expected = hmac.new(
            self.webhook_secret.encode(),
            payload_body,
            hashlib.sha256,
        ).hexdigest()

        return hmac.compare_digest(expected, signature)
