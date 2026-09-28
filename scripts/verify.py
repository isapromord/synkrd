"""Quick verification script — tests product scraper and Supabase connection."""
import sys
import os

# Add parent to path
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

print("=" * 50)
print("  SOFIA BOT — VERIFICATION TEST")
print("=" * 50)

# Test 1: Product Scraper
print("\n🔍 TEST 1: Product Scraper (trendyrd.com)")
try:
    from knowledge.scraper import fetch_all_products, build_product_context
    products = fetch_all_products()
    print(f"   ✅ Found {len(products)} products")
    for p in products:
        status = "✅" if p["available"] else "❌"
        print(f"      {status} {p['name']} — RD${p['price_min']:,.0f}")
    print(f"\n   AI Context preview:")
    ctx = build_product_context(products)
    print(f"   {ctx[:300]}...")
    print(f"   Total context length: {len(ctx)} chars")
except Exception as e:
    print(f"   ❌ FAILED: {e}")

# Test 2: Environment Variables
print("\n🔍 TEST 2: Environment Variables")
from dotenv import load_dotenv
load_dotenv()
checks = {
    "SUPABASE_URL": os.getenv("SUPABASE_URL", ""),
    "SUPABASE_KEY": os.getenv("SUPABASE_KEY", "")[:20] + "..." if os.getenv("SUPABASE_KEY") else "",
    "GEMINI_API_KEY": os.getenv("GEMINI_API_KEY", "")[:15] + "..." if os.getenv("GEMINI_API_KEY") else "",
    "AI_TEMPERATURE": os.getenv("AI_TEMPERATURE", "NOT SET"),
    "PORT": os.getenv("PORT", "NOT SET"),
}
for k, v in checks.items():
    status = "✅" if v and v != "NOT SET" else "⚠️"
    print(f"   {status} {k}: {v}")

# Test 3: Supabase Connection
print("\n🔍 TEST 3: Supabase Connection")
try:
    from supabase import create_client
    url = os.getenv("SUPABASE_URL")
    key = os.getenv("SUPABASE_KEY")
    client = create_client(url, key)
    result = client.table("products").select("count", count="exact").execute()
    print(f"   ✅ Connected! Products in DB: {result.count}")
    result2 = client.table("customers").select("count", count="exact").execute()
    print(f"   ✅ Customers in DB: {result2.count}")
except ImportError:
    print("   ⚠️ supabase package not installed (pip install supabase)")
except Exception as e:
    print(f"   ❌ FAILED: {e}")

# Test 4: Required packages
print("\n🔍 TEST 4: Required Packages")
packages = ["fastapi", "uvicorn", "httpx", "supabase", "google.generativeai", "anthropic", "dotenv"]
for pkg in packages:
    try:
        __import__(pkg)
        print(f"   ✅ {pkg}")
    except ImportError:
        print(f"   ❌ {pkg} — MISSING")

print("\n" + "=" * 50)
print("  VERIFICATION COMPLETE")
print("=" * 50)
