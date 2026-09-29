"""
SynkDR Engine — In-Chat Checkout Flow

Manages the multi-step COD checkout process inside WhatsApp/webchat.
Steps: identify product → collect address → confirm → create order.
"""

import re
import logging
from enum import Enum
from typing import Optional, Tuple
from dataclasses import dataclass, field

logger = logging.getLogger("synkdr.checkout")


# ═══════════════════════════════════════════════════════════════
# CHECKOUT STATES
# ═══════════════════════════════════════════════════════════════

class CheckoutStep(str, Enum):
    IDLE = "idle"                           # Not in checkout
    PRODUCT_CONFIRM = "product_confirm"     # Confirm product + variant
    ADDRESS_COLLECT = "address_collect"     # Collect shipping address
    ORDER_CONFIRM = "order_confirm"         # Show summary, wait for "sí"
    COMPLETED = "completed"                 # Order created


# ═══════════════════════════════════════════════════════════════
# CHECKOUT SESSION
# ═══════════════════════════════════════════════════════════════

@dataclass
class CheckoutSession:
    """Tracks state of an in-progress checkout."""
    step: CheckoutStep = CheckoutStep.IDLE
    product_name: str = ""
    variant_id: str = ""
    variant_title: str = ""
    price: float = 0.0
    quantity: int = 1
    customer_name: str = ""
    customer_phone: str = ""
    address: dict = field(default_factory=dict)
    draft_order_id: str = ""
    order_name: str = ""

    def to_dict(self) -> dict:
        return {
            "step": self.step.value,
            "product_name": self.product_name,
            "variant_id": self.variant_id,
            "variant_title": self.variant_title,
            "price": self.price,
            "quantity": self.quantity,
            "customer_name": self.customer_name,
            "customer_phone": self.customer_phone,
            "address": self.address,
            "draft_order_id": self.draft_order_id,
            "order_name": self.order_name,
        }

    @classmethod
    def from_dict(cls, data: dict) -> "CheckoutSession":
        if not data:
            return cls()
        return cls(
            step=CheckoutStep(data.get("step", "idle")),
            product_name=data.get("product_name", ""),
            variant_id=data.get("variant_id", ""),
            variant_title=data.get("variant_title", ""),
            price=data.get("price", 0.0),
            quantity=data.get("quantity", 1),
            customer_name=data.get("customer_name", ""),
            customer_phone=data.get("customer_phone", ""),
            address=data.get("address", {}),
            draft_order_id=data.get("draft_order_id", ""),
            order_name=data.get("order_name", ""),
        )


# ═══════════════════════════════════════════════════════════════
# PRODUCT MATCHING
# ═══════════════════════════════════════════════════════════════

def find_product_in_catalog(message: str, conversation_history: list, catalog: list) -> Optional[dict]:
    """
    Try to identify which product the customer wants to buy from the catalog.
    Looks at the current message + recent conversation for product references.

    Returns the product dict or None.
    """
    if not catalog:
        return None

    msg_lower = message.lower()

    # Build text to search: current message + last 4 assistant messages (which mention products)
    search_text = msg_lower
    for msg in conversation_history[-8:]:
        if msg.get("role") == "assistant":
            search_text += " " + msg.get("content", "").lower()

    best_match = None
    best_score = 0

    for product in catalog:
        name_lower = product.get("name", "").lower()
        if not name_lower:
            continue

        # Score 1: exact product name in message
        if name_lower in msg_lower:
            return product

        # Score 2: product name words overlap with message
        name_words = set(name_lower.split())
        msg_words = set(msg_lower.split())
        overlap = name_words & msg_words
        # Require at least 2 matching words or 50% of product name words
        if len(overlap) >= 2 or (name_words and len(overlap) / len(name_words) >= 0.5):
            score = len(overlap)
            if score > best_score:
                best_score = score
                best_match = product

        # Score 3: product mentioned in recent AI responses
        if name_lower in search_text and not best_match:
            best_match = product

    return best_match


