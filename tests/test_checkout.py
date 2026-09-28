"""
Tests for In-Chat Checkout Flow (COD)

Tests: product matching, variant selection, address extraction,
confirmation detection, checkout messages, checkout flow state machine,
Shopify draft order creation.
"""

import pytest
import re
from unittest.mock import AsyncMock, patch, MagicMock

from core.checkout import (
    CheckoutSession, CheckoutStep,
    find_product_in_catalog, pick_variant, format_variant_options,
    extract_address_from_message, is_address_sufficient, detect_confirmation,
    build_product_confirm_message, build_variant_selection_message,
    build_order_summary_message, build_order_complete_message, build_cancel_message,
)


# ═══════════════════════════════════════════════════════════════
# TEST DATA
# ═══════════════════════════════════════════════════════════════

SAMPLE_CATALOG = [
    {
        "name": "Faja Colombiana Premium",
        "shopify_id": "100",
        "available": True,
        "price_min": 1500,
        "price_max": 1500,
        "variants_detail": [
            {"id": "1001", "title": "S", "price": 1500, "inventory_quantity": 5, "available": True},
            {"id": "1002", "title": "M", "price": 1500, "inventory_quantity": 3, "available": True},
            {"id": "1003", "title": "L", "price": 1500, "inventory_quantity": 0, "available": False},
        ],
    },
    {
        "name": "Crema Facial Vitamina C",
        "shopify_id": "200",
        "available": True,
        "price_min": 890,
        "price_max": 890,
        "variants_detail": [
            {"id": "2001", "title": "Default Title", "price": 890, "inventory_quantity": 20, "available": True},
        ],
    },
    {
        "name": "Parlante Bluetooth LED",
        "shopify_id": "300",
        "available": True,
        "price_min": 2200,
        "price_max": 2200,
        "variants_detail": [
            {"id": "3001", "title": "Negro", "price": 2200, "inventory_quantity": 8, "available": True},
            {"id": "3002", "title": "Azul", "price": 2200, "inventory_quantity": 2, "available": True},
        ],
    },
    {
        "name": "Combo Belleza Total",
        "shopify_id": "400",
        "available": False,
        "price_min": 3500,
        "price_max": 3500,
        "variants_detail": [
            {"id": "4001", "title": "Default Title", "price": 3500, "inventory_quantity": 0, "available": False},
        ],
    },
]


# ═══════════════════════════════════════════════════════════════
# PRODUCT MATCHING TESTS
# ═══════════════════════════════════════════════════════════════

class TestProductMatching:
    """Test find_product_in_catalog."""

    def test_exact_name_match(self):
        result = find_product_in_catalog("quiero la Faja Colombiana Premium", [], SAMPLE_CATALOG)
        assert result is not None
        assert result["name"] == "Faja Colombiana Premium"

    def test_partial_name_match(self):
        result = find_product_in_catalog("tienen crema facial", [], SAMPLE_CATALOG)
        assert result is not None
        assert result["name"] == "Crema Facial Vitamina C"

    def test_keyword_match(self):
        result = find_product_in_catalog("quiero el parlante bluetooth", [], SAMPLE_CATALOG)
        assert result is not None
        assert result["name"] == "Parlante Bluetooth LED"

    def test_no_match(self):
        result = find_product_in_catalog("hola buenos días", [], SAMPLE_CATALOG)
        assert result is None

    def test_match_from_conversation_history(self):
        """If AI recently mentioned a product, it should be found."""
        history = [
            {"role": "user", "content": "qué productos tienen?"},
            {"role": "assistant", "content": "Tenemos la Crema Facial Vitamina C a RD$890..."},
        ]
        result = find_product_in_catalog("me lo llevo", history, SAMPLE_CATALOG)
        assert result is not None
        assert result["name"] == "Crema Facial Vitamina C"

    def test_empty_catalog(self):
        result = find_product_in_catalog("quiero comprar algo", [], [])
        assert result is None


# ═══════════════════════════════════════════════════════════════
# VARIANT SELECTION TESTS
# ═══════════════════════════════════════════════════════════════

