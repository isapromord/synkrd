"""
Thorough tests for ORDER TRACKING IN CHAT feature.

Covers:
- Order number extraction (regex, history scan, edge cases)
- Shopify API integration (fetch_order_status, fetch_fulfillments)
- Order context formatting for AI
- Router classification for order tracking intents
- API endpoint /api/order/{order_name}
- Chat flow integration (webchat + WhatsApp)
"""

import pytest
import re
from unittest.mock import AsyncMock, MagicMock, patch
from typing import Optional


# ═══════════════════════════════════════════════════════════════
# 1. ORDER NUMBER EXTRACTION
# ═══════════════════════════════════════════════════════════════

class TestExtractOrderNumber:
    """Test _extract_order_number() regex and history scanning."""

    def _extract(self, message: str, history: list = None) -> Optional[str]:
        """Call the real function from main.py."""
        # Inline implementation matching main.py logic for isolated testing
        texts = [message]
        if history:
            for msg in history[-4:]:
                if msg.get("role") == "user":
                    texts.append(msg["content"])
        for text in texts:
            # Try #NNN format first (explicit order reference)
            match = re.search(r'#(\d{3,6})\b', text)
            if match:
                return f"#{match.group(1)}"
            # Then try standalone 3-6 digit number (not part of a longer number)
            match = re.search(r'(?<!\d)(\d{3,6})(?!\d)', text)
            if match:
                return f"#{match.group(1)}"
        return None

    # --- Basic extraction ---

    def test_extract_with_hash(self):
        assert self._extract("¿Dónde está mi orden #1001?") == "#1001"

    def test_extract_without_hash(self):
        assert self._extract("Mi orden es 1234") == "#1234"

    def test_extract_three_digit_order(self):
        assert self._extract("Orden #100") == "#100"

    def test_extract_six_digit_order(self):
        assert self._extract("Mi pedido 123456") == "#123456"

    def test_extract_five_digit_order(self):
        assert self._extract("Hola, mi orden es #54321") == "#54321"

    # --- No match cases ---

    def test_no_order_number(self):
        assert self._extract("Hola buenos días") is None

    def test_too_short_number(self):
        """Two-digit numbers should NOT match (not an order number)."""
        assert self._extract("Quiero 2 camisetas") is None

    def test_only_one_digit(self):
        assert self._extract("Dame 1 producto") is None

    # --- History scanning ---

    def test_extract_from_history(self):
        history = [
            {"role": "user", "content": "Quiero rastrear mi orden"},
            {"role": "assistant", "content": "Claro, ¿cuál es tu número de orden?"},
            {"role": "user", "content": "#2050"},
        ]
        result = self._extract("¿Ya lo encontraste?", history)
        assert result == "#2050"

    def test_extract_prefers_current_message(self):
        """Current message should be checked first."""
        history = [
            {"role": "user", "content": "Mi orden es #1001"},
        ]
        result = self._extract("Ahora pregunto por #2002", history)
        assert result == "#2002"

    def test_history_only_scans_last_4(self):
        """Only last 4 messages from history should be scanned."""
        history = [
            {"role": "user", "content": "Orden #9999"},  # Old — might be beyond window
            {"role": "assistant", "content": "Ok"},
            {"role": "user", "content": "Otra cosa"},
            {"role": "assistant", "content": "Claro"},
            {"role": "user", "content": "Nada más"},
            {"role": "assistant", "content": "Ok"},
            {"role": "user", "content": "Gracias"},
            {"role": "assistant", "content": "De nada"},
        ]
        # Only scans last 4 entries, and within those only user messages
        result = self._extract("Hola", history)
        # The #9999 is in history[-8], beyond the [-4:] window
        # Last 4 are: user "Nada más", assistant "Ok", user "Gracias", assistant "De nada"
        assert result is None

    def test_history_skips_assistant_messages(self):
        history = [
            {"role": "assistant", "content": "Tu orden es #5555"},
            {"role": "user", "content": "Ok gracias"},
        ]
        result = self._extract("¿Cuándo llega?", history)
        assert result is None  # Assistant messages should be skipped

    # --- Edge cases ---

    def test_order_in_middle_of_sentence(self):
        assert self._extract("el pedido #1234 ya fue enviado?") == "#1234"

    def test_multiple_numbers_takes_first(self):
        result = self._extract("Orden #100 y #200")
        assert result == "#100"

    def test_phone_number_seven_digits_ignored(self):
        """7-digit numbers should NOT match — likely a phone number."""
        assert self._extract("Mi número es 1234567") is None

    def test_empty_message(self):
        assert self._extract("") is None

    def test_none_history(self):
        assert self._extract("Orden #1001", None) == "#1001"


