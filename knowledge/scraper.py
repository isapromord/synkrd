"""
SynkDR Engine — Product Scraper

Fetches products from Shopify.
- With access_token: uses Admin API (/admin/api/.../products.json) → returns real inventory_quantity
- Without access_token: falls back to public /products.json (inventory_quantity = null)
"""

import json
import logging
import re
import urllib.request
import urllib.error
import ssl
from typing import Optional

logger = logging.getLogger("synkdr.knowledge.scraper")


def fetch_all_products(
    store_url: str = "trendyrd.com",
    access_token: str = "",
    api_version: str = "2024-10",
) -> list:
    """
    Fetch all products from Shopify Admin API.

    Requires SHOPIFY_ACCESS_TOKEN — the public endpoint does NOT return
    real inventory_quantity, so without the token stock data is useless.
    """
    if not access_token:
        raise ValueError(
            "SHOPIFY_ACCESS_TOKEN is required. "
            "The public Shopify endpoint returns inventory_quantity=null — "
            "real stock counts are only available via the Admin API."
        )
    return _fetch_admin_products(store_url, access_token, api_version)


def _fetch_admin_products(store_url: str, access_token: str, api_version: str) -> list:
    """Fetch via Admin API — returns real inventory counts."""
    products = []
    ctx = ssl.create_default_context()
    # Admin API uses cursor-based pagination via the Link header
    url = f"https://{store_url}/admin/api/{api_version}/products.json?limit=250"

    page = 0
    while url and page < 10:
        try:
            req = urllib.request.Request(url)
            req.add_header("X-Shopify-Access-Token", access_token)
            req.add_header("User-Agent", "Sofia-Bot/1.0")
            response = urllib.request.urlopen(req, context=ctx, timeout=30)
            data = json.loads(response.read())

            page_products = data.get("products", [])
            for p in page_products:
                products.append(_format_product(p, store_url))

            # Follow cursor-based next page (Link header)
            link_header = response.headers.get("Link", "")
            url = _parse_next_link(link_header)
            page += 1

            if not page_products:
                break

        except urllib.error.HTTPError as e:
            logger.error(f"Admin API HTTP error {e.code}: {e.reason}")
            break
        except Exception as e:
            logger.error(f"Admin API error page {page}: {e}")
            break

    logger.info(f"📦 Admin API: fetched {len(products)} products from {store_url}")
    return products


def _parse_next_link(link_header: str) -> Optional[str]:
    """Extract the 'next' URL from a Shopify Link response header."""
    if not link_header:
        return None
    for part in link_header.split(","):
        part = part.strip()
        if 'rel="next"' in part:
            # Format: <https://...>; rel="next"
            match = re.search(r"<([^>]+)>", part)
            if match:
                return match.group(1)
    return None


def _format_product(product: dict, store_url: str) -> dict:
    """Format a Shopify product for Supabase storage."""
    variants = product.get("variants", [])
    images = product.get("images", [])

    # Get price range
    prices = [float(v.get("price", 0)) for v in variants if v.get("price")]
    min_price = min(prices) if prices else 0
    max_price = max(prices) if prices else 0

    # Check availability
    # Shopify returns available=null when inventory tracking is disabled → treat as available.
    # Only mark unavailable when explicitly False.
    available = any(v.get("available") is not False for v in variants)

    # Clean HTML from description
    description = _strip_html(product.get("body_html", "") or "")

    # Build variant info
    variant_data = []
    for v in variants:
        variant_data.append({
            "title": v.get("title", ""),
            "price": v.get("price", "0"),
            # null available = no inventory tracking = available to sell
            "available": v.get("available") is not False,
            "option1": v.get("option1"),
            "option2": v.get("option2"),
            "inventory_quantity": v.get("inventory_quantity", 0),
        })

    # Build options (Color, Size, etc.)
    options = product.get("options", [])
    option_data = []
    for opt in options:
        if opt.get("name") != "Title":  # Skip default "Title" option
            option_data.append({
                "name": opt.get("name"),
                "values": opt.get("values", []),
            })

    return {
        "shopify_id": str(product.get("id", "")),
        "name": product.get("title", ""),
        "description": description[:2000],  # Truncate long descriptions
        "category": product.get("product_type", ""),
        "tags": ", ".join(product.get("tags", [])) if isinstance(product.get("tags"), list) else product.get("tags", ""),
        "price_min": min_price,
        "price_max": max_price,
        "currency": "DOP",
        "image_url": images[0].get("src", "") if images else "",
        "handle": product.get("handle", ""),
        "url": f"https://{store_url}/products/{product.get('handle', '')}",
        "available": available,
        "variants": json.dumps(variant_data),
        "options": json.dumps(option_data),
    }


