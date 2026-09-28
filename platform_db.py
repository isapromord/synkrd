"""
SynkDR Platform — Database operations for super admin.
Manages tenants, plans, platform admins, and cross-tenant stats.
"""
import os
import logging
from typing import Optional
from datetime import datetime, timezone, date

from supabase import create_client

logger = logging.getLogger("synkdr.platform_db")

_platform_client = None


def get_platform_client():
    """Get or create the platform Supabase client."""
    global _platform_client
    if _platform_client:
        return _platform_client

    url = os.getenv("SUPABASE_URL")
    key = os.getenv("SUPABASE_KEY")
    if not url or not key:
        logger.error("❌ Platform DB: missing SUPABASE_URL or SUPABASE_KEY")
        return None

    try:
        _platform_client = create_client(url, key)
        logger.info("✅ Platform DB client initialized")
        return _platform_client
    except Exception as e:
        logger.error(f"❌ Platform DB init failed: {e}")
        return None


# ═══════════════════════════════════════════════════════════════
# SUPER ADMIN AUTH
# ═══════════════════════════════════════════════════════════════

async def verify_platform_admin(auth_user_id: str) -> Optional[dict]:
    """Check if a Supabase Auth user is a registered platform admin."""
    client = get_platform_client()
    if not client:
        return None
    try:
        res = client.table("platform_admins").select("*").eq(
            "auth_user_id", auth_user_id
        ).eq("is_active", True).limit(1).execute()
        return res.data[0] if res.data else None
    except Exception as e:
        logger.error(f"❌ Admin verification failed: {e}")
        return None


async def update_admin_last_login(admin_id: str):
    """Update last_login timestamp for an admin."""
    client = get_platform_client()
    if not client:
        return
    try:
        client.table("platform_admins").update({
            "last_login": datetime.now(timezone.utc).isoformat()
        }).eq("id", admin_id).execute()
    except Exception:
        pass


# ═══════════════════════════════════════════════════════════════
# TENANT CRUD
# ═══════════════════════════════════════════════════════════════

async def list_tenants(status: str = None, limit: int = 50) -> list:
    """List all tenants, optionally filtered by status."""
    client = get_platform_client()
    if not client:
        return []
    try:
        q = client.table("tenants").select(
            "*, plan:tenant_plans(name, display_name, max_conversations_mo, price_usd)"
        ).order("created_at", desc=True).limit(limit)
        if status:
            q = q.eq("status", status)
        res = q.execute()
        return res.data or []
    except Exception as e:
        logger.error(f"❌ List tenants failed: {e}")
        return []


async def get_tenant(tenant_id: str) -> Optional[dict]:
    """Get a single tenant by ID."""
    client = get_platform_client()
    if not client:
        return None
    try:
        res = client.table("tenants").select(
            "*, plan:tenant_plans(name, display_name, max_conversations_mo, price_usd, features)"
        ).eq("id", tenant_id).limit(1).execute()
        return res.data[0] if res.data else None
    except Exception as e:
        logger.error(f"❌ Get tenant failed: {e}")
        return None


async def create_tenant(data: dict) -> Optional[dict]:
    """Create a new tenant."""
    client = get_platform_client()
    if not client:
        return None
    try:
        res = client.table("tenants").insert(data).execute()
        return res.data[0] if res.data else None
    except Exception as e:
        logger.error(f"❌ Create tenant failed: {e}")
        return None


async def update_tenant(tenant_id: str, data: dict) -> Optional[dict]:
    """Update a tenant."""
    client = get_platform_client()
    if not client:
        return None
    try:
        res = client.table("tenants").update(data).eq("id", tenant_id).execute()
        return res.data[0] if res.data else None
    except Exception as e:
        logger.error(f"❌ Update tenant failed: {e}")
        return None


async def delete_tenant(tenant_id: str) -> bool:
    """Soft-delete a tenant (set status to 'deleted')."""
    result = await update_tenant(tenant_id, {"status": "deleted"})
    return result is not None


# ═══════════════════════════════════════════════════════════════
# PLANS
# ═══════════════════════════════════════════════════════════════