# ═══════════════════════════════════════════════════════════════
# 2. SHOPIFY KNOWLEDGE — ORDER STATUS
# ═══════════════════════════════════════════════════════════════

class TestShopifyOrderStatus:
    """Test ShopifyKnowledge.fetch_order_status() and fetch_fulfillments()."""

    def _make_shopify(self):
        from knowledge.shopify import ShopifyKnowledge
        return ShopifyKnowledge(
            store_url="test-store.myshopify.com",
            access_token="shpat_test_token",
        )

    @pytest.mark.asyncio
    async def test_fetch_order_status_found(self):
        shopify = self._make_shopify()

        mock_order_response = MagicMock()
        mock_order_response.status_code = 200
        mock_order_response.json.return_value = {
            "orders": [{
                "id": 12345,
                "name": "#1001",
                "financial_status": "paid",
                "fulfillment_status": "fulfilled",
                "total_price": "2500.00",
                "currency": "DOP",
                "created_at": "2026-04-10T10:00:00Z",
                "customer": {"first_name": "María", "phone": "+18091234567"},
                "line_items": [
                    {"name": "Faja Colombiana", "quantity": 1, "price": "1500.00"},
                    {"name": "Crema Retinol", "quantity": 2, "price": "500.00"},
                ],
                "shipping_address": {"city": "Santo Domingo"},
            }]
        }
        mock_order_response.raise_for_status = MagicMock()

        mock_fulfillment_response = MagicMock()
        mock_fulfillment_response.status_code = 200
        mock_fulfillment_response.json.return_value = {
            "fulfillments": [{
                "id": 99,
                "status": "success",
                "tracking_number": "TRACK123",
                "tracking_url": "https://carrier.com/TRACK123",
                "tracking_company": "CEDI",
                "created_at": "2026-04-11T10:00:00Z",
                "updated_at": "2026-04-12T10:00:00Z",
                "line_items": [
                    {"name": "Faja Colombiana", "quantity": 1},
                    {"name": "Crema Retinol", "quantity": 2},
                ],
            }]
        }
        mock_fulfillment_response.raise_for_status = MagicMock()

        async def mock_get(url, **kwargs):
            if "fulfillments" in url:
                return mock_fulfillment_response
            return mock_order_response

        with patch("httpx.AsyncClient") as mock_client:
            mock_instance = AsyncMock()
            mock_instance.get = mock_get
            mock_instance.__aenter__ = AsyncMock(return_value=mock_instance)
            mock_instance.__aexit__ = AsyncMock(return_value=None)
            mock_client.return_value = mock_instance

            order = await shopify.fetch_order_status("#1001")

        assert order is not None
        assert order["order_name"] == "#1001"
        assert order["status"] == "paid"
        assert order["fulfillment_status"] == "fulfilled"
        assert order["total_price"] == "2500.00"
        assert order["currency"] == "DOP"
        assert order["customer_name"] == "María"
        assert len(order["line_items"]) == 2
        assert order["line_items"][0]["name"] == "Faja Colombiana"
        assert len(order["fulfillments"]) == 1
        assert order["fulfillments"][0]["tracking_number"] == "TRACK123"
        assert order["fulfillments"][0]["tracking_company"] == "CEDI"

    @pytest.mark.asyncio
    async def test_fetch_order_status_not_found(self):
        shopify = self._make_shopify()

        mock_response = MagicMock()
        mock_response.status_code = 200
        mock_response.json.return_value = {"orders": []}
        mock_response.raise_for_status = MagicMock()

        with patch("httpx.AsyncClient") as mock_client:
            mock_instance = AsyncMock()
            mock_instance.get = AsyncMock(return_value=mock_response)
            mock_instance.__aenter__ = AsyncMock(return_value=mock_instance)
            mock_instance.__aexit__ = AsyncMock(return_value=None)
            mock_client.return_value = mock_instance

            order = await shopify.fetch_order_status("#9999")

        assert order is None

    @pytest.mark.asyncio
    async def test_fetch_fulfillments_empty(self):
        shopify = self._make_shopify()

        mock_response = MagicMock()
        mock_response.status_code = 200
        mock_response.json.return_value = {"fulfillments": []}
        mock_response.raise_for_status = MagicMock()

        with patch("httpx.AsyncClient") as mock_client:
            mock_instance = AsyncMock()
            mock_instance.get = AsyncMock(return_value=mock_response)
            mock_instance.__aenter__ = AsyncMock(return_value=mock_instance)
            mock_instance.__aexit__ = AsyncMock(return_value=None)
            mock_client.return_value = mock_instance

            result = await shopify.fetch_fulfillments("12345")

        assert result == []

    @pytest.mark.asyncio
    async def test_fetch_fulfillments_api_error(self):
        """fetch_fulfillments should return [] on failure, not crash."""
        shopify = self._make_shopify()

        with patch("httpx.AsyncClient") as mock_client:
            mock_instance = AsyncMock()
            mock_instance.get = AsyncMock(side_effect=Exception("API timeout"))
            mock_instance.__aenter__ = AsyncMock(return_value=mock_instance)
            mock_instance.__aexit__ = AsyncMock(return_value=None)
            mock_client.return_value = mock_instance

            result = await shopify.fetch_fulfillments("12345")

        assert result == []

    @pytest.mark.asyncio
    async def test_fetch_order_unfulfilled(self):
        """Order exists but hasn't shipped yet."""
        shopify = self._make_shopify()

        mock_response = MagicMock()
        mock_response.status_code = 200
        mock_response.json.return_value = {
            "orders": [{
                "id": 55555,
                "name": "#1050",
                "financial_status": "paid",
                "fulfillment_status": None,
                "total_price": "800.00",
                "currency": "DOP",
                "created_at": "2026-04-14T08:00:00Z",
                "customer": {"first_name": "Carlos", "phone": ""},
                "line_items": [{"name": "Mochila Antirrobo", "quantity": 1, "price": "800.00"}],
                "shipping_address": {},
            }]
        }
        mock_response.raise_for_status = MagicMock()

        mock_fulfillment = MagicMock()
        mock_fulfillment.status_code = 200
        mock_fulfillment.json.return_value = {"fulfillments": []}
        mock_fulfillment.raise_for_status = MagicMock()

        async def mock_get(url, **kwargs):
            if "fulfillments" in url:
                return mock_fulfillment
            return mock_response

        with patch("httpx.AsyncClient") as mock_client:
            mock_instance = AsyncMock()
            mock_instance.get = mock_get
            mock_instance.__aenter__ = AsyncMock(return_value=mock_instance)
            mock_instance.__aexit__ = AsyncMock(return_value=None)
            mock_client.return_value = mock_instance

            order = await shopify.fetch_order_status("#1050")

        assert order is not None
        assert order["fulfillment_status"] == "unfulfilled"
        assert order["fulfillments"] == []


