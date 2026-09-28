"""
Thorough tests for ABANDONED CART RECOVERY feature.

Covers:
- Shopify checkout webhook (capture, validation, edge cases)
- Database operations (save, query pending, mark followed up, mark recovered)
- Scheduled follow-up processor (3-touch strategy, message content)
- Order webhook (recovery tracking)
- End-to-end flow: capture → schedule → follow-up → recovery
"""

import pytest
import json
from unittest.mock import AsyncMock, MagicMock, patch
from datetime import datetime, timezone, timedelta


# ═══════════════════════════════════════════════════════════════
# 1. CHECKOUT WEBHOOK — CART CAPTURE
# ═══════════════════════════════════════════════════════════════

class TestCheckoutWebhook:
    """Test POST /webhook/shopify/checkout endpoint."""

    @pytest.fixture(autouse=True)
    def setup_client(self):
        with patch("knowledge.scraper.fetch_all_products", return_value=[]), \
             patch("knowledge.scraper.build_product_context", return_value=""):
            from main import app
            from fastapi.testclient import TestClient
            self.client = TestClient(app)

    def _checkout_payload(self, **overrides):
        """Build a standard Shopify checkout payload."""
        base = {
            "id": "checkout_abc123",
            "phone": "+18091234567",
            "email": "test@example.com",
            "total_price": "2500.00",
            "currency": "DOP",
            "abandoned_checkout_url": "https://trendyrd.com/cart/recover/abc123",
            "customer": {
                "first_name": "María",
                "last_name": "García",
                "phone": "+18091234567",
            },
            "line_items": [
                {"title": "Faja Colombiana", "quantity": 1, "price": "1500.00", "image_url": "", "variant_title": "M"},
                {"title": "Crema Retinol", "quantity": 2, "price": "500.00", "image_url": "", "variant_title": ""},
            ],
            "shipping_address": {"phone": "+18091234567"},
            "billing_address": {"phone": "+18091234567"},
        }
        base.update(overrides)
        return base

    @patch("database.save_abandoned_checkout", new_callable=AsyncMock, return_value={"id": "uuid-1"})
    def test_valid_checkout_captured(self, mock_save):
        payload = self._checkout_payload()
        response = self.client.post("/webhook/shopify/checkout", json=payload)

        assert response.status_code == 200
        data = response.json()
        assert data["action"] == "captured"
        mock_save.assert_called_once()

        # Verify saved data structure
        saved = mock_save.call_args[0][0]
        assert saved["shopify_checkout_id"] == "checkout_abc123"
        assert saved["customer_phone"] == "+18091234567"
        assert saved["customer_name"] == "María García"
        assert saved["customer_email"] == "test@example.com"
        assert saved["total_price"] == 2500.0
        assert saved["currency"] == "DOP"
        assert saved["checkout_url"] == "https://trendyrd.com/cart/recover/abc123"
        assert saved["status"] == "abandoned"
        assert saved["followup_count"] == 0
        assert len(saved["line_items"]) == 2
        assert saved["line_items"][0]["name"] == "Faja Colombiana"

    @patch("database.save_abandoned_checkout", new_callable=AsyncMock, return_value={"id": "uuid-2"})
    def test_checkout_no_top_level_phone_uses_shipping(self, mock_save):
        """Phone should fallback to shipping_address.phone."""
        payload = self._checkout_payload()
        del payload["phone"]
        response = self.client.post("/webhook/shopify/checkout", json=payload)
        assert response.status_code == 200
        assert response.json()["action"] == "captured"

    @patch("database.save_abandoned_checkout", new_callable=AsyncMock, return_value={"id": "uuid-3"})
    def test_checkout_phone_from_customer(self, mock_save):
        """Phone should fallback to customer.phone."""
        payload = self._checkout_payload()
        del payload["phone"]
        payload["shipping_address"] = {}
        payload["billing_address"] = {}
        response = self.client.post("/webhook/shopify/checkout", json=payload)
        assert response.status_code == 200
        assert response.json()["action"] == "captured"

    def test_checkout_no_phone_skipped(self):
        """Checkouts without ANY phone should be skipped."""
        payload = self._checkout_payload()
        del payload["phone"]
        payload["shipping_address"] = {}
        payload["billing_address"] = {}
        payload["customer"] = {"first_name": "Test"}
        response = self.client.post("/webhook/shopify/checkout", json=payload)
        assert response.status_code == 200
        assert response.json()["action"] == "skipped_no_phone"

    def test_checkout_no_id_skipped(self):
        """Checkouts without an ID should be skipped."""
        payload = self._checkout_payload(id="")
        response = self.client.post("/webhook/shopify/checkout", json=payload)
        assert response.status_code == 200
        assert response.json()["action"] == "skipped_no_id"

    def test_checkout_invalid_json(self):
        """Invalid JSON should return 400."""
        response = self.client.post(
            "/webhook/shopify/checkout",
            content="not json",
            headers={"Content-Type": "application/json"},
        )
        assert response.status_code == 400

    @patch("database.save_abandoned_checkout", new_callable=AsyncMock, return_value={"id": "uuid-4"})
    def test_phone_normalization_10_digits(self, mock_save):
        """10-digit phone should get +1 prefix."""
        payload = self._checkout_payload(phone="8091234567")
        payload["shipping_address"] = {}
        payload["billing_address"] = {}
        payload["customer"] = {}
        response = self.client.post("/webhook/shopify/checkout", json=payload)
        assert response.status_code == 200

        saved = mock_save.call_args[0][0]
        assert saved["customer_phone"] == "+18091234567"

    @patch("database.save_abandoned_checkout", new_callable=AsyncMock, return_value={"id": "uuid-5"})
    def test_phone_normalization_11_digits(self, mock_save):
        """11-digit phone starting with 1 should get + prefix."""
        payload = self._checkout_payload(phone="18091234567")
        payload["shipping_address"] = {}
        payload["billing_address"] = {}
        payload["customer"] = {}
        response = self.client.post("/webhook/shopify/checkout", json=payload)
        assert response.status_code == 200

        saved = mock_save.call_args[0][0]
        assert saved["customer_phone"] == "+18091234567"

    @patch("database.save_abandoned_checkout", new_callable=AsyncMock, return_value={"id": "uuid-6"})
    def test_phone_strips_formatting(self, mock_save):
        """Phone with dashes, spaces, parens should be cleaned."""
        payload = self._checkout_payload(phone="(809) 123-4567")
        payload["shipping_address"] = {}
        payload["billing_address"] = {}
        payload["customer"] = {}
        response = self.client.post("/webhook/shopify/checkout", json=payload)
        assert response.status_code == 200

        saved = mock_save.call_args[0][0]
        assert "(" not in saved["customer_phone"]
        assert ")" not in saved["customer_phone"]
        assert "-" not in saved["customer_phone"]
        assert " " not in saved["customer_phone"]


