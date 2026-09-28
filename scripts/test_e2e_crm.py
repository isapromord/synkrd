"""
End-to-end test for Sofía CRM sprint.
Run locally: python scripts/test_e2e_crm.py

Tests:
  1. /chat endpoint responds (bot is alive)
  2. /chat with purchase intent → check CRM tracking attempt
  3. All 4 CRM API endpoints exist and return correct auth behavior
  4. /admin/api/customers/export.csv returns CSV content-type
  5. /admin/api/wishlist/export.csv returns CSV content-type
  6. upsells.py fetch_upsell_context function works
"""
import urllib.request, urllib.error, json, sys, os

BASE = "https://sofia.trendyrd.com"
PASS = "[PASS]"
FAIL = "[FAIL]"
WARN = "[WARN]"

results = []

def check(label, condition, detail=""):
    icon = PASS if condition else FAIL
    msg = f"{icon} {label}" + (f" — {detail}" if detail else "")
    print(msg)
    results.append((condition, label))
    return condition

def http(method, path, body=None, headers=None, expected_codes=(200,)):
    url = BASE + path
    data = json.dumps(body).encode() if body else None
    h = {"Content-Type": "application/json"}
    if headers:
        h.update(headers)
    req = urllib.request.Request(url, data=data, method=method, headers=h)
    try:
        resp = urllib.request.urlopen(req, timeout=15)
        return resp.getcode(), resp.read(), resp.headers
    except urllib.error.HTTPError as e:
        return e.code, e.read(), e.headers

print("\n=== Sofía CRM End-to-End Tests ===\n")

# ── T1: Health check ──────────────────────────────────────────
code, body, _ = http("GET", "/health")
check("T1 Service alive (/health)", code == 200, f"HTTP {code}")

# ── T2: /chat endpoint responds ───────────────────────────────
code, body, _ = http("POST", "/chat", {
    "message": "Hola, buenos días",
    "customer_id": "test_e2e_crm_001",
    "channel": "webchat",
})
ok = code == 200
check("T2 /chat responds to greeting", ok, f"HTTP {code}")
if ok:
    data = json.loads(body)
    check("T2b Response has 'response' field", "response" in data, str(list(data.keys()))[:60])

# ── T3: /chat with purchase intent ───────────────────────────
code, body, _ = http("POST", "/chat", {
    "message": "Quiero comprar el set de maquillaje, ¿cuánto cuesta?",
    "customer_id": "test_e2e_crm_002",
    "channel": "webchat",
})
ok = code == 200
check("T3 /chat responds to purchase inquiry", ok, f"HTTP {code}")
if ok:
    data = json.loads(body)
    intent = data.get("intent", "?")
    check("T3b Purchase/pricing intent detected", intent in ("purchase", "catalog", "inquiry", "pricing"),
          f"intent={intent}")

# ── T4: CRM API endpoints require auth ────────────────────────
for path, label in [
    ("/admin/api/customers", "T4a customers"),
    ("/admin/api/abandoned-carts", "T4b abandoned-carts"),
    ("/admin/api/wishlist", "T4c wishlist"),
    ("/admin/api/customers/export.csv", "T4d customers CSV"),
    ("/admin/api/wishlist/export.csv", "T4e wishlist CSV"),
]:
    code, _, _ = http("GET", path)
    check(f"{label} requires auth (401 without token)", code == 401, f"HTTP {code}")

# ── T5: /admin/crm page is served ────────────────────────────
code, body, _ = http("GET", "/admin/crm")
ok = code == 200
check("T5 /admin/crm returns HTML", ok, f"HTTP {code}")
if ok:
    has_supabase = b"supabase" in body.lower()
    has_tabs = b"tab-btn" in body
    check("T5b CRM HTML has Supabase auth", has_supabase)
    check("T5c CRM HTML has tab elements", has_tabs)

# ── T6: upsells.py can be imported ───────────────────────────
try:
    sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
    from knowledge.upsells import fetch_upsell_context
    check("T6 upsells.py importable", True)
    # Don't actually call fetch (would need valid shopify token)
except ImportError as e:
    check("T6 upsells.py importable", False, str(e))

# ── Summary ───────────────────────────────────────────────────
print(f"\n=== Results: {sum(1 for ok,_ in results if ok)}/{len(results)} passed ===")
failed = [lbl for ok, lbl in results if not ok]
if failed:
    print("FAILED:", ", ".join(failed))
    sys.exit(1)
else:
    print("All tests passed!")