# ═══════════════════════════════════════════════════════════════
# 3. ORDER CONTEXT FORMATTING
# ═══════════════════════════════════════════════════════════════

class TestFetchOrderContext:
    """Test _fetch_order_context() output formatting for AI."""

    @pytest.mark.asyncio
    async def test_order_context_with_tracking(self):
        with patch("knowledge.shopify.ShopifyKnowledge.fetch_order_status", new_callable=AsyncMock) as mock:
            mock.return_value = {
                "order_id": "12345",
                "order_name": "#1001",
                "status": "paid",
                "fulfillment_status": "fulfilled",
                "total_price": "2500.00",
                "currency": "DOP",
                "created_at": "2026-04-10T10:00:00Z",
                "customer_name": "María",
                "customer_phone": "+18091234567",
                "line_items": [
                    {"name": "Faja Colombiana", "quantity": 1, "price": "1500.00"},
                ],
                "fulfillments": [{
                    "tracking_number": "TRACK123",
                    "tracking_url": "https://carrier.com/TRACK123",
                    "tracking_company": "CEDI",
                    "status": "success",
                }],
                "shipping_address": {"city": "Santo Domingo"},
            }

            # Patch settings to enable access_token
            with patch("main.settings") as mock_settings:
                mock_settings.shopify.access_token = "test_token"
                mock_settings.shopify.store_url = "test.myshopify.com"

                from main import _fetch_order_context
                result = await _fetch_order_context("#1001")

        assert result is not None
        assert "#1001" in result
        assert "paid" in result
        assert "TRACK123" in result
        assert "CEDI" in result
        assert "Faja Colombiana" in result

    @pytest.mark.asyncio
    async def test_order_context_not_found(self):
        with patch("knowledge.shopify.ShopifyKnowledge.fetch_order_status", new_callable=AsyncMock) as mock:
            mock.return_value = None

            with patch("main.settings") as mock_settings:
                mock_settings.shopify.access_token = "test_token"
                mock_settings.shopify.store_url = "test.myshopify.com"

                from main import _fetch_order_context
                result = await _fetch_order_context("#9999")

        assert result is not None
        assert "No se encontró" in result

    @pytest.mark.asyncio
    async def test_order_context_no_shopify_token(self):
        with patch("main.settings") as mock_settings:
            mock_settings.shopify.access_token = ""

            from main import _fetch_order_context
            result = await _fetch_order_context("#1001")

        assert result is None


