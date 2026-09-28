"""
SynkDR Engine — Feature Gate System
Enforces tenant plan features at runtime.

Usage:
    from core.feature_gate import feature_enabled, load_features

    # On startup:
    await load_features(tenant_id="uuid")

    # In any handler:
    if feature_enabled("in_chat_checkout"):
        # proceed with checkout
    else:
        # skip or return "not on your plan" message
"""

import os
import logging
from typing import Optional

logger = logging.getLogger("synkdr.features")

# ── In-memory feature cache ──
_features: dict = {}
_tenant_id: Optional[str] = None
_loaded: bool = False


async def load_features(tenant_id: str = None):
    """
    Load tenant plan features from DB into memory cache.
    Called once at startup and whenever the plan changes.

    If no tenant_id is provided or lookup fails, all features
    default to enabled (backward compatibility for single-bot mode).
    """
    global _features, _tenant_id, _loaded
    import platform_db

    tid = tenant_id or os.getenv("TENANT_ID", "")
    if tid:
        tenant = await platform_db.get_tenant(tid)
        if tenant and tenant.get("plan"):
            _features = tenant["plan"].get("features", {})
            _tenant_id = tid
            _loaded = True
            enabled = [k for k, v in _features.items() if v]
            disabled = [k for k, v in _features.items() if not v]
            logger.info(
                f"🔐 Feature gate loaded — "
                f"{len(enabled)}/{len(_features)} enabled "
                f"(plan: {tenant['plan'].get('display_name', '?')})"
            )
            if disabled:
                logger.info(f"   Disabled: {', '.join(disabled)}")
            return

    # No TENANT_ID — try auto-discover first active tenant
    try:
        tenants = await platform_db.list_tenants(status="active", limit=1)
        if tenants and tenants[0].get("id"):
            first = tenants[0]
            tid = first["id"]
            # Re-fetch with plan join
            tenant = await platform_db.get_tenant(tid)
            if tenant and tenant.get("plan"):
                _features = tenant["plan"].get("features", {})
                _tenant_id = tid
                _loaded = True
                enabled = [k for k, v in _features.items() if v]
                logger.info(
                    f"🔐 Feature gate auto-discovered tenant '{first.get('store_name', tid)}' — "
                    f"{len(enabled)}/{len(_features)} enabled "
                    f"(plan: {tenant['plan'].get('display_name', '?')})"
                )
                return
    except Exception as e:
        logger.warning(f"⚠️ Feature gate auto-discover failed: {e}")

    # No tenant or lookup failed → all features enabled
    _features = {}
    _loaded = True
    logger.info("🔓 Feature gate: no tenant plan — all features enabled (default)")


def feature_enabled(key: str) -> bool:
    """
    Check if a feature is enabled for the current tenant.
    Returns True if:
      - No plan loaded (backward compat / all-enabled mode)
      - Feature key not in plan dict (unknown feature = allowed)
      - Feature explicitly set to True
    Returns False only if feature is explicitly set to False.
    """
    if not _loaded or not _features:
        return True
    return bool(_features.get(key, True))


def get_disabled_message(key: str) -> str:
    """
    Friendly message when a feature is not available on the tenant's plan.
    Used for customer-facing responses (WhatsApp/webchat).
    """
    messages = {
        "webchat": "El chat web no está disponible en tu plan actual.",
        "whatsapp": "WhatsApp no está habilitado en tu plan actual.",
        "voice": "",  # Silent — just skip voice, no message needed
        "in_chat_checkout": (
            "¡Me encantaría ayudarte a comprar! 🛒\n"
            "Por ahora, puedes completar tu compra directamente en nuestra tienda online."
        ),
        "smart_upsell": "",  # Silent
        "customer_memory": "",  # Silent
        "visual_search": (
            "¡Vi tu imagen! 📷 Por ahora no tengo búsqueda visual activada, "
            "pero cuéntame qué buscas y te ayudo a encontrarlo 💕"
        ),
        "price_drop_alerts": (
            "Aún no tengo alertas de precio activas, "
            "pero puedo mostrarte nuestras ofertas actuales 🏷️"
        ),
        "escalation": "",  # Always provide basic escalation for safety
        "shipping_notifications": (
            "Para rastrear tu pedido, contacta directamente a nuestra tienda 📦"
        ),
        "abandoned_cart_recovery": "",  # Silent — scheduler just skips
        "reengagement": "",  # Silent — scheduler just skips
        "analytics": "Analytics no está disponible en tu plan actual.",
        "smart_catalog": "",  # Silent — just no product context
        "discount_codes": "",  # Silent
        "api_access": "API access no está disponible en tu plan actual.",
    }
    return messages.get(key, "Esta función no está disponible en tu plan actual.")


async def refresh():
    """Reload features from DB. Call after plan changes via superadmin."""
    await load_features(_tenant_id)
    logger.info("🔄 Feature gate refreshed")
