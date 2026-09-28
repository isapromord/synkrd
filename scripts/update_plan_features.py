"""
One-time script: Update tenant_plans features in Supabase
with the full 21-feature set for each plan tier.

Run once, then delete.
"""
import os
import json
from dotenv import load_dotenv
from supabase import create_client

load_dotenv()

url = os.getenv("SUPABASE_URL")
key = os.getenv("SUPABASE_KEY")

if not url or not key:
    print("❌ Missing SUPABASE_URL or SUPABASE_KEY in .env")
    exit(1)

client = create_client(url, key)

# ── Full 21-feature definitions per plan tier ──
STARTER_FEATURES = {
    # Channels
    "webchat": True,
    "whatsapp": True,
    "voice": False,
    # Core AI
    "ai_conversational": True,
    "smart_catalog": True,
    "custom_persona": False,
    "spanish_localization": True,
    # Sales
    "in_chat_checkout": False,
    "smart_upsell": False,
    "abandoned_cart_recovery": False,
    "price_drop_alerts": False,
    # Engagement
    "customer_memory": False,
    "visual_search": False,
    "reengagement": False,
    # Operations
    "analytics": True,
    "escalation": True,
    "shipping_notifications": False,
    "discount_codes": False,
    # Platform
    "api_access": False,
    "custom_domain": False,
    "dedicated_support": False,
}

PRO_FEATURES = {
    # Channels
    "webchat": True,
    "whatsapp": True,
    "voice": True,
    # Core AI
    "ai_conversational": True,
    "smart_catalog": True,
    "custom_persona": True,
    "spanish_localization": True,
    # Sales
    "in_chat_checkout": True,
    "smart_upsell": True,
    "abandoned_cart_recovery": False,
    "price_drop_alerts": False,
    # Engagement
    "customer_memory": True,
    "visual_search": False,
    "reengagement": True,
    # Operations
    "analytics": True,
    "escalation": True,
    "shipping_notifications": True,
    "discount_codes": True,
    # Platform
    "api_access": False,
    "custom_domain": False,
    "dedicated_support": False,
}

ENTERPRISE_FEATURES = {
    # Channels
    "webchat": True,
    "whatsapp": True,
    "voice": True,
    # Core AI
    "ai_conversational": True,
    "smart_catalog": True,
    "custom_persona": True,
    "spanish_localization": True,
    # Sales
    "in_chat_checkout": True,
    "smart_upsell": True,
    "abandoned_cart_recovery": True,
    "price_drop_alerts": True,
    # Engagement
    "customer_memory": True,
    "visual_search": True,
    "reengagement": True,
    # Operations
    "analytics": True,
    "escalation": True,
    "shipping_notifications": True,
    "discount_codes": True,
    # Platform
    "api_access": True,
    "custom_domain": True,
    "dedicated_support": True,
}

PLAN_MAP = {
    "starter": STARTER_FEATURES,
    "pro": PRO_FEATURES,
    "enterprise": ENTERPRISE_FEATURES,
}

# ── Fetch existing plans ──
plans = client.table("tenant_plans").select("id, name, features").execute()

if not plans.data:
    print("❌ No plans found in tenant_plans table")
    exit(1)

print(f"Found {len(plans.data)} plans:")
for plan in plans.data:
    name = plan["name"]
    plan_id = plan["id"]
    old_features = plan.get("features", {})
    
    if name in PLAN_MAP:
        new_features = PLAN_MAP[name]
        # Update
        res = client.table("tenant_plans").update(
            {"features": new_features}
        ).eq("id", plan_id).execute()
        
        old_count = sum(1 for v in old_features.values() if v)
        new_count = sum(1 for v in new_features.values() if v)
        print(f"  ✅ {name}: {old_count} → {new_count} features enabled (updated)")
    else:
        print(f"  ⚠️  {name}: no mapping defined, skipped")

# ── Verify ──
print("\n── Verification ──")
plans = client.table("tenant_plans").select("name, features").order("price_usd").execute()
for plan in plans.data:
    features = plan.get("features", {})
    enabled = [k for k, v in features.items() if v]
    disabled = [k for k, v in features.items() if not v]
    print(f"\n{plan['name'].upper()} ({len(enabled)}/{len(features)} enabled):")
    print(f"  ✅ {', '.join(enabled)}")
    print(f"  ❌ {', '.join(disabled)}")

print("\n🎯 Done! Plans updated with full 21-feature sets.")
