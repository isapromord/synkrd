"""
SynkDR Engine — Escalation Engine

Detects when a conversation should be escalated to a human.
Based on Laura AI's proven patterns but made configurable for any bot.
"""

import re
import logging
from typing import Tuple, Optional

logger = logging.getLogger("elisa.escalation")


# ═══════════════════════════════════════════════════════════════
# ESCALATION LEVELS
# ═══════════════════════════════════════════════════════════════
# Level 0: Normal conversation
# Level 1: Minor friction detected — bot handles with empathy
# Level 2: Repeated friction — bot acknowledges explicitly
# Level 3: Customer requests human — connect immediately

NEGATIVE_PHRASES_CRITICAL = [
    r"\b(furioso|furiosa|indignado|estafa|fraude|denuncia|abogado|legal)\b",
    r"\b(peor servicio|nunca más|horrible experiencia)\b",
]

NEGATIVE_PHRASES_WARNING = [
    r"\b(molest|cansad|frustrad|decepcion|malo|mala|lento|tardó mucho)\w*\b",
    r"\b(no sirve|no funciona|no me gusta|no recomiendo)\b",
    r"\b(ya pregunté|ya dije|otra vez|de nuevo)\b",
]

HANDOFF_PHRASES = [
    r"\b(hablar con alguien|persona real|humano|agente|representante)\b",
    r"\b(quiero llamar|necesito hablar|supervisor|encargado|jefe)\b",
    r"\b(conecta|comunica|pasa)\w* con (alguien|una persona|howard)\b",
]


def detect_sentiment(message: str) -> Tuple[Optional[str], Optional[str]]:
    """
    Detect negative sentiment in a customer message.

    Returns:
        (severity, matched_phrase) where severity is:
        - "critical": Immediate escalation needed
        - "warning": Track but don't escalate yet
        - None: No negative sentiment
    """
    msg_lower = message.lower()

    for pattern in NEGATIVE_PHRASES_CRITICAL:
        match = re.search(pattern, msg_lower)
        if match:
            return "critical", match.group()

    for pattern in NEGATIVE_PHRASES_WARNING:
        match = re.search(pattern, msg_lower)
        if match:
            return "warning", match.group()

    return None, None


def check_handoff_request(message: str) -> bool:
    """Check if the customer is explicitly asking to speak with a human."""
    msg_lower = message.lower()
    for pattern in HANDOFF_PHRASES:
        if re.search(pattern, msg_lower):
            return True
    return False


def calculate_escalation_level(
    message: str,
    current_level: int = 0,
    consecutive_warnings: int = 0,
) -> Tuple[int, str, bool]:
    """
    Calculate the appropriate escalation level.

    Args:
        message: Customer's message
        current_level: Current escalation level (0-3)
        consecutive_warnings: Number of consecutive warning-level signals

    Returns:
        (new_level, reason, should_notify_owner)
    """
    # Direct handoff request → Level 3 immediately
    if check_handoff_request(message):
        return 3, "Customer requested human agent", True

    severity, phrase = detect_sentiment(message)

    if severity == "critical":
        return 3, f"Critical sentiment: '{phrase}'", True

    if severity == "warning":
        new_warnings = consecutive_warnings + 1
        if new_warnings >= 3:
            return 3, f"3+ consecutive warnings (latest: '{phrase}')", True
        elif new_warnings >= 2:
            return 2, f"Repeated friction (warning #{new_warnings}: '{phrase}')", False
        else:
            return 1, f"Minor friction: '{phrase}'", False

    # No negative signals — de-escalate gradually
    if current_level > 0:
        return max(0, current_level - 1), "De-escalating", False

    return 0, "Normal conversation", False


def get_escalation_message(level: int, owner_name: str = "Howard") -> Optional[str]:
    """
    Get the appropriate response message for the escalation level.
    Gradual tone: empathetic → acknowledging → connecting.
    """
    messages = {
        1: (
            "Entiendo tu preocupación 😊 Voy a hacer lo posible "
            "por ayudarte. ¿Me podrías dar más detalles?"
        ),
        2: (
            "Veo que esto ha sido complicado y lo lamento mucho. "
            "Quiero asegurarme de que quedes satisfecho/a. "
            "¿Quieres que te conecte con nuestro equipo directamente?"
        ),
        3: (
            f"Entiendo perfectamente. Déjame conectarte con {owner_name}, "
            "nuestro encargado, para que te atienda personalmente 😊 "
            "Ya le notifico y se comunica contigo."
        ),
    }
    return messages.get(level)