# ═══════════════════════════════════════════════════════════════
# 2. ORDER WEBHOOK — RECOVERY TRACKING
# ═══════════════════════════════════════════════════════════════

class TestOrderWebhook:
    """Test POST /webhook/shopify/order endpoint (marks carts recovered)."""

    @pytest.fixture(autouse=True)
    def setup_client(self):
        with patch("knowledge.scraper.fetch_all_products", return_value=[]), \
             patch("knowledge.scraper.build_product_context", return_value=""):
            from main import app
            from fastapi.testclient import TestClient
            self.client = TestClient(app)

    @patch("database.mark_cart_recovered", new_callable=AsyncMock, return_value=True)
    def test_order_recovers_cart(self, mock_recover):
        payload = {"checkout_id": "checkout_abc123", "id": 12345}
        response = self.client.post("/webhook/shopify/order", json=payload)

        assert response.status_code == 200
        assert response.json()["action"] == "processed"
        mock_recover.assert_called_once_with("checkout_abc123")

    @patch("database.mark_cart_recovered", new_callable=AsyncMock, return_value=False)
    def test_order_no_matching_cart(self, mock_recover):
        """Order with no matching abandoned cart should still succeed."""
        payload = {"checkout_id": "unknown_checkout", "id": 99999}
        response = self.client.post("/webhook/shopify/order", json=payload)
        assert response.status_code == 200

    def test_order_no_checkout_id(self):
        """Order without checkout_id should still succeed (no cart to recover)."""
        payload = {"id": 12345}
        response = self.client.post("/webhook/shopify/order", json=payload)
        assert response.status_code == 200

    def test_order_invalid_json(self):
        response = self.client.post(
            "/webhook/shopify/order",
            content="invalid",
            headers={"Content-Type": "application/json"},
        )
        assert response.status_code == 400


