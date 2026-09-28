"""
One-time script to get a Shopify Admin API access token via OAuth.
Run this, click "Install" in the browser, and copy the token.
"""
import http.server
import urllib.parse
import webbrowser
import httpx
import sys
import threading

import os

# ── Sofía Bot credentials from Dev Dashboard (loaded via env) ──
CLIENT_ID = os.getenv("SHOPIFY_CLIENT_ID", "")
CLIENT_SECRET = os.getenv("SHOPIFY_CLIENT_SECRET", "")
SHOP = os.getenv("SHOPIFY_SHOP_DOMAIN", "dp8imj-ca.myshopify.com")
SCOPES = os.getenv("SHOPIFY_SCOPES", "read_products,read_orders,read_all_orders,write_orders,write_draft_orders,read_inventory,read_shipping,read_customers,write_customers,read_fulfillments,write_fulfillments,read_discounts,write_discounts,read_price_rules,write_price_rules,read_checkouts")
REDIRECT_URI = os.getenv("SHOPIFY_REDIRECT_URI", "http://localhost:9999/callback")

access_token = None

class OAuthHandler(http.server.BaseHTTPRequestHandler):
    def do_GET(self):
        global access_token
        parsed = urllib.parse.urlparse(self.path)
        params = urllib.parse.parse_qs(parsed.query)

        if parsed.path == "/callback" and "code" in params:
            code = params["code"][0]
            print(f"\n✅ Received authorization code: {code[:10]}...")

            # Exchange code for access token
            resp = httpx.post(
                f"https://{SHOP}/admin/oauth/access_token",
                json={
                    "client_id": CLIENT_ID,
                    "client_secret": CLIENT_SECRET,
                    "code": code,
                },
            )

            if resp.status_code == 200:
                data = resp.json()
                access_token = data.get("access_token", "")
                self.send_response(200)
                self.send_header("Content-Type", "text/html")
                self.end_headers()
                self.wfile.write(b"""
                    <html><body style="font-family:sans-serif;text-align:center;padding:60px;">
                    <h1 style="color:green;">Token received!</h1>
                    <p>You can close this tab and go back to VS Code.</p>
                    </body></html>
                """)
                print(f"\n{'='*60}")
                print(f"ACCESS TOKEN: {access_token}")
                print(f"{'='*60}")
                print(f"\nAdd this to your .env:")
                print(f"SHOPIFY_ACCESS_TOKEN={access_token}")
                print(f"\nYou can close this script now (Ctrl+C).")
                # Shutdown server after response
                threading.Thread(target=self.server.shutdown).start()
            else:
                self.send_response(500)
                self.send_header("Content-Type", "text/html")
                self.end_headers()
                self.wfile.write(f"Error: {resp.status_code} - {resp.text}".encode())
                print(f"❌ Error exchanging code: {resp.status_code} - {resp.text}")
        else:
            self.send_response(404)
            self.end_headers()

    def log_message(self, format, *args):
        pass  # Suppress default logging


if __name__ == "__main__":
    # Build the authorization URL
    auth_url = (
        f"https://{SHOP}/admin/oauth/authorize"
        f"?client_id={CLIENT_ID}"
        f"&scope={SCOPES}"
        f"&redirect_uri={urllib.parse.quote(REDIRECT_URI)}"
    )

    print("🔑 Shopify OAuth Token Grabber")
    print(f"   Shop: {SHOP}")
    print(f"   Scopes: {SCOPES}")
    print(f"\n📱 Opening browser for authorization...")
    print(f"   If it doesn't open, go to:\n   {auth_url}\n")

    # Start local server
    server = http.server.HTTPServer(("localhost", 9999), OAuthHandler)

    # Open browser
    webbrowser.open(auth_url)

    print("⏳ Waiting for callback...")
    server.serve_forever()

    if access_token:
        print("\n✅ Done! Token saved above.")
    else:
        print("\n❌ No token received.")
