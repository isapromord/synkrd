"""
SynkDR Engine — Sofía Bot (synkdr.com)
Entry point for bot API, webhooks, and chat endpoints.
Runs on port 8002 (Laura/flow-bot=8000, micondo-bot/Elisa=8001 — zero conflicts).
"""

import os
import json
import logging
import re
from contextlib import asynccontextmanager
from datetime import datetime, timezone

from fastapi import FastAPI, HTTPException, Request, Depends, status
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles
from fastapi.responses import FileResponse
from fastapi.security import HTTPBearer, HTTPAuthorizationCredentials

from pathlib import Path
from pydantic import BaseModel
from typing import Optional

from core.config import settings
from core.brain import generate_response
from core.router import classify_intent
from core.state import Conversation, ConversationState
from core.lead_filter import evaluate_ad_gate
from core.escalation import (
    calculate_escalation_level,
    get_escalation_message,
    check_handoff_request,
)
from core.analytics import analytics
from core.notifications import NotificationSender
from core.scheduler import scheduler
from bots.sofia.persona import SYSTEM_PROMPT, GREETINGS, get_system_prompt
from knowledge.scraper import fetch_all_products, build_product_context, search_products, build_search_context
from knowledge.upsells import fetch_upsell_context
from channels.whatsapp import WhatsAppChannel
from core.checkout import (
    CheckoutSession, CheckoutStep,
    find_product_in_catalog, pick_variant, format_variant_options,
    extract_address_from_message, is_address_sufficient, detect_confirmation,
    build_product_confirm_message, build_variant_selection_message,
    build_order_summary_message, build_order_complete_message, build_cancel_message,
)
from core.upsell import build_upsell_response
from core.customer_memory import (
    build_customer_context, learn_from_checkout,
    prefill_checkout_from_profile, get_saved_size_for_product,
)
from core.voice import (
    detect_voice_moment, VoiceMoment, generate_tts,
    prepare_audio_file, cleanup_temp_files,
    transcribe_audio_from_url, VOICE_ENABLED,
)
from core.visual_search import (
    analyze_image, visual_search_products, build_visual_search_response,
)
from core.price_watch import (
    detect_price_watch_intent, find_watched_product,
    build_price_watch_confirmation, find_price_drops,
    match_alerts_to_drops, build_price_drop_text,
    build_price_drop_template_params,
)
from core.reengagement import (
    filter_reengagement_candidates,
    build_reengagement_text,
    build_reengagement_template_params,
)
from core.feature_gate import feature_enabled, load_features as load_feature_gate
from core.feature_gate import get_disabled_message as feature_msg
from core.feature_gate import refresh as refresh_feature_gate
from core.order_confirm import (
    extract_order_details, build_confirmation_message, build_owner_alert,
    confirmacion_cod_params, pedido_en_camino_params, entrega_hoy_params,
    post_entrega_params,
    reply_confirm_ack, reply_delivery_today_ack, reply_reschedule_ack,
    reply_received_ask_review, reply_not_received_ack,
    owner_not_received_alert, owner_reschedule_alert, owner_review_forward,
)
import database as db

# ═══════════════════════════════════════════════════════════════
# LOGGING
# ═══════════════════════════════════════════════════════════════

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(name)s] %(levelname)s: %(message)s",
    datefmt="%Y-%m-%d %H:%M:%S",
)
logger = logging.getLogger("synkdr.main")


# ═══════════════════════════════════════════════════════════════
# GLOBALS
# ═══════════════════════════════════════════════════════════════

_product_context = ""  # Loaded on startup
_products_raw = []  # Raw product list for search
_upsell_context = ""  # ReleaseIt offers — refreshed with catalog sync
_whatsapp: Optional[WhatsAppChannel] = None
_notifier: Optional[NotificationSender] = None
_confirmed_order_ids: set = set()  # Dedup guard for COD confirmation webhook retries

# ── COD lifecycle config ──
_TEMPLATE_LANG = "es_DO"  # matches this WABA's Meta-approved templates
_OWNER_WHATSAPP = os.getenv("OWNER_WHATSAPP", "+18294554783")
# Quick-reply button titles — MUST match the YCloud templates exactly
_BTN_CONFIRM = "Sí, confirmo"
_BTN_DELIVERY_TODAY = "Sí, estaré"
_BTN_RESCHEDULE = "Reprogramar"
_BTN_RECEIVED = "Sí, lo recibí"
_BTN_NOT_RECEIVED = "No me ha llegado"
_COD_BUTTON_TITLES = {
    _BTN_CONFIRM, _BTN_DELIVERY_TODAY, _BTN_RESCHEDULE,
    _BTN_RECEIVED, _BTN_NOT_RECEIVED,
}


# ═══════════════════════════════════════════════════════════════
# APP LIFECYCLE
# ═══════════════════════════════════════════════════════════════

@asynccontextmanager
async def lifespan(app: FastAPI):
    """Application startup and shutdown."""
    global _product_context, _products_raw, _upsell_context, _whatsapp, _notifier

    logger.info("=" * 60)
    logger.info(f"🟢 {settings.bot_name} Bot starting...")
    logger.info(f"   Store: {settings.store_name}")
    logger.info(f"   Port: {settings.port}")
    logger.info(f"   AI: Gemini ({settings.ai.gemini_model}) + Claude ({settings.ai.claude_model})")
    logger.info(f"   Temperature: {settings.ai.temperature}")
    logger.info("=" * 60)

    # Load product catalog on startup
    try:
        products = fetch_all_products(
            settings.shopify.store_url,
            access_token=settings.shopify.access_token,
            api_version=settings.shopify.api_version,
        )
        _products_raw = products
        _product_context = build_product_context(products)
        logger.info(f"📦 Loaded {len(products)} products into context")
    except Exception as e:
        logger.error(f"⚠️ Failed to load products: {e}")
        _product_context = "No hay productos disponibles actualmente."

    # Load ReleaseIt upsell offers
    try:
        _upsell_context = fetch_upsell_context(
            settings.shopify.store_url,
            settings.shopify.access_token,
        )
        if _upsell_context:
            logger.info("🎁 ReleaseIt upsell offers loaded")
    except Exception as e:
        logger.warning(f"⚠️ ReleaseIt upsell load failed (non-fatal): {e}")

    # Initialize WhatsApp channel
    if settings.channels.ycloud_api_key:
        _whatsapp = WhatsAppChannel(
            api_key=settings.channels.ycloud_api_key,
            from_number=settings.channels.whatsapp_from_number,
            webhook_secret=settings.channels.ycloud_webhook_secret,
        )
        logger.info(f"📱 WhatsApp channel initialized: {settings.channels.whatsapp_from_number}")
    else:
        logger.warning("⚠️ No YCloud API key — WhatsApp disabled")

    # Initialize notification sender
    _notifier = NotificationSender(
        telegram_token=settings.escalation_telegram_token,
        telegram_chat_id=settings.escalation_telegram_chat_id,
        owner_name=settings.owner_name,
    )

    # Load feature gates from tenant plan
    await load_feature_gate()

    # Start background scheduler
    async def _sync_products():
        global _product_context, _products_raw, _upsell_context
        
        # Snapshot old prices BEFORE sync (for price drop detection)
        old_prices_map = await db.get_product_prices_from_db()
        old_products_snapshot = [
            {"shopify_id": sid, "price_min": price}
            for sid, price in old_prices_map.items()
        ]
        
        products = fetch_all_products(
            settings.shopify.store_url,
            access_token=settings.shopify.access_token,
            api_version=settings.shopify.api_version,
        )
        for p in products:
            await db.upsert_product(p)
        _products_raw = products
        _product_context = build_product_context(products)
        logger.info(f"📦 Scheduled sync: {len(products)} products refreshed")

        # Refresh ReleaseIt upsell offers (picks up any changes made in ReleaseIt)
        try:
            _upsell_context = fetch_upsell_context(
                settings.shopify.store_url,
                settings.shopify.access_token,
            )
            logger.info("🎁 ReleaseIt upsell context refreshed")
        except Exception as e:
            logger.warning(f"⚠️ ReleaseIt upsell refresh failed (non-fatal): {e}")

        # Check for low stock and alert seller
        from knowledge.scraper import detect_low_stock
        low_stock = detect_low_stock(products, threshold=10)
        if low_stock and _notifier:
            await _notifier.notify_low_stock(low_stock)
            logger.info(f"📦 Low stock alert: {len(low_stock)} products below threshold")

        # ── Price Drop Alerts ──
        if old_products_snapshot and _whatsapp:
            drops = find_price_drops(old_products_snapshot, products)
            if drops and feature_enabled("price_drop_alerts"):
                watches = await db.get_active_price_watches()
                notifications = match_alerts_to_drops(watches, drops)
                for notif in notifications:
                    watch = notif["watch"]
                    drop = notif["drop"]
                    phone = watch["phone"]
                    # Get customer name from profile
                    profile = await db.get_customer_profile(phone)
                    name = (profile or {}).get("name", "")
                    # Send text notification (works within 24h window)
                    msg = build_price_drop_text(
                        customer_name=name,
                        product_name=drop["product"]["name"],
                        old_price=drop["old_price"],
                        new_price=drop["new_price"],
                        product_url=drop["product"].get("url", ""),
                    )
                    sent = await _whatsapp.send_text(phone, msg)
                    if not sent:
                        # Outside 24h window — try template (needs Meta approval)
                        params = build_price_drop_template_params(
                            name, drop["product"]["name"],
                            f"{drop['old_price']:,.0f}",
                            f"{drop['new_price']:,.0f}",
                        )
                        sent = await _whatsapp.send_template(
                            phone, "price_drop_alert", params=params
                        )
                    if sent:
                        await db.mark_price_watch_notified(watch.get("id", ""))
                        logger.info(f"🔔 Price drop alert sent: {phone} → {drop['product']['name']}")
                logger.info(f"🔔 Price drops: {len(drops)} found, {len(notifications)} alerts matched")

    async def _flush_analytics():
        rows = analytics.to_db_rows()
        for row in rows:
            await db.save_analytics_snapshot(row)
        logger.info(f"📊 Analytics flushed: {len(rows)} daily records")

    async def _daily_summary():
        if _notifier and _notifier.is_enabled:
            stats = analytics.get_summary(days=1)
            await _notifier.send_daily_summary(stats)

    async def _cleanup_stale():
        count = await db.close_stale_conversations(hours=24)
        # Mark resolved for analytics
        for _ in range(count):
            analytics.track_conversation_resolved()

    async def _process_reengagement():
        """
        Re-engage customers who ghosted after showing product interest.
        Sends a WhatsApp template (required for >24h window).
        """
        if not _whatsapp or not feature_enabled("reengagement"):
            return

        # 1. Find closed conversations from 24-72h ago
        conversations = await db.find_ghosted_conversations(min_hours=24, max_hours=72)
        if not conversations:
            return

        # 2. Get exclusion sets
        recent_order_phones = await db.get_recent_order_phones(days=7)
        recently_reengaged = await db.get_recently_reengaged_phones(days=7)

        # 3. Filter to valid candidates
        candidates = filter_reengagement_candidates(
            conversations, recent_order_phones, recently_reengaged
        )
        if not candidates:
            return

        logger.info(f"🔄 Processing {len(candidates)} re-engagement candidates")

        sent_count = 0
        for candidate in candidates:
            phone = candidate["phone"]
            product = candidate["product_name"]

            # Get customer name from profile
            profile = await db.get_customer_profile(phone)
            name = (profile or {}).get("name", "")

            # Try text first (within 24h window — unlikely but safe fallback)
            msg = build_reengagement_text(name, product, settings.store_name)
            sent = await _whatsapp.send_text(phone, msg)

            if not sent:
                # Outside 24h window — use template (needs Meta approval)
                params = build_reengagement_template_params(name, product)
                sent = await _whatsapp.send_template(
                    phone, "reengagement_reminder", params=params
                )

            if sent:
                await db.save_reengagement_log(
                    phone=phone,
                    reengagement_type="ghosted",
                    product_name=product,
                    conversation_id=candidate.get("conversation_id", ""),
                )
                sent_count += 1
                logger.info(f"🔄 Re-engagement sent: {phone} → {product}")

        logger.info(f"🔄 Re-engagement complete: {sent_count}/{len(candidates)} sent")

    async def _process_cod_lifecycle():
        """
        Advance COD orders through their delivery-day templates:
          stage 0 → 1: pedido_en_camino  (~Día 1,  age >= 24h)
          stage 1 → 2: entrega_hoy       (~Día 4,  age >= 96h)
          stage 2 → 3: post_entrega      (~Día 5,  age >= 120h), then done
        One stage advances per order per sweep. Runs hourly.
        """
        if not _whatsapp or not feature_enabled("order_confirmation"):
            return

        orders = await db.get_active_cod_orders()
        if not orders:
            return

        now = datetime.now(timezone.utc)
        for o in orders:
            order_id = o.get("order_id", "")
            phone = o.get("phone", "")
            if not order_id or not phone:
                continue
            try:
                created = datetime.fromisoformat(
                    str(o.get("created_at", "")).replace("Z", "+00:00")
                )
            except (ValueError, TypeError):
                continue
            age_h = (now - created).total_seconds() / 3600.0
            stage = o.get("stage", 0)

            if stage < 1 and age_h >= 24:
                if await _whatsapp.send_template(
                    phone, "pedido_en_camino", language=_TEMPLATE_LANG,
                    params=pedido_en_camino_params(o),
                ):
                    await db.advance_cod_stage(order_id, 1)
                    logger.info(f"📦 COD → pedido_en_camino | {order_id}")
            elif stage < 2 and age_h >= 96:
                if await _whatsapp.send_template(
                    phone, "entrega_hoy", language=_TEMPLATE_LANG,
                    params=entrega_hoy_params(o),
                ):
                    await db.advance_cod_stage(order_id, 2)
                    logger.info(f"📦 COD → entrega_hoy | {order_id}")
            elif stage < 3 and age_h >= 120:
                if await _whatsapp.send_template(
                    phone, "post_entrega", language=_TEMPLATE_LANG,
                    params=post_entrega_params(o),
                ):
                    await db.advance_cod_stage(order_id, 3)
                    logger.info(f"📦 COD → post_entrega | {order_id}")

    await scheduler.start(
        sync_products_fn=_sync_products,
        flush_analytics_fn=_flush_analytics,
        send_daily_summary_fn=_daily_summary,
        cleanup_stale_fn=_cleanup_stale,
        abandoned_cart_fn=_process_abandoned_carts,
        reengagement_fn=_process_reengagement,
        cod_lifecycle_fn=_process_cod_lifecycle,
    )

    yield

    await scheduler.stop()
    logger.info(f"🔴 {settings.bot_name} Bot shutting down...")


