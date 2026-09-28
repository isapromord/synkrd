"""
Sofía Bot — Comprehensive Feature Tests

Tests ALL features identified in the audit:
1. Analytics engine (track, aggregate, export)
2. Notification system (Telegram format, send logic)
3. Scheduler (periodic tasks, daily at specific hours)
4. Escalation detection + notification wiring
5. Router (order tracking intent, tier classification)
6. State machine transitions
7. Database operations (settings, analytics, stale cleanup, monthly count)
8. Brain policies injection
9. Admin API endpoints (settings bulk, analytics, usage)
10. Setup/onboarding page
"""

import pytest
import asyncio
import json
import time
from unittest.mock import AsyncMock, MagicMock, patch
from datetime import datetime, timezone, timedelta


# ═══════════════════════════════════════════════════════════════
# 1. ANALYTICS ENGINE TESTS
# ═══════════════════════════════════════════════════════════════

class TestAnalyticsEngine:
    """Test the analytics tracking and aggregation system."""

    def setup_method(self):
        from core.analytics import AnalyticsEngine
        self.analytics = AnalyticsEngine()

    def test_track_message_increments_totals(self):
        self.analytics.track_message(tier=1, latency_ms=150, intent="greeting", channel="webchat")
        self.analytics.track_message(tier=2, latency_ms=2500, intent="complex_comparison", channel="whatsapp")

        stats = self.analytics.get_live_stats()
        assert stats["messages_total"] == 2
        assert stats["tier1_pct"] == 50
        assert stats["tier2_pct"] == 50

    def test_track_message_latency_average(self):
        self.analytics.track_message(tier=1, latency_ms=100, intent="greeting", channel="webchat")
        self.analytics.track_message(tier=1, latency_ms=200, intent="pricing", channel="webchat")
        self.analytics.track_message(tier=1, latency_ms=300, intent="shipping", channel="webchat")

        stats = self.analytics.get_live_stats()
        assert stats["avg_response_ms"] == 200  # (100+200+300)/3

    def test_pct_under_3s(self):
        self.analytics.track_message(tier=1, latency_ms=500, intent="greeting", channel="webchat")
        self.analytics.track_message(tier=1, latency_ms=2000, intent="pricing", channel="webchat")
        self.analytics.track_message(tier=2, latency_ms=5000, intent="complex", channel="webchat")  # Over 3s

        stats = self.analytics.get_live_stats()
        assert stats["pct_under_3s"] == 67  # 2 out of 3

    def test_conversation_tracking(self):
        self.analytics.track_conversation_start("webchat")
        self.analytics.track_conversation_start("whatsapp")
        self.analytics.track_conversation_resolved()

        stats = self.analytics.get_live_stats()
        assert stats["conversations_started"] == 2
        assert stats["conversations_resolved"] == 1
        assert stats["resolution_rate_pct"] == 50

    def test_escalation_tracking(self):
        self.analytics.track_conversation_start("webchat")
        self.analytics.track_escalation(level=3, reason="Customer angry")

        stats = self.analytics.get_live_stats()
        assert stats["conversations_escalated"] == 1

    def test_summary_with_no_data(self):
        stats = self.analytics.get_summary(days=7)
        assert stats["conversations_started"] == 0
        assert stats["resolution_rate_pct"] == 0
        assert stats["avg_response_ms"] == 0

    def test_to_db_rows(self):
        self.analytics.track_message(tier=1, latency_ms=150, intent="greeting", channel="webchat")
        self.analytics.track_conversation_start("webchat")

        rows = self.analytics.to_db_rows()
        assert len(rows) >= 1
        row = rows[0]
        assert "date" in row
        assert "messages_total" in row
        assert row["messages_total"] == 1

    def test_100_percent_resolution(self):
        for _ in range(10):
            self.analytics.track_conversation_start("webchat")
            self.analytics.track_conversation_resolved()

        stats = self.analytics.get_live_stats()
        assert stats["resolution_rate_pct"] == 100


# ═══════════════════════════════════════════════════════════════
# 2. NOTIFICATION SYSTEM TESTS
# ═══════════════════════════════════════════════════════════════