class TestVariantSelection:
    """Test pick_variant."""

    def test_single_variant_product(self):
        """Product with one variant should auto-select."""
        product = SAMPLE_CATALOG[1]  # Crema — single variant
        result = pick_variant(product)
        assert result is not None
        assert result["id"] == "2001"

    def test_multi_variant_no_message(self):
        """Multiple variants without message should return None (ask user)."""
        product = SAMPLE_CATALOG[0]  # Faja — S, M, L
        result = pick_variant(product)
        assert result is None

    def test_multi_variant_match_from_message(self):
        """Variant mentioned in message should match."""
        product = SAMPLE_CATALOG[0]
        result = pick_variant(product, "quiero la M")
        assert result is not None
        assert result["title"] == "M"

    def test_skip_unavailable_variants(self):
        """Should not pick unavailable variants."""
        product = SAMPLE_CATALOG[0]
        result = pick_variant(product, "quiero la L")  # L is out of stock
        assert result is None  # L not available

    def test_color_variant_match(self):
        """Color variants should match."""
        product = SAMPLE_CATALOG[2]  # Parlante — Negro, Azul
        result = pick_variant(product, "el azul")
        assert result is not None
        assert result["title"] == "Azul"

    def test_all_out_of_stock(self):
        """Product with no available variants returns None."""
        product = SAMPLE_CATALOG[3]  # Combo — out of stock
        result = pick_variant(product)
        assert result is None


class TestFormatVariantOptions:
    """Test format_variant_options."""

    def test_multi_variant_format(self):
        product = SAMPLE_CATALOG[0]  # Faja with S, M, L (L unavailable)
        result = format_variant_options(product)
        assert "S" in result
        assert "M" in result
        assert "L" not in result  # Out of stock
        assert "RD$" in result

    def test_single_default_variant(self):
        product = SAMPLE_CATALOG[1]  # Crema — Default Title
        result = format_variant_options(product)
        assert result == ""  # Should return empty for single default variant

    def test_low_stock_tags(self):
        product = SAMPLE_CATALOG[2]  # Parlante — Azul has 2 units
        result = format_variant_options(product)
        assert "🔥" in result  # Azul has 2 units (≤3)


# ═══════════════════════════════════════════════════════════════
# ADDRESS EXTRACTION TESTS
# ═══════════════════════════════════════════════════════════════

class TestAddressExtraction:
    """Test extract_address_from_message."""

    def test_full_address(self):
        addr = extract_address_from_message("Calle 5 #23, Piantini, Santo Domingo")
        assert addr.get("address1")
        assert addr.get("city") == "Santo Domingo"
        assert addr.get("country") == "DO"

    def test_sector_detection(self):
        addr = extract_address_from_message("Vivo en Naco, calle 3")
        assert "city" in addr
        assert addr["city"] == "Santo Domingo"  # Naco is in SD

    def test_city_detection(self):
        addr = extract_address_from_message("Me quedo en Santiago, calle del sol #45")
        assert addr.get("city") == "Santiago"

    def test_strip_prefix(self):
        addr = extract_address_from_message("Mi dirección es Av. Winston Churchill 234")
        assert addr["address1"]
        assert not addr["address1"].lower().startswith("mi dirección")

    def test_minimal_address(self):
        addr = extract_address_from_message("calle 5 numero 12")
        assert addr.get("address1")
        assert addr.get("country") == "DO"


class TestAddressSufficiency:
    """Test is_address_sufficient."""

    def test_sufficient_address(self):
        assert is_address_sufficient({"address1": "Calle 5 #23, Piantini"}) is True

    def test_insufficient_empty(self):
        assert is_address_sufficient({}) is False
        assert is_address_sufficient({"address1": ""}) is False

    def test_insufficient_too_short(self):
        assert is_address_sufficient({"address1": "Abc"}) is False


# ═══════════════════════════════════════════════════════════════
# CONFIRMATION DETECTION TESTS
# ═══════════════════════════════════════════════════════════════

class TestConfirmationDetection:
    """Test detect_confirmation."""

    @pytest.mark.parametrize("msg", [
        "sí", "si", "dale", "confirmo", "listo", "ok", "va",
        "claro", "perfecto", "adelante", "lo quiero",
        "sí confirmo", "dale procede",
    ])
    def test_positive_confirmations(self, msg):
        assert detect_confirmation(msg) is True

    @pytest.mark.parametrize("msg", [
        "no", "cancel", "déjalo", "olvídalo", "mejor no",
        "no quiero", "cambié de opinión", "otro día",
    ])
    def test_negative_confirmations(self, msg):
        assert detect_confirmation(msg) is False

    def test_ambiguous_responses(self):
        assert detect_confirmation("cuánto cuesta el envío?") is None
        assert detect_confirmation("y aceptan tarjeta?") is None
        assert detect_confirmation("déjame pensarlo") is None