app = FastAPI(
    title=f"{settings.bot_name} Bot — {settings.store_name} | SynkDR Engine",
    description=f"SynkDR Engine — AI Customer Service Bot for {settings.store_name}",
    version="1.0.0",
    lifespan=lifespan,
)

# Serve static files (widget.js, demo.html)
STATIC_DIR = Path(__file__).parent / "static"
if STATIC_DIR.exists():
    app.mount("/static", StaticFiles(directory=str(STATIC_DIR)), name="static")

# CORS for web chat widget
app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.channels.webchat_cors_origins.split(","),
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


# ═══════════════════════════════════════════════════════════════
# REQUEST MODELS
# ═══════════════════════════════════════════════════════════════

class ChatRequest(BaseModel):
    """Web chat message from a customer."""
    customer_id: str
    message: str
    channel: str = "webchat"


class ChatResponse(BaseModel):
    """Response from Sofía."""
    response: str
    tier_used: int
    intent: str
    state: str
    model_used: str
    latency_ms: int


class AdminMessage(BaseModel):
    """Message sent manually by admin from HQ."""
    message: str


class BotSettingUpdate(BaseModel):
    """Payload to update a bot setting."""
    value: str


# ═══════════════════════════════════════════════════════════════
# AUTHENTICATION (JWT Bearer for Sofía HQ)
# ═══════════════════════════════════════════════════════════════
security = HTTPBearer(auto_error=False)

async def get_current_admin(credentials: HTTPAuthorizationCredentials = Depends(security)):
    """Validate Supabase JWT token from Authorization header."""
    if not credentials:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Token de autenticación requerido",
            headers={"WWW-Authenticate": "Bearer"},
        )
    
    user_data = await db.verify_admin_token(credentials.credentials)
    if not user_data:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Token inválido o expirado",
            headers={"WWW-Authenticate": "Bearer"},
        )
    return user_data


# ═══════════════════════════════════════════════════════════════
# DEMO PAGE (Chat Widget)
# ═══════════════════════════════════════════════════════════════

@app.get("/demo", tags=["Widget"])
async def demo_page():
    """Serve the Sofía chat widget demo page."""
    demo_file = STATIC_DIR / "demo.html"
    if demo_file.exists():
        return FileResponse(str(demo_file), media_type="text/html")
    raise HTTPException(status_code=404, detail="Demo page not found")


@app.get("/setup", tags=["Onboarding"])
async def setup_page():
    """Serve the onboarding/setup wizard page."""
    setup_file = STATIC_DIR / "setup.html"
    if setup_file.exists():
        return FileResponse(str(setup_file), media_type="text/html")
    raise HTTPException(status_code=404, detail="Setup page not found")


# ═══════════════════════════════════════════════════════════════
# HEALTH & INFO
# ═══════════════════════════════════════════════════════════════

@app.get("/", tags=["Landing"])
async def landing_page():
    """Serve the Sofía AI marketing landing page."""
    root_index = Path("index.html")
    if root_index.exists():
        return FileResponse(str(root_index), media_type="text/html")
    landing_v2 = STATIC_DIR / "landing-v2.html"
    landing_file = STATIC_DIR / "landing.html"
    # Prefer v2 if it exists
    target = landing_v2 if landing_v2.exists() else landing_file
    if target.exists():
        return FileResponse(str(target), media_type="text/html")
    # Fallback to JSON status if landing page doesn't exist
    return {"bot": settings.bot_name, "status": "running"}


@app.get("/api/status", tags=["Health"])
async def bot_status():
    """Bot status / info endpoint (JSON)."""
    return {
        "bot": settings.bot_name,
        "store": settings.store_name,
        "version": "1.0.0",
        "framework": "SynkDR Engine v1",
        "status": "running",
        "whatsapp": bool(_whatsapp),
        "products_loaded": bool(_product_context),
        "timestamp": datetime.now(timezone.utc).isoformat(),
    }


@app.get("/health")
async def health():
    """Health check for monitoring."""
    return {"status": "ok", "bot": settings.bot_name}


# ═══════════════════════════════════════════════════════════════
# SMART PRODUCT CONTEXT (Search-Enhanced)
# ═══════════════════════════════════════════════════════════════

def _build_smart_context(message: str, history: list = None) -> str:
    """
    Build product context using real search instead of dumping all products.
    
    Strategy:
    - Search current message + recent conversation for product keywords
    - If matches found: return detailed info for those products + brief catalog summary
    - If no matches: return the full lightweight catalog for general browsing
    """
    # Build search query from current message + last 3 user messages
    search_parts = [message]
    if history:
        for msg in history[-6:]:
            if msg.get("role") == "user":
                search_parts.append(msg["content"])
    search_query = " ".join(search_parts)

    # Search for relevant products
    matches = search_products(search_query, _products_raw, max_results=5)

    if matches:
        # Build rich context for matched products + brief category overview
        rich_context = build_search_context(matches)
        
        # Add a brief catalog summary so Sofía knows what else exists
        categories = {}
        for p in _products_raw:
            cat = p.get("category") or "Otros"
            categories[cat] = categories.get(cat, 0) + 1
        cat_summary = ", ".join(f"{cat} ({n})" for cat, n in categories.items())
        
        return (
            f"🔍 PRODUCTOS RELEVANTES A LA CONVERSACIÓN:\n{rich_context}\n"
            f"📊 CATÁLOGO COMPLETO: {len(_products_raw)} productos en categorías: {cat_summary}\n"
            f"Si el cliente pregunta por otros productos, puedes mencionarle estas categorías."
        )
    
    # No specific match — return full lightweight catalog
    return _product_context


# ═══════════════════════════════════════════════════════════════
# ORDER TRACKING HELPER (Used by /chat and /webhook/whatsapp)
# ═══════════════════════════════════════════════════════════════

def _extract_order_number(message: str, history: list = None) -> Optional[str]:
    """Extract an order number (e.g., #1001) from message or recent history."""
    texts = [message]
    if history:
        for msg in history[-4:]:
            if msg.get("role") == "user":
                texts.append(msg["content"])

    for text in texts:
        # Try #NNN format first (explicit order reference)
        match = re.search(r'#(\d{3,6})\b', text)
        if match:
            return f"#{match.group(1)}"
        # Then try standalone 3-6 digit number (not part of a longer number)
        match = re.search(r'(?<!\d)(\d{3,6})(?!\d)', text)
        if match:
            return f"#{match.group(1)}"
    return None


async def _fetch_order_context(order_name: str) -> Optional[str]:
    """
    Fetch order details from Shopify and build context for the AI.
    Returns a formatted string or None if order not found.
    """
    if not settings.shopify.access_token:
        return None

    from knowledge.shopify import ShopifyKnowledge
    shopify = ShopifyKnowledge(
        store_url=settings.shopify.store_url,
        access_token=settings.shopify.access_token,
    )

    try:
        order = await shopify.fetch_order_status(order_name)
        if not order:
            return f"📦 ORDEN {order_name}: No se encontró en el sistema."

        # Build human-readable order context for the AI
        lines = [f"📦 INFORMACIÓN DE ORDEN {order['order_name']}:"]
        lines.append(f"   Estado pago: {order['status']}")

        # Fulfillment status translation
        fs_map = {
            "unfulfilled": "Pendiente de envío",
            "fulfilled": "Enviado / Entregado",
            "partially_fulfilled": "Parcialmente enviado",
            "cancelled": "Cancelado",
        }
        lines.append(f"   Estado envío: {fs_map.get(order['fulfillment_status'], order['fulfillment_status'])}")
        lines.append(f"   Total: {order['currency']} {order['total_price']}")
        lines.append(f"   Fecha: {order['created_at'][:10]}")

        # Line items
        if order.get("line_items"):
            items_str = ", ".join(
                f"{li['name']} x{li['quantity']}" for li in order["line_items"]
            )
            lines.append(f"   Productos: {items_str}")

        # Fulfillment / tracking
        for f in order.get("fulfillments", []):
            if f.get("tracking_number"):
                lines.append(f"   🚚 Tracking: {f['tracking_number']} ({f.get('tracking_company', 'N/A')})")
                if f.get("tracking_url"):
                    lines.append(f"   Link de rastreo: {f['tracking_url']}")
                lines.append(f"   Estado del envío: {f.get('status', 'N/A')}")

        return "\n".join(lines)

    except Exception as e:
        logger.error(f"Order context fetch failed: {e}")
        return None


# ═══════════════════════════════════════════════════════════════
# IN-CHAT CHECKOUT HANDLER
# ═══════════════════════════════════════════════════════════════