async def list_plans(include_inactive: bool = False) -> list:
    """List all available plans."""
    client = get_platform_client()
    if not client:
        return []
    try:
        q = client.table("tenant_plans").select("*").order("price_usd")
        if not include_inactive:
            q = q.eq("is_active", True)
        res = q.execute()
        return res.data or []
    except Exception as e:
        logger.error(f"❌ List plans failed: {e}")
        return []


async def create_plan(data: dict) -> Optional[dict]:
    """Create a new plan."""
    client = get_platform_client()
    if not client:
        return None
    try:
        res = client.table("tenant_plans").insert(data).execute()
        return res.data[0] if res.data else None
    except Exception as e:
        logger.error(f"❌ Create plan failed: {e}")
        return None


async def update_plan(plan_id: str, data: dict) -> Optional[dict]:
    """Update a plan."""
    client = get_platform_client()
    if not client:
        return None
    try:
        res = client.table("tenant_plans").update(data).eq("id", plan_id).execute()
        return res.data[0] if res.data else None
    except Exception as e:
        logger.error(f"❌ Update plan failed: {e}")
        return None


# ═══════════════════════════════════════════════════════════════
# PLATFORM LOGS
# ═══════════════════════════════════════════════════════════════

async def log_action(admin_id: str, action: str, tenant_id: str = None, details: dict = None):
    """Log a platform admin action."""
    client = get_platform_client()
    if not client:
        return
    try:
        client.table("platform_logs").insert({
            "admin_id": admin_id,
            "tenant_id": tenant_id,
            "action": action,
            "details": details or {},
        }).execute()
    except Exception as e:
        logger.error(f"❌ Log action failed: {e}")


async def get_logs(limit: int = 100, tenant_id: str = None) -> list:
    """Get recent platform activity logs."""
    client = get_platform_client()
    if not client:
        return []
    try:
        q = client.table("platform_logs").select(
            "*, admin:platform_admins(name, email), tenant:tenants(name, slug)"
        ).order("created_at", desc=True).limit(limit)
        if tenant_id:
            q = q.eq("tenant_id", tenant_id)
        res = q.execute()
        return res.data or []
    except Exception as e:
        logger.error(f"❌ Get logs failed: {e}")
        return []


# ═══════════════════════════════════════════════════════════════
# CROSS-TENANT STATS
# ═══════════════════════════════════════════════════════════════

async def get_tenant_live_stats(tenant: dict) -> dict:
    """Connect to a tenant's Supabase and pull live stats."""
    try:
        tenant_client = create_client(tenant["supabase_url"], tenant["supabase_anon_key"])

        # Conversations
        convs = tenant_client.table("conversations").select(
            "id", count="exact"
        ).limit(1).execute()
        total_convs = convs.count if hasattr(convs, "count") and convs.count else 0

        active_convs = tenant_client.table("conversations").select(
            "id", count="exact"
        ).eq("state", "active").limit(1).execute()
        active_count = active_convs.count if hasattr(active_convs, "count") and active_convs.count else 0

        # Messages
        msgs = tenant_client.table("messages").select(
            "id", count="exact"
        ).limit(1).execute()
        total_msgs = msgs.count if hasattr(msgs, "count") and msgs.count else 0

        # Products
        prods = tenant_client.table("products").select(
            "id", count="exact"
        ).limit(1).execute()
        total_products = prods.count if hasattr(prods, "count") and prods.count else 0

        return {
            "total_conversations": total_convs,
            "active_conversations": active_count,
            "total_messages": total_msgs,
            "total_products": total_products,
            "status": "online",
        }
    except Exception as e:
        logger.error(f"❌ Tenant stats failed for {tenant.get('name')}: {e}")
        return {
            "total_conversations": 0,
            "active_conversations": 0,
            "total_messages": 0,
            "total_products": 0,
            "status": "error",
            "error": str(e),
        }