# ═══════════════════════════════════════════════════════════════
# CHECKOUT MESSAGE FORMATTING TESTS
# ═══════════════════════════════════════════════════════════════

class TestCheckoutMessages:
    """Test message builder functions."""

    def test_product_confirm_message(self):
        msg = build_product_confirm_message("Faja Colombiana", "M", 1500)
        assert "Faja Colombiana" in msg
        assert "M" in msg
        assert "1,500" in msg
        assert "dirección" in msg.lower()
        assert "recibirlo" in msg.lower()

    def test_product_confirm_no_variant(self):
        msg = build_product_confirm_message("Crema Facial", "Default Title", 890)
        assert "Default Title" not in msg  # Should hide default variant
        assert "890" in msg

    def test_variant_selection_message(self):
        msg = build_variant_selection_message("Faja", "  • S — RD$1,500\n  • M — RD$1,500")
        assert "Faja" in msg
        assert "S" in msg
        assert "M" in msg
        assert "prefieres" in msg.lower()

    def test_order_summary_message(self):
        session = CheckoutSession(
            product_name="Parlante Bluetooth LED",
            variant_title="Azul",
            price=2200,
            quantity=1,
            address={"address1": "Calle 5 #23, Piantini", "city": "Santo Domingo"},
        )
        msg = build_order_summary_message(session)
        assert "Parlante Bluetooth LED" in msg
        assert "Azul" in msg
        assert "2,200" in msg
        assert "Piantini" in msg
        assert "Confirmas" in msg

    def test_order_complete_message(self):
        msg = build_order_complete_message("#1045", "2200")
        assert "#1045" in msg
        assert "2,200" in msg
        assert "recibirlo" in msg.lower()
        assert "días" in msg.lower()

    def test_cancel_message(self):
        msg = build_cancel_message()
        assert "cancelado" in msg.lower()


# ═══════════════════════════════════════════════════════════════
# CHECKOUT SESSION SERIALIZATION
# ═══════════════════════════════════════════════════════════════

class TestCheckoutSession:
    """Test CheckoutSession to_dict / from_dict."""

    def test_round_trip(self):
        session = CheckoutSession(
            step=CheckoutStep.ADDRESS_COLLECT,
            product_name="Faja",
            variant_id="1001",
            price=1500,
            customer_phone="+18091234567",
        )
        data = session.to_dict()
        restored = CheckoutSession.from_dict(data)
        assert restored.step == CheckoutStep.ADDRESS_COLLECT
        assert restored.product_name == "Faja"
        assert restored.variant_id == "1001"
        assert restored.price == 1500

    def test_from_empty_dict(self):
        session = CheckoutSession.from_dict({})
        assert session.step == CheckoutStep.IDLE

    def test_from_none(self):
        session = CheckoutSession.from_dict(None)
        assert session.step == CheckoutStep.IDLE


# ═══════════════════════════════════════════════════════════════
# SHOPIFY DRAFT ORDER TESTS
# ═══════════════════════════════════════════════════════════════

