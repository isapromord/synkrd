"""
SynkDR Engine — Visual Product Search

Customer sends a photo → Gemini analyzes it → matches against catalog.
Uses Gemini Flash multimodal (same key, zero extra cost).

Flow: Image URL → download → Gemini vision → product description → search_products() → results
"""

import os
import logging
import tempfile
from typing import Optional

logger = logging.getLogger("synkdr.visual_search")


# ═══════════════════════════════════════════════════════════════
# IMAGE ANALYSIS — Gemini Flash Multimodal
# ═══════════════════════════════════════════════════════════════

# Prompt tells Gemini to describe the product in search-friendly terms
VISION_PROMPT = """Analiza esta imagen de producto y devuelve SOLO una descripción corta para buscar en un catálogo de e-commerce dominicano.

Incluye:
- Tipo de producto (faja, zapato, vestido, maquillaje, skincare, etc.)
- Color principal
- Material o estilo si es visible (colombiana, deportiva, elegante, etc.)
- Cualquier detalle relevante (talla visible, marca visible, patrón)

Formato: una línea, máximo 15 palabras, en español.
Si NO es un producto o no se puede identificar, responde: NO_PRODUCT

Ejemplos:
- "faja colombiana negra tipo cinturilla reductora"
- "zapatillas deportivas blancas Nike running"  
- "sérum facial vitamina C skincare"
- "vestido rojo elegante largo fiesta"
"""

# Caption templates for image messages with text
IMAGE_CAPTION_PROMPT = """Analiza esta imagen que un cliente envió a una tienda online.
El cliente escribió: "{caption}"

Combina lo que dice el cliente con lo que ves en la imagen.
Devuelve SOLO una descripción corta para buscar en el catálogo (máximo 15 palabras, español).
Si NO es un producto, responde: NO_PRODUCT
"""


async def analyze_image(image_url: str, caption: str = "", ycloud_api_key: str = "") -> Optional[str]:
    """
    Download and analyze a product image using Gemini Vision.
    
    Args:
        image_url: URL to the image (from YCloud webhook)
        caption: Optional text the customer sent with the image
        ycloud_api_key: API key for authenticated download from YCloud
        
    Returns:
        Product description string for catalog search, or None
    """
    try:
        import httpx

        # Download image
        headers = {"X-API-Key": ycloud_api_key} if ycloud_api_key else {}
        async with httpx.AsyncClient(timeout=30) as client:
            resp = await client.get(image_url, headers=headers, follow_redirects=True)
            if resp.status_code != 200:
                logger.error(f"❌ Image download failed: {resp.status_code}")
                return None
            image_bytes = resp.content

        if not image_bytes or len(image_bytes) < 500:
            logger.warning("⚠️ Image too small or empty")
            return None

        # Detect mime type from content-type or URL
        content_type = resp.headers.get("content-type", "")
        mime_type = _detect_mime_type(content_type, image_url)

        # Analyze with Gemini Vision
        description = await _gemini_analyze(image_bytes, mime_type, caption)
        return description

    except Exception as e:
        logger.error(f"❌ Image analysis failed: {e}")
        return None


async def _gemini_analyze(image_bytes: bytes, mime_type: str, caption: str = "") -> Optional[str]:
    """Send image to Gemini for product analysis."""
    try:
        from core.brain import get_gemini_client
        from google.genai import types

        client = get_gemini_client()
        if not client:
            logger.error("❌ Gemini client not available")
            return None

        # Build prompt
        if caption:
            prompt_text = IMAGE_CAPTION_PROMPT.format(caption=caption)
        else:
            prompt_text = VISION_PROMPT

        # Gemini multimodal: text + inline image
        response = client.models.generate_content(
            model="gemini-2.5-flash",
            contents=[
                types.Content(
                    parts=[
                        types.Part.from_text(text=prompt_text),
                        types.Part.from_bytes(data=image_bytes, mime_type=mime_type),
                    ]
                )
            ],
        )

        result = response.text.strip()
        
        if not result or result == "NO_PRODUCT":
            logger.info("📷 Image is not a product")
            return None

        logger.info(f"📷 Visual analysis: '{result}'")
        return result

    except Exception as e:
        logger.error(f"❌ Gemini vision failed: {e}")
        return None


# ═══════════════════════════════════════════════════════════════
# SEARCH + FORMAT RESULTS
# ═══════════════════════════════════════════════════════════════

def visual_search_products(description: str, products: list, max_results: int = 3) -> list:
    """
    Search catalog using the visual description from Gemini.
    Wrapper around search_products with visual-optimized defaults.
    """
    from knowledge.scraper import search_products
    
    if not description or not products:
        return []

    return search_products(description, products, max_results=max_results)


def build_visual_search_response(matches: list, description: str = "") -> str:
    """
    Build a friendly response with visual search matches.
    
    Args:
        matches: List of product dicts from visual_search_products()
        description: The Gemini-generated description (for context)
    """
    if not matches:
        return (
            "No encontré algo exactamente igual en nuestro catálogo, "
            "pero dime más sobre lo que buscas y te ayudo a encontrarlo 💕"
        )

    if len(matches) == 1:
        p = matches[0]
        price = _format_price(p)
        return (
            f"¡Encontré algo muy similar! 😍\n\n"
            f"👉 *{p['name']}* — {price}\n"
            f"   {_availability(p)}\n"
            f"   {p.get('url', '')}\n\n"
            f"¿Te interesa? 💕"
        )

    lines = ["¡Mira lo que encontré! 😍\n"]
    for i, p in enumerate(matches, 1):
        price = _format_price(p)
        lines.append(f"{i}. *{p['name']}* — {price}")
        lines.append(f"   {_availability(p)}")

    lines.append("\n¿Cuál te gusta más? 💕")
    return "\n".join(lines)


# ═══════════════════════════════════════════════════════════════
# HELPERS
# ═══════════════════════════════════════════════════════════════

def _format_price(product: dict) -> str:
    """Format price range for display."""
    price_min = product.get("price_min", 0)
    price_max = product.get("price_max", 0)
    if price_max > price_min:
        return f"RD${price_min:,.0f} - RD${price_max:,.0f}"
    return f"RD${price_min:,.0f}"


def _availability(product: dict) -> str:
    return "✅ Disponible" if product.get("available") else "❌ Agotado"


def _detect_mime_type(content_type: str, url: str) -> str:
    """Detect image MIME type from headers or URL extension."""
    if "jpeg" in content_type or "jpg" in content_type:
        return "image/jpeg"
    if "png" in content_type:
        return "image/png"
    if "webp" in content_type:
        return "image/webp"
    if "gif" in content_type:
        return "image/gif"

    # Fallback to URL extension
    url_lower = url.lower()
    if ".png" in url_lower:
        return "image/png"
    if ".webp" in url_lower:
        return "image/webp"
    if ".gif" in url_lower:
        return "image/gif"

    return "image/jpeg"  # Default — WhatsApp usually sends JPEG
