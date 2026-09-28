"""
SynkDR Engine — Supabase Client

Handles all database operations for the customer service bot.
"""

import os
import logging
import httpx
from typing import Optional
from datetime import datetime, timezone

logger = logging.getLogger("synkdr.database")

_supabase_client = None


def get_supabase():
    """Lazy-initialize Supabase client."""
    global _supabase_client
    if _supabase_client is None:
        try:
            from supabase import create_client
            from core.config import settings

            url = settings.database.supabase_url
            key = settings.database.supabase_key

            if not url or not key:
                logger.warning("⚠️ Supabase URL or KEY not configured")
                return None

            _supabase_client = create_client(url, key)
            logger.info("✅ Supabase client initialized")
        except Exception as e:
            logger.error(f"❌ Failed to initialize Supabase: {e}")
    return _supabase_client


# ═══════════════════════════════════════════════════════════════
# AUTH TOKEN VERIFICATION
# ═══════════════════════════════════════════════════════════════

async def verify_admin_token(token: str) -> Optional[dict]:
    """
    Verify a Supabase Auth JWT token by calling the GoTrue /auth/v1/user endpoint.
    Returns user data dict if valid, None if invalid.
    """
    supabase_url = os.getenv("SUPABASE_URL", "")
    if not supabase_url or not token:
        return None

    try:
        async with httpx.AsyncClient() as client:
            res = await client.get(
                f"{supabase_url}/auth/v1/user",
                headers={
                    "Authorization": f"Bearer {token}",
                    "apikey": os.getenv("SUPABASE_KEY", ""),
                },
                timeout=10.0,
            )
        if res.status_code == 200:
            return res.json()
        logger.warning(f"Auth token verification failed: {res.status_code}")
        return None
    except Exception as e:
        logger.error(f"Auth token verification error: {e}")
        return None


# ═══════════════════════════════════════════════════════════════
# CONVERSATION OPERATIONS
# ═══════════════════════════════════════════════════════════════

async def get_db_customer_id(raw_customer_id: str) -> Optional[str]:
    """Get or create customer UUID from string phone/session ID."""
    client = get_supabase()
    if not client:
        return None

    try:
        # First try to get existing customer
        result = client.table("customers").select("id").eq("phone", raw_customer_id).limit(1).execute()
        if result.data:
            return result.data[0]["id"]
            
        # If not exists, insert new customer with that phone/ID
        res = client.table("customers").insert({"phone": raw_customer_id}).execute()
        if res.data:
            return res.data[0]["id"]
    except Exception as e:
        logger.error(f"❌ Customer lookup/creation failed: {e}")
    return None


async def save_conversation(conversation_data: dict) -> Optional[dict]:
    """
    Save or update a conversation session.
    Uses 'conversations' table in Supabase.
    """
    client = get_supabase()
    if not client:
        return None

    try:
        raw_customer_id = conversation_data["customer_id"]
        db_cust_id = await get_db_customer_id(raw_customer_id)
        if not db_cust_id:
            logger.error(f"❌ Failed to get UUID for customer_id {raw_customer_id}")
            return None
        
        # Prepare metadata payload (wrap history and product_interests inside)
        meta = conversation_data.get("metadata", {}).copy()
        meta["history"] = conversation_data.get("history", [])
        meta["product_interests"] = conversation_data.get("product_interests", [])
        
        real_state = conversation_data.get("state", "greeting")
        meta["real_state"] = real_state
        
        # Map back to allowed DB enum states
        db_state = "active"
        if real_state == "escalated": db_state = "escalated"
        if real_state == "inactive": db_state = "closed"
        if real_state == "post_sale": db_state = "closed"

        # Map back to allowed DB enum status (SynkDR Dashboard)
        db_status = conversation_data.get("status", "active")
        if db_status not in ("active", "won", "lost"):
            db_status = "active"

        # Map channel to DB-allowed values
        raw_channel = conversation_data.get("channel", "whatsapp")
        db_channel = "webchat" if raw_channel in ("web", "webchat") else raw_channel

        row_data = {
            "customer_id": db_cust_id,
            "channel": db_channel,
            "state": db_state,
            "status": db_status,
            "last_message_at": datetime.now(timezone.utc).isoformat(),
            "metadata": meta,
            "messages_count": len(meta["history"])
        }
        
        conv_id = conversation_data.get("id")
        if conv_id:
            row_data["id"] = conv_id
            result = client.table("conversations").upsert(row_data).execute()
        else:
            result = client.table("conversations").insert(row_data).execute()
            
        return result.data[0] if result.data else None
    except Exception as e:
        logger.error(f"❌ Conversation save failed: {e}")
        return None