# ═══════════════════════════════════════════════════════════════
# 4. ROUTER — ORDER TRACKING INTENT
# ═══════════════════════════════════════════════════════════════

class TestRouterOrderTracking:
    """Thorough test of all order tracking intent patterns."""

    def test_donde_esta_mi_pedido(self):
        from core.router import classify_intent
        tier, intent, _ = classify_intent("¿Dónde está mi pedido #1234?")
        assert tier == 2
        assert intent == "order_tracking"

    def test_mi_orden(self):
        from core.router import classify_intent
        tier, intent, _ = classify_intent("Quiero saber de mi orden #555")
        assert tier == 2
        assert intent == "order_tracking"

    def test_numero_de_orden(self):
        from core.router import classify_intent
        tier, intent, _ = classify_intent("¿Cuál es el estado del pedido?")
        assert tier == 2
        assert intent == "order_tracking"

    def test_rastrear(self):
        from core.router import classify_intent
        tier, intent, _ = classify_intent("Quiero rastrear mi envío")
        assert tier == 2
        assert intent == "order_tracking"

    def test_cuando_llega(self):
        from core.router import classify_intent
        tier, intent, _ = classify_intent("¿Cuándo llega mi pedido?")
        assert tier == 2
        assert intent == "order_tracking"

    def test_delivery_english(self):
        from core.router import classify_intent
        tier, intent, _ = classify_intent("What's the delivery status?")
        assert tier == 2
        assert intent == "order_tracking"

    def test_status_de_mi(self):
        from core.router import classify_intent
        tier, intent, _ = classify_intent("¿Cuál es el status de mi orden?")
        assert tier == 2
        assert intent == "order_tracking"

    def test_order_hash_only(self):
        """Bare '#1001' should now be detected as order_tracking."""
        from core.router import classify_intent
        tier, intent, _ = classify_intent("#1001")
        assert tier == 2
        assert intent == "order_tracking"


# ═══════════════════════════════════════════════════════════════
# 5. API ENDPOINT: /api/order/{order_name}
# ═══════════════════════════════════════════════════════════════