# ═══════════════════════════════════════════════════════════════
# 3. DATABASE OPERATIONS
# ═══════════════════════════════════════════════════════════════

class TestAbandonedCartDB:
    """Test database operations for abandoned carts."""

    @pytest.mark.asyncio
    async def test_save_abandoned_checkout(self):
        mock_client = MagicMock()
        mock_table = MagicMock()
        mock_upsert = MagicMock()
        mock_execute = MagicMock()
        mock_execute.data = [{"id": "uuid-test", "shopify_checkout_id": "ck_123"}]

        mock_client.table.return_value = mock_table
        mock_table.upsert.return_value = mock_upsert
        mock_upsert.execute.return_value = mock_execute

        with patch("database.get_supabase", return_value=mock_client):
            from database import save_abandoned_checkout
            result = await save_abandoned_checkout({
                "shopify_checkout_id": "ck_123",
                "customer_phone": "+18091234567",
                "total_price": 1500.0,
            })

        assert result is not None
        mock_table.upsert.assert_called_once()
        # Verify upsert uses on_conflict for idempotency
        call_kwargs = mock_table.upsert.call_args
        assert call_kwargs[1]["on_conflict"] == "shopify_checkout_id"

    @pytest.mark.asyncio
    async def test_save_abandoned_checkout_no_client(self):
        with patch("database.get_supabase", return_value=None):
            from database import save_abandoned_checkout
            result = await save_abandoned_checkout({"shopify_checkout_id": "ck_x"})
        assert result is None

    @pytest.mark.asyncio
    async def test_get_pending_abandoned_carts(self):
        mock_client = MagicMock()
        mock_table = MagicMock()

        # Chain mock: table().select().eq().lt().gte().lte().order().limit().execute()
        chain = MagicMock()
        mock_client.table.return_value = chain
        chain.select.return_value = chain
        chain.eq.return_value = chain
        chain.lt.return_value = chain
        chain.gte.return_value = chain
        chain.lte.return_value = chain
        chain.order.return_value = chain
        chain.limit.return_value = chain

        mock_result = MagicMock()
        mock_result.data = [
            {"id": "cart-1", "customer_phone": "+18091111111", "followup_count": 0},
            {"id": "cart-2", "customer_phone": "+18092222222", "followup_count": 1},
        ]
        chain.execute.return_value = mock_result

        with patch("database.get_supabase", return_value=mock_client):
            from database import get_pending_abandoned_carts
            carts = await get_pending_abandoned_carts(min_age_minutes=30, max_age_hours=48)

        assert len(carts) == 2
        # Verify filters: status=abandoned, followup_count < 3
        chain.eq.assert_called_with("status", "abandoned")
        chain.lt.assert_called_with("followup_count", 3)

    @pytest.mark.asyncio
    async def test_mark_cart_followed_up(self):
        mock_client = MagicMock()
        chain = MagicMock()
        mock_client.table.return_value = chain
        chain.update.return_value = chain
        chain.eq.return_value = chain
        chain.execute.return_value = MagicMock()

        with patch("database.get_supabase", return_value=mock_client):
            from database import mark_cart_followed_up
            result = await mark_cart_followed_up("cart-uuid-1", 2)

        assert result is True
        # Verify it updates followup_count
        update_arg = chain.update.call_args[0][0]
        assert update_arg["followup_count"] == 2
        assert "last_followup_at" in update_arg

    @pytest.mark.asyncio
    async def test_mark_cart_recovered(self):
        mock_client = MagicMock()
        chain = MagicMock()
        mock_client.table.return_value = chain
        chain.update.return_value = chain
        chain.eq.return_value = chain
        chain.execute.return_value = MagicMock()

        with patch("database.get_supabase", return_value=mock_client):
            from database import mark_cart_recovered
            result = await mark_cart_recovered("checkout_abc123")

        assert result is True
        update_arg = chain.update.call_args[0][0]
        assert update_arg["status"] == "recovered"
        chain.eq.assert_called_with("shopify_checkout_id", "checkout_abc123")