async def get_conversation(customer_id: str) -> Optional[dict]:
    """Load a conversation session by literal string customer ID (phone or session)."""
    client = get_supabase()
    if not client:
        return None

    try:
        db_cust_id = await get_db_customer_id(customer_id)
        if not db_cust_id:
            return None

        result = client.table("conversations").select("*").eq(
            "customer_id", db_cust_id
        ).neq("state", "closed").order(
            "last_message_at", desc=True
        ).limit(1).execute()
        
        if not result.data:
            return None
            
        row = result.data[0]
        meta = row.get("metadata", {})
        
        # Reconstruct the dict to match what Conversation.from_dict() expects
        return {
            "id": row["id"],
            "db_customer_id": db_cust_id,
            "customer_id": customer_id, # String ID used by system
            "channel": row["channel"],
            "state": meta.get("real_state", row["state"]),
            "history": meta.get("history", []),
            "product_interests": meta.get("product_interests", []),
            "metadata": meta
        }
    except Exception as e:
        logger.error(f"❌ Conversation load failed: {e}")
        return None


# ═══════════════════════════════════════════════════════════════
# CUSTOMER OPERATIONS
# ═══════════════════════════════════════════════════════════════

async def upsert_customer(customer: dict) -> Optional[dict]:
    """Insert or update a customer record."""
    client = get_supabase()
    if not client:
        return None

    try:
        result = client.table("customers").upsert(
            customer, on_conflict="phone"
        ).execute()
        return result.data[0] if result.data else None
    except Exception as e:
        logger.error(f"❌ Customer upsert failed: {e}")
        return None


async def get_customer_by_phone(phone: str) -> Optional[dict]:
    """Find a customer by phone number."""
    client = get_supabase()
    if not client:
        return None

    try:
        result = client.table("customers").select("*").eq(
            "phone", phone
        ).limit(1).execute()
        return result.data[0] if result.data else None
    except Exception as e:
        logger.error(f"❌ Customer lookup failed: {e}")
        return None


# ═══════════════════════════════════════════════════════════════
# MESSAGE OPERATIONS
# ═══════════════════════════════════════════════════════════════

async def save_message(message: dict) -> Optional[dict]:
    """Save a message to the messages table."""
    client = get_supabase()
    if not client:
        return None

    try:
        result = client.table("messages").insert(message).execute()
        return result.data[0] if result.data else None
    except Exception as e:
        logger.error(f"❌ Message save failed: {e}")
        return None


# ═══════════════════════════════════════════════════════════════
# PRODUCT OPERATIONS
# ═══════════════════════════════════════════════════════════════

async def upsert_product(product: dict) -> Optional[dict]:
    """Insert or update a product from Shopify store."""
    client = get_supabase()
    if not client:
        return None

    try:
        product["synced_at"] = datetime.now(timezone.utc).isoformat()
        result = client.table("products").upsert(
            product, on_conflict="shopify_id"
        ).execute()
        return result.data[0] if result.data else None
    except Exception as e:
        logger.error(f"❌ Product upsert failed: {e}")
        return None


async def get_all_products(available_only: bool = True) -> list:
    """Get all products from database."""
    client = get_supabase()
    if not client:
        return []

    try:
        query = client.table("products").select("*")
        if available_only:
            query = query.eq("available", True)
        result = query.order("name").execute()
        return result.data or []
    except Exception as e:
        logger.error(f"❌ Products fetch failed: {e}")
        return []


# ═══════════════════════════════════════════════════════════════
# ESCALATION LOG
# ═══════════════════════════════════════════════════════════════