def pick_variant(product: dict, message: str = "") -> Optional[dict]:
    """
    Pick the right variant from a product.
    If only one available variant, return it.
    If message mentions a size/color, match it.
    """
    variants = product.get("variants_detail", [])
    available = [v for v in variants if v.get("available")]

    if not available:
        return None
    if len(available) == 1:
        return available[0]

    # Try to match variant title from message
    msg_lower = message.lower()
    for v in available:
        title_lower = v.get("title", "").lower()
        if title_lower != "default title" and title_lower in msg_lower:
            return v

    # Return the first available (AI will ask for clarification if needed)
    return None


def format_variant_options(product: dict) -> str:
    """Format available variants for display to customer."""
    variants = product.get("variants_detail", [])
    available = [v for v in variants if v.get("available")]
    if not available:
        return "No hay variantes disponibles."

    if len(available) == 1 and available[0].get("title") in ("Default Title", "Default"):
        return ""  # Single variant product, no need to show options

    lines = []
    for v in available:
        title = v.get("title", "Default")
        price = v.get("price", 0)
        qty = v.get("inventory_quantity", 0)
        stock_tag = ""
        if 0 < qty <= 3:
            stock_tag = " 🔥 Últimas!"
        elif 0 < qty <= 10:
            stock_tag = " ⚡ Pocas"
        lines.append(f"  • {title} — RD${price:,.0f}{stock_tag}")
    return "\n".join(lines)


# ═══════════════════════════════════════════════════════════════
# ADDRESS EXTRACTION
# ═══════════════════════════════════════════════════════════════

# Common Dominican cities/provinces for validation
DR_CITIES = {
    "santo domingo", "santiago", "la vega", "san cristóbal", "san cristobal",
    "la romana", "san pedro de macorís", "san pedro de macoris", "higüey", "higuey",
    "puerto plata", "san francisco de macorís", "san francisco de macoris",
    "la altagracia", "monte plata", "bonao", "moca", "baní", "bani",
    "azua", "barahona", "nagua", "cotuí", "cotui", "punta cana",
    "bávaro", "bavaro", "sosúa", "sosua", "cabarete",
}

# Sectors/neighborhoods in Santo Domingo
SD_SECTORS = {
    "piantini", "naco", "evaristo morales", "gazcue", "zona colonial",
    "los prados", "bella vista", "ensanche julieta", "arroyo hondo",
    "los cacicazgos", "seralles", "serralles", "paraíso", "paraiso",
    "alma rosa", "los ríos", "los rios", "herrera", "mirador sur",
    "mirador norte", "quisqueya", "jardines del norte", "villa mella",
    "los alcarrizos", "villa consuelo", "cristo rey", "capotillo",
    "los mina", "sabana perdida", "villa faro",
}


def extract_address_from_message(message: str) -> dict:
    """
    Extract shipping address components from a customer message.
    Returns dict with address1, city, province (may be partial).
    """
    msg_lower = message.lower().strip()
    address = {}

    # Check for Google Maps URL in message
    maps_match = re.search(r"https?://(?:maps\.google\.com|goo\.gl/maps|www\.google\.com/maps)[^\s]+", message)
    if maps_match:
        address["location_url"] = maps_match.group(0)

    # Extract full address as address1 (the raw text)
    # Remove common prefixes customers add
    cleaned = re.sub(r"^(mi dirección es|dirección:|envíamelo a|enviamelo a|vivo en|es|📍\s*ubicación.*?:\s*)\s*", "", msg_lower)
    address["address1"] = cleaned.strip().title()

    # Try to detect city
    for city in DR_CITIES:
        if city in msg_lower:
            address["city"] = city.title()
            break

    # Try to detect sector (for Santo Domingo)
    for sector in SD_SECTORS:
        if sector in msg_lower:
            if "city" not in address:
                address["city"] = "Santo Domingo"
            # Prepend sector to address if not already there
            if sector not in address["address1"].lower():
                address["address1"] = f"{sector.title()}, {address['address1']}"
            break

    # Province = city for most DR cases
    if "city" in address:
        address["province"] = address["city"]

    address["country"] = "DO"
    return address


def is_address_sufficient(address: dict) -> bool:
    """Check if we have enough address info to create an order."""
    return bool(address.get("location_url") or (address.get("address1") and len(address.get("address1", "")) > 5))