class TestShopifyDraftOrder:
    """Test ShopifyKnowledge.create_draft_order."""

    @pytest.mark.asyncio
    async def test_create_draft_order_success(self):
        """Successful draft order creation."""
        from knowledge.shopify import ShopifyKnowledge

        mock_response = MagicMock()
        mock_response.status_code = 200
        mock_response.raise_for_status = MagicMock()
        mock_response.json.return_value = {
            "draft_order": {
                "id": 99999,
                "name": "#D123",
                "total_price": "1500.00",
                "currency": "DOP",
                "status": "open",
                "invoice_url": "https://trendyrd.com/...",
                "line_items": [
                    {"title": "Faja Colombiana", "quantity": 1, "price": "1500.00"}
                ],
            }
        }

        shopify = ShopifyKnowledge("test.com", "fake-token")

        with patch("httpx.AsyncClient") as mock_client_cls:
            mock_client = AsyncMock()
            mock_client.post = AsyncMock(return_value=mock_response)
            mock_client.__aenter__ = AsyncMock(return_value=mock_client)
            mock_client.__aexit__ = AsyncMock(return_value=False)
            mock_client_cls.return_value = mock_client

            result = await shopify.create_draft_order(
                line_items=[{"variant_id": "1001", "quantity": 1}],
                shipping_address={"address1": "Calle 5, Piantini", "city": "Santo Domingo"},
                customer_phone="+18091234567",
                customer_name="Juan Pérez",
            )

        assert result is not None
        assert result["draft_order_id"] == "99999"
        assert result["order_name"] == "#D123"
        assert result["total_price"] == "1500.00"

    @pytest.mark.asyncio
    async def test_create_draft_order_api_failure(self):
        """API error should return None, not crash."""
        from knowledge.shopify import ShopifyKnowledge
        import httpx

        mock_response = MagicMock()
        mock_response.status_code = 422
        mock_response.text = "Unprocessable Entity"
        mock_response.raise_for_status.side_effect = httpx.HTTPStatusError(
            "422", request=MagicMock(), response=mock_response
        )

        shopify = ShopifyKnowledge("test.com", "fake-token")

        with patch("httpx.AsyncClient") as mock_client_cls:
            mock_client = AsyncMock()
            mock_client.post = AsyncMock(return_value=mock_response)
            mock_client.__aenter__ = AsyncMock(return_value=mock_client)
            mock_client.__aexit__ = AsyncMock(return_value=False)
            mock_client_cls.return_value = mock_client

            result = await shopify.create_draft_order(
                line_items=[{"variant_id": "1001", "quantity": 1}],
                shipping_address={"address1": "Calle 5"},
                customer_phone="+18091234567",
            )

        assert result is None

    @pytest.mark.asyncio
    async def test_complete_draft_order_success(self):
        """Complete a draft order (convert to real order)."""
        from knowledge.shopify import ShopifyKnowledge

        mock_response = MagicMock()
        mock_response.status_code = 200
        mock_response.raise_for_status = MagicMock()
        mock_response.json.return_value = {
            "draft_order": {
                "id": 99999,
                "name": "#1045",
                "order_id": 88888,
                "status": "completed",
            }
        }

        shopify = ShopifyKnowledge("test.com", "fake-token")

        with patch("httpx.AsyncClient") as mock_client_cls:
            mock_client = AsyncMock()
            mock_client.put = AsyncMock(return_value=mock_response)
            mock_client.__aenter__ = AsyncMock(return_value=mock_client)
            mock_client.__aexit__ = AsyncMock(return_value=False)
            mock_client_cls.return_value = mock_client

            result = await shopify.complete_draft_order("99999")

        assert result is not None
        assert result["order_id"] == "88888"
        assert result["status"] == "completed"


# ═══════════════════════════════════════════════════════════════
# CHECKOUT FLOW STATE MACHINE TESTS
# ═══════════════════════════════════════════════════════════════

