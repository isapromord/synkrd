"""
SynkDR Engine — Customer Memory

Persistent memory for returning customers: names, addresses, sizes,
purchase history, and preferences. Auto-learns from every interaction.
"""

import logging
from typing import Optional
from datetime import datetime, timezone

logger = logging.getLogger("synkdr.memory")


# ═══════════════════════════════════════════════════════════════
# PROFILE LOADING & CONTEXT BUILDING
# ═══════════════════════════════════════════════════════════════

def build_customer_context(profile: dict) -> str:
    """
    Build a text snippet injected into the AI system prompt
    so Sofía 'remembers' the customer.

    Returns empty string for new customers (no profile yet).
    """
    if not profile:
        return ""

    parts = []
    name = profile.get("name", "")
    if name:
        parts.append(f"- Se llama **{name}**. Salúdale por su nombre.")

    # Address
    addr = profile.get("default_address") or {}
    if addr.get("address1"):
        city = addr.get("city", "")
        addr_str = addr["address1"]
        if city:
            addr_str += f", {city}"
        parts.append(f"- Dirección guardada: {addr_str}")

    # Purchase history
    total_orders = profile.get("total_orders", 0)
    total_spent = profile.get("total_spent", 0)
    if total_orders > 0:
        parts.append(
            f"- Cliente recurrente: {total_orders} pedido(s), "
            f"RD${float(total_spent):,.0f} en total."
        )

    # Recent products
    product_history = profile.get("product_history") or []
    if product_history:
        recent = product_history[-3:]  # Last 3 purchases
        names = [p.get("name", "?") for p in recent]
        parts.append(f"- Últimas compras: {', '.join(names)}")

    # Size preferences
    sizes = profile.get("preferred_sizes") or {}
    if sizes:
        size_str = ", ".join(f"{k}: {v}" for k, v in sizes.items())
        parts.append(f"- Tallas conocidas: {size_str}")

    # Categories
    categories = profile.get("preferred_categories") or []
    if categories:
        parts.append(f"- Le interesan: {', '.join(categories)}")

    if not parts:
        return ""

    header = "👤 MEMORIA DEL CLIENTE (info privada — úsala naturalmente, NO la repitas textualmente):"
    return header + "\n" + "\n".join(parts)


# ═══════════════════════════════════════════════════════════════
# AUTO-LEARN FROM COMPLETED CHECKOUT
# ═══════════════════════════════════════════════════════════════

def learn_from_checkout(existing_profile: Optional[dict], checkout_session) -> dict:
    """
    Build an update dict for customer_profiles after a completed checkout.
    Takes the checkout session and existing profile (may be None) to merge.

    Returns dict ready for upsert_customer_profile().
    """
    profile = existing_profile or {}

    updates = {}

    # Name
    name = getattr(checkout_session, "customer_name", "") or ""
    if name and name != getattr(checkout_session, "customer_phone", ""):
        updates["name"] = name

    # Address — always update with latest
    address = getattr(checkout_session, "address", {}) or {}
    if address.get("address1"):
        updates["default_address"] = address

    # Order counters
    prev_orders = profile.get("total_orders", 0) or 0
    prev_spent = float(profile.get("total_spent", 0) or 0)
    price = getattr(checkout_session, "price", 0) or 0
    qty = getattr(checkout_session, "quantity", 1) or 1
    order_total = price * qty

    updates["total_orders"] = prev_orders + 1
    updates["total_spent"] = prev_spent + order_total
    updates["last_order_date"] = datetime.now(timezone.utc).isoformat()

    # Product history — append, keep last 10
    product_history = list(profile.get("product_history") or [])
    product_history.append({
        "name": getattr(checkout_session, "product_name", ""),
        "variant": getattr(checkout_session, "variant_title", ""),
        "price": price,
        "date": datetime.now(timezone.utc).strftime("%Y-%m-%d"),
    })
    updates["product_history"] = product_history[-10:]

    # Size preferences — learn variant as size for product category
    variant_title = getattr(checkout_session, "variant_title", "") or ""
    product_name = getattr(checkout_session, "product_name", "") or ""
    if variant_title and variant_title not in ("Default Title", "Default"):
        sizes = dict(profile.get("preferred_sizes") or {})
        # Use simplified product name as key
        size_key = _simplify_product_name(product_name)
        if size_key:
            sizes[size_key] = variant_title
            updates["preferred_sizes"] = sizes

    # Category preferences — extract from product name
    category = _detect_category(product_name)
    if category:
        categories = list(profile.get("preferred_categories") or [])
        if category not in categories:
            categories.append(category)
            updates["preferred_categories"] = categories[-5:]  # Keep last 5

    # Channel
    channel = getattr(checkout_session, "channel", None)
    if channel:
        updates["channel"] = channel

    return updates


# ═══════════════════════════════════════════════════════════════
# CHECKOUT SHORTCUT — PRE-FILL FROM MEMORY
# ═══════════════════════════════════════════════════════════════

def prefill_checkout_from_profile(profile: dict, checkout_session) -> bool:
    """
    Pre-fill a CheckoutSession with saved customer data.
    Returns True if address was pre-filled (can skip address step).
    """
    if not profile:
        return False

    address_prefilled = False

    # Pre-fill name
    name = profile.get("name", "")
    if name and not checkout_session.customer_name:
        checkout_session.customer_name = name

    # Pre-fill address
    saved_address = profile.get("default_address") or {}
    if saved_address.get("address1") and not checkout_session.address:
        checkout_session.address = saved_address
        address_prefilled = True

    return address_prefilled


def get_saved_size_for_product(profile: dict, product_name: str) -> Optional[str]:
    """
    Check if we know this customer's preferred size for a product.
    Returns the size string or None.
    """
    if not profile:
        return None

    sizes = profile.get("preferred_sizes") or {}
    key = _simplify_product_name(product_name)
    return sizes.get(key)


# ═══════════════════════════════════════════════════════════════
# INTERNAL HELPERS
# ═══════════════════════════════════════════════════════════════

# Product categories for auto-classification
CATEGORY_KEYWORDS = {
    "belleza": ["crema", "sérum", "serum", "mascarilla", "facial", "skin", "beauty"],
    "fajas": ["faja", "body", "cinturilla", "waist"],
    "tecnología": ["parlante", "bluetooth", "audífono", "cargador", "led", "smart"],
    "ropa": ["camisa", "blusa", "vestido", "pantalón", "short", "jean"],
    "zapatos": ["zapato", "tenis", "sandalia", "bota"],
    "accesorios": ["reloj", "gafas", "bolso", "cartera", "collar"],
    "hogar": ["almohada", "sábana", "organizador", "lámpara"],
}


def _detect_category(product_name: str) -> Optional[str]:
    """Detect product category from name."""
    name_lower = product_name.lower()
    for category, keywords in CATEGORY_KEYWORDS.items():
        for kw in keywords:
            if kw in name_lower:
                return category
    return None


def _simplify_product_name(product_name: str) -> str:
    """Simplify product name to use as a size-preference key."""
    name_lower = product_name.lower()
    # Try to find a category keyword as key
    for category, keywords in CATEGORY_KEYWORDS.items():
        for kw in keywords:
            if kw in name_lower:
                return kw
    # Fallback: first two words
    words = product_name.split()[:2]
    return " ".join(words).lower() if words else ""
