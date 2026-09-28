"""
SynkDR Engine — Re-engagement Module

Detects customers who showed interest but didn't buy ("ghosted")
and sends them a proactive template to re-engage.

Two scenarios:
1. Left on read — bot sent last message, customer never replied
2. No purchase — customer browsed/asked about products but never ordered

Uses WhatsApp templates (required for >24h window per Meta rules).
"""

import logging
from typing import Optional

logger = logging.getLogger("synkdr.reengagement")


def is_conversation_ghosted(metadata: dict) -> bool:
    """
    Check if the customer left the bot on read.
    Returns True if the last message in conversation history was from the assistant.
    """
    history = metadata.get("history", [])
    if not history:
        return False
    last = history[-1]
    return last.get("role") == "assistant"


def get_top_product_interest(metadata: dict) -> Optional[str]:
    """Get the main product the customer was interested in."""
    interests = metadata.get("product_interests", [])
    return interests[0] if interests else None


def filter_reengagement_candidates(
    conversations: list,
    recent_orders_phones: set,
    recently_reengaged_phones: set,
) -> list:
    """
    Filter conversations down to re-engagement candidates.

    A candidate must:
    - Have been ghosted (last message from bot)
    - Have at least one product interest
    - NOT have placed a recent order
    - NOT have been re-engaged recently

    Args:
        conversations: List of closed conversation dicts with 'phone' and 'metadata'.
        recent_orders_phones: Set of phones who ordered recently.
        recently_reengaged_phones: Set of phones already re-engaged.

    Returns:
        List of candidate dicts: {phone, product_name, conversation_id}.
    """
    candidates = []
    for conv in conversations:
        phone = conv.get("phone", "")
        meta = conv.get("metadata", {})
        conv_id = conv.get("id", "")

        if not phone:
            continue
        if phone in recent_orders_phones:
            continue
        if phone in recently_reengaged_phones:
            continue
        if not is_conversation_ghosted(meta):
            continue

        product = get_top_product_interest(meta)
        if not product:
            continue

        candidates.append({
            "phone": phone,
            "product_name": product,
            "conversation_id": conv_id,
        })

    return candidates


def build_reengagement_text(customer_name: str, product_name: str, store_name: str) -> str:
    """
    Build re-engagement WhatsApp text message.
    Used when customer is within the 24h window (unlikely for ghosted, but fallback).
    """
    name = customer_name or "amig@"
    return (
        f"¡Hola {name}! 👋\n\n"
        f"Vi que estabas interesad@ en {product_name}. "
        f"¿Todavía te interesa? 🤔\n\n"
        f"Si tienes alguna pregunta o quieres que te ayude a decidir, "
        f"¡aquí estoy! Me encantaría ayudarte 😊\n\n"
        f"— {store_name}"
    )


def build_reengagement_template_params(customer_name: str, product_name: str) -> list:
    """
    Build parameters for the 'reengagement_reminder' WhatsApp template.

    Template should be registered in YCloud/Meta with 2 body params:
      {{1}} = Customer name
      {{2}} = Product name

    Returns list of param strings.
    """
    name = customer_name if customer_name else "amig@"
    return [name, product_name]