class TestCheckoutFlowIntegration:
    """Test the full checkout flow via _handle_checkout_flow."""

    @pytest.fixture
    def mock_products(self):
        """Inject products into main module."""
        import main
        original = main._products_raw
        main._products_raw = SAMPLE_CATALOG
        yield
        main._products_raw = original

    @pytest.fixture
    def conversation(self):
        """Create a fresh conversation."""
        from core.state import Conversation
        conv = Conversation(customer_id="+18091234567", channel="whatsapp")
        return conv

    @pytest.mark.asyncio
    async def test_purchase_intent_starts_checkout_single_variant(self, mock_products, conversation):
        """Purchase intent with single-variant product → address collection."""
        from main import _handle_checkout_flow

        conversation.history = [
            {"role": "user", "content": "qué cremas tienen?"},
            {"role": "assistant", "content": "Tenemos la Crema Facial Vitamina C a RD$890"},
            {"role": "user", "content": "me la llevo"},
        ]

        result = await _handle_checkout_flow(
            message="me la llevo",
            conversation=conversation,
            intent="purchase",
            customer_phone="+18091234567",
        )

        assert result is not None
        assert "890" in result
        assert "dirección" in result.lower()
        checkout = conversation.metadata.get("checkout", {})
        assert checkout["step"] == "address_collect"

    @pytest.mark.asyncio
    async def test_purchase_intent_multi_variant_asks_selection(self, mock_products, conversation):
        """Multi-variant product → asks which variant."""
        from main import _handle_checkout_flow

        conversation.history = [
            {"role": "assistant", "content": "La Faja Colombiana Premium a RD$1,500"},
        ]

        result = await _handle_checkout_flow(
            message="lo quiero",
            conversation=conversation,
            intent="purchase",
            customer_phone="+18091234567",
        )

        assert result is not None
        assert "S" in result
        assert "M" in result
        checkout = conversation.metadata.get("checkout", {})
        assert checkout["step"] == "product_confirm"

    @pytest.mark.asyncio
    async def test_variant_selection_then_address(self, mock_products, conversation):
        """After selecting variant → moves to address collection."""
        from main import _handle_checkout_flow

        # Simulate being in product_confirm step
        conversation.metadata["checkout"] = CheckoutSession(
            step=CheckoutStep.PRODUCT_CONFIRM,
            product_name="Faja Colombiana Premium",
        ).to_dict()

        result = await _handle_checkout_flow(
            message="quiero la M",
            conversation=conversation,
            intent="purchase",
            customer_phone="+18091234567",
        )

        assert result is not None
        assert "1,500" in result
        assert "dirección" in result.lower()
        checkout = conversation.metadata.get("checkout", {})
        assert checkout["step"] == "address_collect"
        assert checkout["variant_title"] == "M"

    @pytest.mark.asyncio
    async def test_address_collection_shows_summary(self, mock_products, conversation):
        """After giving address → shows order summary."""
        from main import _handle_checkout_flow

        conversation.metadata["checkout"] = CheckoutSession(
            step=CheckoutStep.ADDRESS_COLLECT,
            product_name="Crema Facial Vitamina C",
            variant_id="2001",
            variant_title="Default Title",
            price=890,
        ).to_dict()

        result = await _handle_checkout_flow(
            message="Calle 5 #23, Piantini, Santo Domingo",
            conversation=conversation,
            intent="general",
            customer_phone="+18091234567",
        )

        assert result is not None
        assert "Crema Facial" in result
        assert "890" in result
        assert "Confirmas" in result
        checkout = conversation.metadata.get("checkout", {})
        assert checkout["step"] == "order_confirm"

    @pytest.mark.asyncio
    async def test_confirmation_creates_order(self, mock_products, conversation):
        """Confirming order → creates Shopify draft order."""
        from main import _handle_checkout_flow

        conversation.metadata["checkout"] = CheckoutSession(
            step=CheckoutStep.ORDER_CONFIRM,
            product_name="Crema Facial Vitamina C",
            variant_id="2001",
            variant_title="Default Title",
            price=890,
            customer_phone="+18091234567",
            address={"address1": "Calle 5 #23, Piantini", "city": "Santo Domingo"},
        ).to_dict()

        with patch("main._create_shopify_order", new_callable=AsyncMock) as mock_create, \
             patch("main.db.save_chat_order", new_callable=AsyncMock) as mock_save, \
             patch("main._notifier", None):
            mock_create.return_value = {
                "draft_order_id": "99999",
                "order_name": "#1045",
                "total_price": "890",
            }

            result = await _handle_checkout_flow(
                message="sí confirmo",
                conversation=conversation,
                intent="general",
                customer_phone="+18091234567",
            )

        assert result is not None
        assert "#1045" in result
        assert "890" in result
        mock_create.assert_called_once()
        mock_save.assert_called_once()

    @pytest.mark.asyncio
    async def test_cancellation_resets_checkout(self, mock_products, conversation):
        """Saying 'no' during confirmation → cancels checkout."""
        from main import _handle_checkout_flow

        conversation.metadata["checkout"] = CheckoutSession(
            step=CheckoutStep.ORDER_CONFIRM,
            product_name="Crema Facial",
            variant_id="2001",
            price=890,
        ).to_dict()

        result = await _handle_checkout_flow(
            message="no, mejor no",
            conversation=conversation,
            intent="general",
            customer_phone="+18091234567",
        )

        assert result is not None
        assert "cancelado" in result.lower()
        checkout = conversation.metadata.get("checkout", {})
        assert checkout["step"] == "idle"

    @pytest.mark.asyncio
    async def test_cancel_during_address_collection(self, mock_products, conversation):
        """Cancel during address step."""
        from main import _handle_checkout_flow

        conversation.metadata["checkout"] = CheckoutSession(
            step=CheckoutStep.ADDRESS_COLLECT,
            product_name="Crema Facial",
            variant_id="2001",
            price=890,
        ).to_dict()

        result = await _handle_checkout_flow(
            message="déjalo, no quiero",
            conversation=conversation,
            intent="general",
            customer_phone="+18091234567",
        )

        assert result is not None
        assert "cancelado" in result.lower()

    @pytest.mark.asyncio
    async def test_no_product_match_returns_none(self, mock_products, conversation):
        """Purchase intent with no matching product → returns None (normal AI)."""
        from main import _handle_checkout_flow

        result = await _handle_checkout_flow(
            message="quiero comprar algo bonito",
            conversation=conversation,
            intent="purchase",
            customer_phone="+18091234567",
        )

        assert result is None  # Falls through to normal AI

    @pytest.mark.asyncio
    async def test_unavailable_product_returns_none(self, mock_products, conversation):
        """Purchase intent for out-of-stock product → returns None."""
        from main import _handle_checkout_flow

        conversation.history = [
            {"role": "assistant", "content": "El Combo Belleza Total está agotado"},
        ]

        result = await _handle_checkout_flow(
            message="quiero el combo belleza total",
            conversation=conversation,
            intent="purchase",
            customer_phone="+18091234567",
        )

        assert result is None

    @pytest.mark.asyncio
    async def test_shopify_failure_graceful(self, mock_products, conversation):
        """Shopify API failure → graceful error message."""
        from main import _handle_checkout_flow

        conversation.metadata["checkout"] = CheckoutSession(
            step=CheckoutStep.ORDER_CONFIRM,
            product_name="Crema Facial",
            variant_id="2001",
            price=890,
            customer_phone="+18091234567",
            address={"address1": "Calle 5 #23"},
        ).to_dict()

        with patch("main._create_shopify_order", new_callable=AsyncMock) as mock_create:
            mock_create.return_value = None  # Shopify failed

            result = await _handle_checkout_flow(
                message="sí",
                conversation=conversation,
                intent="general",
                customer_phone="+18091234567",
            )

        assert result is not None
        assert "inconveniente" in result.lower()
        checkout = conversation.metadata.get("checkout", {})
        assert checkout["step"] == "idle"  # Reset after failure