def _strip_html(html: str) -> str:
    """Remove HTML tags and clean up text."""
    text = re.sub(r"<[^>]+>", " ", html)
    text = re.sub(r"\s+", " ", text).strip()
    # Decode HTML entities
    text = text.replace("&amp;", "&").replace("&lt;", "<").replace("&gt;", ">")
    text = text.replace("&#39;", "'").replace("&quot;", '"')
    return text


def build_product_context(products: list) -> str:
    """
    Build product context string for AI prompt injection.
    This gives Sofía knowledge about available products.
    Includes urgency tags for low-stock items.
    """
    if not products:
        return "No hay productos disponibles actualmente."

    lines = ["CATÁLOGO DE PRODUCTOS:"]
    for p in products:
        price = f"RD${p['price_min']:,.0f}"
        if p["price_max"] > p["price_min"]:
            price += f" - RD${p['price_max']:,.0f}"

        availability = "✅ Disponible" if p.get("available") else "❌ Agotado"

        # Show variant stock levels + urgency
        stock_info = ""
        urgency_tag = ""
        variants_raw = p.get("variants", "[]")
        vlist = json.loads(variants_raw) if isinstance(variants_raw, str) else variants_raw
        in_stock = [v for v in vlist if v.get("available") or v.get("inventory_quantity", 0) > 0]
        if in_stock and len(in_stock) < len(vlist):
            stock_info = f" | {len(in_stock)}/{len(vlist)} variantes en stock"

        # Calculate total inventory for urgency detection
        total_qty = sum(v.get("inventory_quantity", 0) for v in vlist)
        if total_qty > 0 and total_qty <= 5:
            urgency_tag = f" | 🔥 ¡ÚLTIMAS {total_qty} UNIDADES!"
        elif total_qty > 5 and total_qty <= 20:
            urgency_tag = f" | ⚡ Quedan pocas ({total_qty} unidades)"
        elif total_qty > 20:
            urgency_tag = " | 🔥 POPULAR"

        # Add options info (sizes, colors)
        options_str = ""
        opts = json.loads(p.get("options", "[]")) if isinstance(p.get("options"), str) else p.get("options", [])
        for opt in opts:
            if opt.get("values"):
                options_str += f" | {opt['name']}: {', '.join(opt['values'])}"

        category = p.get("category", "")
        cat_str = f" | Categoría: {category}" if category else ""

        lines.append(
            f"- {p['name']}: {price} | {availability}{urgency_tag}{stock_info}{options_str}{cat_str} | {p.get('url', '')}"
        )

        # Add short description if available
        desc = p.get("description", "")
        if desc and len(desc) > 10:
            lines.append(f"  → {desc[:150]}")

    return "\n".join(lines)


def detect_low_stock(products: list, threshold: int = 10) -> list:
    """
    Scan products and return those with total inventory at or below threshold.
    
    Returns list of dicts: [{name, total_qty, variants_detail}]
    Used by scheduler to trigger seller alerts.
    """
    low_stock = []
    for p in products:
        if not p.get("available"):
            continue  # Skip fully out-of-stock (already agotado)
        variants_raw = p.get("variants", "[]")
        vlist = json.loads(variants_raw) if isinstance(variants_raw, str) else variants_raw
        total_qty = sum(v.get("inventory_quantity", 0) for v in vlist)
        if 0 < total_qty <= threshold:
            low_stock.append({
                "name": p.get("name", "Unknown"),
                "total_qty": total_qty,
                "variants_detail": [
                    {"title": v.get("title", ""), "qty": v.get("inventory_quantity", 0)}
                    for v in vlist if v.get("inventory_quantity", 0) > 0
                ],
            })
    return low_stock


