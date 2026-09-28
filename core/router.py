"""
SynkDR Engine — Intent Router

Classifies customer messages to determine which AI tier should handle them.
This is a lightweight, deterministic classifier — no AI needed for routing.

Tier 1 (Gemini Flash):  Simple queries — product info, pricing, shipping, returns
Tier 2 (Claude Sonnet): Complex queries — complaints, comparisons, persuasion, edge cases
"""

import re
import logging
from typing import Tuple

logger = logging.getLogger("elisa.router")

# ═══════════════════════════════════════════════════════════════
# TIER DEFINITIONS
# ═══════════════════════════════════════════════════════════════

TIER_GEMINI = 1   # Fast, cheap — handles 80% of traffic
TIER_CLAUDE = 2   # Smart, deep — handles complex 20%

# ═══════════════════════════════════════════════════════════════
# INTENT PATTERNS — Deterministic keyword matching
# ═══════════════════════════════════════════════════════════════

# Tier 2 escalation signals (if ANY match → use Claude)
TIER2_PATTERNS = {
    "frustration": [
        r"\b(molest|enojad|frustrad|cansad|hart|decepcion|horrible|pésimo|malo|mala)\w*\b",
        r"\b(no sirve|no funciona|no me gusta|quiero devolver)\b",
        r"\b(reclam|quej|demand|report)\w*\b",
    ],
    "escalation": [
        r"\b(hablar con|comunicar con|persona real|humano|supervisor|encargado|jefe)\b",
        r"\b(quiero llamar|necesito hablar|asesor|representante)\b",
    ],
    "complex_comparison": [
        r"\b(comparar|diferencia|mejor|cuál|cual|recomiend|versus|vs)\b.*\b(producto|artículo)\b",
        r"\b(no sé|no se|indecis|ayúdame a elegir|no puedo decidir)\b",
    ],
    "negotiation": [
        r"\b(descuento|rebaj|oferta|precio especial|más barato|muy caro|mucho dinero)\b",
        r"\b(puedo pagar|plan de pago|financ)\w*\b",
    ],
    "order_tracking": [
        r"\b(mi orden|mi pedido|número de orden|estado del pedido)\b",
        r"#\d{3,}",  # Bare #1001 references (# is not a word char, so no \b needed)
        r"\b(dónde está mi|rastrear|rastreo|status de mi)\b",
        r"\b(cuándo llega|cuando llega|fecha de entrega|delivery)\b",
    ],
    "post_sale_issue": [
        r"\b(no llegó|no ha llegado|pedido|orden|tracking|seguimiento|devolución|reembolso)\b",
        r"\b(producto dañado|vino roto|no era|equivocad)\w*\b",
    ],
}

# Tier 1 patterns (if match and no Tier 2 signals → Gemini)
TIER1_PATTERNS = {
    "greeting": [
        r"\b(hola|buenos?|buenas|saludos|hey|hi|qué tal|que tal)\b",
    ],
    "product_info": [
        r"\b(product|artículo|articulo|tienen|venden|hay|busco|quiero ver|muestrame|mostrar)\w*\b",
        r"\b(faja|crema|mascarilla|mochila|parlante|camiseta|batidor|combo|aceite|joyero|boob tape)\b",
        r"\b(belleza|hogar|tecnología|tecnologia|salud|accesorio)\b",
    ],
    "pricing": [
        r"\b(cuánto|cuanto|precio|cuesta|vale|cost|valor|rango|barato|caro)\w*\b",
        r"\b(RD\$?|pesos?|dop)\b",
    ],
    "shipping": [
        r"\b(envío|envio|delivery|entreg|despacho|lleg|demora|tarda|días|dias|tiempo)\w*\b",
        r"\b(envían|envian|hacen envío|zona|ciudad|interior|santo domingo|santiago)\b",
    ],
    "payment": [
        r"\b(pag|contra entrega|COD|transferencia|tarjeta|efectivo|cómo pago|como pago)\w*\b",
    ],
    "returns": [
        r"\b(devol|cambio|garantía|garantia|reembolso|no me gustó|no me gusto)\w*\b",
    ],
    "catalog": [
        r"\b(catálogo|catalogo|todo lo que tienen|qué venden|que venden|categorías|categorias)\b",
        r"\b(más productos|mas productos|ver más|ver mas|otro|otros|otra opción)\b",
    ],
    "purchase": [
        r"\b(comprar|pedir|ordenar|quiero|lo quiero|me lo llevo|sepáramelo|separamelo)\b",
        r"\b(agregar|carrito|checkout|finalizar|confirmar pedido)\b",
        r"\b(me lo llevo|te lo pido|lo pido|quiero ese|quiero esa|esa misma|ese mismo)\b",
    ],
}


def classify_intent(message: str, conversation_length: int = 0) -> Tuple[int, str, str]:
    """
    Classify a customer message and determine which AI tier to use.

    Args:
        message: The customer's message text
        conversation_length: Number of messages in the conversation so far

    Returns:
        Tuple of (tier, intent_category, reason)
    """
    msg_lower = message.lower().strip()

    # Check Tier 2 patterns first (escalation takes priority)
    for category, patterns in TIER2_PATTERNS.items():
        for pattern in patterns:
            if re.search(pattern, msg_lower):
                logger.info(f"🔴 Tier 2 (Claude) | intent={category} | match={pattern}")
                return TIER_CLAUDE, category, f"Matched Tier 2 pattern: {category}"

    # Long conversations get smarter AI (after 6+ messages, likely complex)
    if conversation_length >= 6:
        logger.info(f"🟡 Tier 2 (Claude) | reason=long_conversation ({conversation_length} msgs)")
        return TIER_CLAUDE, "long_conversation", "Conversation exceeds 6 messages"

    # Check Tier 1 patterns
    for category, patterns in TIER1_PATTERNS.items():
        for pattern in patterns:
            if re.search(pattern, msg_lower):
                logger.info(f"🟢 Tier 1 (Gemini) | intent={category}")
                return TIER_GEMINI, category, f"Matched Tier 1 pattern: {category}"

    # Default: short/unknown messages → Gemini (it's cheaper)
    if len(msg_lower) < 50:
        logger.info("🟢 Tier 1 (Gemini) | reason=short_message_default")
        return TIER_GEMINI, "general", "Short message, defaulting to Tier 1"

    # Longer unclassified messages → Claude (might be complex)
    logger.info("🟡 Tier 2 (Claude) | reason=unclassified_long_message")
    return TIER_CLAUDE, "unclassified", "Long unclassified message, using Tier 2"