# ═══════════════════════════════════════════════════════════════
# 4. FOLLOW-UP PROCESSOR — 3-TOUCH STRATEGY
# ═══════════════════════════════════════════════════════════════

class TestAbandonedCartProcessor:
    """Test _process_abandoned_carts() scheduler logic."""

    def _make_cart(self, followup_count=0, name="María García", total=2500.0):
        return {
            "id": f"cart-{followup_count}",
            "customer_phone": "+18091234567",
            "customer_name": name,
            "total_price": total,
            "currency": "DOP",
            "checkout_url": "https://trendyrd.com/cart/recover/abc123",
            "followup_count": followup_count,
            "line_items": [
                {"name": "Faja Colombiana", "quantity": 1, "price": "1500.00"},
                {"name": "Crema Retinol", "quantity": 2, "price": "500.00"},
            ],
        }

    @pytest.mark.asyncio
    @patch("database.mark_cart_followed_up", new_callable=AsyncMock, return_value=True)
    @patch("database.get_pending_abandoned_carts", new_callable=AsyncMock)
    async def test_fu1_friendly_reminder(self, mock_get_carts, mock_mark):
        """FU1 (first follow-up) should be friendly with product names + cart link."""
        mock_get_carts.return_value = [self._make_cart(followup_count=0)]

        mock_wa = AsyncMock()
        mock_wa.send_text = AsyncMock(return_value=True)

        with patch("main._whatsapp", mock_wa):
            from main import _process_abandoned_carts
            await _process_abandoned_carts()

        mock_wa.send_text.assert_called_once()
        phone, msg = mock_wa.send_text.call_args[0]

        assert phone == "+18091234567"
        assert "María" in msg  # Uses first name
        assert "Faja Colombiana" in msg  # Product names
        assert "Crema Retinol" in msg
        assert "DOP 2,500" in msg  # Total price
        assert "recover/abc123" in msg  # Cart restore link
        assert "👋" in msg or "Hola" in msg.lower()  # Friendly tone
        mock_mark.assert_called_once_with("cart-0", 1)  # Updated to count=1

    @pytest.mark.asyncio
    @patch("database.mark_cart_followed_up", new_callable=AsyncMock, return_value=True)
    @patch("database.get_pending_abandoned_carts", new_callable=AsyncMock)
    async def test_fu2_helpful_urgency(self, mock_get_carts, mock_mark):
        """FU2 (second follow-up) should offer help + urgency."""
        mock_get_carts.return_value = [self._make_cart(followup_count=1)]

        mock_wa = AsyncMock()
        mock_wa.send_text = AsyncMock(return_value=True)

        with patch("main._whatsapp", mock_wa):
            from main import _process_abandoned_carts
            await _process_abandoned_carts()

        phone, msg = mock_wa.send_text.call_args[0]
        assert "duda" in msg.lower() or "ayuda" in msg.lower()  # Offers help
        assert "recover/abc123" in msg  # Cart link
        mock_mark.assert_called_once_with("cart-1", 2)

    @pytest.mark.asyncio
    @patch("database.mark_cart_followed_up", new_callable=AsyncMock, return_value=True)
    @patch("database.get_pending_abandoned_carts", new_callable=AsyncMock)
    async def test_fu3_last_chance(self, mock_get_carts, mock_mark):
        """FU3 (third follow-up) should be soft close / last chance."""
        mock_get_carts.return_value = [self._make_cart(followup_count=2)]

        mock_wa = AsyncMock()
        mock_wa.send_text = AsyncMock(return_value=True)

        with patch("main._whatsapp", mock_wa):
            from main import _process_abandoned_carts
            await _process_abandoned_carts()

        phone, msg = mock_wa.send_text.call_args[0]
        assert "problema" in msg.lower() or "no es el momento" in msg.lower()  # Respectful close
        assert "recover/abc123" in msg  # Still includes link
        mock_mark.assert_called_once_with("cart-2", 3)

    @pytest.mark.asyncio
    @patch("database.get_pending_abandoned_carts", new_callable=AsyncMock, return_value=[])
    async def test_no_pending_carts_no_action(self, mock_get_carts):
        """When no carts pending, should exit gracefully."""
        mock_wa = AsyncMock()
        mock_wa.send_text = AsyncMock()

        with patch("main._whatsapp", mock_wa):
            from main import _process_abandoned_carts
            await _process_abandoned_carts()

        mock_wa.send_text.assert_not_called()

    @pytest.mark.asyncio
    async def test_no_whatsapp_client_skips(self):
        """When WhatsApp client not configured, should skip."""
        with patch("main._whatsapp", None):
            from main import _process_abandoned_carts
            await _process_abandoned_carts()
            # Should not raise

    @pytest.mark.asyncio
    @patch("database.mark_cart_followed_up", new_callable=AsyncMock, return_value=True)
    @patch("database.get_pending_abandoned_carts", new_callable=AsyncMock)
    async def test_multiple_carts_processed(self, mock_get_carts, mock_mark):
        """Multiple carts should each get a follow-up."""
        mock_get_carts.return_value = [
            self._make_cart(followup_count=0),
            {**self._make_cart(followup_count=1), "id": "cart-b", "customer_phone": "+18099999999", "customer_name": "Carlos"},
        ]

        mock_wa = AsyncMock()
        mock_wa.send_text = AsyncMock(return_value=True)

        with patch("main._whatsapp", mock_wa):
            from main import _process_abandoned_carts
            await _process_abandoned_carts()

        assert mock_wa.send_text.call_count == 2
        assert mock_mark.call_count == 2

    @pytest.mark.asyncio
    @patch("database.mark_cart_followed_up", new_callable=AsyncMock, return_value=True)
    @patch("database.get_pending_abandoned_carts", new_callable=AsyncMock)
    async def test_whatsapp_send_failure_does_not_mark(self, mock_get_carts, mock_mark):
        """If WhatsApp send fails, should NOT mark cart as followed up."""
        mock_get_carts.return_value = [self._make_cart(followup_count=0)]

        mock_wa = AsyncMock()
        mock_wa.send_text = AsyncMock(return_value=False)

        with patch("main._whatsapp", mock_wa):
            from main import _process_abandoned_carts
            await _process_abandoned_carts()

        mock_wa.send_text.assert_called_once()
        mock_mark.assert_not_called()  # Should NOT mark on failure

    @pytest.mark.asyncio
    @patch("database.mark_cart_followed_up", new_callable=AsyncMock, return_value=True)
    @patch("database.get_pending_abandoned_carts", new_callable=AsyncMock)
    async def test_fu1_truncates_long_item_lists(self, mock_get_carts, mock_mark):
        """FU1 with 5+ items should show 3 + 'y X más'."""
        cart = self._make_cart(followup_count=0)
        cart["line_items"] = [
            {"name": f"Product {i}", "quantity": 1, "price": "100.00"}
            for i in range(5)
        ]
        mock_get_carts.return_value = [cart]

        mock_wa = AsyncMock()
        mock_wa.send_text = AsyncMock(return_value=True)

        with patch("main._whatsapp", mock_wa):
            from main import _process_abandoned_carts
            await _process_abandoned_carts()

        phone, msg = mock_wa.send_text.call_args[0]
        assert "Product 0" in msg
        assert "Product 1" in msg
        assert "Product 2" in msg
        assert "2 más" in msg  # 5 - 3 = 2 más

    @pytest.mark.asyncio
    @patch("database.mark_cart_followed_up", new_callable=AsyncMock, return_value=True)
    @patch("database.get_pending_abandoned_carts", new_callable=AsyncMock)
    async def test_uses_first_name_only(self, mock_get_carts, mock_mark):
        """Should use first name only (split on space), not full name."""
        mock_get_carts.return_value = [self._make_cart(followup_count=0, name="Ana Beatriz Rodríguez")]

        mock_wa = AsyncMock()
        mock_wa.send_text = AsyncMock(return_value=True)

        with patch("main._whatsapp", mock_wa):
            from main import _process_abandoned_carts
            await _process_abandoned_carts()

        phone, msg = mock_wa.send_text.call_args[0]
        assert "Ana" in msg
        assert "Rodríguez" not in msg

    @pytest.mark.asyncio
    @patch("database.mark_cart_followed_up", new_callable=AsyncMock, return_value=True)
    @patch("database.get_pending_abandoned_carts", new_callable=AsyncMock)
    async def test_no_name_uses_fallback(self, mock_get_carts, mock_mark):
        """When customer_name is empty, should use 'amig@' fallback."""
        mock_get_carts.return_value = [self._make_cart(followup_count=0, name="")]

        mock_wa = AsyncMock()
        mock_wa.send_text = AsyncMock(return_value=True)

        with patch("main._whatsapp", mock_wa):
            from main import _process_abandoned_carts
            await _process_abandoned_carts()

        phone, msg = mock_wa.send_text.call_args[0]
        assert "amig@" in msg