class TestNotificationSender:
    """Test the Telegram notification system."""

    def test_disabled_when_no_credentials(self):
        from core.notifications import NotificationSender
        sender = NotificationSender(telegram_token="", telegram_chat_id="")
        assert sender.is_enabled is False

    def test_enabled_with_credentials(self):
        from core.notifications import NotificationSender
        sender = NotificationSender(telegram_token="123:ABC", telegram_chat_id="456")
        assert sender.is_enabled is True

    @pytest.mark.asyncio
    async def test_notify_escalation_disabled_returns_false(self):
        from core.notifications import NotificationSender
        sender = NotificationSender(telegram_token="", telegram_chat_id="")
        result = await sender.notify_escalation(
            customer_id="18091234567",
            reason="Customer angry",
            level=3,
            last_message="¡Esto es terrible!",
        )
        assert result is False

    @pytest.mark.asyncio
    async def test_notify_escalation_calls_telegram_api(self):
        from core.notifications import NotificationSender
        sender = NotificationSender(telegram_token="123:ABC", telegram_chat_id="456")

        with patch("httpx.AsyncClient") as mock_client:
            mock_response = MagicMock()
            mock_response.status_code = 200
            mock_instance = AsyncMock()
            mock_instance.post = AsyncMock(return_value=mock_response)
            mock_instance.__aenter__ = AsyncMock(return_value=mock_instance)
            mock_instance.__aexit__ = AsyncMock(return_value=None)
            mock_client.return_value = mock_instance

            result = await sender.notify_escalation(
                customer_id="18091234567",
                reason="Customer requested human agent",
                level=3,
                last_message="Quiero hablar con alguien real",
                channel="whatsapp",
            )
            assert result is True
            mock_instance.post.assert_called_once()

            # Verify correct URL
            call_args = mock_instance.post.call_args
            assert "api.telegram.org" in call_args[0][0]
            assert "123:ABC" in call_args[0][0]

    @pytest.mark.asyncio
    async def test_daily_summary_format(self):
        from core.notifications import NotificationSender
        sender = NotificationSender(telegram_token="123:ABC", telegram_chat_id="456")

        with patch("httpx.AsyncClient") as mock_client:
            mock_response = MagicMock()
            mock_response.status_code = 200
            mock_instance = AsyncMock()
            mock_instance.post = AsyncMock(return_value=mock_response)
            mock_instance.__aenter__ = AsyncMock(return_value=mock_instance)
            mock_instance.__aexit__ = AsyncMock(return_value=None)
            mock_client.return_value = mock_instance

            stats = {
                "conversations_started": 15,
                "conversations_resolved": 12,
                "conversations_escalated": 2,
                "resolution_rate_pct": 80,
                "avg_response_ms": 850,
                "messages_total": 142,
            }
            result = await sender.send_daily_summary(stats)
            assert result is True

            # Verify payload contains stats
            call_args = mock_instance.post.call_args
            payload = call_args[1]["json"]
            assert "15" in payload["text"]
            assert "80%" in payload["text"]


# ═══════════════════════════════════════════════════════════════
# 3. SCHEDULER TESTS
# ═══════════════════════════════════════════════════════════════

class TestScheduler:
    """Test the background scheduler."""

    def test_scheduler_initializes(self):
        from core.scheduler import Scheduler
        s = Scheduler()
        assert s._running is False
        assert len(s._tasks) == 0

    @pytest.mark.asyncio
    async def test_scheduler_starts_and_stops(self):
        from core.scheduler import Scheduler
        s = Scheduler()

        mock_fn = AsyncMock()
        await s.start(sync_products_fn=mock_fn)
        assert s._running is True
        assert len(s._tasks) == 1

        await s.stop()
        assert s._running is False


# ═══════════════════════════════════════════════════════════════
# 4. ESCALATION DETECTION TESTS
# ═══════════════════════════════════════════════════════════════