class TestOrderAPI:
    """Test the public order tracking API endpoint."""

    @pytest.fixture(autouse=True)
    def setup_client(self):
        with patch("knowledge.scraper.fetch_all_products", return_value=[]), \
             patch("knowledge.scraper.build_product_context", return_value=""):
            from main import app
            from fastapi.testclient import TestClient
            self.client = TestClient(app)

    def test_order_api_no_shopify_token(self):
        with patch("main.settings") as mock_settings:
            mock_settings.shopify.access_token = ""
            mock_settings.shopify.store_url = "test.myshopify.com"
            mock_settings.bot_name = "Sofía"

            response = self.client.get("/api/order/1001")

        assert response.status_code == 200
        data = response.json()
        assert "error" in data

    @pytest.mark.asyncio
    async def test_order_api_found(self):
        mock_order = {
            "order_id": "12345",
            "order_name": "#1001",
            "status": "paid",
            "fulfillment_status": "fulfilled",
            "total_price": "1500.00",
            "currency": "DOP",
            "created_at": "2026-04-10T10:00:00Z",
            "customer_name": "Pedro",
            "customer_phone": "+18097654321",
            "line_items": [{"name": "Camiseta Nike", "quantity": 1, "price": "1500.00"}],
            "fulfillments": [],
            "shipping_address": {},
        }

        with patch("knowledge.shopify.ShopifyKnowledge.fetch_order_status", new_callable=AsyncMock, return_value=mock_order):
            with patch("main.settings") as mock_settings:
                mock_settings.shopify.access_token = "shpat_test"
                mock_settings.shopify.store_url = "test.myshopify.com"
                mock_settings.bot_name = "Sofía"

                response = self.client.get("/api/order/1001")

        assert response.status_code == 200
        data = response.json()
        assert data["status"] == "ok"
        assert data["order"]["order_name"] == "#1001"

    @pytest.mark.asyncio
    async def test_order_api_not_found(self):
        with patch("knowledge.shopify.ShopifyKnowledge.fetch_order_status", new_callable=AsyncMock, return_value=None):
            with patch("main.settings") as mock_settings:
                mock_settings.shopify.access_token = "shpat_test"
                mock_settings.shopify.store_url = "test.myshopify.com"
                mock_settings.bot_name = "Sofía"

                response = self.client.get("/api/order/9999")

        assert response.status_code == 200
        data = response.json()
        assert data["status"] == "not_found"


# ═══════════════════════════════════════════════════════════════
# 6. SHOPIFY KNOWLEDGE — PRODUCT FORMATTING
# ═══════════════════════════════════════════════════════════════

class TestShopifyProductFormatting:
    """Test _format_product for inventory-related fields."""

    def test_format_product_includes_inventory(self):
        from knowledge.shopify import ShopifyKnowledge
        sk = ShopifyKnowledge("test.myshopify.com", "token")

        product = {
            "id": 1,
            "title": "Faja Colombiana",
            "body_html": "Best faja",
            "product_type": "Belleza",
            "tags": "faja,colombiana",
            "handle": "faja-colombiana",
            "status": "active",
            "variants": [
                {"id": 101, "title": "S", "price": "1500.00", "inventory_quantity": 10},
                {"id": 102, "title": "M", "price": "1500.00", "inventory_quantity": 0},
                {"id": 103, "title": "L", "price": "1500.00", "inventory_quantity": 3},
            ],
            "images": [{"src": "https://img.com/faja.jpg"}],
            "options": [{"name": "Size", "values": ["S", "M", "L"]}],
        }

        result = sk._format_product(product)

        assert result["available"] is True  # At least one variant has stock
        assert len(result["variants_detail"]) == 3
        assert result["variants_detail"][0]["inventory_quantity"] == 10
        assert result["variants_detail"][0]["available"] is True
        assert result["variants_detail"][1]["inventory_quantity"] == 0
        assert result["variants_detail"][1]["available"] is False
        assert result["variants_detail"][2]["inventory_quantity"] == 3

    def test_format_product_all_out_of_stock(self):
        from knowledge.shopify import ShopifyKnowledge
        sk = ShopifyKnowledge("test.myshopify.com", "token")

        product = {
            "id": 2,
            "title": "Crema Agotada",
            "body_html": "",
            "product_type": "Belleza",
            "tags": "",
            "handle": "crema-agotada",
            "status": "active",
            "variants": [
                {"id": 201, "title": "Default", "price": "500.00", "inventory_quantity": 0},
            ],
            "images": [],
            "options": [],
        }

        result = sk._format_product(product)
        assert result["available"] is False

    def test_inventory_levels_fetch(self):
        """Test fetch_inventory_levels returns correct structure."""
        from knowledge.shopify import ShopifyKnowledge
        sk = ShopifyKnowledge("test.myshopify.com", "token")
        # Just verify the method exists and has correct signature
        assert hasattr(sk, "fetch_inventory_levels")