# ═══════════════════════════════════════════════════════════════
# 5. SCHEDULER INTEGRATION
# ═══════════════════════════════════════════════════════════════

class TestSchedulerAbandonedCart:
    """Test that the scheduler properly wires up abandoned cart recovery."""

    @pytest.mark.asyncio
    async def test_scheduler_accepts_abandoned_cart_fn(self):
        from core.scheduler import Scheduler
        s = Scheduler()

        mock_fn = AsyncMock()
        await s.start(abandoned_cart_fn=mock_fn)
        assert s._running is True
        assert len(s._tasks) == 1  # Only abandoned cart task

        await s.stop()

    @pytest.mark.asyncio
    async def test_scheduler_all_tasks(self):
        from core.scheduler import Scheduler
        s = Scheduler()

        await s.start(
            sync_products_fn=AsyncMock(),
            flush_analytics_fn=AsyncMock(),
            cleanup_stale_fn=AsyncMock(),
            abandoned_cart_fn=AsyncMock(),
            send_daily_summary_fn=AsyncMock(),
        )
        assert s._running is True
        assert len(s._tasks) == 5  # All 5 tasks

        await s.stop()


# ═══════════════════════════════════════════════════════════════
# 6. SCHEMA VALIDATION
# ═══════════════════════════════════════════════════════════════