# ═══════════════════════════════════════════════════════════════
# PRODUCT SEARCH ENGINE
# ═══════════════════════════════════════════════════════════════

# Keywords that map to common product terms in Spanish
_SEARCH_SYNONYMS = {
    "faja": ["faja", "reductora", "colombiana", "levanta cola", "short"],
    "crema": ["crema", "facial", "retinol", "guanjing", "ojos", "eye"],
    "mascarilla": ["mascarilla", "facial", "barra", "té verde", "tea"],
    "mascara": ["máscara", "mascara", "cabello", "colágeno", "karseell", "hair"],
    "aceite": ["aceite", "argán", "argan", "marroquí", "karseell", "oil"],
    "combo": ["combo", "kit", "set"],
    "parlante": ["parlante", "speaker", "bocina", "sonido", "magnético"],
    "mochila": ["mochila", "antirrobo", "backpack", "bolso"],
    "banda": ["banda", "audio", "dormir", "gym", "headband"],
    "camiseta": ["camiseta", "compresión", "masculina", "hombre"],
    "masajeador": ["masajeador", "masaje", "pies", "muscular"],
    "cocina": ["cocina", "batidor", "espumante", "eléctrico"],
    "joyero": ["joyero", "joya", "pulsera", "bracelet", "jewelry"],
    "vino": ["vino", "destapador", "abridor", "botella", "wine"],
    "boob": ["boob", "tape", "busto", "levanta", "breast", "bra"],
    "belleza": ["belleza", "beauty", "skin", "piel", "cabello", "hair"],
    "hogar": ["hogar", "casa", "home", "cocina", "kitchen"],
    "salud": ["salud", "health", "masaje", "compresión"],
    "tecnología": ["tecnología", "tech", "parlante", "audio"],
}

# Common Spanish words that should be ignored in product search
_STOPWORDS = {
    "hola", "como", "estas", "estás", "bien", "bueno", "buena", "buenos", "buenas",
    "quiero", "quisiera", "necesito", "busco", "tienes", "tienen", "tiene",
    "puedes", "pueden", "puede", "mostrar", "mostrarme", "enseñar", "enseñame",
    "cuanto", "cuánto", "cuesta", "vale", "precio", "veces", "usar", "debo",
    "para", "por", "con", "sin", "los", "las", "del", "que", "qué",
    "algo", "cosa", "producto", "productos", "esto", "eso", "ese", "esta",
    "hay", "ver", "dame", "dime", "favor", "gracias", "pagina", "página",
    "web", "online", "línea", "linea", "ahora", "hoy", "donde", "dónde",
    "muy", "más", "mas", "mejor", "cual", "cuál", "todo", "todos", "todas",
    "uno", "una", "unos", "unas", "otro", "otra", "otros", "otras",
    "tambien", "también", "soy", "estoy", "aqui", "aquí", "ahi", "ahí",
}


def search_products(query: str, products: list, max_results: int = 5) -> list:
    """
    Search products by keyword matching against name, description, category, and tags.
    Returns a ranked list of matching products with full details.
    """
    if not query or not products:
        return []

    # Clean query: lowercase, strip punctuation, remove stopwords
    query_clean = re.sub(r'[¿?¡!.,;:"\']', '', query.lower())
    query_words = [w for w in query_clean.split() if w not in _STOPWORDS and len(w) >= 3]

    if not query_words:
        return []  # Only stopwords — return empty (will use full catalog fallback)

    # Expand query with synonyms (exact word match only)
    expanded_words = set(query_words)
    for word in query_words:
        for _key, synonyms in _SEARCH_SYNONYMS.items():
            if word in synonyms:
                expanded_words.update(synonyms)
            # Also check if query word is a stem of a synonym (e.g. "fajas" → "faja")
            elif any(word.rstrip('s') == s or s.startswith(word.rstrip('s')) for s in synonyms):
                expanded_words.update(synonyms)

    scored = []
    for p in products:
        score = 0
        name_lower = p.get("name", "").lower()
        desc_lower = p.get("description", "").lower()
        cat_lower = p.get("category", "").lower()
        tags_lower = p.get("tags", "").lower()

        for word in expanded_words:
            if len(word) < 3:
                continue
            # Name match: highest weight
            if word in name_lower:
                score += 10
            # Category match: high weight
            if word in cat_lower:
                score += 8
            # Tags match
            if word in tags_lower:
                score += 5
            # Description match: only for words >= 4 chars (avoid false positives)
            if len(word) >= 4 and word in desc_lower:
                score += 2

        # Minimum score threshold: require at least a name/category/tag match
        # (desc-only matches with score <= 4 are too weak)
        if score >= 5:
            scored.append((score, p))

    # Sort by score descending
    scored.sort(key=lambda x: x[0], reverse=True)
    return [p for _, p in scored[:max_results]]