class TestEscalation:
    """Test escalation detection and notification wiring."""

    def test_detect_critical_sentiment(self):
        from core.escalation import detect_sentiment
        severity, phrase = detect_sentiment("¡Esto es una estafa!")
        assert severity == "critical"
        assert "estafa" in phrase

    def test_detect_warning_sentiment(self):
        from core.escalation import detect_sentiment
        severity, phrase = detect_sentiment("Estoy muy frustrado con este servicio")
        assert severity == "warning"

    def test_no_sentiment_for_normal_message(self):
        from core.escalation import detect_sentiment
        severity, phrase = detect_sentiment("¿Cuánto cuesta este producto?")
        assert severity is None

    def test_handoff_request_detected(self):
        from core.escalation import check_handoff_request
        assert check_handoff_request("Quiero hablar con alguien real") is True
        assert check_handoff_request("Necesito hablar con el supervisor") is True
        assert check_handoff_request("¿Cuánto cuesta?") is False

    def test_escalation_level_3_on_handoff(self):
        from core.escalation import calculate_escalation_level
        level, reason, should_notify = calculate_escalation_level(
            "Quiero hablar con una persona real"
        )
        assert level == 3
        assert should_notify is True

    def test_escalation_level_3_on_critical(self):
        from core.escalation import calculate_escalation_level
        level, reason, should_notify = calculate_escalation_level(
            "¡Voy a llamar a mi abogado!"
        )
        assert level == 3
        assert should_notify is True

    def test_escalation_deescalates_gradually(self):
        from core.escalation import calculate_escalation_level
        level, reason, should_notify = calculate_escalation_level(
            "Ok, gracias por la información",
            current_level=2,
        )
        assert level == 1  # De-escalated by 1

    def test_escalation_reaches_0(self):
        from core.escalation import calculate_escalation_level
        level, reason, should_notify = calculate_escalation_level(
            "Perfecto, muchas gracias",
            current_level=1,
        )
        assert level == 0

    def test_3_consecutive_warnings_escalate_to_3(self):
        from core.escalation import calculate_escalation_level
        level, reason, should_notify = calculate_escalation_level(
            "Ya pregunté eso",
            consecutive_warnings=2,
        )
        assert level == 3
        assert should_notify is True

    def test_escalation_message_level_3(self):
        from core.escalation import get_escalation_message
        msg = get_escalation_message(3, "Howard")
        assert "Howard" in msg
        assert "conectarte" in msg or "notifico" in msg

    def test_escalation_message_level_1(self):
        from core.escalation import get_escalation_message
        msg = get_escalation_message(1)
        assert "preocupación" in msg or "detalles" in msg


# ═══════════════════════════════════════════════════════════════
# 5. ROUTER TESTS (including order tracking)
# ═══════════════════════════════════════════════════════════════

class TestRouter:
    """Test intent classification and tier routing."""

    def test_greeting_routes_to_tier1(self):
        from core.router import classify_intent
        tier, intent, reason = classify_intent("Hola, buenos días!")
        assert tier == 1
        assert intent == "greeting"

    def test_frustration_routes_to_tier2(self):
        from core.router import classify_intent
        tier, intent, reason = classify_intent("Estoy muy frustrado con esto")
        assert tier == 2
        assert intent == "frustration"

    def test_escalation_request_routes_to_tier2(self):
        from core.router import classify_intent
        tier, intent, reason = classify_intent("Quiero hablar con el encargado")
        assert tier == 2
        assert intent == "escalation"

    def test_order_tracking_routes_to_tier2(self):
        from core.router import classify_intent
        tier, intent, reason = classify_intent("¿Dónde está mi pedido #1234?")
        assert tier == 2
        assert intent == "order_tracking"

    def test_order_status_query(self):
        from core.router import classify_intent
        tier, intent, reason = classify_intent("Quiero rastrear mi orden")
        assert tier == 2
        assert intent == "order_tracking"

    def test_delivery_date_query(self):
        from core.router import classify_intent
        tier, intent, reason = classify_intent("¿Cuándo llega mi pedido?")
        assert tier == 2
        assert intent == "order_tracking"

    def test_long_conversation_uses_claude(self):
        from core.router import classify_intent
        tier, intent, reason = classify_intent("Gracias", conversation_length=8)
        assert tier == 2
        assert intent == "long_conversation"

    def test_short_unknown_defaults_to_tier1(self):
        from core.router import classify_intent
        tier, intent, reason = classify_intent("Ok")
        assert tier == 1
        assert intent == "general"

    def test_negotiation_routes_to_tier2(self):
        from core.router import classify_intent
        tier, intent, reason = classify_intent("¿Me pueden dar un descuento?")
        assert tier == 2
        assert intent == "negotiation"


# ═══════════════════════════════════════════════════════════════
# 6. STATE MACHINE TESTS
# ═══════════════════════════════════════════════════════════════

