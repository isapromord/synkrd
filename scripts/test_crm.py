"""
Integration test for sofia_customers CRM table.
Run on VPS: python3 /tmp/test_crm.py
"""
import urllib.request, json, sys

SUPABASE_URL = 'https://votyvfjbrjmcghekaatk.supabase.co'
ANON_KEY = 'eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9.eyJpc3MiOiJzdXBhYmFzZSIsInJlZiI6InZvdHl2ZmpicmptY2doZWthYXRrIiwicm9sZSI6ImFub24iLCJpYXQiOjE3NzIzOTA3NDksImV4cCI6MjA4Nzk2Njc0OX0.-vo_fUfBzty-mPXn61tv-v8azBcXeL3nF0JBEgYopK0'

def req(method, path, body=None, key=ANON_KEY):
    url = SUPABASE_URL + path
    data = json.dumps(body).encode() if body else None
    r = urllib.request.Request(url, data=data, method=method, headers={
        'apikey': key, 'Authorization': f'Bearer {key}',
        'Content-Type': 'application/json', 'Prefer': 'return=representation',
    })
    try:
        resp = urllib.request.urlopen(r)
        return resp.getcode(), json.loads(resp.read())
    except urllib.error.HTTPError as e:
        return e.code, json.loads(e.read())

print("=== CRM Integration Tests ===\n")

# Test 1: Table exists (GET with anon key)
code, body = req('GET', '/rest/v1/sofia_customers?limit=1')
if code == 200:
    print(f"[PASS] T1 Table exists — GET returned {code}, rows: {len(body)}")
else:
    print(f"[FAIL] T1 Table missing — {code}: {body}")
    sys.exit(1)

# Test 2: Write with anon key (should be blocked by RLS)
code, body = req('POST', '/rest/v1/sofia_customers',
                 {'customer_id': 'test_rls_check', 'name': 'RLS Test', 'channel': 'webchat'})
if code in (403, 401):
    print(f"[PASS] T2 RLS blocks anon writes — {code}")
elif code == 201:
    print(f"[WARN] T2 Anon key CAN write (RLS not restrictive) — row created. "
          f"This means writes from the bot WILL work, but consider restricting.")
    # Clean up
    req('DELETE', '/rest/v1/sofia_customers?customer_id=eq.test_rls_check')
else:
    print(f"[INFO] T2 Anon write got {code}: {body}")

# Test 3: Can the bot service (same anon key) write?
# If T2 is 403, CRM tracking is silently broken — need SUPABASE_SERVICE_KEY
print(f"\n=== Summary ===")
if code in (403, 401):
    print("ACTION REQUIRED: Bot uses anon key but RLS blocks its writes.")
    print("Fix: Add SUPABASE_SERVICE_KEY to .env and update get_supabase() to use it.")
elif code == 201:
    print("Writes work fine with anon key.")
else:
    print(f"Unexpected result: {code}")