def build_search_context(products: list) -> str:
    """Build rich product context for search results — includes full descriptions."""
    if not products:
        return ""

    lines = []
    for i, p in enumerate(products, 1):
        price = f"RD${p['price_min']:,.0f}"
        if p["price_max"] > p["price_min"]:
            price += f" - RD${p['price_max']:,.0f}"

        availability = "✅ Disponible" if p.get("available") else "❌ Agotado"

        options_str = ""
        opts = json.loads(p.get("options", "[]")) if isinstance(p.get("options"), str) else p.get("options", [])
        for opt in opts:
            if opt.get("values"):
                options_str += f"\n   Opciones {opt['name']}: {', '.join(opt['values'])}"

        category = p.get("category", "")

        lines.append(f"📦 PRODUCTO {i}: {p['name']}")
        lines.append(f"   Precio: {price}")
        lines.append(f"   Estado: {availability}")
        if category:
            lines.append(f"   Categoría: {category}")
        if options_str:
            lines.append(options_str)
        lines.append(f"   Link: {p.get('url', '')}")

        # Show variant-level inventory with urgency
        variants_raw = p.get("variants", "[]")
        vlist = json.loads(variants_raw) if isinstance(variants_raw, str) else variants_raw

        # Total inventory urgency tag
        total_qty = sum(v.get("inventory_quantity", 0) for v in vlist)
        if total_qty > 0 and total_qty <= 5:
            lines.append(f"   🔥 ¡ÚLTIMAS {total_qty} UNIDADES! — Dile al cliente exactamente cuántas quedan para crear urgencia")
        elif total_qty > 5 and total_qty <= 20:
            lines.append(f"   ⚡ Quedan pocas: {total_qty} unidades — Menciona que el stock es limitado")
        elif total_qty > 20:
            lines.append(f"   🔥 POPULAR: Di que este producto se está vendiendo muy rápido. NO des la cantidad.")

        if vlist and len(vlist) > 1:
            stock_lines = []
            for v in vlist:
                qty = v.get("inventory_quantity", 0) or 0
                is_available = v.get("available", True)  # True = available (null treated as available)
                title = v.get("title", "Default")
                if is_available and qty > 0:
                    stock_lines.append(f"✅ {title} ({qty} disponibles)")
                elif is_available and qty == 0:
                    # available=True, qty=null/0 → inventory not tracked → in stock
                    stock_lines.append(f"✅ {title} (disponible)")
                else:
                    stock_lines.append(f"❌ {title} (agotado)")
            lines.append(f"   Inventario por variante: {', '.join(stock_lines)}")

        # FULL description — this is the key difference
        desc = p.get("description", "")
        if desc and len(desc) > 10:
            lines.append(f"   Descripción completa: {desc}")
        lines.append("")

    return "\n".join(lines)


# ═══════════════════════════════════════════════════════════════
# CLI: Run directly to test product scraping
# ═══════════════════════════════════════════════════════════════

if __name__ == "__main__":
    print("🔍 Scraping products from Shopify store...")
    products = fetch_all_products()
    print(f"\n📦 Found {len(products)} products:\n")
    for p in products:
        status = "✅" if p["available"] else "❌"
        print(f"  {status} {p['name']} — RD${p['price_min']:,.0f}")
        if p.get("options") and p["options"] != "[]":
            opts = json.loads(p["options"]) if isinstance(p["options"], str) else p["options"]
            for opt in opts:
                print(f"     {opt['name']}: {', '.join(opt.get('values', []))}")

    print(f"\n--- Product Context for AI ---")
    print(build_product_context(products))