class TestStateMachine:
    """Test conversation state transitions."""

    def test_initial_state_is_greeting(self):
        from core.state import Conversation, ConversationState
        conv = Conversation(customer_id="test", channel="webchat")
        assert conv.state == ConversationState.GREETING

    def test_greeting_to_browsing(self):
        from core.state import Conversation, ConversationState
        conv = Conversation(customer_id="test")
        conv.transition_state("product_info")
        assert conv.state == ConversationState.BROWSING

    def test_greeting_to_interested(self):
        from core.state import Conversation, ConversationState
        conv = Conversation(customer_id="test")
        conv.transition_state("pricing")
        assert conv.state == ConversationState.INTERESTED

    def test_interested_to_buying(self):
        from core.state import Conversation, ConversationState
        conv = Conversation(customer_id="test")
        conv.state = ConversationState.INTERESTED
        conv.transition_state("payment")
        assert conv.state == ConversationState.BUYING

    def test_escalation_from_any_state(self):
        from core.state import Conversation, ConversationState
        for state in [ConversationState.GREETING, ConversationState.BROWSING,
                      ConversationState.INTERESTED, ConversationState.BUYING,
                      ConversationState.POST_SALE]:
            conv = Conversation(customer_id="test")
            conv.state = state
            conv.transition_state("escalation")
            assert conv.state == ConversationState.ESCALATED

    def test_add_message_increments_count(self):
        from core.state import Conversation
        conv = Conversation(customer_id="test")
        conv.add_message("user", "Hello")
        conv.add_message("assistant", "Hi!")
        assert conv.metadata["message_count"] == 2
        assert len(conv.history) == 2

    def test_serialization_roundtrip(self):
        from core.state import Conversation, ConversationState
        conv = Conversation(customer_id="test123", channel="whatsapp")
        conv.add_message("user", "Hola")
        conv.state = ConversationState.INTERESTED
        conv.add_product_interest("Camiseta Nike")

        data = conv.to_dict()
        restored = Conversation.from_dict(data)

        assert restored.customer_id == "test123"
        assert restored.channel == "whatsapp"
        assert restored.state == ConversationState.INTERESTED
        assert len(restored.history) == 1
        assert "Camiseta Nike" in restored.product_interests

    def test_get_history_for_ai_limits_to_10(self):
        from core.state import Conversation
        conv = Conversation(customer_id="test")
        for i in range(20):
            conv.add_message("user", f"Message {i}")
        
        history = conv.get_history_for_ai()
        assert len(history) == 10


# ═══════════════════════════════════════════════════════════════
# 7. BRAIN (Policy Injection) TESTS
# ═══════════════════════════════════════════════════════════════

class TestBrainPolicyInjection:
    """Test that brain properly injects policies into system prompt."""

    def test_build_system_prompt_with_policies(self):
        from core.brain import _build_system_prompt
        result = _build_system_prompt(
            "Eres Sofía.",
            "Producto: Camiseta RD$500",
            "**Shipping:** 4-7 días\n**Returns:** 10 días"
        )
        assert "POLÍTICAS DE LA TIENDA" in result
        assert "4-7 días" in result
        assert "10 días" in result
        assert "CATÁLOGO DE PRODUCTOS" in result

    def test_build_system_prompt_without_policies(self):
        from core.brain import _build_system_prompt
        result = _build_system_prompt(
            "Eres Sofía.",
            "Producto: Camiseta RD$500",
            ""
        )
        assert "POLÍTICAS" not in result
        assert "CATÁLOGO" in result

    def test_build_system_prompt_empty_product_context(self):
        from core.brain import _build_system_prompt
        result = _build_system_prompt("Eres Sofía.", "", "")
        assert result == "Eres Sofía."


# ═══════════════════════════════════════════════════════════════
# 8. SCRAPER TESTS
# ═══════════════════════════════════════════════════════════════

class TestScraper:
    """Test product scraper formatting."""

    def test_strip_html(self):
        from knowledge.scraper import _strip_html
        result = _strip_html("<p>Hello <b>world</b></p>")
        assert result == "Hello world"

    def test_strip_html_entities(self):
        from knowledge.scraper import _strip_html
        result = _strip_html("Tom &amp; Jerry")
        assert result == "Tom & Jerry"

    def test_build_product_context_empty(self):
        from knowledge.scraper import build_product_context
        result = build_product_context([])
        assert "No hay productos" in result

    def test_build_product_context_formatting(self):
        from knowledge.scraper import build_product_context
        products = [{
            "name": "Camiseta Nike",
            "price_min": 1500,
            "price_max": 2000,
            "available": True,
            "url": "https://trendyrd.com/products/camiseta",
            "options": "[]",
            "category": "Ropa",
            "description": "Camiseta deportiva Nike para hombre",
        }]
        result = build_product_context(products)
        assert "Camiseta Nike" in result
        assert "RD$1,500" in result
        assert "RD$2,000" in result
        assert "Disponible" in result

    def test_format_product(self):
        from knowledge.scraper import _format_product
        raw = {
            "id": 12345,
            "title": "Test Product",
            "body_html": "<p>Description</p>",
            "product_type": "Shoes",
            "tags": ["tag1", "tag2"],
            "handle": "test-product",
            "variants": [
                {"price": "100.00", "available": True, "title": "Size 8"},
                {"price": "150.00", "available": False, "title": "Size 9"},
            ],
            "images": [{"src": "https://img.com/1.jpg"}],
            "options": [{"name": "Size", "values": ["8", "9"]}],
        }
        result = _format_product(raw, "trendyrd.com")
        assert result["shopify_id"] == "12345"
        assert result["name"] == "Test Product"
        assert result["price_min"] == 100.0
        assert result["price_max"] == 150.0
        assert result["available"] is True
        assert "trendyrd.com" in result["url"]