async def log_escalation(
    customer_id: str,
    reason: str,
    level: int,
    message: str = "",
) -> None:
    """Log an escalation event. Stores as a system message."""
    client = get_supabase()
    if not client:
        return

    try:
        # Log escalation as a system message in the messages table
        await save_message({
            "role": "system",
            "content": f"ESCALATION L{level}: {reason} | Trigger: {message[:200]}",
            "intent": "escalation",
            "ai_tier": 0,
        })
        logger.warning(f"🚨 Escalation logged: L{level} for {customer_id}")
    except Exception as e:
        logger.error(f"❌ Escalation log failed: {e}")


# ═══════════════════════════════════════════════════════════════
# SYNKDR DASHBOARD (ADMIN SETTINGS)
# ═══════════════════════════════════════════════════════════════

async def get_bot_setting(key: str) -> Optional[str]:
    """Retrieve a setting value from bot_settings table."""
    client = get_supabase()
    if not client:
        return None

    try:
        result = client.table("bot_settings").select("value").eq("key", key).limit(1).execute()
        return result.data[0]["value"] if result.data else None
    except Exception as e:
        logger.error(f"❌ Failed to fetch bot setting '{key}': {e}")
        return None


async def set_bot_setting(key: str, value: str, description: str = "") -> bool:
    """Insert or update a setting in bot_settings table."""
    client = get_supabase()
    if not client:
        return False

    try:
        data = {
            "key": key,
            "value": value,
            "updated_at": datetime.now(timezone.utc).isoformat()
        }
        if description:
            data["description"] = description
            
        result = client.table("bot_settings").upsert(data, on_conflict="key").execute()
        return bool(result.data)
    except Exception as e:
        logger.error(f"❌ Failed to save bot setting '{key}': {e}")
        return False


# ═══════════════════════════════════════════════════════════════
# ANALYTICS PERSISTENCE
# ═══════════════════════════════════════════════════════════════

async def save_analytics_snapshot(row: dict) -> bool:
    """Save a daily analytics snapshot to analytics_daily table."""
    client = get_supabase()
    if not client:
        return False

    try:
        result = client.table("analytics_daily").upsert(
            row, on_conflict="date"
        ).execute()
        return bool(result.data)
    except Exception as e:
        logger.error(f"❌ Analytics save failed: {e}")
        return False


async def get_analytics_range(days: int = 7) -> list:
    """Get analytics data for the last N days."""
    client = get_supabase()
    if not client:
        return []

    try:
        from_date = (datetime.now(timezone.utc) - __import__('datetime').timedelta(days=days)).strftime("%Y-%m-%d")
        result = client.table("analytics_daily").select("*").gte(
            "date", from_date
        ).order("date", desc=True).execute()
        return result.data or []
    except Exception as e:
        logger.error(f"❌ Analytics fetch failed: {e}")
        return []


# ═══════════════════════════════════════════════════════════════
# STALE CONVERSATION CLEANUP
# ═══════════════════════════════════════════════════════════════

async def close_stale_conversations(hours: int = 24) -> int:
    """Close conversations with no activity in the last N hours."""
    client = get_supabase()
    if not client:
        return 0

    try:
        cutoff = (datetime.now(timezone.utc) - __import__('datetime').timedelta(hours=hours)).isoformat()
        result = client.table("conversations").update(
            {"state": "closed", "status": "lost"}
        ).eq("state", "active").lt("last_message_at", cutoff).execute()
        count = len(result.data) if result.data else 0
        if count > 0:
            logger.info(f"🧹 Closed {count} stale conversations (>{hours}h inactive)")
        return count
    except Exception as e:
        logger.error(f"❌ Stale conversation cleanup failed: {e}")
        return 0


# ═══════════════════════════════════════════════════════════════
# CONVERSATION MONTHLY COUNTS (Plan Limits)
# ═══════════════════════════════════════════════════════════════

