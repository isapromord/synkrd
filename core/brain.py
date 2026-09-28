"""
SynkDR Engine — Core AI Brain

Hybrid AI engine for e-commerce:
  Tier 1: Gemini Flash — fast, cheap (80% of queries)
  Tier 2: Claude Sonnet — deep reasoning (20% of queries)

Both engines receive the SAME system prompt (Sofía's persona)
so responses are indistinguishable in tone and personality.
"""

import os
import json
import logging
import time
from typing import Optional

logger = logging.getLogger("synkdr.brain")

# ═══════════════════════════════════════════════════════════════
# AI CLIENT INITIALIZATION
# ═══════════════════════════════════════════════════════════════

_gemini_client = None
_anthropic_client = None


def get_gemini_client():
    """Lazy-initialize Google Gemini client."""
    global _gemini_client
    if _gemini_client is None:
        try:
            from google import genai
            from core.config import settings
            _gemini_client = genai.Client(api_key=settings.ai.gemini_api_key)
            logger.info("✅ Gemini client initialized")
        except Exception as e:
            logger.error(f"❌ Failed to initialize Gemini: {e}")
    return _gemini_client


def get_anthropic_client():
    """Lazy-initialize Anthropic Claude client."""
    global _anthropic_client
    if _anthropic_client is None:
        try:
            import anthropic
            from core.config import settings
            _anthropic_client = anthropic.Anthropic(api_key=settings.ai.anthropic_api_key)
            logger.info("✅ Anthropic client initialized")
        except Exception as e:
            logger.error(f"❌ Failed to initialize Anthropic: {e}")
    return _anthropic_client


# ═══════════════════════════════════════════════════════════════
# CORE AI FUNCTIONS
# ═══════════════════════════════════════════════════════════════

async def generate_response(
    message: str,
    conversation_history: list = None,
    product_context: str = "",
    system_prompt: str = "",
    tier: int = 1,
    policies_context: str = "",
) -> dict:
    """
    Generate a response from Sofía using the appropriate AI tier.

    Args:
        message: Customer's message
        conversation_history: List of previous messages [{role, content}]
        product_context: Product catalog from Shopify store
        system_prompt: Sofía's unified system prompt
        tier: 1 = Gemini (fast/cheap), 2 = Claude (complex)
        policies_context: Dynamic store policies from admin panel

    Returns:
        dict with keys: response, model_used, tokens_used, latency_ms
    """
    if conversation_history is None:
        conversation_history = []

    start_time = time.time()

    # Build the full prompt with context
    full_system = _build_system_prompt(system_prompt, product_context, policies_context)

    try:
        if tier == 1:
            result = await _call_gemini(message, conversation_history, full_system)
        elif tier == 2:
            result = await _call_claude(message, conversation_history, full_system)
        else:
            logger.warning(f"Unknown tier {tier}, falling back to Gemini")
            result = await _call_gemini(message, conversation_history, full_system)

    except Exception as e:
        logger.error(f"❌ Tier {tier} failed: {e}")
        # Automatic fallback: Tier 1 fails → try Tier 2, and vice versa
        fallback_tier = 2 if tier == 1 else 1
        logger.info(f"🔄 Falling back to Tier {fallback_tier}")
        try:
            if fallback_tier == 1:
                result = await _call_gemini(message, conversation_history, full_system)
            else:
                result = await _call_claude(message, conversation_history, full_system)
        except Exception as fallback_error:
            logger.error(f"❌ Fallback Tier {fallback_tier} also failed: {fallback_error}")
            result = {
                "response": "Disculpa, estoy teniendo un problemita técnico. "
                            "¿Puedes intentar de nuevo en un momentito? 🙏",
                "model_used": "error",
                "tokens_used": 0,
            }

    latency_ms = int((time.time() - start_time) * 1000)
    result["latency_ms"] = latency_ms

    logger.info(
        f"🧠 Response generated | model={result['model_used']} | "
        f"tokens={result.get('tokens_used', 0)} | latency={latency_ms}ms"
    )

    return result