class TestAbandonedCartsSchema:
    """Verify the SQL schema covers all needed fields."""

    def test_schema_file_exists_and_has_required_fields(self):
        import os
        schema_path = os.path.join(
            os.path.dirname(os.path.dirname(__file__)),
            "scripts", "abandoned_carts_schema.sql"
        )
        assert os.path.exists(schema_path), "Schema file missing"

        with open(schema_path, "r", encoding="utf-8") as f:
            sql = f.read()

        # Required columns
        assert "shopify_checkout_id" in sql
        assert "customer_phone" in sql
        assert "customer_name" in sql
        assert "customer_email" in sql
        assert "total_price" in sql
        assert "currency" in sql
        assert "line_items" in sql
        assert "checkout_url" in sql
        assert "status" in sql
        assert "followup_count" in sql
        assert "last_followup_at" in sql
        assert "created_at" in sql

        # Indexes for performance
        assert "idx_abandoned_carts_status" in sql
        assert "idx_abandoned_carts_phone" in sql
        assert "idx_abandoned_carts_created" in sql

        # RLS enabled
        assert "ENABLE ROW LEVEL SECURITY" in sql

        # Status enum constraint
        assert "abandoned" in sql
        assert "recovered" in sql
        assert "expired" in sql

        # UNIQUE constraint on checkout id (for upsert/idempotency)
        assert "UNIQUE" in sql