async def get_monthly_conversation_count() -> int:
    """Count conversations started this month (for plan limit enforcement)."""
    client = get_supabase()
    if not client:
        return 0

    try:
        first_of_month = datetime.now(timezone.utc).replace(day=1, hour=0, minute=0, second=0).isoformat()
        result = client.table("conversations").select("id", count="exact").gte(
            "started_at", first_of_month
        ).limit(1).execute()
        return result.count if hasattr(result, "count") and result.count else 0
    except Exception as e:
        logger.error(f"❌ Monthly count failed: {e}")
        return 0


# ═══════════════════════════════════════════════════════════════
# ALL BOT SETTINGS (bulk load for admin panel)
# ═══════════════════════════════════════════════════════════════

async def get_all_bot_settings() -> dict:
    """Get all bot settings as a key→value dict."""
    client = get_supabase()
    if not client:
        return {}

    try:
        result = client.table("bot_settings").select("key, value").execute()
        return {row["key"]: row["value"] for row in (result.data or [])}
    except Exception as e:
        logger.error(f"❌ Failed to fetch all bot settings: {e}")
        return {}


# ═══════════════════════════════════════════════════════════════
# ABANDONED CART OPERATIONS
# ═══════════════════════════════════════════════════════════════

async def save_abandoned_checkout(checkout: dict) -> Optional[dict]:
    """Save a Shopify abandoned checkout for follow-up."""
    client = get_supabase()
    if not client:
        return None

    try:
        result = client.table("abandoned_carts").upsert(
            checkout, on_conflict="shopify_checkout_id"
        ).execute()
        return result.data[0] if result.data else None
    except Exception as e:
        logger.error(f"❌ Abandoned cart save failed: {e}")
        return None


async def get_pending_abandoned_carts(min_age_minutes: int = 30, max_age_hours: int = 24) -> list:
    """
    Get abandoned carts that are ready for follow-up.
    - At least min_age_minutes old (give customer time to complete)
    - Less than max_age_hours old (don't message too late)
    - Not yet recovered or followed up
    """
    client = get_supabase()
    if not client:
        return []

    try:
        from datetime import timedelta
        now = datetime.now(timezone.utc)
        min_time = (now - timedelta(hours=max_age_hours)).isoformat()
        max_time = (now - timedelta(minutes=min_age_minutes)).isoformat()

        result = (
            client.table("abandoned_carts")
            .select("*")
            .eq("status", "abandoned")
            .lt("followup_count", 3)
            .gte("created_at", min_time)
            .lte("created_at", max_time)
            .order("created_at")
            .limit(50)
            .execute()
        )
        return result.data or []
    except Exception as e:
        logger.error(f"❌ Abandoned carts fetch failed: {e}")
        return []


async def mark_cart_followed_up(cart_id: str, followup_count: int) -> bool:
    """Update a cart's follow-up count and last follow-up time."""
    client = get_supabase()
    if not client:
        return False

    try:
        client.table("abandoned_carts").update({
            "followup_count": followup_count,
            "last_followup_at": datetime.now(timezone.utc).isoformat(),
        }).eq("id", cart_id).execute()
        return True
    except Exception as e:
        logger.error(f"❌ Cart follow-up update failed: {e}")
        return False


async def mark_cart_recovered(shopify_checkout_id: str) -> bool:
    """Mark a cart as recovered (customer completed purchase)."""
    client = get_supabase()
    if not client:
        return False

    try:
        client.table("abandoned_carts").update({
            "status": "recovered",
        }).eq("shopify_checkout_id", shopify_checkout_id).execute()
        return True
    except Exception as e:
        logger.error(f"❌ Cart recovery update failed: {e}")
        return False


# ═══════════════════════════════════════════════════════════════
# COD ORDER LIFECYCLE (sofia_cod_orders)
# ═══════════════════════════════════════════════════════════════

async def save_cod_order(order: dict) -> Optional[dict]:
    """Persist a COD order for lifecycle follow-ups (idempotent on order_id)."""
    client = get_supabase()
    if not client:
        return None
    try:
        result = client.table("sofia_cod_orders").upsert(
            order, on_conflict="order_id"
        ).execute()
        return result.data[0] if result.data else None
    except Exception as e:
        logger.error(f"❌ COD order save failed: {e}")
        return None


