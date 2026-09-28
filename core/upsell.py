"""
SynkDR Engine — Smart Upsell Module

Recommends complementary products after checkout completion.
Uses category matching + tag overlap to find relevant cross-sells.

Strategy:
1. Detect the purchased product's category
2. Find products in the SAME or COMPLEMENTARY categories
3. Exclude the product just purchased
4. Rank by tag overlap (most related first)
5. Append upsell suggestion to the order confirmation message
"""

import logging
from typing import Optional

logger = logging.getLogger("synkdr.upsell")


# ═══════════════════════════════════════════════════════════════
# CATEGORY COMPLEMENTARITY MAP
# ═══════════════════════════════════════════════════════════════

# If customer bought from category X, also suggest from these categories.
# Order matters: first = most relevant complement.
COMPLEMENTARY_CATEGORIES = {
    "belleza": ["belleza", "accesorios"],
    "fajas": ["belleza", "ropa"],
    "ropa": ["zapatos", "accesorios", "fajas"],
    "zapatos": ["ropa", "accesorios"],
    "accesorios": ["belleza", "ropa"],
    "tecnología": ["tecnología", "hogar"],
    "hogar": ["hogar", "tecnología"],
}

# Category detection keywords (same set as customer_memory.py — kept in sync)
_CATEGORY_KEYWORDS = {
    "belleza": ["crema", "sérum", "serum", "mascarilla", "facial", "skin", "beauty"],
    "fajas": ["faja", "body", "cinturilla", "waist"],
    "tecnología": ["parlante", "bluetooth", "audífono", "cargador", "led", "smart"],
    "ropa": ["camisa", "blusa", "vestido", "pantalón", "short", "jean"],
    "zapatos": ["zapato", "tenis", "sandalia", "bota"],
    "accesorios": ["reloj", "gafas", "bolso", "cartera", "collar"],
    "hogar": ["almohada", "sábana", "organizador", "lámpara"],
}


def detect_category(product_name: str) -> Optional[str]:
    """Detect product category from name keywords."""
    name_lower = product_name.lower()
    for category, keywords in _CATEGORY_KEYWORDS.items():
        for kw in keywords:
            if kw in name_lower:
                return category
    return None


def get_complementary_categories(category: str) -> list:
    """Get categories that complement a given category."""
    return COMPLEMENTARY_CATEGORIES.get(category, [])


def score_product_relevance(candidate: dict, purchased_tags: set) -> int:
    """
    Score how relevant a candidate product is to the purchased one.
    Higher = more relevant.

    Scoring:
    - Tag overlap: +3 per shared tag
    - Has price info: +1
    - Available: +2
    """
    score = 0
    candidate_tags = {t.strip().lower() for t in candidate.get("tags", "").split(",") if t.strip()}
    overlap = purchased_tags & candidate_tags
    score += len(overlap) * 3

    if candidate.get("price_min", 0) > 0:
        score += 1
    if candidate.get("available", False):
        score += 2

    return score


def find_upsell_products(
    purchased_product_name: str,
    purchased_shopify_id: str,
    catalog: list,
    max_results: int = 2,
    customer_history: list = None,
) -> list:
    """
    Find the best upsell products given what was just purchased.

    Args:
        purchased_product_name: Name of the product just bought.
        purchased_shopify_id: Shopify ID to exclude from results.
        catalog: Full product list (_products_raw).
        max_results: Max recommendations to return.
        customer_history: Optional list of previously purchased product names.

    Returns:
        List of product dicts, ranked by relevance.
    """
    if not catalog:
        return []

    # Build exclusion set (purchased + history)
    exclude_ids = {purchased_shopify_id}
    history_names = set()
    if customer_history:
        history_names = {h.get("name", "").lower() for h in customer_history if h.get("name")}

    # Detect purchased product category
    category = detect_category(purchased_product_name)
    target_categories = get_complementary_categories(category) if category else []

    # Get the tags of the purchased product
    purchased_tags = set()
    for p in catalog:
        if p.get("shopify_id") == purchased_shopify_id:
            purchased_tags = {t.strip().lower() for t in p.get("tags", "").split(",") if t.strip()}
            break

    # Filter candidates
    candidates = []
    for p in catalog:
        pid = p.get("shopify_id", "")
        if pid in exclude_ids:
            continue
        if not p.get("available", False):
            continue
        if p.get("name", "").lower() in history_names:
            continue

        # Category filter: if we know the category, only suggest from complementary ones
        if target_categories:
            p_category = detect_category(p.get("name", ""))
            if p_category and p_category not in target_categories:
                continue

        score = score_product_relevance(p, purchased_tags)
        candidates.append((score, p))

    # Sort by score descending, take top N
    candidates.sort(key=lambda x: x[0], reverse=True)
    return [p for _, p in candidates[:max_results]]


def build_upsell_message(products: list) -> str:
    """
    Build the upsell suggestion text to append after order confirmation.

    Args:
        products: List of recommended product dicts.

    Returns:
        Formatted upsell string, or empty string if no products.
    """
    if not products:
        return ""

    lines = ["\n\n💡 *Para aprovechar el mismo envío:*\n"]

    for i, p in enumerate(products, 1):
        name = p.get("name", "")
        price = p.get("price_min", 0)
        price_str = f"RD${price:,.0f}" if price else ""
        lines.append(f"  {i}. {name} — {price_str}")

    lines.append("\n¿Te agrego alguno al paquete con precio especial? 😊")

    return "\n".join(lines)


def build_volume_discount_upsell(purchased_product_name: str, unit_price: float = 0.0) -> str:
    """
    When no complementary product exists, offer a 2nd unit of the same
    product with a 15% discount on the total order to leverage the same courier.
    """
    discount_pct = 15
    if unit_price > 0:
        second_unit_price = round(unit_price * (1 - discount_pct / 100))
        combo_total = unit_price + second_unit_price
        return (
            f"\n\n💡 *¡Oferta especial para aprovechar este mismo envío!* 🛵\n"
            f"Si agregas una *2da unidad* de {purchased_product_name}, te la dejamos con un *{discount_pct}% de descuento*:\n"
            f"• 2 unidades por solo *RD${combo_total:,.0f}* (en vez de RD${(unit_price * 2):,.0f}).\n"
            f"¿Te agrego la segunda al paquete? 👀"
        )
    return (
        f"\n\n💡 *¡Aprovecha el mismo envío!* 🛵\n"
        f"Si agregas una *segunda unidad* de {purchased_product_name}, te aplicamos un *15% de descuento* en tu orden total.\n"
        f"¿Te agrego la 2da unidad? 👀"
    )


def build_upsell_response(
    purchased_product_name: str,
    purchased_shopify_id: str,
    catalog: list,
    customer_history: list = None,
    unit_price: float = 0.0,
) -> str:
    """
    One-call convenience: find complementary products or fallback to volume discount.
    Returns the upsell text to append.
    """
    if not catalog:
        return ""

    products = find_upsell_products(
        purchased_product_name=purchased_product_name,
        purchased_shopify_id=purchased_shopify_id,
        catalog=catalog,
        customer_history=customer_history,
    )
    if products:
        return build_upsell_message(products)
    
    if purchased_product_name:
        return build_volume_discount_upsell(purchased_product_name, unit_price)

    return ""