async def _handle_checkout_flow(
    message: str,
    conversation: Conversation,
    intent: str,
    customer_phone: str = "",
    customer_profile: dict = None,
) -> Optional[str]:
    """
    Handle the multi-step in-chat checkout flow.
    Returns a response string if checkout is active, or None to fall through to normal AI.

    Flow:
    1. Purchase intent detected + product identified → start checkout, ask for address
    2. Address received → show summary, ask for confirmation
    3. Confirmation → create draft order in Shopify → send success message
    """
    # Load checkout session from conversation metadata
    checkout_data = conversation.metadata.get("checkout", {})
    session = CheckoutSession.from_dict(checkout_data)

    # ─── Step A: Handle active checkout (already in progress) ───
    if session.step == CheckoutStep.PRODUCT_CONFIRM:
        # Customer should be picking a variant
        product = find_product_in_catalog(message, conversation.history, _products_raw)
        variant = pick_variant(product, message) if product else None

        # Try to match variant from the message directly (customer saying "la M", "talla L", etc.)
        if not variant and session.product_name:
            for p in _products_raw:
                if p.get("name", "").lower() == session.product_name.lower():
                    variant = pick_variant(p, message)
                    if variant:
                        product = p
                    break

        if variant:
            session.variant_id = variant["id"]
            session.variant_title = variant.get("title", "")
            session.price = variant.get("price", 0)
            session.customer_phone = customer_phone or conversation.customer_id

            # Check if customer memory can skip address step
            if prefill_checkout_from_profile(customer_profile, session):
                session.step = CheckoutStep.ORDER_CONFIRM
                conversation.metadata["checkout"] = session.to_dict()
                return build_order_summary_message(session)

            session.step = CheckoutStep.ADDRESS_COLLECT
            conversation.metadata["checkout"] = session.to_dict()
            return build_product_confirm_message(
                session.product_name, session.variant_title, session.price,
            )

        # Still can't determine variant — let AI ask again
        return None

    if session.step == CheckoutStep.ADDRESS_COLLECT:
        # Check if customer wants to cancel
        confirmation = detect_confirmation(message)
        if confirmation is False:
            session.step = CheckoutStep.IDLE
            conversation.metadata["checkout"] = session.to_dict()
            return build_cancel_message()

        # Extract address from message
        address = extract_address_from_message(message)
        if is_address_sufficient(address):
            session.address = address
            session.customer_phone = customer_phone or conversation.customer_id

            # Capture customer name from conversation history
            for msg in conversation.history:
                if msg.get("role") == "user" and not session.customer_name:
                    # AI usually captures name early in conversation
                    pass
            # Use phone as fallback identifier
            if not session.customer_name:
                session.customer_name = customer_phone or conversation.customer_id

            session.step = CheckoutStep.ORDER_CONFIRM
            conversation.metadata["checkout"] = session.to_dict()
            return build_order_summary_message(session)

        # Address not sufficient — let AI ask for more detail
        return None

    if session.step == CheckoutStep.ORDER_CONFIRM:
        confirmation = detect_confirmation(message)

        if confirmation is True:
            # ── CREATE THE ORDER ──
            order_result = await _create_shopify_order(session)
            if order_result:
                session.order_name = order_result.get("order_name", "")
                session.draft_order_id = order_result.get("draft_order_id", "")
                session.step = CheckoutStep.COMPLETED
                conversation.metadata["checkout"] = session.to_dict()

                # Save to DB for tracking
                await db.save_chat_order({
                    "customer_phone": session.customer_phone,
                    "customer_name": session.customer_name,
                    "product_name": session.product_name,
                    "variant_id": session.variant_id,
                    "variant_title": session.variant_title,
                    "price": session.price,
                    "quantity": session.quantity,
                    "address": session.address,
                    "draft_order_id": session.draft_order_id,
                    "order_name": session.order_name,
                    "status": "confirmed",
                    "channel": conversation.channel,
                })

                # Auto-learn customer memory from completed checkout
                try:
                    existing_profile = await db.get_customer_profile(session.customer_phone)
                    profile_updates = learn_from_checkout(existing_profile, session)
                    await db.upsert_customer_profile(session.customer_phone, profile_updates)
                    logger.info(f"🧠 Customer memory updated for {session.customer_phone}")
                except Exception as e:
                    logger.warning(f"⚠️ Customer memory update failed (non-fatal): {e}")

                # Notify owner
                if _notifier:
                    total = session.price * session.quantity
                    await _notifier.send(
                        f"🛒 *Nuevo pedido por chat!*\n"
                        f"📦 {session.product_name} ({session.variant_title})\n"
                        f"💰 RD${total:,.0f} — COD\n"
                        f"📱 {session.customer_phone}\n"
                        f"📍 {session.address.get('address1', '')}" +
                        (f"\n🗺️ GPS: {session.address['location_url']}" if session.address.get('location_url') else "")
                    )

                # Build confirmation + smart upsell (feature-gated)
                confirmation_msg = build_order_complete_message(
                    session.order_name,
                    str(session.price * session.quantity),
                )
                upsell_text = ""
                if feature_enabled("smart_upsell"):
                    # Find purchased product's shopify_id for upsell
                    purchased_id = ""
                    for p in _products_raw:
                        if p.get("name") == session.product_name:
                            purchased_id = p.get("shopify_id", "")
                            break
                    customer_history = (existing_profile or {}).get("product_history", [])
                    upsell_text = build_upsell_response(
                        purchased_product_name=session.product_name,
                        purchased_shopify_id=purchased_id,
                        catalog=_products_raw,
                        customer_history=customer_history,
                        unit_price=session.price,
                    )
                return confirmation_msg + upsell_text
            else:
                # Shopify API failed — graceful fallback
                session.step = CheckoutStep.IDLE
                conversation.metadata["checkout"] = session.to_dict()
                logger.error("Checkout: Shopify draft order creation failed")
                return (
                    "Hubo un inconveniente al procesar tu pedido 😔\n"
                    "Déjame conectarte con Howard para completarlo manualmente.\n"
                    "¡Tu producto está separado! 📦"
                )

        elif confirmation is False:
            session.step = CheckoutStep.IDLE
            conversation.metadata["checkout"] = session.to_dict()
            return build_cancel_message()

        # Ambiguous response — let AI handle
        return None

    # ─── Step B: Start new checkout (purchase intent detected) ───
    if intent == "purchase" and session.step == CheckoutStep.IDLE:
        product = find_product_in_catalog(message, conversation.history, _products_raw)
        if not product or not product.get("available"):
            return None  # No product matched — let AI respond naturally

        variant = pick_variant(product, message)

        session.product_name = product["name"]

        if variant:
            # Single variant or variant matched — go straight to address
            session.variant_id = variant["id"]
            session.variant_title = variant.get("title", "")
            session.price = variant.get("price", 0)
            session.customer_phone = customer_phone or conversation.customer_id

            # Check if customer memory can skip address step
            if prefill_checkout_from_profile(customer_profile, session):
                session.step = CheckoutStep.ORDER_CONFIRM
                conversation.metadata["checkout"] = session.to_dict()
                return build_order_summary_message(session)

            session.step = CheckoutStep.ADDRESS_COLLECT
            conversation.metadata["checkout"] = session.to_dict()
            return build_product_confirm_message(
                session.product_name, session.variant_title, session.price,
            )
        else:
            # Multiple variants — ask which one
            variants_text = format_variant_options(product)
            if variants_text:
                session.step = CheckoutStep.PRODUCT_CONFIRM
                conversation.metadata["checkout"] = session.to_dict()
                return build_variant_selection_message(product["name"], variants_text)
            else:
                return None  # No available variants

    return None  # Not in checkout flow


async def _create_shopify_order(session: CheckoutSession) -> Optional[dict]:
    """Create a draft order in Shopify from a checkout session."""
    if not settings.shopify.access_token:
        logger.warning("Checkout: No Shopify access token — cannot create order")
        return None

    from knowledge.shopify import ShopifyKnowledge
    shopify = ShopifyKnowledge(
        store_url=settings.shopify.store_url,
        access_token=settings.shopify.access_token,
    )

    draft = await shopify.create_draft_order(
        line_items=[{"variant_id": session.variant_id, "quantity": session.quantity}],
        shipping_address=session.address,
        customer_phone=session.customer_phone,
        customer_name=session.customer_name,
        note=f"Pedido via chat — SynkDR ({session.customer_phone})",
    )

    if not draft:
        return None

    # Complete the draft order (converts to real order with payment pending = COD)
    completed = await shopify.complete_draft_order(draft["draft_order_id"])
    if completed and completed.get("order_id"):
        await db.update_chat_order_status(
            draft["draft_order_id"], "completed", completed["order_id"]
        )
        return {
            "draft_order_id": draft["draft_order_id"],
            "order_name": completed.get("order_name", draft.get("order_name", "")),
            "total_price": draft.get("total_price", "0"),
        }

    # Draft created but not completed — still return it
    return draft


# ═══════════════════════════════════════════════════════════════
# CORE CHAT ENDPOINT (Web Chat + API)
# ═══════════════════════════════════════════════════════════════

@app.post("/chat", response_model=ChatResponse)
async def chat_endpoint(request: ChatRequest):
    """
    Main chat endpoint — handles incoming messages from web chat or API.

    Flow:
    1. Load or create conversation
    2. Classify intent → determine AI tier
    3. Check escalation signals
    4. Generate response via appropriate AI tier
    5. Save conversation state
    6. Return response
    """
    logger.info(
        f"💬 Incoming | customer={request.customer_id} | "
        f"channel={request.channel} | msg=\"{request.message[:50]}...\""
    )

    # ── Feature gate: webchat channel ──
    if not feature_enabled("webchat"):
        raise HTTPException(status_code=403, detail=feature_msg("webchat"))

    # Step 1: Load or create conversation
    conv_data = await db.get_conversation(request.customer_id)
    if conv_data:
        conversation = Conversation.from_dict(conv_data)
    else:
        conversation = Conversation(
            customer_id=request.customer_id,
            channel=request.channel,
        )
        # Track new conversation
        analytics.track_conversation_start(request.channel)

    # Step 1.5: Load customer memory profile (feature-gated)
    if feature_enabled("customer_memory"):
        customer_profile = await db.get_customer_profile(request.customer_id)
        customer_context = build_customer_context(customer_profile)
    else:
        customer_profile = None
        customer_context = ""

    # Add customer message to history
    conversation.add_message("user", request.message)

    # Step 2: Classify intent and determine tier
    tier, intent, reason = classify_intent(
        request.message,
        conversation_length=conversation.metadata.get("message_count", 0),
    )

    # Step 3: Check escalation (feature-gated)
    if feature_enabled("escalation"):
        esc_level, esc_reason, should_notify = calculate_escalation_level(
            request.message,
            current_level=conversation.metadata.get("escalation_level", 0),
        )
    else:
        esc_level, esc_reason, should_notify = 0, "", False

    if esc_level >= 3:
        response_text = get_escalation_message(3, settings.owner_name)
        conversation.state = ConversationState.ESCALATED
        conversation.metadata["escalation_level"] = esc_level

        await db.log_escalation(
            customer_id=request.customer_id,
            reason=esc_reason,
            level=esc_level,
            message=request.message,
        )

        # Send real-time notification to owner
        analytics.track_escalation(esc_level, esc_reason)
        if _notifier:
            await _notifier.notify_escalation(
                customer_id=request.customer_id,
                reason=esc_reason,
                level=esc_level,
                last_message=request.message,
                channel=request.channel,
            )

        logger.warning(
            f"🚨 ESCALATION Level {esc_level} | "
            f"customer={request.customer_id} | reason={esc_reason}"
        )

        conversation.add_message("assistant", response_text)
        conv_result = await db.save_conversation(conversation.to_dict())

        # Persist messages for admin Chats view
        if conv_result and conv_result.get("id"):
            conv_uuid = conv_result["id"]
            await db.save_message({
                "conversation_id": conv_uuid,
                "role": "customer",
                "content": request.message,
                "intent": "escalation",
            })
            await db.save_message({
                "conversation_id": conv_uuid,
                "role": "assistant",
                "content": response_text,
                "intent": "escalation",
                "ai_model": "escalation_engine",
                "ai_tier": 0,
            })

        return ChatResponse(
            response=response_text,
            tier_used=0,
            intent="escalation",
            state=conversation.state.value,
            model_used="escalation_engine",
            latency_ms=0,
        )

    # Update escalation level
    conversation.metadata["escalation_level"] = esc_level

    # Step 4: Transition conversation state
    conversation.transition_state(intent)

    # Step 4.5: Check in-chat checkout flow (feature-gated)
    checkout_response = None
    if feature_enabled("in_chat_checkout"):
        checkout_response = await _handle_checkout_flow(
            message=request.message,
            conversation=conversation,
            intent=intent,
            customer_phone=request.customer_id,
            customer_profile=customer_profile,
        )
    if checkout_response:
        conversation.add_message("assistant", checkout_response)
        conv_result = await db.save_conversation(conversation.to_dict())

        if conv_result and conv_result.get("id"):
            conv_uuid = conv_result["id"]
            await db.save_message({
                "conversation_id": conv_uuid,
                "role": "customer",
                "content": request.message,
                "intent": "checkout",
            })
            await db.save_message({
                "conversation_id": conv_uuid,
                "role": "assistant",
                "content": checkout_response,
                "intent": "checkout",
                "ai_model": "checkout_engine",
                "ai_tier": 0,
            })

        analytics.track_message(tier=0, latency_ms=0, intent="checkout", channel=request.channel)

        return ChatResponse(
            response=checkout_response,
            tier_used=0,
            intent="checkout",
            state=conversation.state.value,
            model_used="checkout_engine",
            latency_ms=0,
        )

    # Step 5: Generate AI response with product context
    dynamic_prompt = await db.get_bot_setting("system_prompt")
    active_prompt = dynamic_prompt if dynamic_prompt else get_system_prompt(settings.store_name, _upsell_context)

    # Load dynamic policies for AI context
    policies_parts = []
    for key in ["policy_shipping", "policy_returns", "policy_payment", "policy_hours", "policy_faq"]:
        val = await db.get_bot_setting(key)
        if val:
            label = key.replace("policy_", "").replace("_", " ").title()
            policies_parts.append(f"**{label}:** {val}")
    policies_context = "\n".join(policies_parts)

    # Inject customer memory into prompt
    memory_prompt = active_prompt
    if customer_context:
        memory_prompt = active_prompt + "\n\n" + customer_context

    ai_result = await generate_response(
        message=request.message,
        conversation_history=conversation.get_history_for_ai(),
        product_context=_build_smart_context(request.message, conversation.get_history_for_ai()) if feature_enabled("smart_catalog") else "",
        system_prompt=memory_prompt,
        tier=tier,
        policies_context=policies_context,
    )

    response_text = ai_result["response"]

    # If order_tracking intent, enrich with real order data (feature-gated)
    if intent == "order_tracking" and feature_enabled("shipping_notifications"):
        order_num = _extract_order_number(request.message, conversation.get_history_for_ai())
        if order_num:
            order_ctx = await _fetch_order_context(order_num)
            if order_ctx:
                ai_result = await generate_response(
                    message=request.message,
                    conversation_history=conversation.get_history_for_ai(),
                    product_context=order_ctx,
                    system_prompt=active_prompt + "\n\n📦 INSTRUCCIONES PARA SEGUIMIENTO DE ORDEN:\n- Comparte la información del pedido de forma clara y amigable\n- Si hay tracking, comparte el número y el link\n- Si no ha sido enviado, tranquiliza al cliente\n- Si el cliente no dio un número de orden, pídele que lo comparta",
                    tier=2,  # Always use Claude for order tracking (complex)
                    policies_context=policies_context,
                )
                response_text = ai_result["response"]
        else:
            # No order number found — ask for it
            ai_result = await generate_response(
                message=request.message,
                conversation_history=conversation.get_history_for_ai(),
                product_context="",
                system_prompt=active_prompt + "\n\n📦 El cliente quiere rastrear una orden pero NO proporcionó número de orden. Pídele amablemente que comparta su número de orden (ejemplo: #1001) para poder ayudarle.",
                tier=1,
                policies_context=policies_context,
            )
            response_text = ai_result["response"]

    # Add optional escalation empathy prefix
    if esc_level in (1, 2):
        empathy = get_escalation_message(esc_level, settings.owner_name)
        if empathy:
            response_text = empathy

    # Step 5.5: Out-of-stock demand detection
    # If Sofía's response indicates the product/variant isn't available,
    # save customer demand + notify owner so they can act on it.
    _OOS_SIGNALS = [
        "no tenemos", "no disponible", "agotado", "solo la tenemos disponible en",
        "solo tenemos en", "no está disponible", "no contamos con", "no la tenemos en",
        "no lo tenemos en", "solo disponible en", "no existe en",
    ]
    if intent in ("catalog", "purchase") and any(s in response_text.lower() for s in _OOS_SIGNALS):
        try:
            # Find the product being discussed using the smart search
            from knowledge.scraper import search_products
            matched = search_products(request.message, _products_raw, max_results=1)
            product_name = matched[0]["name"] if matched else ""
            # Extract what variant the customer wanted (raw message is best signal)
            variant_hint = request.message[:120]
            if product_name and _notifier:
                await _notifier.notify_out_of_stock_demand(
                    customer_id=request.customer_id,
                    product_name=product_name,
                    variant_title=variant_hint,
                    channel=request.channel,
                )
            if product_name:
                shopify_id = matched[0].get("shopify_id", "") if matched else ""
                await db.save_wishlist_item(
                    customer_id=request.customer_id,
                    product_name=product_name,
                    variant_title=variant_hint,
                    shopify_product_id=shopify_id,
                    channel=request.channel,
                )
                logger.info(
                    f"📋 Wishlist demand saved: {request.customer_id} → "
                    f"{product_name} ({variant_hint[:60]})"
                )
        except Exception as e:
            logger.warning(f"⚠️ OOS demand tracking failed (non-fatal): {e}")

    # Step 6: Save response to conversation
    conversation.add_message("assistant", response_text)
    conv_result = await db.save_conversation(conversation.to_dict())

    # Step 7: Persist individual messages to `messages` table for admin Chats view
    if conv_result and conv_result.get("id"):
        conv_uuid = conv_result["id"]
        await db.save_message({
            "conversation_id": conv_uuid,
            "role": "customer",
            "content": request.message,
            "intent": intent,
        })
        await db.save_message({
            "conversation_id": conv_uuid,
            "role": "assistant",
            "content": response_text,
            "intent": intent,
            "ai_model": ai_result.get("model_used"),
            "ai_tier": tier,
            "latency_ms": ai_result.get("latency_ms", 0),
        })

    # Track analytics
    analytics.track_message(
        tier=tier,
        latency_ms=ai_result.get("latency_ms", 0),
        intent=intent,
        channel=request.channel,
    )

    # CRM: track every customer turn (non-fatal)
    try:
        _purchase_intents = ("purchase", "checkout", "cart", "pricing")
        _is_purchase = intent in _purchase_intents
        from knowledge.scraper import search_products
        _interested_product = ""
        if _is_purchase:
            _matched = search_products(request.message, _products_raw, max_results=1)
            _interested_product = _matched[0]["name"] if _matched else ""
        await db.track_customer_interaction(
            customer_id=request.customer_id,
            name=conversation.customer_name or "",
            channel=request.channel,
            purchase_intent=_is_purchase,
            last_interested_product=_interested_product,
        )
    except Exception as _crm_e:
        logger.debug(f"CRM tracking skipped: {_crm_e}")

    return ChatResponse(
        response=response_text,
        tier_used=tier,
        intent=intent,
        state=conversation.state.value,
        model_used=ai_result.get("model_used", "unknown"),
        latency_ms=ai_result.get("latency_ms", 0),
    )