async def get_active_cod_orders(max_age_hours: int = 240) -> list:
    """Get active COD orders that may be due for a lifecycle follow-up."""
    client = get_supabase()
    if not client:
        return []
    try:
        from datetime import timedelta
        min_time = (datetime.now(timezone.utc) - timedelta(hours=max_age_hours)).isoformat()
        result = (
            client.table("sofia_cod_orders")
            .select("*")
            .eq("status", "active")
            .gte("created_at", min_time)
            .order("created_at")
            .limit(100)
            .execute()
        )
        return result.data or []
    except Exception as e:
        logger.error(f"❌ COD orders fetch failed: {e}")
        return []


async def get_cod_order_by_phone(phone: str) -> Optional[dict]:
    """Find the most recent COD order for a phone (button taps arrive by phone)."""
    client = get_supabase()
    if not client:
        return None
    try:
        result = (
            client.table("sofia_cod_orders")
            .select("*")
            .eq("phone", phone)
            .order("created_at", desc=True)
            .limit(1)
            .execute()
        )
        return result.data[0] if result.data else None
    except Exception as e:
        logger.error(f"❌ COD order by phone failed: {e}")
        return None


async def advance_cod_stage(order_id: str, stage: int) -> bool:
    """Record that a lifecycle template was sent (advance the stage)."""
    client = get_supabase()
    if not client:
        return False
    try:
        client.table("sofia_cod_orders").update({
            "stage": stage,
            "last_stage_at": datetime.now(timezone.utc).isoformat(),
        }).eq("order_id", order_id).execute()
        return True
    except Exception as e:
        logger.error(f"❌ COD stage update failed: {e}")
        return False


async def set_cod_order_status(order_id: str, status: str, confirmed: Optional[bool] = None) -> bool:
    """Update a COD order's status (received / not_received / rescheduled / done)."""
    client = get_supabase()
    if not client:
        return False
    try:
        update = {"status": status}
        if confirmed is not None:
            update["confirmed"] = confirmed
        client.table("sofia_cod_orders").update(update).eq("order_id", order_id).execute()
        return True
    except Exception as e:
        logger.error(f"❌ COD status update failed: {e}")
        return False


# ═══════════════════════════════════════════════════════════════
# IN-CHAT CHECKOUT ORDERS
# ═══════════════════════════════════════════════════════════════

async def save_chat_order(order_data: dict) -> Optional[dict]:
    """
    Save an order created through in-chat checkout.
    Tracks the full lifecycle: draft → completed.
    """
    client = get_supabase()
    if not client:
        return None

    try:
        result = client.table("chat_orders").insert(order_data).execute()
        return result.data[0] if result.data else None
    except Exception as e:
        logger.error(f"❌ Chat order save failed: {e}")
        return None


async def update_chat_order_status(draft_order_id: str, status: str, shopify_order_id: str = "") -> bool:
    """Update a chat order's status (e.g., draft → completed)."""
    client = get_supabase()
    if not client:
        return False

    try:
        update = {"status": status}
        if shopify_order_id:
            update["shopify_order_id"] = shopify_order_id
        client.table("chat_orders").update(update).eq(
            "draft_order_id", draft_order_id
        ).execute()
        return True
    except Exception as e:
        logger.error(f"❌ Chat order status update failed: {e}")
        return False


# ═══════════════════════════════════════════════════════════════
# CUSTOMER PROFILES (Memory)
# ═══════════════════════════════════════════════════════════════

async def get_customer_profile(phone: str) -> Optional[dict]:
    """Load a customer's persistent profile by phone."""
    client = get_supabase()
    if not client:
        return None
    try:
        result = client.table("customer_profiles").select("*").eq(
            "phone", phone
        ).limit(1).execute()
        return result.data[0] if result.data else None
    except Exception as e:
        logger.error(f"❌ Customer profile lookup failed: {e}")
        return None


