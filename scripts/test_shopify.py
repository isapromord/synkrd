"""Quick test: Can we access TrendyRD Shopify Admin API with legacy app credentials?"""
import urllib.request
import json
import base64
import ssl

API_KEY = "0bf8afbbbc375151c51f320dcf56f2a1"
API_SECRET = "8a41793420b6e8ac9b9f0fcbdd0467a2"
STORE = "trendyrd.myshopify.com"
API_VERSION = "2024-10"

url = f"https://{STORE}/admin/api/{API_VERSION}/products.json?limit=3"

# Basic Auth
credentials = base64.b64encode(f"{API_KEY}:{API_SECRET}".encode()).decode()
req = urllib.request.Request(url)
req.add_header("Authorization", f"Basic {credentials}")
req.add_header("Content-Type", "application/json")

ctx = ssl.create_default_context()

try:
    response = urllib.request.urlopen(req, context=ctx)
    data = json.loads(response.read())
    products = data.get("products", [])
    print(f"✅ SUCCESS! Found {len(products)} products:")
    for p in products:
        price = p["variants"][0]["price"] if p.get("variants") else "N/A"
        print(f"  - {p['title']} | RD${price} | Status: {p.get('status', 'unknown')}")
except urllib.error.HTTPError as e:
    body = e.read().decode()
    print(f"❌ HTTP {e.code}: {body}")
except Exception as e:
    print(f"❌ Error: {e}")