# ═══════════════════════════════════════════════════════════════
# WHATSAPP WEBHOOK (YCloud)
# ═══════════════════════════════════════════════════════════════

@app.post("/webhook/whatsapp", tags=["WhatsApp"])
async def whatsapp_webhook(request: Request):
    """
    Receive incoming WhatsApp messages from YCloud webhook.
    
    Flow:
    1. Parse YCloud webhook payload
    2. Extract sender phone and message
    3. Route through chat engine (same as /chat but auto-replies via WhatsApp)
    4. Send response back via YCloud API
    """
    try:
        payload = await request.json()
    except Exception:
        raise HTTPException(status_code=400, detail="Invalid JSON")

    if not _whatsapp:
        logger.error("WhatsApp channel not initialized")
        return {"status": "error", "message": "WhatsApp not configured"}

    # ── Feature gate: WhatsApp channel ──
    if not feature_enabled("whatsapp"):
        logger.info("📱 WhatsApp message ignored — feature disabled")
        return {"status": "ok", "action": "channel_disabled"}

    # Parse the webhook
    parsed = _whatsapp.parse_webhook(payload)
    if not parsed:
        # Not a customer message (status update, etc.) — acknowledge
        return {"status": "ok", "action": "ignored"}

    sender = parsed["sender_phone"]
    message_text = parsed["message_text"]
    whatsapp_name = parsed.get("whatsapp_name", "")
    customer_sent_audio = parsed.get("message_type") == "audio"

    # Transcribe incoming voice notes (feature-gated)
    if customer_sent_audio and parsed.get("audio_url") and feature_enabled("voice"):
        transcript = transcribe_audio_from_url(
            audio_url=parsed["audio_url"],
            ycloud_api_key=settings.channels.ycloud_api_key,
        )
        if transcript:
            message_text = transcript
            logger.info(f"🎙️ Voice transcribed: '{transcript[:60]}...'")

    logger.info(
        f"📱 WhatsApp | from={sender} | name={whatsapp_name} | "
        f"msg=\"{message_text[:50]}...\""
    )

    # Load or create conversation
    conv_data = await db.get_conversation(sender)
    if conv_data:
        conversation = Conversation.from_dict(conv_data)
    else:
        conversation = Conversation(
            customer_id=sender,
            channel="whatsapp",
        )

    # ── COD lifecycle interactions (button taps + review capture) ──
    # These come from real order customers, so they bypass the Meta-Ads gate.
    cod_response = await _handle_cod_interaction(sender, message_text, parsed, conversation)
    if cod_response:
        return cod_response

    # ── Meta Ads-only gate: only auto-respond to Click-to-WhatsApp ad leads ──
    should_respond, source_tag, is_new_ad_lead = evaluate_ad_gate(
        referral_source_id=parsed.get("referral_source_id", ""),
        existing_source=conversation.metadata.get("source", ""),
        meta_ads_only=settings.meta_ads_only,
    )
    if is_new_ad_lead:
        conversation.metadata["source"] = source_tag
        conversation.metadata["ad_id"] = parsed.get("referral_source_id", "")
        if parsed.get("referral_headline"):
            conversation.metadata["ad_headline"] = parsed.get("referral_headline", "")
        logger.info(
            f"🎯 CTWA lead | from={sender} | ad_id={parsed.get('referral_source_id', '')[:24]}"
        )
    if not should_respond:
        logger.info(
            f"🚫 Ignored non-campaign message | from={sender} | name={whatsapp_name}"
        )
        return {"status": "ok", "action": "ignored_not_campaign"}

    # Load customer memory profile (feature-gated)
    if feature_enabled("customer_memory"):
        customer_profile = await db.get_customer_profile(sender)
        customer_context = build_customer_context(customer_profile)
    else:
        customer_profile = None
        customer_context = ""

    # ── Image Handling: Bank Transfer Receipt Validator OR Visual Product Search ──
    if parsed.get("message_type") == "image" and parsed.get("image_url"):
        # 1. First check if it's a bank transfer receipt
        from core.receipt_validator import validate_payment_receipt
        receipt_result = await validate_payment_receipt(
            image_url=parsed["image_url"],
            ycloud_api_key=settings.channels.ycloud_api_key,
        )

        if receipt_result.get("is_receipt") and receipt_result.get("is_authentic"):
            bank = receipt_result.get("bank", "tu banco")
            amount = receipt_result.get("amount", 0)
            auth_code = receipt_result.get("auth_code", "")
            matches_target = receipt_result.get("beneficiary_matches_target", False)

            if matches_target:
                response_text = (
                    f"¡Comprobante recibido y validado con éxito! 🎉💳\n\n"
                    f"🏦 *Banco:* {bank}\n"
                    f"💰 *Monto:* RD${amount:,.0f}\n"
                    f"🔢 *No. Autorización:* {auth_code}\n\n"
                    f"Tu pago fue recibido a nombre de Howard Eduardo Luna Perez. "
                    f"Estamos procesando tu orden para despacho inmediato. ¡Muchas gracias! 🙌"
                )
                logger.info(f"✅ Verified bank receipt from {sender}: {bank} RD${amount} Auth:{auth_code}")
                if _notifier:
                    try:
                        await _notifier.send(
                            f"💰 *PAGO POR TRANSFERENCIA VERIFICADO*\n"
                            f"📱 Cliente: {sender}\n"
                            f"🏦 Banco: {bank} | RD${amount:,.0f}\n"
                            f"🔢 Auth: {auth_code}\n"
                            f"✅ Beneficiario: Howard Eduardo Luna Perez"
                        )
                    except Exception as e:
                        logger.warning(f"Could not send owner receipt alert: {e}")
            else:
                response_text = (
                    f"Recibí el comprobante de {bank} por RD${amount:,.0f} (No. {auth_code}), "
                    f"pero el titular o cuenta destino no coincide exactamente con las cuentas oficiales de la tienda. "
                    f"Nuestro equipo humano lo verificará enseguida para confirmar tu orden. 🔍"
                )

            conversation.add_message("user", "[Comprobante de transferencia]")
            conversation.add_message("assistant", response_text)
            conv_result = await db.save_conversation(conversation.to_dict())
            if conv_result and conv_result.get("id"):
                conv_uuid = conv_result["id"]
                await db.save_message({"conversation_id": conv_uuid, "role": "customer", "content": "[Comprobante de pago]", "intent": "payment_receipt"})
                await db.save_message({"conversation_id": conv_uuid, "role": "assistant", "content": response_text, "intent": "payment_receipt", "ai_model": "gemini-vision", "ai_tier": 1})
            await _whatsapp.send_text(sender, response_text)
            return {"status": "ok", "action": "receipt_validated"}

        # 2. If not a bank receipt, proceed to visual product search
        if feature_enabled("visual_search"):
            image_caption = message_text if message_text != "[Imagen recibida]" else ""
            description = await analyze_image(
                image_url=parsed["image_url"],
                caption=image_caption,
                ycloud_api_key=settings.channels.ycloud_api_key,
            )
            if description:
                matches = visual_search_products(description, _products_raw, max_results=3)
                response_text = build_visual_search_response(matches, description)
            else:
                response_text = (
                    "¡Vi tu imagen! 📷 No pude identificar el producto, "
                    "pero cuéntame qué buscas y te ayudo a encontrarlo 💕"
                )
        else:
            response_text = feature_msg("visual_search")

        conversation.add_message("user", message_text)
        conversation.add_message("assistant", response_text)
        conv_result = await db.save_conversation(conversation.to_dict())
        if conv_result and conv_result.get("id"):
            conv_uuid = conv_result["id"]
            await db.save_message({"conversation_id": conv_uuid, "role": "customer", "content": message_text, "intent": "visual_search"})
            await db.save_message({"conversation_id": conv_uuid, "role": "assistant", "content": response_text, "intent": "visual_search", "ai_model": "gemini-vision", "ai_tier": 1})
        await _whatsapp.send_text(sender, response_text)
        return {"status": "ok", "action": "visual_search_replied"}

    conversation.add_message("user", message_text)

    # Classify intent
    tier, intent, reason = classify_intent(
        message_text,
        conversation_length=conversation.metadata.get("message_count", 0),
    )

    # Check escalation (feature-gated)
    if feature_enabled("escalation"):
        esc_level, esc_reason, should_notify = calculate_escalation_level(
            message_text,
            current_level=conversation.metadata.get("escalation_level", 0),
        )
    else:
        esc_level, esc_reason, should_notify = 0, "", False

    if esc_level >= 3:
        response_text = get_escalation_message(3, settings.owner_name)
        conversation.state = ConversationState.ESCALATED
    else:
        conversation.metadata["escalation_level"] = esc_level
        conversation.transition_state(intent)

        # Check in-chat checkout flow first (feature-gated)
        checkout_response = None
        if feature_enabled("in_chat_checkout"):
            checkout_response = await _handle_checkout_flow(
                message=message_text,
                conversation=conversation,
                intent=intent,
                customer_phone=sender,
                customer_profile=customer_profile,
            )
        if checkout_response:
            response_text = checkout_response
            # Save and send
            conversation.add_message("assistant", response_text)
            await db.save_conversation(conversation.to_dict())
            await _whatsapp.send_text(sender, response_text)
            return {"status": "ok", "action": "checkout_replied"}

        # Generate AI response with product context
        dynamic_prompt = await db.get_bot_setting("system_prompt")
        active_prompt = dynamic_prompt if dynamic_prompt else get_system_prompt(settings.store_name, _upsell_context)

        # Inject customer memory into prompt
        wa_memory_prompt = active_prompt
        if customer_context:
            wa_memory_prompt = active_prompt + "\n\n" + customer_context

        ai_result = await generate_response(
            message=message_text,
            conversation_history=conversation.get_history_for_ai(),
            product_context=_build_smart_context(message_text, conversation.get_history_for_ai()) if feature_enabled("smart_catalog") else "",
            system_prompt=wa_memory_prompt,
            tier=tier,
        )
        response_text = ai_result["response"]

        # If order_tracking intent, enrich with real order data (feature-gated)
        if intent == "order_tracking" and feature_enabled("shipping_notifications"):
            order_num = _extract_order_number(message_text, conversation.get_history_for_ai())
            if order_num:
                order_ctx = await _fetch_order_context(order_num)
                if order_ctx:
                    ai_result = await generate_response(
                        message=message_text,
                        conversation_history=conversation.get_history_for_ai(),
                        product_context=order_ctx,
                        system_prompt=active_prompt + "\n\n📦 INSTRUCCIONES PARA SEGUIMIENTO DE ORDEN:\n- Comparte la información del pedido de forma clara y amigable\n- Si hay tracking, comparte el número y el link\n- Si no ha sido enviado, tranquiliza al cliente\n- Si el cliente no dio un número de orden, pídele que lo comparta",
                        tier=2,
                        policies_context="",
                    )
                    response_text = ai_result["response"]
            else:
                ai_result = await generate_response(
                    message=message_text,
                    conversation_history=conversation.get_history_for_ai(),
                    product_context="",
                    system_prompt=active_prompt + "\n\n📦 El cliente quiere rastrear una orden pero NO proporcionó número de orden. Pídele amablemente que comparta su número de orden (ejemplo: #1001) para poder ayudarle.",
                    tier=1,
                    policies_context="",
                )
                response_text = ai_result["response"]

    # Save conversation
    conversation.add_message("assistant", response_text)
    conv_result = await db.save_conversation(conversation.to_dict())

    # Persist individual messages to `messages` table for admin Chats view
    if conv_result and conv_result.get("id"):
        conv_uuid = conv_result["id"]
        await db.save_message({
            "conversation_id": conv_uuid,
            "role": "customer",
            "content": message_text,
            "intent": intent,
        })
        await db.save_message({
            "conversation_id": conv_uuid,
            "role": "assistant",
            "content": response_text,
            "intent": intent,
            "ai_model": ai_result.get("model_used") if esc_level < 3 else "escalation_engine",
            "ai_tier": tier if esc_level < 3 else 0,
            "latency_ms": ai_result.get("latency_ms", 0) if esc_level < 3 else 0,
        })

    # Send reply via WhatsApp (voice or text)
    voice_sent = False
    checkout_step = conversation.metadata.get("checkout_step", "")
    is_first = conversation.metadata.get("message_count", 0) <= 2

    # ── Price Watch: detect "está cara" / "avísame si baja" (feature-gated) ──
    if feature_enabled("price_drop_alerts") and detect_price_watch_intent(message_text):
        watched = find_watched_product(
            message_text, conversation.get_history_for_ai(), _products_raw
        )
        if watched:
            price = watched.get("price_min", 0)
            await db.save_price_watch(
                phone=sender,
                product_shopify_id=watched["shopify_id"],
                product_name=watched["name"],
                price_at_watch=price,
            )
            watch_msg = build_price_watch_confirmation(watched["name"], price)
            await _whatsapp.send_text(sender, watch_msg)
            logger.info(f"📝 Price watch saved: {sender} → {watched['name']} @ RD${price:,.0f}")

    moment = VoiceMoment.NONE
    if feature_enabled("voice"):
        moment = detect_voice_moment(
            response_text=response_text,
            intent=intent,
            is_first_message=is_first,
            customer_sent_audio=customer_sent_audio,
            checkout_step=checkout_step,
        )

    if moment != VoiceMoment.NONE:
        pcm_data = generate_tts(response_text, moment)
        if pcm_data:
            audio_result = prepare_audio_file(pcm_data)
            if audio_result:
                audio_path, mime_type, filename = audio_result
                voice_sent = await _whatsapp.send_audio(sender, audio_path, mime_type)
                cleanup_temp_files(audio_path, audio_path.replace(".ogg", ".wav"))

    # Always send text as well (fallback + readable reference)
    await _whatsapp.send_text(sender, response_text)

    # CRM: track WhatsApp customer (non-fatal)
    try:
        _wa_purchase_intents = ("purchase", "checkout", "cart", "pricing")
        _wa_is_purchase = intent in _wa_purchase_intents
        from knowledge.scraper import search_products as _wa_search
        _wa_product = ""
        if _wa_is_purchase:
            _wa_matched = _wa_search(message_text, _products_raw, max_results=1)
            _wa_product = _wa_matched[0]["name"] if _wa_matched else ""
        await db.track_customer_interaction(
            customer_id=sender,
            name=whatsapp_name or "",
            phone=sender,
            channel="whatsapp",
            purchase_intent=_wa_is_purchase,
            last_interested_product=_wa_product,
        )
    except Exception as _crm_wa_e:
        logger.debug(f"CRM WA tracking skipped: {_crm_wa_e}")

    return {"status": "ok", "action": "replied"}