async def upsert_customer_profile(phone: str, updates: dict) -> Optional[dict]:
    """Create or update a customer profile. Always sets updated_at and last_seen."""
    client = get_supabase()
    if not client:
        return None
    try:
        from datetime import datetime, timezone
        now = datetime.now(timezone.utc).isoformat()
        data = {"phone": phone, "updated_at": now, "last_seen": now, **updates}
        result = client.table("customer_profiles").upsert(
            data, on_conflict="phone"
        ).execute()
        return result.data[0] if result.data else None
    except Exception as e:
        logger.error(f"❌ Customer profile upsert failed: {e}")
        return None


# ═══════════════════════════════════════════════════════════════
# PRICE WATCH (Price Drop Alerts)
# ═══════════════════════════════════════════════════════════════

async def save_price_watch(
    phone: str,
    product_shopify_id: str,
    product_name: str,
    price_at_watch: float,
) -> Optional[dict]:
    """Save a price watch — customer wants to be notified if this product drops."""
    client = get_supabase()
    if not client:
        return None
    try:
        data = {
            "phone": phone,
            "product_shopify_id": product_shopify_id,
            "product_name": product_name,
            "price_at_watch": price_at_watch,
            "notified": False,
        }
        result = client.table("price_watches").upsert(
            data, on_conflict="phone,product_shopify_id"
        ).execute()
        return result.data[0] if result.data else None
    except Exception as e:
        logger.error(f"❌ Price watch save failed: {e}")
        return None


async def get_active_price_watches() -> list:
    """Get all price watches that haven't been notified yet."""
    client = get_supabase()
    if not client:
        return []
    try:
        result = client.table("price_watches").select("*").eq(
            "notified", False
        ).execute()
        return result.data or []
    except Exception as e:
        logger.error(f"❌ Price watches fetch failed: {e}")
        return []


async def mark_price_watch_notified(watch_id: str) -> bool:
    """Mark a price watch as notified (alert sent)."""
    client = get_supabase()
    if not client:
        return False
    try:
        client.table("price_watches").update(
            {"notified": True}
        ).eq("id", watch_id).execute()
        return True
    except Exception as e:
        logger.error(f"❌ Price watch update failed: {e}")
        return False


async def delete_price_watch(phone: str, product_shopify_id: str) -> bool:
    """Remove a price watch (customer bought it or unsubscribed)."""
    client = get_supabase()
    if not client:
        return False
    try:
        client.table("price_watches").delete().eq(
            "phone", phone
        ).eq(
            "product_shopify_id", product_shopify_id
        ).execute()
        return True
    except Exception as e:
        logger.error(f"❌ Price watch delete failed: {e}")
        return False


async def get_product_prices_from_db() -> dict:
    """Get current product prices from DB (before sync overwrites them).
    Returns dict of {shopify_id: price_min}."""
    client = get_supabase()
    if not client:
        return {}
    try:
        result = client.table("products").select("shopify_id,price_min").execute()
        return {p["shopify_id"]: p["price_min"] for p in (result.data or [])}
    except Exception as e:
        logger.error(f"❌ Product prices fetch failed: {e}")
        return {}


# ═══════════════════════════════════════════════════════════════
# RE-ENGAGEMENT (Ghosted / Didn't Buy)
# ═══════════════════════════════════════════════════════════════

async def find_ghosted_conversations(min_hours: int = 24, max_hours: int = 72) -> list:
    """
    Find closed conversations where the customer stopped responding.
    Returns list of dicts with: id, phone, metadata, last_message_at.
    Joins conversations → customers to get phone.
    """
    client = get_supabase()
    if not client:
        return []
    try:
        from datetime import timedelta
        now = datetime.now(timezone.utc)
        min_time = (now - timedelta(hours=max_hours)).isoformat()
        max_time = (now - timedelta(hours=min_hours)).isoformat()

        result = (
            client.table("conversations")
            .select("id, customer_id, metadata, last_message_at")
            .eq("state", "closed")
            .eq("status", "lost")
            .gte("last_message_at", min_time)
            .lte("last_message_at", max_time)
            .limit(100)
            .execute()
        )
        if not result.data:
            return []

        # Resolve customer_id UUIDs to phone numbers
        conversations = result.data
        cust_ids = list({c["customer_id"] for c in conversations})
        phone_map = {}
        for cid in cust_ids:
            cust = client.table("customers").select("id, phone").eq("id", cid).limit(1).execute()
            if cust.data:
                phone_map[cid] = cust.data[0]["phone"]

        enriched = []
        for conv in conversations:
            phone = phone_map.get(conv["customer_id"], "")
            if phone:
                enriched.append({
                    "id": conv["id"],
                    "phone": phone,
                    "metadata": conv.get("metadata", {}),
                    "last_message_at": conv["last_message_at"],
                })
        return enriched
    except Exception as e:
        logger.error(f"❌ Ghosted conversations fetch failed: {e}")
        return []