def _build_system_prompt(base_prompt: str, product_context: str, policies_context: str = "") -> str:
    """Combine persona prompt with product context and dynamic policies."""
    parts = [base_prompt]

    if policies_context:
        parts.append(
            "\n\n📋 POLÍTICAS DE LA TIENDA (usa esta información para responder preguntas):\n"
            + policies_context
        )

    if product_context:
        parts.append(
            "\n\n🛍️ CATÁLOGO DE PRODUCTOS (referencia interna — NO lo muestres completo):\n"
            + product_context
            + "\n\n⚠️ INSTRUCCIONES SOBRE EL CATÁLOGO:"
            "\n- NUNCA listes todos los productos de una vez"
            "\n- Si preguntan qué vendes → menciona 2-3 CATEGORÍAS y pregunta qué les interesa"
            "\n- Si preguntan por un producto → da info de ESE producto solamente"
            "\n- Máximo recomendar 2-3 productos por mensaje"
            "\n- Siempre termina con una pregunta para guiar la conversación"
        )

    return "\n".join(parts)


# ═══════════════════════════════════════════════════════════════
# GEMINI (TIER 1) — Fast & Cheap
# ═══════════════════════════════════════════════════════════════

async def _call_gemini(
    message: str,
    conversation_history: list,
    system_prompt: str,
) -> dict:
    """Call Google Gemini Flash for fast e-commerce Q&A."""
    from core.config import settings

    client = get_gemini_client()
    if not client:
        raise RuntimeError("Gemini client not available")

    # Build conversation for Gemini
    contents = []

    # Add conversation history
    for msg in conversation_history[-10:]:  # Last 10 messages for context
        role = "user" if msg.get("role") == "user" else "model"
        contents.append({"role": role, "parts": [{"text": msg["content"]}]})

    # Add current message
    contents.append({"role": "user", "parts": [{"text": message}]})

    response = client.models.generate_content(
        model=settings.ai.gemini_model,
        contents=contents,
        config={
            "system_instruction": system_prompt,
            "max_output_tokens": settings.ai.max_tokens,
            "temperature": settings.ai.temperature,
        },
    )

    response_text = response.text or ""
    tokens_used = 0
    if hasattr(response, "usage_metadata") and response.usage_metadata:
        tokens_used = getattr(response.usage_metadata, "total_token_count", 0)

    return {
        "response": response_text.strip(),
        "model_used": settings.ai.gemini_model,
        "tokens_used": tokens_used,
    }


# ═══════════════════════════════════════════════════════════════
# CLAUDE (TIER 2) — Deep Reasoning
# ═══════════════════════════════════════════════════════════════

async def _call_claude(
    message: str,
    conversation_history: list,
    system_prompt: str,
) -> dict:
    """Call Claude Sonnet for complex conversations with fallback chain."""
    from core.config import settings

    client = get_anthropic_client()
    if not client:
        raise RuntimeError("Anthropic client not available")

    # Build messages for Claude
    messages = []
    for msg in conversation_history[-10:]:
        role = msg.get("role", "user")
        if role not in ("user", "assistant"):
            role = "user"
        messages.append({"role": role, "content": msg["content"]})

    messages.append({"role": "user", "content": message})

    # Try primary model, then fallback
    models_to_try = [
        settings.ai.claude_model,
        settings.ai.claude_fallback_model,
    ]

    last_error = None
    for model in models_to_try:
        try:
            response = client.messages.create(
                model=model,
                max_tokens=settings.ai.max_tokens,
                system=system_prompt,
                messages=messages,
            )

            response_text = ""
            if response.content:
                response_text = response.content[0].text

            tokens_used = 0
            if hasattr(response, "usage"):
                tokens_used = (
                    getattr(response.usage, "input_tokens", 0)
                    + getattr(response.usage, "output_tokens", 0)
                )

            return {
                "response": response_text.strip(),
                "model_used": model,
                "tokens_used": tokens_used,
            }

        except Exception as e:
            logger.warning(f"⚠️ Claude model {model} failed: {e}")
            last_error = e
            continue

    raise RuntimeError(f"All Claude models failed. Last error: {last_error}")
