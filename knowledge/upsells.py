"""
ReleaseIt Upsell Knowledge Fetcher
Reads quantity-offer configuration from Shopify metafields (stored by ReleaseIt)
and builds a formatted text block for Sofía's system prompt.

Refreshed every 24h alongside the product catalog sync — so any change
the merchant makes in ReleaseIt is reflected in Sofía within the next sync.
"""
import json
import logging
import urllib.request
import ssl
from typing import Optional

logger = logging.getLogger(__name__)

RELEASEIT_NAMESPACE = "_rsi_cod_form_sf"


def fetch_upsell_context(store_url: str, access_token: str) -> str:
    """
    Fetch active quantity-offer upsells from ReleaseIt and return
    a formatted string ready to be injected into Sofía's system prompt.

    Returns empty string if token is missing or API call fails.
    """
    if not store_url or not access_token:
        return ""

    try:
        # Normalise store URL
        hostname = store_url.replace("https://", "").replace("http://", "").rstrip("/")

        ctx = ssl.create_default_context()

        def _get(path: str) -> dict:
            url = f"https://{hostname}/admin/api/2024-10/{path}"
            req = urllib.request.Request(url)
            req.add_header("X-Shopify-Access-Token", access_token)
            resp = urllib.request.urlopen(req, context=ctx, timeout=15)
            return json.loads(resp.read())

        # ── Step 1: Fetch ReleaseIt quantity_offers metafield ──────────────
        mf_data = _get("metafields.json?limit=50").get("metafields", [])
        raw_offers_json = None
        for mf in mf_data:
            if mf.get("namespace") == RELEASEIT_NAMESPACE and mf.get("key") == "quantity_offers_json":
                raw_offers_json = mf.get("value")
                break

        if not raw_offers_json:
            logger.info("ℹ️ ReleaseIt: no quantity_offers_json metafield found")
            return ""

        offers = json.loads(raw_offers_json)
        active_offers = [o for o in offers if o.get("isActive")]
        if not active_offers:
            logger.info("ℹ️ ReleaseIt: no active quantity offers")
            return ""

        # ── Step 2: Resolve product IDs → names ────────────────────────────
        products_data = _get("products.json?limit=250").get("products", [])
        id_to_name = {
            str(p["id"]): p["title"]
            for p in products_data
        }
        id_to_price = {
            str(p["id"]): float(p["variants"][0]["price"])
            for p in products_data
            if p.get("variants")
        }

        # ── Step 3: Build formatted table ──────────────────────────────────
        lines = [
            "🎁 DESCUENTOS POR CANTIDAD — ReleaseIt (se actualizan automáticamente):",
            "Si el cliente muestra INTERÉS REAL en comprar uno de estos productos, menciónalo "
            "UNA SOLA VEZ de forma natural, como consejo de amiga:",
            "",
        ]

        for offer in active_offers:
            pids = offer.get("pIds", [])
            sub_offers = offer.get("offers", [])

            # Find the discount offer (the one with qty > 1)
            best = None
            for sub in sub_offers:
                if sub.get("qty", 1) > 1:
                    best = sub
                    break
            if not best:
                continue

            qty = best.get("qty", 2)
            ds = best.get("ds", {})
            discount_type = ds.get("t", "none")
            discount_val = ds.get("v", 0)

            if discount_type == "percentage":
                pct = discount_val / 100
                # ReleaseIt stores percentage * 100 (2000 = 20%)
                discount_str = f"{pct:.0f}% OFF comprando {qty}"
                if qty == 2 and pct >= 40:
                    discount_str = f"{pct:.0f}% OFF en la 2da unidad"
            elif discount_type == "fixed_amount":
                discount_str = f"RD${discount_val / 100:,.0f} de descuento comprando {qty}"
            else:
                continue  # No discount — skip

            # Build product name list
            names = []
            for pid in pids:
                n = id_to_name.get(str(pid))
                if n:
                    names.append(n)

            if not names:
                continue

            price = id_to_price.get(str(pids[0]), 0) if pids else 0
            price_str = f" (RD${price:,.0f})" if price else ""

            for name in names:
                lines.append(f"• {name}{price_str} → {discount_str}")

        if len(lines) <= 3:  # Only header, no products
            return ""

        lines += [
            "",
            "CÓMO MENCIONARLO: '¡Esa [producto] está buenísima! Y si llevas [qty], te sale con [X]% OFF. ¿Te mando las [qty]? 😄'",
            "El descuento se aplica AUTOMÁTICAMENTE al seleccionar la cantidad en el formulario de checkout.",
            "NO hay código — no inventes ninguno.",
            "Solo menciona el descuento DESPUÉS de que el cliente muestre interés en ese producto específico.",
        ]

        result = "\n".join(lines)
        logger.info(f"🎁 ReleaseIt: {len(active_offers)} active upsells loaded")
        return result

    except Exception as e:
        logger.warning(f"⚠️ ReleaseIt upsell fetch failed (non-fatal): {e}")
        return ""