# ═══════════════════════════════════════════════════════════════
# ROUTER PURCHASE INTENT TESTS
# ═══════════════════════════════════════════════════════════════

class TestRouterPurchaseIntent:
    """Ensure purchase keywords are properly detected."""

    @pytest.mark.parametrize("msg", [
        "lo quiero",
        "me lo llevo",
        "quiero comprar",
        "te lo pido",
        "esa misma",
        "ese mismo",
        "sepáramelo",
    ])
    def test_purchase_intent_detected(self, msg):
        from core.router import classify_intent
        tier, intent, reason = classify_intent(msg)
        assert intent == "purchase", f"'{msg}' should detect purchase intent, got '{intent}'"


# ═══════════════════════════════════════════════════════════════
# STATE MACHINE TRANSITION TESTS
# ═══════════════════════════════════════════════════════════════

class TestStateMachineBuying:
    """Test that purchase intent triggers BUYING state from all relevant states."""

    def test_greeting_to_buying(self):
        from core.state import Conversation, ConversationState
        conv = Conversation(customer_id="test")
        conv.state = ConversationState.GREETING
        new = conv.transition_state("purchase")
        assert new == ConversationState.BUYING

    def test_browsing_to_buying(self):
        from core.state import Conversation, ConversationState
        conv = Conversation(customer_id="test")
        conv.state = ConversationState.BROWSING
        new = conv.transition_state("purchase")
        assert new == ConversationState.BUYING

    def test_interested_to_buying(self):
        from core.state import Conversation, ConversationState
        conv = Conversation(customer_id="test")
        conv.state = ConversationState.INTERESTED
        new = conv.transition_state("purchase")
        assert new == ConversationState.BUYING