# ═══════════════════════════════════════════════════════════════
# CONFIRMATION DETECTION
# ═══════════════════════════════════════════════════════════════

CONFIRM_PATTERNS = [
    r"^(sí|si|yes|confirmo|dale|listo|va|claro|seguro|afirmativo|ok|okey|perfecto|vamos)\b",
    r"^(confirmar?|acepto|hecho|procede|adelante)\b",
    r"\b(lo quiero|me lo llevo|sí.*confirmo|procede con|dale.*pedido)\b",
]

CANCEL_PATTERNS = [
    r"^(no|cancel|nah|déjalo|dejalo|olvídalo|olvidalo)\b",
    r"\b(no quiero|cambi[eé] de opinión|mejor no|otro día|otro dia|fue un error|error|cancelar|cancela)\b",
]


def detect_confirmation(message: str) -> Optional[bool]:
    """
    Detect if message is a confirmation (True), cancellation (False), or neither (None).
    """
    msg_lower = message.lower().strip()

    for pattern in CONFIRM_PATTERNS:
        if re.search(pattern, msg_lower):
            return True

    for pattern in CANCEL_PATTERNS:
        if re.search(pattern, msg_lower):
            return False

    return None


# ═══════════════════════════════════════════════════════════════
# CHECKOUT FLOW MESSAGES
# ═══════════════════════════════════════════════════════════════

def build_product_confirm_message(product_name: str, variant_title: str, price: float, quantity: int = 1) -> str:
    """Build the 'confirm product' message."""
    total = price * quantity
    variant_info = f" ({variant_title})" if variant_title and variant_title not in ("Default Title", "Default") else ""
    qty_info = f" × {quantity}" if quantity > 1 else ""

    return (
        f"¡Excelente elección! 🎉\n\n"
        f"📦 {product_name}{variant_info}{qty_info}\n"
        f"💰 RD${total:,.0f} — Pagas al recibirlo\n\n"
        f"¿A qué dirección te lo envío? 📍\n"
        f"(Calle, número, sector, ciudad — y para asegurar la entrega de tu orden, envíame tu ubicación actual con el clip 📎 de WhatsApp para que el chofer llegue directo a tu puerta 🛵)"
    )


def build_variant_selection_message(product_name: str, variants_text: str) -> str:
    """Ask customer to pick a variant."""
    return (
        f"¡Buena elección! El {product_name} viene en varias opciones:\n\n"
        f"{variants_text}\n\n"
        f"¿Cuál prefieres?"
    )


def build_order_summary_message(session: CheckoutSession) -> str:
    """Build the order confirmation summary."""
    variant_info = f" ({session.variant_title})" if session.variant_title and session.variant_title not in ("Default Title", "Default") else ""
    qty_info = f" × {session.quantity}" if session.quantity > 1 else ""
    total = session.price * session.quantity

    address_str = session.address.get("address1", "")
    city = session.address.get("city", "")
    if city and city.lower() not in address_str.lower():
        address_str += f", {city}"
    
    loc_pin = ""
    if session.address.get("location_url"):
        loc_pin = f"\n🗺️ Pin GPS: {session.address['location_url']}"

    return (
        f"📋 *Tu pedido:*\n\n"
        f"📦 {session.product_name}{variant_info}{qty_info}\n"
        f"💰 RD${total:,.0f} — Pago contra entrega\n"
        f"📍 {address_str}{loc_pin}\n\n"
        f"¿Confirmas el pedido? ✅"
    )


def build_order_complete_message(order_name: str, total_price: str, delivery_days: str = "4-7") -> str:
    """Build the order confirmation message after successful creation."""
    return (
        f"¡Pedido confirmado! 🎉\n\n"
        f"🧾 Orden: {order_name}\n"
        f"💰 Total: RD${float(total_price):,.0f} — Pagas al recibirlo\n"
        f"🚚 Te llega en {delivery_days} días laborables\n\n"
        f"Te aviso cuando salga tu paquete 📦\n"
        f"¿Necesitas algo más?"
    )


def build_cancel_message() -> str:
    """Build cancellation message."""
    return (
        "No hay problema 😊 Pedido cancelado.\n"
        "Si cambias de opinión o necesitas algo más, aquí estoy 💜"
    )
