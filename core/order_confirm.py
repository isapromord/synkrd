"""
SynkDR Engine — Order Confirmation (Anti-Rejection COD Flow)

When a NEW order arrives from the online store (Shopify orders/create webhook),
Sofía proactively reaches out on WhatsApp to CONFIRM the order and ask the
customer to make sure someone will be home to receive it.

This is the single highest-impact task a human customer-service rep does for a
COD (contra entrega) store: confirming delivery availability BEFORE dispatch
dramatically reduces failed deliveries / rejected packages.

This module is PURE + deterministic (no side effects). main.py orchestrates
sending via the WhatsApp channel and logging.
"""

import logging
from typing import Optional

logger = logging.getLogger("synkdr.order_confirm")


# ═══════════════════════════════════════════════════════════════
# PAYMENT METHOD DETECTION
# ═══════════════════════════════════════════════════════════════

# Gateway/name fragments that indicate Cash-On-Delivery
_COD_GATEWAY_HINTS = (
    "cash on delivery",
    "cash_on_delivery",
    "contra entrega",
    "contraentrega",
    "contra-entrega",
    "cod",
    "manual",  # Shopify manual payment is the usual COD setup for DR stores
)


def is_cod_order(payload: dict) -> bool:
    """
    Decide whether a Shopify order is Cash-On-Delivery (pago contra entrega).

    Heuristics (any match → COD):
    - financial_status is "pending" (payment not captured yet)
    - a payment gateway name looks like COD / manual

    Prepaid orders (transfer/card already captured) return False.
    """
    financial_status = (payload.get("financial_status") or "").lower()
    if financial_status == "pending":
        return True

    gateways = payload.get("payment_gateway_names") or []
    gateway_str = " ".join(str(g).lower() for g in gateways)
    if payload.get("gateway"):
        gateway_str += " " + str(payload["gateway"]).lower()

    return any(hint in gateway_str for hint in _COD_GATEWAY_HINTS)


# ═══════════════════════════════════════════════════════════════
# PHONE NORMALIZATION (Dominican default)
# ═══════════════════════════════════════════════════════════════

def normalize_phone(phone: str) -> str:
    """
    Normalize a phone number to E.164-ish format with a country code.
    Defaults missing country codes to +1 (Dominican Republic / North America).
    Returns "" if no usable phone.
    """
    if not phone:
        return ""

    cleaned = (
        phone.replace(" ", "")
        .replace("-", "")
        .replace("(", "")
        .replace(")", "")
        .replace(".", "")
    )
    if not cleaned:
        return ""

    if cleaned.startswith("+"):
        return cleaned
    if cleaned.startswith("1") and len(cleaned) == 11:
        return f"+{cleaned}"
    if len(cleaned) == 10:
        return f"+1{cleaned}"
    # Unknown format — prefix + and hope the channel handles it
    return f"+{cleaned}"


# ═══════════════════════════════════════════════════════════════
# ORDER DETAIL EXTRACTION
# ═══════════════════════════════════════════════════════════════

def extract_order_details(payload: dict) -> Optional[dict]:
    """
    Parse a Shopify orders/create payload into the fields needed to build
    a confirmation message.

    Returns a dict with:
        order_name, phone, first_name, items_str, item_count, total, currency, is_cod
    Returns None if there is no phone (can't reach the customer).
    """
    phone_raw = (
        payload.get("phone")
        or payload.get("shipping_address", {}).get("phone")
        or payload.get("billing_address", {}).get("phone")
        or payload.get("customer", {}).get("phone")
        or ""
    )
    phone = normalize_phone(phone_raw)
    if not phone:
        return None

    # Customer first name
    first_name = ""
    ship = payload.get("shipping_address") or {}
    cust = payload.get("customer") or {}
    first_name = (
        ship.get("first_name")
        or cust.get("first_name")
        or (payload.get("billing_address") or {}).get("first_name")
        or ""
    ).strip()

    # Line items → readable string (max 3)
    line_items = payload.get("line_items") or []
    names = []
    for li in line_items:
        title = li.get("title") or li.get("name") or ""
        qty = li.get("quantity", 1)
        if not title:
            continue
        names.append(f"{title}" + (f" ×{qty}" if qty and qty > 1 else ""))

    shown = names[:3]
    items_str = ", ".join(shown)
    if len(names) > 3:
        items_str += f" y {len(names) - 3} más"

    return {
        "order_name": payload.get("name") or f"#{payload.get('order_number', '')}",
        "phone": phone,
        "first_name": first_name,
        "items_str": items_str,
        "item_count": len(names),
        "total": float(payload.get("total_price", 0) or 0),
        "currency": payload.get("currency", "DOP"),
        "is_cod": is_cod_order(payload),
    }