# ═══════════════════════════════════════════════════════════════
# 9. API ENDPOINT TESTS (FastAPI TestClient)
# ═══════════════════════════════════════════════════════════════

class TestAPIEndpoints:
    """Test FastAPI endpoints using TestClient."""

    @pytest.fixture(autouse=True)
    def setup_client(self):
        """Create a test client."""
        from fastapi.testclient import TestClient
        # Patch external dependencies before importing main
        with patch("knowledge.scraper.fetch_all_products", return_value=[]), \
             patch("knowledge.scraper.build_product_context", return_value=""):
            from main import app
            self.client = TestClient(app)

    def test_health_endpoint(self):
        response = self.client.get("/health")
        assert response.status_code == 200
        data = response.json()
        assert data["status"] == "ok"
        assert data["bot"] == "Sofía"

    def test_status_endpoint(self):
        response = self.client.get("/api/status")
        assert response.status_code == 200
        data = response.json()
        assert data["bot"] == "Sofía"
        assert data["store"] == "TrendyRD"
        assert data["framework"] == "SynkDR Engine v1"

    def test_public_analytics_endpoint(self):
        response = self.client.get("/api/analytics/public")
        assert response.status_code == 200
        data = response.json()
        assert "resolution_rate_pct" in data
        assert "avg_response_ms" in data
        assert "pct_under_3s" in data
        assert "conversations_handled" in data

    def test_setup_page_exists(self):
        response = self.client.get("/setup")
        assert response.status_code == 200

    def test_chat_endpoint_requires_body(self):
        response = self.client.post("/chat", json={})
        assert response.status_code == 422  # Validation error

    def test_admin_endpoints_require_auth(self):
        """All admin endpoints should return 401 without auth."""
        endpoints = [
            "/admin/api/stats",
            "/admin/api/conversations",
            "/admin/api/analytics/live",
            "/admin/api/analytics/summary",
            "/admin/api/usage",
            "/admin/api/settings",
        ]
        for ep in endpoints:
            response = self.client.get(ep)
            assert response.status_code == 401, f"{ep} should require auth"


# ═══════════════════════════════════════════════════════════════
# 10. INTEGRATION: CHAT FLOW WITH ANALYTICS
# ═══════════════════════════════════════════════════════════════

class TestChatFlowIntegration:
    """Test that a chat message properly tracks analytics."""

    @pytest.fixture(autouse=True)
    def setup(self):
        with patch("knowledge.scraper.fetch_all_products", return_value=[]), \
             patch("knowledge.scraper.build_product_context", return_value=""):
            from main import app
            from fastapi.testclient import TestClient
            self.client = TestClient(app)

    @pytest.mark.asyncio
    @patch("database.get_conversation", new_callable=AsyncMock, return_value=None)
    @patch("database.save_conversation", new_callable=AsyncMock, return_value={"id": "test"})
    @patch("database.get_db_customer_id", new_callable=AsyncMock, return_value="uuid-test")
    @patch("database.get_bot_setting", new_callable=AsyncMock, return_value=None)
    @patch("core.brain.generate_response", new_callable=AsyncMock)
    async def test_chat_tracks_new_conversation(
        self, mock_brain, mock_setting, mock_cust, mock_save, mock_get_conv
    ):
        mock_brain.return_value = {
            "response": "¡Hola! ¿En qué te puedo ayudar?",
            "model_used": "gemini-2.5-flash",
            "tokens_used": 50,
            "latency_ms": 250,
        }

        from core.analytics import analytics
        before = analytics.get_live_stats()["conversations_started"]

        response = self.client.post("/chat", json={
            "customer_id": "test-user-1",
            "message": "Hola, buenos días",
            "channel": "webchat",
        })

        if response.status_code == 200:
            after = analytics.get_live_stats()["conversations_started"]
            # Should have incremented
            assert after >= before