async def get_recent_order_phones(days: int = 7) -> set:
    """Get phones of customers who placed a chat order recently."""
    client = get_supabase()
    if not client:
        return set()
    try:
        from datetime import timedelta
        cutoff = (datetime.now(timezone.utc) - timedelta(days=days)).isoformat()
        result = (
            client.table("chat_orders")
            .select("customer_phone")
            .gte("created_at", cutoff)
            .execute()
        )
        return {r["customer_phone"] for r in (result.data or [])}
    except Exception as e:
        logger.error(f"❌ Recent orders fetch failed: {e}")
        return set()


async def save_reengagement_log(
    phone: str, reengagement_type: str, product_name: str = "", conversation_id: str = ""
) -> Optional[dict]:
    """Log a re-engagement attempt to avoid spamming."""
    client = get_supabase()
    if not client:
        return None
    try:
        data = {
            "phone": phone,
            "type": reengagement_type,
            "product_name": product_name,
            "conversation_id": conversation_id,
        }
        result = client.table("reengagement_log").insert(data).execute()
        return result.data[0] if result.data else None
    except Exception as e:
        logger.error(f"❌ Reengagement log save failed: {e}")
        return None


async def get_recently_reengaged_phones(days: int = 7) -> set:
    """Get phones that were already re-engaged in the last N days."""
    client = get_supabase()
    if not client:
        return set()
    try:
        from datetime import timedelta
        cutoff = (datetime.now(timezone.utc) - timedelta(days=days)).isoformat()
        result = (
            client.table("reengagement_log")
            .select("phone")
            .gte("created_at", cutoff)
            .execute()
        )
        return {r["phone"] for r in (result.data or [])}
    except Exception as e:
        logger.error(f"❌ Reengagement log fetch failed: {e}")
        return set()


# ═══════════════════════════════════════════════════════════════
# WISHLIST — Out-of-stock demand tracking
# ═══════════════════════════════════════════════════════════════

async def save_wishlist_item(
    customer_id: str,
    product_name: str,
    variant_title: str,
    shopify_product_id: str = "",
    channel: str = "webchat",
) -> Optional[dict]:
    """
    Save a customer's interest in an out-of-stock or non-existent variant.
    Used to notify the owner of real demand and to alert customer when restocked.
    """
    client = get_supabase()
    if not client:
        return None
    try:
        data = {
            "customer_id": customer_id,
            "product_name": product_name,
            "variant_title": variant_title,
            "shopify_product_id": shopify_product_id,
            "channel": channel,
            "notified": False,
        }
        result = (
            client.table("customer_wishlist")
            .upsert(data, on_conflict="customer_id,product_name,variant_title")
            .execute()
        )
        return result.data[0] if result.data else None
    except Exception as e:
        logger.error(f"❌ Wishlist save failed: {e}")
        return None


async def get_wishlist_for_variant(product_name: str, variant_title: str) -> list:
    """
    Get all customers waiting for a specific variant.
    Called by restock scheduler when a variant becomes available again.
    """
    client = get_supabase()
    if not client:
        return []
    try:
        result = (
            client.table("customer_wishlist")
            .select("customer_id, channel")
            .eq("product_name", product_name)
            .eq("variant_title", variant_title)
            .eq("notified", False)
            .execute()
        )
        return result.data or []
    except Exception as e:
        logger.error(f"❌ Wishlist fetch failed: {e}")
        return []