# ═══════════════════════════════════════════════════════════════
# SHOPIFY WEBHOOKS (Abandoned Cart + Order Completion)
# ═══════════════════════════════════════════════════════════════

@app.post("/webhook/shopify/checkout", tags=["Shopify"])
async def shopify_checkout_webhook(request: Request):
    """
    Receive Shopify checkout/create or checkout/update webhook.
    Captures abandoned carts for WhatsApp follow-up.
    
    Configure in Shopify Admin → Settings → Notifications → Webhooks:
    - Event: Checkout creation (checkouts/create)
    - URL: https://synkdr.com/{bot}/webhook/shopify/checkout
    """
    try:
        payload = await request.json()
    except Exception:
        raise HTTPException(status_code=400, detail="Invalid JSON")

    # Extract customer phone (required for WhatsApp follow-up)
    phone = (
        payload.get("phone")
        or payload.get("shipping_address", {}).get("phone")
        or payload.get("billing_address", {}).get("phone")
        or payload.get("customer", {}).get("phone")
    )

    if not phone:
        logger.debug("Checkout webhook: no phone number, skipping")
        return {"status": "ok", "action": "skipped_no_phone"}

    # Clean phone number (ensure it has country code)
    phone = phone.replace(" ", "").replace("-", "").replace("(", "").replace(")", "")
    if not phone.startswith("+"):
        if phone.startswith("1") and len(phone) == 11:
            phone = f"+{phone}"
        elif len(phone) == 10:
            phone = f"+1{phone}"  # Default DR country code

    checkout_id = str(payload.get("id", ""))
    if not checkout_id:
        return {"status": "ok", "action": "skipped_no_id"}

    # Build line items
    line_items = []
    for li in payload.get("line_items", []):
        line_items.append({
            "name": li.get("title", ""),
            "quantity": li.get("quantity", 1),
            "price": li.get("price", "0"),
            "image_url": li.get("image_url", ""),
            "variant": li.get("variant_title", ""),
        })

    # Build checkout URL (magic link that restores the cart)
    checkout_url = payload.get("abandoned_checkout_url", "")

    customer_name = ""
    if payload.get("customer"):
        customer_name = (
            payload["customer"].get("first_name", "")
            + " "
            + payload["customer"].get("last_name", "")
        ).strip()

    cart_data = {
        "shopify_checkout_id": checkout_id,
        "customer_phone": phone,
        "customer_name": customer_name,
        "customer_email": payload.get("email", ""),
        "total_price": float(payload.get("total_price", 0)),
        "currency": payload.get("currency", "DOP"),
        "line_items": line_items,
        "checkout_url": checkout_url,
        "status": "abandoned",
        "followup_count": 0,
    }

    await db.save_abandoned_checkout(cart_data)
    logger.info(f"🛒 Abandoned checkout captured: {checkout_id} | phone={phone} | ${cart_data['total_price']}")

    return {"status": "ok", "action": "captured"}


@app.post("/webhook/shopify/order", tags=["Shopify"])
async def shopify_order_webhook(request: Request):
    """
    Receive Shopify order/create webhook.
    Marks any matching abandoned cart as 'recovered'.
    
    Configure in Shopify Admin → Settings → Notifications → Webhooks:
    - Event: Order creation (orders/create)
    - URL: https://synkdr.com/{bot}/webhook/shopify/order
    """
    try:
        payload = await request.json()
    except Exception:
        raise HTTPException(status_code=400, detail="Invalid JSON")

    checkout_id = str(payload.get("checkout_id", ""))
    if checkout_id:
        recovered = await db.mark_cart_recovered(checkout_id)
        if recovered:
            logger.info(f"✅ Cart recovered! checkout_id={checkout_id}")

    # ── Proactive COD confirmation (anti-rejection) ──
    # When a new order arrives from the online store, Sofía reaches out on
    # WhatsApp to confirm the order and ask the customer to be available for
    # delivery. This is what most reduces failed COD deliveries.
    await _send_order_confirmation(payload)

    return {"status": "ok", "action": "processed"}


async def _send_order_confirmation(payload: dict):
    """
    Send a proactive WhatsApp confirmation for a new online-store order.
    Safe no-op if WhatsApp isn't configured, the feature is off, the order
    has no phone, or the order was already confirmed (webhook retry).
    """
    if not _whatsapp or not feature_enabled("order_confirmation"):
        return

    order_id = str(payload.get("id", "")) or str(payload.get("order_number", ""))
    if order_id and order_id in _confirmed_order_ids:
        logger.debug(f"Order {order_id} already confirmed — skipping")
        return

    details = extract_order_details(payload)
    if not details:
        logger.info("Order confirmation: no phone on order — skipping")
        return

    if order_id:
        _confirmed_order_ids.add(order_id)

    try:
        is_cod = details.get("is_cod")
        if is_cod:
            # Approved template delivers even outside the 24h free-form window
            sent = await _whatsapp.send_template(
                details["phone"], "confirmacion_cod",
                language=_TEMPLATE_LANG,
                params=confirmacion_cod_params(details),
            )
            if not sent:
                # Fallback to free-form (only delivers within 24h window)
                sent = await _whatsapp.send_text(
                    details["phone"],
                    build_confirmation_message(
                        details, bot_name=settings.bot_name, store_name=settings.store_name
                    ),
                )
        else:
            sent = await _whatsapp.send_text(
                details["phone"],
                build_confirmation_message(
                    details, bot_name=settings.bot_name, store_name=settings.store_name
                ),
            )

        if sent:
            logger.info(
                f"📦 COD confirmation sent | order={details['order_name']} | "
                f"phone={details['phone']} | cod={details['is_cod']}"
            )
            # Persist COD orders for automated lifecycle follow-ups
            if is_cod:
                await db.save_cod_order({
                    "order_id": order_id or details["order_name"],
                    "order_name": details["order_name"],
                    "phone": details["phone"],
                    "first_name": details.get("first_name", ""),
                    "items_str": details.get("items_str", ""),
                    "total": details.get("total", 0),
                    "currency": details.get("currency", "DOP"),
                    "stage": 0,
                    "status": "active",
                })
            if _notifier:
                await _notifier.send(build_owner_alert(details))
        else:
            # Send failed (e.g. outside 24h window + template not yet approved) —
            # un-dedup so a retry can try again, and alert the owner to reach out.
            if order_id:
                _confirmed_order_ids.discard(order_id)
            logger.warning(
                f"📦 COD confirmation FAILED to send | order={details['order_name']} | "
                f"phone={details['phone']}"
            )
            alert = (
                f"⚠️ No pude confirmar por WhatsApp el pedido "
                f"{details['order_name']} ({details['phone']}). "
                f"Confírmalo manualmente para evitar rechazo COD."
            )
            await _send_owner_whatsapp(alert)
            if _notifier:
                await _notifier.send(alert)
    except Exception as e:
        if order_id:
            _confirmed_order_ids.discard(order_id)
        logger.error(f"Order confirmation error: {e}")