async def get_platform_overview() -> dict:
    """Get aggregate stats across all tenants."""
    tenants = await list_tenants()
    active_tenants = [t for t in tenants if t["status"] == "active"]
    setup_tenants = [t for t in tenants if t["status"] == "setup"]
    suspended = [t for t in tenants if t["status"] == "suspended"]

    total_conversations = 0
    total_messages = 0
    total_products = 0
    online_count = 0

    for t in active_tenants:
        stats = await get_tenant_live_stats(t)
        total_conversations += stats["total_conversations"]
        total_messages += stats["total_messages"]
        total_products += stats["total_products"]
        if stats["status"] == "online":
            online_count += 1

    return {
        "total_tenants": len(tenants),
        "active_tenants": len(active_tenants),
        "setup_tenants": len(setup_tenants),
        "suspended_tenants": len(suspended),
        "online_tenants": online_count,
        "total_conversations": total_conversations,
        "total_messages": total_messages,
        "total_products": total_products,
    }


async def save_tenant_stats_snapshot(tenant_id: str, stats: dict):
    """Save a daily stats snapshot for a tenant."""
    client = get_platform_client()
    if not client:
        return
    try:
        today = date.today().isoformat()
        client.table("tenant_stats").upsert({
            "tenant_id": tenant_id,
            "date": today,
            "conversations_count": stats.get("total_conversations", 0),
            "messages_count": stats.get("total_messages", 0),
            "products_synced": stats.get("total_products", 0),
        }, on_conflict="tenant_id,date").execute()
    except Exception as e:
        logger.error(f"❌ Stats snapshot failed: {e}")


# ═══════════════════════════════════════════════════════════════
# STOREFRONT TEMPLATES REGISTRY (SynkRD Themes)
# ═══════════════════════════════════════════════════════════════

STOREFRONT_TEMPLATES = [
    {
        "id": "apex-cod",
        "name": "Apex COD ⚡",
        "badge": "⭐ Recomendado • Alta Conversión RD",
        "category": "High-Converting COD",
        "description": "Plantilla insignia optimizada para venta por impulso con Pago Contra Entrega en República Dominicana. Incluye Stories móviles, Split Hero con oferta spotlight, Bento Grid, UGC Reviews, Sofía AI Chat integrado y escudo anti-robo de imágenes.",
        "preview_url": "https://www.trendyrd.com",
        "thumbnail": "https://www.trendyrd.com/static/og-preview.png",
        "is_active": True,
        "features": [
            "Stories Circulares Móviles",
            "Split Hero con Spotlight Deal",
            "Bento Grid de Categorías",
            "Checkout COD de 1 Clic con WhatsApp",
            "Sofía AI Asistente de Ventas Integrado",
            "Escudo Anti-Copia / Anti-Robo de Imágenes",
            "Notificaciones Flotantes de Ventas en Vivo"
        ],
        "default_config": {
            "primary_color": "#002d4b",
            "accent_color": "#ed1515",
            "currency": "DOP",
            "currency_symbol": "RD$"
        }
    },
    {
        "id": "classic-shrine",
        "name": "Classic Shrine 🛍️",
        "badge": "Catálogo Estándar",
        "category": "E-Commerce Clásico",
        "description": "Diseño limpio y equilibrado para tiendas con catálogos amplios y navegación tradicional.",
        "preview_url": "https://www.trendyrd.com/?theme=shrine",
        "thumbnail": "https://images.unsplash.com/photo-1555529669-e69e7aa0ba9a?w=800",
        "is_active": True,
        "features": [
            "Banner Hero Promocional",
            "Grid de Productos 4 Columnas",
            "Filtros de Colecciones",
            "Checkout Express"
        ],
        "default_config": {
            "primary_color": "#002d4b",
            "accent_color": "#ed1515",
            "currency": "DOP",
            "currency_symbol": "RD$"
        }
    }
]


def list_storefront_templates() -> list:
    """List available storefront templates for new stores."""
    return [t for t in STOREFRONT_TEMPLATES if t.get("is_active", True)]


def get_storefront_template(template_id: str) -> Optional[dict]:
    """Get template metadata by ID."""
    for t in STOREFRONT_TEMPLATES:
        if t["id"] == template_id:
            return t
    return None