async def mark_wishlist_notified(customer_id: str, product_name: str, variant_title: str) -> None:
    """Mark a wishlist entry as notified so we don't spam."""
    client = get_supabase()
    if not client:
        return
    try:
        client.table("customer_wishlist").update({"notified": True}).eq(
            "customer_id", customer_id
        ).eq("product_name", product_name).eq("variant_title", variant_title).execute()
    except Exception as e:
        logger.error(f"❌ Wishlist mark notified failed: {e}")



# ═══════════════════════════════════════════════════════════════
# CRM — sofia_customers table
# ═══════════════════════════════════════════════════════════════

async def track_customer_interaction(
    customer_id: str,
    *,
    name: str = "",
    phone: str = "",
    channel: str = "webchat",
    purchase_intent: bool = False,
    last_interested_product: str = "",
    has_order: bool = False,
    last_order_product: str = "",
) -> None:
    """
    Upsert a customer record after every conversation turn.
    Increments total_messages, updates last_seen and funnel signals.
    Never downgrades purchase_intent or has_order once they are True.
    """
    client = get_supabase()
    if not client:
        return
    try:
        from datetime import datetime, timezone
        now = datetime.now(timezone.utc).isoformat()

        existing = client.table("sofia_customers").select(
            "total_messages,purchase_intent,has_order,channels_used,total_orders"
        ).eq("customer_id", customer_id).limit(1).execute()

        row = existing.data[0] if existing.data else {}

        total_msgs = row.get("total_messages", 0) + 1
        channels = list(set(row.get("channels_used") or []))
        if channel and channel not in channels:
            channels.append(channel)

        data = {
            "customer_id": customer_id,
            "last_seen": now,
            "total_messages": total_msgs,
            "channels_used": channels,
            "updated_at": now,
        }
        if name:
            data["name"] = name
        if phone:
            data["phone"] = phone
        if channel and not row:
            data["channel"] = channel  # first channel — only meaningful on insert
        if purchase_intent:
            data["purchase_intent"] = True
        if last_interested_product:
            data["last_interested_product"] = last_interested_product
        if has_order:
            data["has_order"] = True
            data["total_orders"] = (row.get("total_orders") or 0) + 1
        if last_order_product:
            data["last_order_product"] = last_order_product

        client.table("sofia_customers").upsert(
            data, on_conflict="customer_id"
        ).execute()
    except Exception as e:
        logger.error(f"❌ CRM track failed: {e}")


async def get_all_customers(
    limit: int = 500,
    offset: int = 0,
    channel: str = "",
    has_order: Optional[bool] = None,
    purchase_intent: Optional[bool] = None,
) -> list:
    """List all customers, most recent first, with optional filters."""
    client = get_supabase()
    if not client:
        return []
    try:
        q = client.table("sofia_customers").select("*").order(
            "last_seen", desc=True
        ).range(offset, offset + limit - 1)
        if channel:
            q = q.contains("channels_used", [channel])
        if has_order is not None:
            q = q.eq("has_order", has_order)
        if purchase_intent is not None:
            q = q.eq("purchase_intent", purchase_intent)
        return q.execute().data or []
    except Exception as e:
        logger.error(f"❌ CRM get_all_customers failed: {e}")
        return []


async def get_abandoned_carts(limit: int = 200) -> list:
    """Customers who showed purchase intent but never placed an order via chat."""
    client = get_supabase()
    if not client:
        return []
    try:
        return (
            client.table("sofia_customers")
            .select("*")
            .eq("purchase_intent", True)
            .eq("has_order", False)
            .order("last_seen", desc=True)
            .limit(limit)
            .execute()
            .data or []
        )
    except Exception as e:
        logger.error(f"❌ CRM get_abandoned_carts failed: {e}")
        return []


async def get_all_wishlist_items(limit: int = 500) -> list:
    """Return all wishlist entries (OOS demand), most recent first."""
    client = get_supabase()
    if not client:
        return []
    try:
        return (
            client.table("customer_wishlist")
            .select("*")
            .order("created_at", desc=True)
            .limit(limit)
            .execute()
            .data or []
        )
    except Exception as e:
        logger.error(f"❌ Wishlist get_all failed: {e}")
        return []
