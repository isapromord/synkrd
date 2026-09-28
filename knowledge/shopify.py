"""
SynkDR Engine — Shopify Knowledge Source

Fetches product data from Shopify API and syncs to Supabase.
This is the PLUGGABLE knowledge layer — swap Shopify for menu API, etc.
"""

import logging
import httpx
from typing import Optional

logger = logging.getLogger("synkdr.knowledge.shopify")


class ShopifyKnowledge:
    """
    Shopify API integration for product knowledge.
    
    Fetches products, variants, and inventory from Shopify Admin API.
    Syncs data to Supabase for fast retrieval during conversations.
    """

    def __init__(self, store_url: str, access_token: str, api_version: str = "2024-10"):
        self.store_url = store_url
        self.base_url = f"https://{store_url}/admin/api/{api_version}"
        self.headers = {
            "X-Shopify-Access-Token": access_token,
            "Content-Type": "application/json",
        }

    async def fetch_all_products(self) -> list:
        """Fetch all products from Shopify."""
        products = []
        url = f"{self.base_url}/products.json?limit=250"

        async with httpx.AsyncClient(timeout=30) as client:
            while url:
                response = await client.get(url, headers=self.headers)
                response.raise_for_status()
                data = response.json()

                for product in data.get("products", []):
                    products.append(self._format_product(product))

                # Pagination via Link header
                link_header = response.headers.get("Link", "")
                url = self._extract_next_url(link_header)

        logger.info(f"📦 Fetched {len(products)} products from Shopify")
        return products

    async def fetch_product_by_id(self, product_id: str) -> Optional[dict]:
        """Fetch a single product by Shopify ID."""
        url = f"{self.base_url}/products/{product_id}.json"

        async with httpx.AsyncClient(timeout=30) as client:
            response = await client.get(url, headers=self.headers)
            if response.status_code == 404:
                return None
            response.raise_for_status()
            data = response.json()
            return self._format_product(data.get("product", {}))

    async def fetch_inventory_levels(self, product_ids: list) -> dict:
        """
        Fetch inventory quantities for products.
        Returns dict mapping variant_id -> inventory_quantity.
        """
        inventory = {}
        # Get inventory item IDs from product variants
        for pid in product_ids:
            url = f"{self.base_url}/products/{pid}.json?fields=id,variants"
            try:
                async with httpx.AsyncClient(timeout=30) as client:
                    response = await client.get(url, headers=self.headers)
                    if response.status_code == 200:
                        data = response.json()
                        for v in data.get("product", {}).get("variants", []):
                            inventory[str(v["id"])] = {
                                "quantity": v.get("inventory_quantity", 0),
                                "title": v.get("title", "Default"),
                            }
            except Exception as e:
                logger.warning(f"Inventory fetch failed for product {pid}: {e}")
        return inventory

    async def fetch_fulfillments(self, order_id: str) -> list:
        """
        Fetch fulfillment details for an order (tracking numbers, carrier, status).
        """
        url = f"{self.base_url}/orders/{order_id}/fulfillments.json"
        try:
            async with httpx.AsyncClient(timeout=30) as client:
                response = await client.get(url, headers=self.headers)
                response.raise_for_status()
                data = response.json()
                fulfillments = []
                for f in data.get("fulfillments", []):
                    fulfillments.append({
                        "id": f.get("id"),
                        "status": f.get("status"),  # pending, open, success, cancelled, failure
                        "tracking_number": f.get("tracking_number"),
                        "tracking_url": f.get("tracking_url"),
                        "tracking_company": f.get("tracking_company"),
                        "created_at": f.get("created_at"),
                        "updated_at": f.get("updated_at"),
                        "line_items": [
                            {"name": li.get("name"), "quantity": li.get("quantity")}
                            for li in f.get("line_items", [])
                        ],
                    })
                return fulfillments
        except Exception as e:
            logger.warning(f"Fulfillment fetch failed for order {order_id}: {e}")
            return []

    async def fetch_order_status(self, order_name: str) -> Optional[dict]:
        """
        Fetch order status by order name (e.g., '#1001').
        Used when customers ask about their order.
        """
        url = f"{self.base_url}/orders.json?name={order_name}&status=any"

        async with httpx.AsyncClient(timeout=30) as client:
            response = await client.get(url, headers=self.headers)
            response.raise_for_status()
            data = response.json()

            orders = data.get("orders", [])
            if not orders:
                return None

            order = orders[0]
            order_id = order.get("id")

            # Fetch fulfillment details
            fulfillments = await self.fetch_fulfillments(str(order_id)) if order_id else []

            # Build line items summary
            line_items = []
            for li in order.get("line_items", []):
                line_items.append({
                    "name": li.get("name"),
                    "quantity": li.get("quantity"),
                    "price": li.get("price"),
                })

            return {
                "order_id": str(order_id),
                "order_name": order.get("name"),
                "status": order.get("financial_status"),
                "fulfillment_status": order.get("fulfillment_status") or "unfulfilled",
                "total_price": order.get("total_price"),
                "currency": order.get("currency"),
                "created_at": order.get("created_at"),
                "customer_name": order.get("customer", {}).get("first_name", ""),
                "customer_phone": order.get("customer", {}).get("phone", ""),
                "line_items": line_items,
                "fulfillments": fulfillments,
                "shipping_address": order.get("shipping_address", {}),
            }

    async def create_draft_order(
        self,
        line_items: list,
        shipping_address: dict,
        customer_phone: str,
        customer_name: str = "",
        note: str = "",
    ) -> Optional[dict]:
        """
        Create a draft order in Shopify for COD (Cash on Delivery).

        Args:
            line_items: List of dicts with 'variant_id' and 'quantity'
            shipping_address: Dict with address1, city, province, country, phone
            customer_phone: Customer phone number
            customer_name: Customer full name
            note: Order note (e.g., 'pedido via WhatsApp — Sofía AI')

        Returns:
            Dict with draft_order_id, order_name, total_price, invoice_url or None
        """
        url = f"{self.base_url}/draft_orders.json"

        # Split name into first/last
        name_parts = customer_name.strip().split(" ", 1) if customer_name else [""]
        first_name = name_parts[0]
        last_name = name_parts[1] if len(name_parts) > 1 else ""

        # Build shipping address with customer info
        address = {
            "first_name": first_name,
            "last_name": last_name,
            "address1": shipping_address.get("address1", ""),
            "address2": shipping_address.get("address2", ""),
            "city": shipping_address.get("city", ""),
            "province": shipping_address.get("province", ""),
            "country": shipping_address.get("country", "DO"),
            "zip": shipping_address.get("zip", ""),
            "phone": customer_phone,
        }

        payload = {
            "draft_order": {
                "line_items": [
                    {"variant_id": int(li["variant_id"]), "quantity": li.get("quantity", 1)}
                    for li in line_items
                ],
                "shipping_address": address,
                "billing_address": address,
                "customer": {
                    "first_name": first_name,
                    "last_name": last_name,
                    "phone": customer_phone,
                },
                "note": note or "Pedido via WhatsApp — SynkDR",
                "tags": "synkdr_chat,cod",
                "payment_terms": None,
            }
        }

        try:
            async with httpx.AsyncClient(timeout=30) as client:
                response = await client.post(url, headers=self.headers, json=payload)
                response.raise_for_status()
                data = response.json()
                draft = data.get("draft_order", {})

                logger.info(
                    f"📦 Draft order created: {draft.get('name')} | "
                    f"total={draft.get('total_price')} | phone={customer_phone}"
                )

                return {
                    "draft_order_id": str(draft.get("id", "")),
                    "order_name": draft.get("name", ""),
                    "total_price": draft.get("total_price", "0"),
                    "currency": draft.get("currency", "DOP"),
                    "line_items": [
                        {"name": li.get("title", ""), "quantity": li.get("quantity", 1), "price": li.get("price", "0")}
                        for li in draft.get("line_items", [])
                    ],
                    "invoice_url": draft.get("invoice_url", ""),
                    "status": draft.get("status", "open"),
                }
        except httpx.HTTPStatusError as e:
            logger.error(f"❌ Draft order creation failed: {e.response.status_code} — {e.response.text}")
            return None
        except Exception as e:
            logger.error(f"❌ Draft order creation error: {e}")
            return None

    async def complete_draft_order(self, draft_order_id: str) -> Optional[dict]:
        """
        Complete a draft order (converts it to a real order, marks as COD/pending payment).
        """
        url = f"{self.base_url}/draft_orders/{draft_order_id}/complete.json?payment_pending=true"
        try:
            async with httpx.AsyncClient(timeout=30) as client:
                response = await client.put(url, headers=self.headers)
                response.raise_for_status()
                data = response.json()
                draft = data.get("draft_order", {})
                order_id = draft.get("order_id")
                logger.info(f"✅ Draft order completed → order_id={order_id}")
                return {
                    "order_id": str(order_id) if order_id else None,
                    "order_name": draft.get("name", ""),
                    "status": draft.get("status", ""),
                }
        except Exception as e:
            logger.error(f"❌ Draft order completion failed: {e}")
            return None

    def _format_product(self, product: dict) -> dict:
        """Format Shopify product data for Supabase storage."""
        variants = product.get("variants", [])
        images = product.get("images", [])

        # Get price range
        prices = [float(v.get("price", 0)) for v in variants if v.get("price")]
        min_price = min(prices) if prices else 0
        max_price = max(prices) if prices else 0

        # Get variant options (sizes, colors, etc.)
        options = []
        for option in product.get("options", []):
            options.append({
                "name": option.get("name"),
                "values": option.get("values", []),
            })

        return {
            "shopify_id": str(product.get("id")),
            "name": product.get("title", ""),
            "description": product.get("body_html", ""),
            "category": product.get("product_type", ""),
            "tags": product.get("tags", ""),
            "price_min": min_price,
            "price_max": max_price,
            "currency": "DOP",  # Dominican Peso
            "variants_count": len(variants),
            "options": options,
            "image_url": images[0].get("src", "") if images else "",
            "handle": product.get("handle", ""),
            "url": f"https://{self.store_url}/products/{product.get('handle', '')}",
            "status": product.get("status", "active"),
            "available": any(
                v.get("inventory_quantity", 0) > 0
                for v in variants
            ),
            "variants_detail": [
                {
                    "id": str(v.get("id", "")),
                    "title": v.get("title", "Default"),
                    "price": float(v.get("price", 0)),
                    "inventory_quantity": v.get("inventory_quantity", 0),
                    "available": v.get("inventory_quantity", 0) > 0,
                }
                for v in variants
            ],
        }

    def _extract_next_url(self, link_header: str) -> Optional[str]:
        """Extract next page URL from Shopify Link header."""
        if not link_header:
            return None
        for part in link_header.split(","):
            if 'rel="next"' in part:
                url = part.split(";")[0].strip().strip("<>")
                return url
        return None


def build_product_context(products: list) -> str:
    """
    Build product context string for AI prompt injection.
    
    This gives Sofía knowledge about available products so she can
    answer customer questions accurately.
    """
    if not products:
        return "No hay productos disponibles actualmente."

    lines = []
    for p in products:
        price = f"RD${p['price_min']:,.0f}"
        if p["price_max"] > p["price_min"]:
            price += f" - RD${p['price_max']:,.0f}"

        availability = "✅ Disponible" if p.get("available") else "❌ Agotado"

        lines.append(
            f"- {p['name']}: {price} | {availability} | {p.get('url', '')}"
        )

    return "\n".join(lines)