async def _send_owner_whatsapp(text: str) -> bool:
    """
    Alert the store owner on WhatsApp (+18294554783 by default).

    Always uses the approved `alerta_dueno` template: the owner rarely has an
    open 24h free-form window, and YCloud reports HTTP 200 even when Meta drops
    an out-of-window text message, so a plain send_text would silently fail to
    deliver. Templates deliver regardless of the 24h window.
    """
    if not _whatsapp:
        return False
    # Template params forbid newlines/tabs and 4+ consecutive spaces. A customer
    # review forwarded to the owner could contain any of these, so normalize.
    safe = re.sub(r"[\r\n\t]+", " · ", text)
    safe = re.sub(r" {4,}", "   ", safe).strip()
    sent = await _whatsapp.send_template(
        _OWNER_WHATSAPP, "alerta_dueno", language=_TEMPLATE_LANG, params=[safe]
    )
    if not sent:
        # Last resort: try free-form in case a window happens to be open.
        sent = await _whatsapp.send_text(_OWNER_WHATSAPP, text)
    return sent


async def _finish_cod_reply(sender: str, user_text: str, reply: str, conversation):
    """Persist the exchange and send Sofía's reply for a COD interaction."""
    conversation.add_message("user", user_text)
    conversation.add_message("assistant", reply)
    await db.save_conversation(conversation.to_dict())
    await _whatsapp.send_text(sender, reply)


async def _handle_cod_interaction(sender, message_text, parsed, conversation):
    """
    Handle COD lifecycle button taps and post-delivery review capture.
    These come from real order customers, so they BYPASS the Meta-Ads gate.
    Returns a response dict if handled, else None.
    """
    if not _whatsapp:
        return None

    text = (message_text or "").strip()
    is_button = parsed.get("message_type") in ("button", "interactive")
    awaiting_review = conversation.metadata.get("awaiting_cod_review", False)

    # 1) Review capture — a customer who confirmed receipt is now writing their opinion
    if awaiting_review and not (is_button and text in _COD_BUTTON_TITLES):
        order = await db.get_cod_order_by_phone(sender) or {}
        await _send_owner_whatsapp(owner_review_forward(order, text))
        conversation.metadata["awaiting_cod_review"] = False
        reply = "¡Mil gracias por tu opinión! 🌟 La compartí con el equipo. ¡Un abrazo! 💛"
        await _finish_cod_reply(sender, text, reply, conversation)
        return {"status": "ok", "action": "cod_review_captured"}

    # 2) Quick-reply button taps
    if text not in _COD_BUTTON_TITLES:
        return None

    order = await db.get_cod_order_by_phone(sender) or {}
    order_id = order.get("order_id", "")

    if text == _BTN_CONFIRM:
        if order_id:
            await db.set_cod_order_status(order_id, "active", confirmed=True)
        reply = reply_confirm_ack(order)
    elif text == _BTN_DELIVERY_TODAY:
        if order_id:
            await db.set_cod_order_status(order_id, "active", confirmed=True)
        reply = reply_delivery_today_ack(order)
    elif text == _BTN_RESCHEDULE:
        if order_id:
            await db.set_cod_order_status(order_id, "rescheduled")
        await _send_owner_whatsapp(owner_reschedule_alert(order))
        reply = reply_reschedule_ack(order)
    elif text == _BTN_RECEIVED:
        if order_id:
            await db.set_cod_order_status(order_id, "received")
        conversation.metadata["awaiting_cod_review"] = True
        reply = reply_received_ask_review(order)
    elif text == _BTN_NOT_RECEIVED:
        if order_id:
            await db.set_cod_order_status(order_id, "not_received")
        await _send_owner_whatsapp(owner_not_received_alert(order))
        reply = reply_not_received_ack(order)
    else:
        return None

    await _finish_cod_reply(sender, text, reply, conversation)
    return {"status": "ok", "action": "cod_button_handled"}


# ═══════════════════════════════════════════════════════════════
# ABANDONED CART RECOVERY (Scheduled Task)
# ═══════════════════════════════════════════════════════════════

async def _process_abandoned_carts():
    """
    Check for abandoned carts and send WhatsApp follow-ups.
    Called by the scheduler every 15 minutes.
    
    Follow-up strategy (3 touches):
    - FU1 (30 min):  Friendly reminder with product names + cart link
    - FU2 (4 hours): Urgency + "¿necesitas ayuda?"
    - FU3 (24 hours): Last chance / soft close
    """
    if not _whatsapp or not feature_enabled("abandoned_cart_recovery"):
        return

    carts = await db.get_pending_abandoned_carts(min_age_minutes=30, max_age_hours=48)
    if not carts:
        return

    logger.info(f"🛒 Processing {len(carts)} abandoned carts for follow-up")

    for cart in carts:
        phone = cart["customer_phone"]
        name_parts = cart.get("customer_name", "").split()
        name = name_parts[0] if name_parts else "amig@"
        items = cart.get("line_items", [])
        total = cart.get("total_price", 0)
        url = cart.get("checkout_url", "")
        fu_count = cart.get("followup_count", 0)
        currency = cart.get("currency", "DOP")

        # Build product list (max 3 items)
        item_names = [i.get("name", "") for i in items[:3]]
        items_str = ", ".join(item_names)
        if len(items) > 3:
            items_str += f" y {len(items) - 3} más"

        # Choose follow-up message based on count
        if fu_count == 0:
            # FU1: Friendly reminder (30 min - 4 hours)
            msg = (
                f"¡Hola {name}! 👋 Soy {settings.bot_name} de {settings.store_name}.\n\n"
                f"Vi que dejaste algo en tu carrito:\n"
                f"🛒 {items_str}\n"
                f"💰 Total: {currency} {total:,.0f}\n\n"
                f"¿Te gustaría completar tu compra? Tu carrito te espera aquí:\n"
                f"👉 {url}\n\n"
                f"Si tienes alguna pregunta sobre los productos, ¡estoy aquí para ayudarte! 😊"
            )
        elif fu_count == 1:
            # FU2: Helpful + urgency (4-24 hours)
            msg = (
                f"Hola {name}, soy {settings.bot_name} de {settings.store_name} 🛍️\n\n"
                f"Tu carrito con {items_str} sigue esperándote.\n\n"
                f"¿Tienes alguna duda sobre el envío, pago o los productos? "
                f"Estoy aquí para ayudarte con lo que necesites.\n\n"
                f"👉 {url}"
            )
        else:
            # FU3: Last chance (24-48 hours)
            msg = (
                f"Hola {name} 👋\n\n"
                f"Solo quería avisarte que tu carrito de {settings.store_name} sigue activo.\n\n"
                f"Si decidiste que no es el momento, no hay problema. "
                f"Pero si necesitas ayuda, aquí estoy.\n\n"
                f"👉 {url}"
            )

        success = await _whatsapp.send_text(phone, msg)
        if success:
            await db.mark_cart_followed_up(cart["id"], fu_count + 1)
            logger.info(f"🛒 Cart FU{fu_count + 1} sent to {phone}")
        else:
            logger.warning(f"🛒 Cart FU{fu_count + 1} FAILED for {phone}")


# ═══════════════════════════════════════════════════════════════
# PRODUCT SYNC ENDPOINT
# ═══════════════════════════════════════════════════════════════

@app.post("/sync/products", tags=["Admin"])
async def sync_products(request: Request):
    """
    Sync products from Shopify store into Supabase.
    Called manually, by n8n workflow, or on schedule.
    """
    global _product_context, _products_raw

    auth = request.headers.get("X-Sync-Key", "")
    if auth != settings.sync_key:
        raise HTTPException(status_code=401, detail="Invalid sync key")

    products = fetch_all_products(
        settings.shopify.store_url,
        access_token=settings.shopify.access_token,
        api_version=settings.shopify.api_version,
    )

    synced = 0
    for product in products:
        result = await db.upsert_product(product)
        if result:
            synced += 1

    # Refresh in-memory product context
    _products_raw = products
    _product_context = build_product_context(products)

    logger.info(f"📦 Product sync complete: {synced}/{len(products)} products")

    return {
        "status": "ok",
        "total_products": len(products),
        "synced": synced,
        "timestamp": datetime.now(timezone.utc).isoformat(),
    }


# ═══════════════════════════════════════════════════════════════
# ADMIN API (SOFÍA HQ)
# ═══════════════════════════════════════════════════════════════

@app.get("/login", tags=["Auth"])
async def login_page():
    """Serve the Sofía HQ login page."""
    login_file = STATIC_DIR / "login.html"
    if login_file.exists():
        return FileResponse(str(login_file), media_type="text/html")
    raise HTTPException(status_code=404, detail="Login page not found")


@app.get("/admin", tags=["Admin"])
async def admin_dashboard():
    """Serve the Sofía HQ admin dashboard (auth check is client-side via JS)."""
    admin_file = STATIC_DIR / "admin.html"
    if admin_file.exists():
        return FileResponse(str(admin_file), media_type="text/html")
    raise HTTPException(status_code=404, detail="Admin dashboard not found")


@app.get("/admin/api/stats", tags=["Admin"], dependencies=[Depends(get_current_admin)])
async def admin_get_stats():
    """Get high-level KPIs for Sofía HQ Dashboard."""
    client = db.get_supabase()
    if not client:
        return {"error": "DB not connected"}
    
    try:
        res_conv = client.table("conversations").select("id", count="exact").limit(1).execute()
        res_msgs = client.table("messages").select("id", count="exact").limit(1).execute()
        
        # Catalog stats
        res_products = client.table("products").select("id,category,available,price_min", count="exact").execute()
        products = res_products.data or []
        categories = {}
        available_count = 0
        for p in products:
            cat = p.get("category") or "Sin categoría"
            categories[cat] = categories.get(cat, 0) + 1
            if p.get("available"):
                available_count += 1
        
        return {
            "total_conversations": res_conv.count if hasattr(res_conv, "count") else 0,
            "total_messages": res_msgs.count if hasattr(res_msgs, "count") else 0,
            "catalog": {
                "total_products": len(products),
                "available": available_count,
                "categories": categories,
            }
        }
    except Exception as e:
        logger.error(f"❌ Error getting stats: {e}")
        return {"error": str(e)}


@app.get("/admin/api/conversations", tags=["Admin"], dependencies=[Depends(get_current_admin)])
async def admin_get_conversations(limit: int = 50):
    """Get recent conversations for Sofía HQ Dashboard."""
    client = db.get_supabase()
    if not client:
        return {"error": "DB not connected"}
        
    try:
        res = client.table("conversations").select(
            "id, channel, state, status, last_message_at, customer:customers(phone, name)"
        ).order("last_message_at", desc=True).limit(limit).execute()
        
        return {"conversations": res.data or []}
    except Exception as e:
        logger.error(f"❌ Error getting conversations: {e}")
        return {"error": str(e)}


@app.get("/admin/api/conversation/{conv_id}", tags=["Admin"], dependencies=[Depends(get_current_admin)])
async def admin_get_conversation_detail(conv_id: str):
    """Get full history of a specific conversation."""
    client = db.get_supabase()
    if not client:
        return {"error": "DB not connected"}
        
    try:
        # Get messages from dedicated table
        res = client.table("messages").select("*").eq("conversation_id", conv_id).order("created_at").execute()
        msg_rows = res.data or []

        # Also check metadata.history (older conversations stored history there)
        conv_res = client.table("conversations").select("metadata, last_message_at").eq("id", conv_id).limit(1).execute()
        history_msgs = []
        if conv_res.data:
            meta = conv_res.data[0].get("metadata") or {}
            history = meta.get("history", [])
            for h in history:
                role = h.get("role", "customer")
                if role == "user":
                    role = "customer"
                history_msgs.append({
                    "role": role,
                    "content": h.get("content", ""),
                    "created_at": h.get("timestamp") or conv_res.data[0].get("last_message_at"),
                })

        # Use whichever source has more messages (metadata has full history for older convs)
        return {"messages": history_msgs if len(history_msgs) > len(msg_rows) else msg_rows}
    except Exception as e:
        logger.error(f"❌ Error getting conversation detail: {e}")
        return {"error": str(e)}