# ═══════════════════════════════════════════════════════════════
# MESSAGE BUILDERS
# ═══════════════════════════════════════════════════════════════

def build_confirmation_message(
    details: dict,
    bot_name: str = "Sofía",
    store_name: str = "la tienda",
    delivery_days: str = "4-7",
) -> str:
    """
    Build the proactive WhatsApp confirmation message.

    For COD orders → includes the anti-rejection ask (confirm someone will
    receive it). For prepaid orders → a lighter thank-you + delivery window.
    """
    name = details.get("first_name") or ""
    greeting_name = f" {name}" if name else ""
    order_name = details.get("order_name", "")
    items_str = details.get("items_str", "tu pedido")
    total = details.get("total", 0)
    currency = details.get("currency", "DOP")
    currency_sym = "RD$" if currency in ("DOP", "RD$") else currency

    if details.get("is_cod"):
        return (
            f"¡Hola{greeting_name}! 👋 Soy {bot_name} de {store_name}.\n\n"
            f"¡Recibimos tu pedido! 🎉\n"
            f"🧾 Orden: {order_name}\n"
            f"📦 {items_str}\n"
            f"💰 {currency_sym}{total:,.0f} — Pagas al recibirlo 📲\n\n"
            f"El mensajero pasa en {delivery_days} días laborables 🛵\n"
            f"Para asegurar la entrega, ¿me confirmas que habrá alguien "
            f"en la dirección para recibirlo? ✅"
        )

    # Prepaid order — already paid
    return (
        f"¡Hola{greeting_name}! 👋 Soy {bot_name} de {store_name}.\n\n"
        f"¡Recibimos tu pedido y tu pago! 🎉\n"
        f"🧾 Orden: {order_name}\n"
        f"📦 {items_str}\n\n"
        f"Te llega en {delivery_days} días laborables con código de seguimiento 📦\n"
        f"¿Confirmas que la dirección de entrega está correcta? ✅"
    )


def build_owner_alert(details: dict) -> str:
    """Build the Telegram alert sent to the store owner about a new order."""
    tag = "COD" if details.get("is_cod") else "Prepago"
    currency = details.get("currency", "DOP")
    currency_sym = "RD$" if currency in ("DOP", "RD$") else currency
    return (
        f"🛒 *Nuevo pedido web* ({tag})\n"
        f"🧾 {details.get('order_name', '')}\n"
        f"📦 {details.get('items_str', '')}\n"
        f"💰 {currency_sym}{details.get('total', 0):,.0f}\n"
        f"📱 {details.get('phone', '')}\n"
        f"✅ Sofía envió confirmación de entrega al cliente."
    )


# ═══════════════════════════════════════════════════════════════
# TEMPLATE PARAM BUILDERS (YCloud es_DO templates)
# Order of params MUST match the {{1}},{{2}},... in each YCloud template.
# ═══════════════════════════════════════════════════════════════

def _fmt_total(details: dict) -> str:
    try:
        return f"{float(details.get('total', 0) or 0):,.0f}"
    except (TypeError, ValueError):
        return "0"


