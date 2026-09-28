"""
SynkDR Engine — Price Watch & Drop Alerts

Tracks products customers expressed interest in at a certain price.
When prices drop during Shopify sync, queues alerts for sending.

Flow:
1. Customer says "está cara" / "avísame si baja" → save_price_watch(phone, product, current_price)
2. Scheduler syncs products → compare_prices_and_alert(old_products, new_products)
3. For each drop → send template via WhatsApp (24h+ window) or text (within 24h)
"""

import re
import logging
from typing import Optional

logger = logging.getLogger("synkdr.price_watch")


# ═══════════════════════════════════════════════════════════════
# PRICE INTEREST DETECTION
# ═══════════════════════════════════════════════════════════════

# Patterns that signal "I want this but the price is the blocker"
PRICE_WATCH_PATTERNS = [
    r"\b(avís[ae]me|notifí[cq]ame|dime|avisame)\b.*(baj[ae]|oferta|descuento|rebaj)",
    r"\b(baj[ae]|oferta|descuento|rebaj)\b.*(avís[ae]me|notifí[cq]ame|dime|avisame)",
    r"\b(está|esta|muy|es)\b.*(car[oa]|costoso|elevado)",
    r"\b(me (gusta|interesa|encanta))\b.*(pero|precio|car[oa])",
    r"\b(cuando|si)\b.*(baj[ae] de precio|haya oferta|tenga descuento|rebaj)",
    r"\b(alert[ae]me|házmelo saber|hazmelo saber)\b",
    r"\bme interesa pero\b",
]

_compiled_patterns = [re.compile(p, re.IGNORECASE) for p in PRICE_WATCH_PATTERNS]


def detect_price_watch_intent(message: str) -> bool:
    """
    Detect if the customer is expressing price-sensitive interest.
    E.g., "Me gusta la faja pero está cara", "Avísame si baja"
    """
    for pattern in _compiled_patterns:
        if pattern.search(message):
            return True
    return False


# ═══════════════════════════════════════════════════════════════
# PRODUCT MATCHING — Find what product they're watching
# ═══════════════════════════════════════════════════════════════

def find_watched_product(message: str, conversation_history: list, products: list) -> Optional[dict]:
    """
    Determine which product the customer wants to watch.
    
    Strategy:
    1. Search current message for product name keywords
    2. Look at recent conversation for product mentions
    3. Return the most likely product match
    """
    from knowledge.scraper import search_products

    # Try matching from current message first
    matches = search_products(message, products, max_results=1)
    if matches:
        return matches[0]

    # Look back through recent conversation for product context
    recent_msgs = conversation_history[-6:] if conversation_history else []
    for msg in reversed(recent_msgs):
        content = msg.get("content", "") if isinstance(msg, dict) else str(msg)
        if not content:
            continue
        matches = search_products(content, products, max_results=1)
        if matches:
            return matches[0]

    return None


# ═══════════════════════════════════════════════════════════════
# PRICE COMPARISON — Detect drops during sync
# ═══════════════════════════════════════════════════════════════

def find_price_drops(old_products: list, new_products: list, min_drop_pct: float = 5.0) -> list:
    """
    Compare old vs new product lists and find price drops.
    
    Args:
        old_products: Products from DB (before sync)
        new_products: Fresh products from Shopify
        min_drop_pct: Minimum % drop to trigger alert (default 5%)
    
    Returns:
        List of dicts: {product, old_price, new_price, drop_pct}
    """
    # Build lookup by shopify_id
    old_prices = {}
    for p in old_products:
        sid = p.get("shopify_id", "")
        if sid:
            old_prices[sid] = p.get("price_min", 0)

    drops = []
    for p in new_products:
        sid = p.get("shopify_id", "")
        new_price = p.get("price_min", 0)
        old_price = old_prices.get(sid, 0)

        if old_price > 0 and new_price > 0 and new_price < old_price:
            drop_pct = ((old_price - new_price) / old_price) * 100
            if drop_pct >= min_drop_pct:
                drops.append({
                    "product": p,
                    "old_price": old_price,
                    "new_price": new_price,
                    "drop_pct": round(drop_pct, 1),
                })

    return drops


def match_alerts_to_drops(watches: list, drops: list) -> list:
    """
    Match price watches to price drops.
    
    Args:
        watches: List of price_watch records from DB
        drops: List of price drop dicts from find_price_drops()
        
    Returns:
        List of {watch, drop} dicts — customers to notify
    """
    # Build drop lookup by shopify_id
    drop_by_id = {}
    for d in drops:
        sid = d["product"].get("shopify_id", "")
        if sid:
            drop_by_id[sid] = d

    notifications = []
    for watch in watches:
        sid = watch.get("product_shopify_id", "")
        if sid in drop_by_id:
            drop = drop_by_id[sid]
            # Only notify if new price is below what they saw
            if drop["new_price"] < watch.get("price_at_watch", float("inf")):
                notifications.append({
                    "watch": watch,
                    "drop": drop,
                })

    return notifications


# ═══════════════════════════════════════════════════════════════
# MESSAGE BUILDERS
# ═══════════════════════════════════════════════════════════════

def build_price_watch_confirmation(product_name: str, price: float) -> str:
    """Confirmation message when we save a price watch."""
    return (
        f"¡Anotado! 📝 Te aviso si *{product_name}* baja de "
        f"RD${price:,.0f}. Prometo ser la primera en decirte 💕"
    )


def build_price_drop_text(
    customer_name: str,
    product_name: str,
    old_price: float,
    new_price: float,
    product_url: str = "",
) -> str:
    """Build a friendly price drop notification (for within 24h window)."""
    savings = old_price - new_price
    name_part = f"¡Hola {customer_name}!" if customer_name else "¡Hola!"
    
    msg = (
        f"{name_part} 🎉\n\n"
        f"*{product_name}* bajó de precio:\n"
        f"   ~~RD${old_price:,.0f}~~ → *RD${new_price:,.0f}*\n"
        f"   ¡Te ahorras RD${savings:,.0f}! 🔥\n"
    )
    if product_url:
        msg += f"\n👉 {product_url}\n"
    msg += "\n¿Te interesa? Solo dime y te lo separo 💕"
    return msg


def build_price_drop_template_params(
    customer_name: str,
    product_name: str,
    old_price: str,
    new_price: str,
) -> list:
    """
    Build params for the 'price_drop_alert' WhatsApp template.
    
    Template expected format (submit to Meta for approval):
    "¡Hola {{1}}! 🎉 {{2}} bajó de {{3}} a {{4}}. ¿Te interesa?"
    
    Returns list of param strings in order.
    """
    name = customer_name if customer_name else "amiga"
    return [name, product_name, f"RD${old_price}", f"RD${new_price}"]