@app.post("/admin/api/conversation/{conv_id}/send", tags=["Admin"], dependencies=[Depends(get_current_admin)])
async def admin_send_message(conv_id: str, payload: AdminMessage):
    """Admin taking over and sending a message manually."""
    client = db.get_supabase()
    if not client:
        return {"error": "DB not connected"}
        
    try:
        # Get conversation to know channel and customer ID
        res = client.table("conversations").select("*").eq("id", conv_id).limit(1).execute()
        if not res.data:
            return {"error": "Conversation not found"}
        
        conv_data = res.data[0]
        customer_id = conv_data["customer_id"]
        channel = conv_data["channel"]
        
        # Save message to DB via State machine to maintain internal sync
        conv_obj = Conversation.from_dict(conv_data)
        conv_obj.add_message("assistant", payload.message)
        # Force state to ESCALATED if admin is talking manually? 
        # Actually let's just leave it active or as is, but we could mark it escalated.
        conv_obj.state = ConversationState.ESCALATED
        await db.save_conversation(conv_obj.to_dict())
        
        # Send via WhatsApp if the channel is WhatsApp
        if channel == "whatsapp" and _whatsapp:
            await _whatsapp.send_text(customer_id, payload.message)
            
        return {"status": "ok", "message": "sent"}
    except Exception as e:
        logger.error(f"❌ Error sending manual message: {e}")
        return {"error": str(e)}


@app.get("/admin/api/settings", tags=["Admin"], dependencies=[Depends(get_current_admin)])
async def admin_get_all_settings():
    """Get all bot settings as key-value pairs."""
    settings_dict = await db.get_all_bot_settings()
    return {"settings": settings_dict}


@app.post("/admin/api/settings/bulk", tags=["Admin"], dependencies=[Depends(get_current_admin)])
async def admin_save_bulk_settings(request: Request):
    """Save multiple settings at once."""
    try:
        payload = await request.json()
        settings_dict = payload.get("settings", {})
        saved = 0
        for key, value in settings_dict.items():
            if await db.set_bot_setting(key, str(value)):
                saved += 1
        return {"status": "ok", "saved": saved}
    except Exception as e:
        return {"error": str(e)}


@app.get("/admin/api/settings/{key}", tags=["Admin"], dependencies=[Depends(get_current_admin)])
async def admin_get_setting(key: str):
    """Get a specific bot setting."""
    val = await db.get_bot_setting(key)
    return {"key": key, "value": val or ""}


@app.post("/admin/api/settings/{key}", tags=["Admin"], dependencies=[Depends(get_current_admin)])
async def admin_save_setting(key: str, payload: BotSettingUpdate):
    """Update a specific bot setting."""
    success = await db.set_bot_setting(key, payload.value)
    if success:
        return {"status": "ok"}
    return {"error": "Failed to save setting"}


@app.get("/admin/api/catalog", tags=["Admin"], dependencies=[Depends(get_current_admin)])
async def admin_get_catalog():
    """Get catalog products for dashboard display."""
    client = db.get_supabase()
    if not client:
        return {"products": []}
    try:
        res = client.table("products").select(
            "name,category,price_min,price_max,currency,available,image_url,url"
        ).order("name").execute()
        return {"products": res.data or []}
    except Exception as e:
        logger.error(f"❌ Error getting catalog: {e}")
        return {"products": []}


@app.post("/admin/api/sync", tags=["Admin"], dependencies=[Depends(get_current_admin)])
async def admin_trigger_sync():
    """Manual trigger to sync the catalog from Shopify to Supabase and context."""
    global _product_context, _products_raw, _upsell_context
    try:
        products = fetch_all_products(
            settings.shopify.store_url,
            access_token=settings.shopify.access_token,
            api_version=settings.shopify.api_version,
        )
        synced = 0
        for product in products:
            if await db.upsert_product(product):
                synced += 1

        # Refresh in-memory product context
        _products_raw = products
        _product_context = build_product_context(products)

        # Refresh ReleaseIt upsell context
        _upsell_context = fetch_upsell_context(
            settings.shopify.store_url,
            settings.shopify.access_token,
        )
        logger.info(f"📦 Admin manual sync complete: {synced}/{len(products)} products + upsells refreshed")
        return {"status": "ok", "total_products": len(products), "synced": synced}
    except Exception as e:
        logger.error(f"❌ Error during manual sync: {e}")
        return {"error": str(e)}


# ═══════════════════════════════════════════════════════════════
# ANALYTICS API (Real metrics — replaces fabricated stats)
# ═══════════════════════════════════════════════════════════════

@app.get("/admin/api/analytics/live", tags=["Analytics"], dependencies=[Depends(get_current_admin)])
async def admin_analytics_live():
    """Get real-time analytics for today."""
    return analytics.get_live_stats()


@app.get("/admin/api/analytics/summary", tags=["Analytics"], dependencies=[Depends(get_current_admin)])
async def admin_analytics_summary(days: int = 7):
    """Get aggregated analytics for the last N days."""
    return analytics.get_summary(days=min(days, 90))


@app.get("/api/analytics/public", tags=["Analytics"])
async def public_analytics():
    """
    Public-facing analytics for the landing page.
    Returns real metrics (no auth required — only safe/aggregated data).
    """
    stats = analytics.get_summary(days=30)
    return {
        "resolution_rate_pct": stats.get("resolution_rate_pct", 0),
        "avg_response_ms": stats.get("avg_response_ms", 0),
        "pct_under_3s": stats.get("pct_under_3s", 0),
        "conversations_handled": stats.get("conversations_started", 0),
    }


@app.get("/api/plans", tags=["Public"])
async def public_plans():
    """Public pricing plans for the landing page (no auth)."""
    plans = await platform_db.list_plans()
    # Only expose safe fields
    return {"plans": [
        {
            "name": p["name"],
            "display_name": p["display_name"],
            "price_usd": p["price_usd"],
            "max_conversations_mo": p["max_conversations_mo"],
            "max_products": p["max_products"],
            "features": p.get("features", {}),
        } for p in plans
    ]}


@app.get("/api/templates", tags=["Public"])
async def public_templates():
    """Public storefront templates available for SynkRD stores (no auth)."""
    return {"templates": platform_db.list_storefront_templates()}



# ═══════════════════════════════════════════════════════════════
# ORDER TRACKING API
# ═══════════════════════════════════════════════════════════════

@app.get("/api/order/{order_name}", tags=["Orders"])
async def track_order(order_name: str):
    """
    Track an order by order name (e.g., '#1001').
    Uses Shopify Admin API if access token is configured.
    """
    from knowledge.shopify import ShopifyKnowledge

    if not settings.shopify.access_token:
        return {"error": "Shopify Admin API not configured — order tracking unavailable"}

    shopify = ShopifyKnowledge(
        store_url=settings.shopify.store_url,
        access_token=settings.shopify.access_token,
    )

    try:
        order = await shopify.fetch_order_status(order_name)
        if order:
            return {"status": "ok", "order": order}
        return {"status": "not_found", "message": f"No se encontró la orden {order_name}"}
    except Exception as e:
        logger.error(f"❌ Order tracking failed: {e}")
        return {"error": str(e)}


# ═══════════════════════════════════════════════════════════════
# MONTHLY CONVERSATION COUNT (Plan Limits)
# ═══════════════════════════════════════════════════════════════

@app.get("/admin/api/usage", tags=["Admin"], dependencies=[Depends(get_current_admin)])
async def admin_get_usage():
    """Get monthly conversation usage for plan limit tracking."""
    monthly_count = await db.get_monthly_conversation_count()
    plan_limit = await db.get_bot_setting("plan_conversation_limit")
    limit = int(plan_limit) if plan_limit else 500  # Default: Starter plan

    return {
        "month_conversations": monthly_count,
        "plan_limit": limit,
        "usage_pct": round((monthly_count / limit) * 100) if limit > 0 else 0,
        "remaining": max(0, limit - monthly_count),
    }


# ═══════════════════════════════════════════════════════════════
# SUPER ADMIN (Platform SaaS Management)
# ═══════════════════════════════════════════════════════════════
import platform_db


async def get_platform_admin(credentials: HTTPAuthorizationCredentials = Depends(security)):
    """Validate token AND verify the user is a registered platform super admin."""
    if not credentials:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Token de autenticación requerido",
            headers={"WWW-Authenticate": "Bearer"},
        )

    user_data = await db.verify_admin_token(credentials.credentials)
    if not user_data:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Token inválido o expirado",
            headers={"WWW-Authenticate": "Bearer"},
        )

    admin = await platform_db.verify_platform_admin(user_data["id"], email=user_data.get("email"))
    if not admin:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Acceso denegado — no eres super admin",
        )

    return {"user": user_data, "admin": admin}


# ── Pages ──

@app.get("/superadmin/login", tags=["SuperAdmin"])
async def superadmin_login_page():
    """Serve the super admin login page."""
    f = STATIC_DIR / "superadmin_login.html"
    if f.exists():
        return FileResponse(str(f), media_type="text/html")
    raise HTTPException(status_code=404, detail="Page not found")


@app.get("/superadmin", tags=["SuperAdmin"])
async def superadmin_dashboard_page():
    """Serve the super admin dashboard SPA."""
    f = STATIC_DIR / "superadmin.html"
    if f.exists():
        return FileResponse(str(f), media_type="text/html")
    raise HTTPException(status_code=404, detail="Page not found")


# ── Overview ──

@app.get("/superadmin/api/overview", tags=["SuperAdmin"], dependencies=[Depends(get_platform_admin)])
async def superadmin_overview():
    """Get aggregate platform stats (all tenants)."""
    overview = await platform_db.get_platform_overview()
    plans = await platform_db.list_plans()
    return {"overview": overview, "plans": plans}


# ── Tenants CRUD ──

class TenantCreate(BaseModel):
    name: str
    slug: str
    owner_email: str
    owner_name: str = ""
    bot_name: str = "Sofía"
    plan_id: Optional[str] = None
    store_url: str = ""
    supabase_url: str = ""
    supabase_anon_key: str = ""


class TenantUpdate(BaseModel):
    name: Optional[str] = None
    status: Optional[str] = None
    plan_id: Optional[str] = None
    bot_name: Optional[str] = None
    store_url: Optional[str] = None
    supabase_url: Optional[str] = None
    supabase_anon_key: Optional[str] = None
    ai_provider: Optional[str] = None
    ai_model: Optional[str] = None
    ai_temperature: Optional[float] = None
    ai_max_tokens: Optional[int] = None


@app.get("/superadmin/api/tenants", tags=["SuperAdmin"])
async def superadmin_list_tenants(admin_ctx=Depends(get_platform_admin)):
    """List all tenants on the platform."""
    tenants = await platform_db.list_tenants()
    return {"tenants": tenants, "total": len(tenants)}


@app.post("/superadmin/api/tenants", tags=["SuperAdmin"])
async def superadmin_create_tenant(payload: TenantCreate, admin_ctx=Depends(get_platform_admin)):
    """Create a new tenant account."""
    data = payload.model_dump(exclude_none=True)
    tenant = await platform_db.create_tenant(data)
    if not tenant:
        raise HTTPException(status_code=500, detail="Error creating tenant")

    await platform_db.log_action(
        admin_id=admin_ctx["admin"]["id"],
        action="tenant_created",
        tenant_id=tenant["id"],
        details={"name": tenant["name"], "slug": tenant["slug"]},
    )
    return {"tenant": tenant}


@app.get("/superadmin/api/tenants/{tenant_id}", tags=["SuperAdmin"])
async def superadmin_get_tenant(tenant_id: str, admin_ctx=Depends(get_platform_admin)):
    """Get full details for a single tenant."""
    tenant = await platform_db.get_tenant(tenant_id)
    if not tenant:
        raise HTTPException(status_code=404, detail="Tenant not found")

    # Pull live stats from the tenant's own Supabase
    live_stats = {}
    if tenant.get("supabase_url") and tenant.get("supabase_anon_key"):
        live_stats = await platform_db.get_tenant_live_stats(tenant)

    return {"tenant": tenant, "live_stats": live_stats}