def _name_or_default(details: dict) -> str:
    return details.get("first_name") or "amig@"


def confirmacion_cod_params(details: dict) -> list:
    """{{1}}nombre {{2}}orden {{3}}items {{4}}total"""
    return [
        _name_or_default(details),
        details.get("order_name", ""),
        details.get("items_str", "tu pedido"),
        _fmt_total(details),
    ]


def pedido_en_camino_params(details: dict) -> list:
    """{{1}}nombre {{2}}orden"""
    return [_name_or_default(details), details.get("order_name", "")]


def entrega_hoy_params(details: dict) -> list:
    """{{1}}nombre {{2}}orden {{3}}total"""
    return [_name_or_default(details), details.get("order_name", ""), _fmt_total(details)]


def post_entrega_params(details: dict) -> list:
    """{{1}}nombre {{2}}orden"""
    return [_name_or_default(details), details.get("order_name", "")]


# ═══════════════════════════════════════════════════════════════
# BUTTON-TAP RESPONSES (free-form; a tap reopens the 24h window)
# details here is a stored sofia_cod_orders row (or {}).
# ═══════════════════════════════════════════════════════════════

def _n(order: dict) -> str:
    return order.get("first_name") or "amig@"


def _o(order: dict) -> str:
    return order.get("order_name") or "tu pedido"


def reply_confirm_ack(order: dict) -> str:
    return (
        f"¡Perfecto {_n(order)}! 🙌 Tu pedido {_o(order)} queda confirmado. "
        f"Te aviso cuando salga en camino. 📦"
    )


def reply_delivery_today_ack(order: dict) -> str:
    return (
        f"¡Genial {_n(order)}! 🛵 El mensajero va en camino hoy. "
        f"Ten listo tu pago al recibir. ¡Gracias! 💛"
    )


def reply_reschedule_ack(order: dict) -> str:
    return (
        f"Claro {_n(order)}, sin problema 📅 ¿Qué día te queda mejor para recibir "
        f"tu pedido {_o(order)}? Escríbeme el día y lo coordinamos."
    )


def reply_received_ask_review(order: dict) -> str:
    return (
        f"¡Qué bueno {_n(order)}! 🎉 Gracias por tu compra. "
        f"¿Nos regalas tu opinión del producto? Escríbela aquí y la comparto "
        f"con el equipo 💛"
    )


def reply_not_received_ack(order: dict) -> str:
    return (
        f"¡Ay {_n(order)}, lo siento! 😟 Ya estoy avisando al equipo para que revise "
        f"tu pedido {_o(order)} de inmediato. Te contactamos enseguida. 🙏"
    )


# ── Owner alert bodies (inner text; wrapper added by alerta_dueno template) ──
# NOTE: These strings are passed as a WhatsApp template {{1}} parameter, which
# forbids newlines / tabs / 4+ spaces. Keep everything on a single line using
# " · " separators, or Meta rejects the send with a format error.

def owner_not_received_alert(order: dict) -> str:
    return (
        f"⚠️ PEDIDO NO RECIBIDO · "
        f"{order.get('order_name', '')} — {order.get('first_name', '')} · "
        f"📱 {order.get('phone', '')} · "
        f"El cliente reporta que NO le ha llegado. Revisar con el mensajero."
    )


def owner_reschedule_alert(order: dict) -> str:
    return (
        f"📅 REPROGRAMAR ENTREGA · "
        f"{order.get('order_name', '')} — {order.get('first_name', '')} · "
        f"📱 {order.get('phone', '')} · "
        f"El cliente pidió reprogramar la entrega."
    )


def owner_review_forward(order: dict, review_text: str) -> str:
    return (
        f"⭐ NUEVA RESEÑA · "
        f"{order.get('order_name', '')} — {order.get('first_name', '')} · "
        f"📱 {order.get('phone', '')} · "
        f"\"{review_text}\""
    )