@app.put("/superadmin/api/tenants/{tenant_id}", tags=["SuperAdmin"])
async def superadmin_update_tenant(tenant_id: str, payload: TenantUpdate, admin_ctx=Depends(get_platform_admin)):
    """Update a tenant's config."""
    data = payload.model_dump(exclude_none=True)
    if not data:
        raise HTTPException(status_code=400, detail="No fields to update")

    tenant = await platform_db.update_tenant(tenant_id, data)
    if not tenant:
        raise HTTPException(status_code=500, detail="Error updating tenant")

    await platform_db.log_action(
        admin_id=admin_ctx["admin"]["id"],
        action="tenant_updated",
        tenant_id=tenant_id,
        details={"fields": list(data.keys())},
    )
    return {"tenant": tenant}


@app.delete("/superadmin/api/tenants/{tenant_id}", tags=["SuperAdmin"])
async def superadmin_delete_tenant(tenant_id: str, admin_ctx=Depends(get_platform_admin)):
    """Soft-delete a tenant (set status = 'deleted')."""
    success = await platform_db.delete_tenant(tenant_id)
    if not success:
        raise HTTPException(status_code=500, detail="Error deleting tenant")

    await platform_db.log_action(
        admin_id=admin_ctx["admin"]["id"],
        action="tenant_deleted",
        tenant_id=tenant_id,
    )
    return {"status": "deleted"}


# ── Plans CRUD ──

class PlanCreate(BaseModel):
    name: str
    display_name: str
    max_conversations_mo: int = 500
    max_products: int = 100
    price_usd: float = 0
    features: dict = {}


class PlanUpdate(BaseModel):
    display_name: Optional[str] = None
    max_conversations_mo: Optional[int] = None
    max_products: Optional[int] = None
    price_usd: Optional[float] = None
    features: Optional[dict] = None
    is_active: Optional[bool] = None


@app.get("/superadmin/api/plans", tags=["SuperAdmin"], dependencies=[Depends(get_platform_admin)])
async def superadmin_list_plans():
    """List all available tenant plans."""
    plans = await platform_db.list_plans()
    return {"plans": plans}


@app.post("/superadmin/api/plans", tags=["SuperAdmin"])
async def superadmin_create_plan(payload: PlanCreate, admin_ctx=Depends(get_platform_admin)):
    """Create a new plan."""
    data = payload.model_dump(exclude_none=True)
    plan = await platform_db.create_plan(data)
    if not plan:
        raise HTTPException(status_code=500, detail="Error creating plan")
    await platform_db.log_action(admin_id=admin_ctx["admin"]["id"], action="plan_created", details={"name": plan["name"]})
    return {"plan": plan}


@app.put("/superadmin/api/plans/{plan_id}", tags=["SuperAdmin"])
async def superadmin_update_plan(plan_id: str, payload: PlanUpdate, admin_ctx=Depends(get_platform_admin)):
    """Update an existing plan."""
    data = payload.model_dump(exclude_none=True)
    if not data:
        raise HTTPException(status_code=400, detail="No fields to update")
    plan = await platform_db.update_plan(plan_id, data)
    if not plan:
        raise HTTPException(status_code=500, detail="Error updating plan")
    await platform_db.log_action(admin_id=admin_ctx["admin"]["id"], action="plan_updated", details={"plan": plan["name"], "fields": list(data.keys())})
    # Refresh feature gate if the active tenant's plan was updated
    await refresh_feature_gate()
    return {"plan": plan}


@app.delete("/superadmin/api/plans/{plan_id}", tags=["SuperAdmin"])
async def superadmin_delete_plan(plan_id: str, admin_ctx=Depends(get_platform_admin)):
    """Deactivate a plan."""
    plan = await platform_db.update_plan(plan_id, {"is_active": False})
    if not plan:
        raise HTTPException(status_code=500, detail="Error deleting plan")
    await platform_db.log_action(admin_id=admin_ctx["admin"]["id"], action="plan_deleted", details={"name": plan["name"]})
    return {"status": "deactivated"}


# ── Logs ──

@app.get("/superadmin/api/logs", tags=["SuperAdmin"], dependencies=[Depends(get_platform_admin)])
async def superadmin_get_logs(limit: int = 100, tenant_id: str = None):
    """Get platform audit logs."""
    logs = await platform_db.get_logs(limit=limit, tenant_id=tenant_id)
    return {"logs": logs, "total": len(logs)}


# ── Tenant Stats Snapshot ──

@app.post("/superadmin/api/tenants/{tenant_id}/snapshot", tags=["SuperAdmin"])
async def superadmin_snapshot_stats(tenant_id: str, admin_ctx=Depends(get_platform_admin)):
    """Save a daily stats snapshot for a tenant."""
    tenant = await platform_db.get_tenant(tenant_id)
    if not tenant:
        raise HTTPException(status_code=404, detail="Tenant not found")

    stats = await platform_db.get_tenant_live_stats(tenant)
    await platform_db.save_tenant_stats_snapshot(tenant_id, stats)
    return {"status": "saved", "stats": stats}


# ═══════════════════════════════════════════════════════════════
# CRM ADMIN API
# ═══════════════════════════════════════════════════════════════

@app.get("/admin/crm", tags=["Admin"])
async def crm_dashboard_page():
    """Serve the CRM admin dashboard HTML."""
    from fastapi.responses import FileResponse
    return FileResponse("static/crm.html")


@app.get("/admin/api/customers", tags=["Admin"], dependencies=[Depends(get_current_admin)])
async def admin_get_customers(
    limit: int = 200,
    offset: int = 0,
    channel: str = "",
):
    """List all customers Sofía has talked to."""
    data = await db.get_all_customers(limit=limit, offset=offset, channel=channel)
    return {"customers": data, "count": len(data)}


@app.get("/admin/api/customers/export.csv", tags=["Admin"], dependencies=[Depends(get_current_admin)])
async def admin_export_customers_csv():
    """Export all customers as CSV."""
    import csv, io
    from fastapi.responses import StreamingResponse
    customers = await db.get_all_customers(limit=5000)
    output = io.StringIO()
    writer = csv.DictWriter(output, fieldnames=[
        "customer_id", "name", "phone", "email", "channel", "channels_used",
        "first_seen", "last_seen", "total_messages",
        "purchase_intent", "last_interested_product",
        "has_order", "last_order_product", "total_orders",
    ])
    writer.writeheader()
    for row in customers:
        row["channels_used"] = ",".join(row.get("channels_used") or [])
        writer.writerow({k: row.get(k, "") for k in writer.fieldnames})
    output.seek(0)
    return StreamingResponse(
        iter([output.getvalue()]),
        media_type="text/csv",
        headers={"Content-Disposition": "attachment; filename=sofia_customers.csv"},
    )


@app.get("/admin/api/abandoned-carts", tags=["Admin"], dependencies=[Depends(get_current_admin)])
async def admin_get_abandoned_carts():
    """List customers with purchase intent who never placed an order."""
    data = await db.get_abandoned_carts()
    return {"abandoned_carts": data, "count": len(data)}


@app.get("/admin/api/wishlist", tags=["Admin"], dependencies=[Depends(get_current_admin)])
async def admin_get_wishlist():
    """List all wishlist (out-of-stock demand) entries."""
    data = await db.get_all_wishlist_items()
    return {"wishlist": data, "count": len(data)}


@app.get("/admin/api/wishlist/export.csv", tags=["Admin"], dependencies=[Depends(get_current_admin)])
async def admin_export_wishlist_csv():
    """Export wishlist as CSV."""
    import csv, io
    from fastapi.responses import StreamingResponse
    wishlist = await db.get_all_wishlist_items(limit=5000)
    output = io.StringIO()
    writer = csv.DictWriter(output, fieldnames=[
        "customer_id", "product_name", "variant_title", "shopify_product_id",
        "channel", "notified", "created_at",
    ])
    writer.writeheader()
    for row in wishlist:
        writer.writerow({k: row.get(k, "") for k in writer.fieldnames})
    output.seek(0)
    return StreamingResponse(
        iter([output.getvalue()]),
        media_type="text/csv",
        headers={"Content-Disposition": "attachment; filename=sofia_wishlist.csv"},
    )


# ═══════════════════════════════════════════════════════════════
# MEDIA & IMAGE UPLOAD ENDPOINT (TrendyRD & SynkRD Product Assets)
# ═══════════════════════════════════════════════════════════════
import base64
from fastapi import UploadFile, File
from fastapi.responses import JSONResponse

MEDIA_PRODUCTS_DIR = Path("/var/www/nexusrd-media/products")
MEDIA_PRODUCTS_DIR.mkdir(parents=True, exist_ok=True)
MEDIA_BASE_URL = "https://srv806559.hstgr.cloud/media/products"

ALLOWED_EXTENSIONS = {".png", ".jpg", ".jpeg", ".webp", ".gif", ".svg"}

@app.post("/api/upload", tags=["Media"])
@app.post("/upload", tags=["Media"])
async def upload_product_media(
    request: Request,
    files: Optional[list[UploadFile]] = File(None),
    file: Optional[UploadFile] = File(None),
):
    """
    Universal multi-image & animated GIF upload endpoint.
    Accepts:
      1. Multipart form: files (multiple) or file (single)
      2. JSON body: { base64: "...", filename: "..." } or { files: [{ base64, filename }] }
    Stores files untouched in /var/www/nexusrd-media/products/ preserving full GIF animation frames.
    """
    uploaded_urls = []
    content_type = request.headers.get("content-type", "")

    # 1. Handle JSON / Base64 payload
    if "application/json" in content_type:
        try:
            body = await request.json()
            items = []
            if "files" in body and isinstance(body["files"], list):
                items = body["files"]
            elif "base64" in body:
                items = [body]

            for item in items:
                b64_str = item.get("base64", "")
                fname = item.get("filename", "image.png")
                if not b64_str:
                    continue

                # Strip data URL prefix if present
                ext = ".png"
                if "," in b64_str:
                    header, b64_str = b64_str.split(",", 1)
                    if "image/gif" in header:
                        ext = ".gif"
                    elif "image/webp" in header:
                        ext = ".webp"
                    elif "image/jpeg" in header or "image/jpg" in header:
                        ext = ".jpg"
                else:
                    ext = Path(fname).suffix.lower() or ".png"

                clean_base = re.sub(r'[^a-zA-Z0-9_-]', '_', Path(fname).stem)[:40]
                unique_name = f"{int(datetime.now(timezone.utc).timestamp() * 1000)}_{clean_base}{ext}"
                target_path = MEDIA_PRODUCTS_DIR / unique_name

                data_bytes = base64.b64decode(b64_str)
                with open(target_path, "wb") as f_out:
                    f_out.write(data_bytes)

                uploaded_urls.append(f"{MEDIA_BASE_URL}/{unique_name}")

        except Exception as e:
            logger.error(f"Error saving base64 upload: {e}")
            return JSONResponse(status_code=500, content={"error": f"Base64 upload failed: {str(e)}"})

    # 2. Handle Multipart Form files
    all_files = []
    if files:
        all_files.extend(files)
    if file:
        all_files.append(file)

    if all_files:
        for f in all_files:
            try:
                original_name = f.filename or "image.png"
                ext = Path(original_name).suffix.lower()
                if ext not in ALLOWED_EXTENSIONS:
                    ext = ".png"
                
                clean_base = re.sub(r'[^a-zA-Z0-9_-]', '_', Path(original_name).stem)[:40]
                unique_name = f"{int(datetime.now(timezone.utc).timestamp() * 1000)}_{clean_base}{ext}"
                target_path = MEDIA_PRODUCTS_DIR / unique_name

                content = await f.read()
                with open(target_path, "wb") as f_out:
                    f_out.write(content)

                uploaded_urls.append(f"{MEDIA_BASE_URL}/{unique_name}")
            except Exception as e:
                logger.error(f"Error saving uploaded file {f.filename}: {e}")

    if not uploaded_urls:
        return JSONResponse(status_code=400, content={"error": "No valid files received"})

    response = JSONResponse(
        content={
            "url": uploaded_urls[0],
            "urls": uploaded_urls,
            "count": len(uploaded_urls),
        }
    )
    response.headers["Access-Control-Allow-Origin"] = "*"
    return response

@app.options("/api/upload", tags=["Media"])
@app.options("/upload", tags=["Media"])
async def upload_options():
    res = JSONResponse(content={"status": "ok"})
    res.headers["Access-Control-Allow-Origin"] = "*"
    res.headers["Access-Control-Allow-Methods"] = "POST, OPTIONS"
    res.headers["Access-Control-Allow-Headers"] = "*"
    return res


# ═══════════════════════════════════════════════════════════════
# ENTRY POINT
# ═══════════════════════════════════════════════════════════════

if __name__ == "__main__":
    import uvicorn
    uvicorn.run(
        "main:app",
        host=settings.host,
        port=settings.port,
        reload=True,
    )
