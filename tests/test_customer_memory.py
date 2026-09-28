"""
Tests for Customer Memory (persistent customer profiles).

Tests: context building, auto-learning from checkout, checkout pre-fill,
category detection, size preference tracking, profile round-trip.
"""

import pytest
from unittest.mock import AsyncMock, patch, MagicMock
from datetime import datetime, timezone

from core.customer_memory import (
    build_customer_context,
    learn_from_checkout,
    prefill_checkout_from_profile,
    get_saved_size_for_product,
    _detect_category,
    _simplify_product_name,
    CATEGORY_KEYWORDS,
)
from core.checkout import CheckoutSession, CheckoutStep


# ═══════════════════════════════════════════════════════════════
# TEST DATA
# ═══════════════════════════════════════════════════════════════

EMPTY_PROFILE = {}

NEW_CUSTOMER_PROFILE = {
    "phone": "+18091234567",
    "name": None,
    "default_address": {},
    "total_orders": 0,
    "total_spent": 0,
    "preferred_sizes": {},
    "preferred_categories": [],
    "product_history": [],
}

RETURNING_CUSTOMER_PROFILE = {
    "phone": "+18091234567",
    "name": "María González",
    "default_address": {
        "address1": "Calle 5 #23, Piantini",
        "city": "Santo Domingo",
        "province": "Santo Domingo",
        "country": "DO",
    },
    "total_orders": 3,
    "total_spent": 4500.00,
    "last_order_date": "2026-04-10T14:30:00+00:00",
    "preferred_sizes": {"faja": "M", "crema": "Default Title"},
    "preferred_categories": ["belleza", "fajas"],
    "product_history": [
        {"name": "Crema Facial Vitamina C", "variant": "Default Title", "price": 890, "date": "2026-03-15"},
        {"name": "Faja Colombiana Premium", "variant": "M", "price": 1500, "date": "2026-04-01"},
        {"name": "Sérum Anti-edad", "variant": "Default Title", "price": 1200, "date": "2026-04-10"},
    ],
    "first_seen": "2026-03-15T10:00:00+00:00",
    "last_seen": "2026-04-10T14:30:00+00:00",
    "channel": "whatsapp",
}


# ═══════════════════════════════════════════════════════════════
# CONTEXT BUILDING TESTS
# ═══════════════════════════════════════════════════════════════

class TestBuildCustomerContext:
    """Test build_customer_context for AI prompt injection."""

    def test_empty_profile_returns_empty(self):
        assert build_customer_context(None) == ""
        assert build_customer_context({}) == ""

    def test_new_customer_no_data(self):
        result = build_customer_context(NEW_CUSTOMER_PROFILE)
        assert result == ""  # No useful info to inject

    def test_returning_customer_has_name(self):
        result = build_customer_context(RETURNING_CUSTOMER_PROFILE)
        assert "María González" in result

    def test_returning_customer_has_address(self):
        result = build_customer_context(RETURNING_CUSTOMER_PROFILE)
        assert "Piantini" in result

    def test_returning_customer_has_order_count(self):
        result = build_customer_context(RETURNING_CUSTOMER_PROFILE)
        assert "3 pedido" in result
        assert "4,500" in result

    def test_returning_customer_has_recent_purchases(self):
        result = build_customer_context(RETURNING_CUSTOMER_PROFILE)
        assert "Sérum Anti-edad" in result

    def test_returning_customer_has_sizes(self):
        result = build_customer_context(RETURNING_CUSTOMER_PROFILE)
        assert "faja: M" in result

    def test_returning_customer_has_categories(self):
        result = build_customer_context(RETURNING_CUSTOMER_PROFILE)
        assert "belleza" in result

    def test_context_has_privacy_header(self):
        result = build_customer_context(RETURNING_CUSTOMER_PROFILE)
        assert "MEMORIA DEL CLIENTE" in result
        assert "NO la repitas" in result

    def test_partial_profile_name_only(self):
        profile = {"name": "Juan", "total_orders": 0}
        result = build_customer_context(profile)
        assert "Juan" in result
        assert "pedido" not in result


# ═══════════════════════════════════════════════════════════════
# AUTO-LEARN FROM CHECKOUT
# ═══════════════════════════════════════════════════════════════

class TestLearnFromCheckout:
    """Test learn_from_checkout auto-learning."""

    def _make_session(self, **kwargs):
        defaults = {
            "step": CheckoutStep.COMPLETED,
            "product_name": "Faja Colombiana Premium",
            "variant_id": "1001",
            "variant_title": "M",
            "price": 1500,
            "quantity": 1,
            "customer_name": "María González",
            "customer_phone": "+18091234567",
            "address": {"address1": "Calle 5 #23, Piantini", "city": "Santo Domingo", "country": "DO"},
        }
        defaults.update(kwargs)
        return CheckoutSession(**defaults)

    def test_first_order_creates_profile(self):
        session = self._make_session()
        updates = learn_from_checkout(None, session)

        assert updates["name"] == "María González"
        assert updates["default_address"]["city"] == "Santo Domingo"
        assert updates["total_orders"] == 1
        assert updates["total_spent"] == 1500
        assert len(updates["product_history"]) == 1
        assert updates["product_history"][0]["name"] == "Faja Colombiana Premium"

    def test_returning_customer_increments(self):
        session = self._make_session(product_name="Crema Facial Vitamina C", variant_title="Default Title", price=890)
        updates = learn_from_checkout(RETURNING_CUSTOMER_PROFILE, session)

        assert updates["total_orders"] == 4  # Was 3
        assert updates["total_spent"] == 5390  # Was 4500 + 890

    def test_learns_size_preference(self):
        session = self._make_session()
        updates = learn_from_checkout(None, session)

        assert "preferred_sizes" in updates
        assert updates["preferred_sizes"]["faja"] == "M"

    def test_default_title_not_saved_as_size(self):
        session = self._make_session(variant_title="Default Title")
        updates = learn_from_checkout(None, session)

        # "Default Title" shouldn't be saved as a size preference
        sizes = updates.get("preferred_sizes", {})
        for v in sizes.values():
            assert v != "Default Title"

    def test_learns_category(self):
        session = self._make_session()
        updates = learn_from_checkout(None, session)

        assert "fajas" in updates.get("preferred_categories", [])

    def test_product_history_keeps_last_10(self):
        # Start with 10 existing products
        profile = {
            "total_orders": 10,
            "total_spent": 15000,
            "product_history": [
                {"name": f"Product {i}", "variant": "X", "price": 100, "date": "2026-01-01"}
                for i in range(10)
            ],
        }
        session = self._make_session()
        updates = learn_from_checkout(profile, session)

        assert len(updates["product_history"]) == 10  # Still 10 (oldest dropped)
        assert updates["product_history"][-1]["name"] == "Faja Colombiana Premium"
        assert updates["product_history"][0]["name"] == "Product 1"  # Product 0 dropped

    def test_address_always_updates(self):
        session = self._make_session(
            address={"address1": "New Street 99", "city": "Santiago", "country": "DO"}
        )
        updates = learn_from_checkout(RETURNING_CUSTOMER_PROFILE, session)
        assert updates["default_address"]["city"] == "Santiago"

    def test_phone_not_saved_as_name(self):
        session = self._make_session(customer_name="+18091234567", customer_phone="+18091234567")
        updates = learn_from_checkout(None, session)
        assert "name" not in updates  # Phone shouldn't be saved as name


# ═══════════════════════════════════════════════════════════════
# CHECKOUT PRE-FILL TESTS
# ═══════════════════════════════════════════════════════════════

class TestPrefillCheckout:
    """Test prefill_checkout_from_profile for checkout shortcuts."""

    def test_no_profile_returns_false(self):
        session = CheckoutSession()
        assert prefill_checkout_from_profile(None, session) is False
        assert prefill_checkout_from_profile({}, session) is False

    def test_prefills_address(self):
        session = CheckoutSession()
        result = prefill_checkout_from_profile(RETURNING_CUSTOMER_PROFILE, session)

        assert result is True  # Address was pre-filled
        assert session.address["city"] == "Santo Domingo"
        assert "Piantini" in session.address["address1"]

    def test_prefills_name(self):
        session = CheckoutSession()
        prefill_checkout_from_profile(RETURNING_CUSTOMER_PROFILE, session)

        assert session.customer_name == "María González"

    def test_does_not_overwrite_existing_address(self):
        session = CheckoutSession(address={"address1": "Custom Street", "city": "Santiago"})
        result = prefill_checkout_from_profile(RETURNING_CUSTOMER_PROFILE, session)

        assert result is False  # Already had address
        assert session.address["city"] == "Santiago"  # Kept original

    def test_new_customer_no_address(self):
        session = CheckoutSession()
        result = prefill_checkout_from_profile(NEW_CUSTOMER_PROFILE, session)

        assert result is False
        assert not session.address


class TestGetSavedSize:
    """Test get_saved_size_for_product."""

    def test_known_size(self):
        result = get_saved_size_for_product(RETURNING_CUSTOMER_PROFILE, "Faja Colombiana Premium")
        assert result == "M"

    def test_unknown_product(self):
        result = get_saved_size_for_product(RETURNING_CUSTOMER_PROFILE, "Parlante Bluetooth LED")
        assert result is None

    def test_no_profile(self):
        result = get_saved_size_for_product(None, "Faja Colombiana Premium")
        assert result is None


# ═══════════════════════════════════════════════════════════════
# CATEGORY DETECTION TESTS
# ═══════════════════════════════════════════════════════════════

class TestCategoryDetection:
    """Test _detect_category."""

    @pytest.mark.parametrize("name,expected", [
        ("Crema Facial Vitamina C", "belleza"),
        ("Faja Colombiana Premium", "fajas"),
        ("Parlante Bluetooth LED", "tecnología"),
        ("Zapato Deportivo Nike", "zapatos"),
        ("Bolso de Cuero", "accesorios"),
        ("Producto Random XYZ", None),
    ])
    def test_category_detection(self, name, expected):
        assert _detect_category(name) == expected


class TestSimplifyProductName:
    """Test _simplify_product_name for size preference keys."""

    def test_faja_product(self):
        assert _simplify_product_name("Faja Colombiana Premium") == "faja"

    def test_crema_product(self):
        result = _simplify_product_name("Crema Facial Vitamina C")
        assert result in ("crema", "facial")  # Both are belleza keywords

    def test_unknown_product(self):
        result = _simplify_product_name("Super Widget 3000")
        assert result == "super widget"


# ═══════════════════════════════════════════════════════════════
# INTEGRATION: CHECKOUT FLOW WITH MEMORY
# ═══════════════════════════════════════════════════════════════

class TestCheckoutWithMemory:
    """Test that checkout flow uses customer memory correctly."""

    @pytest.fixture
    def mock_products(self):
        import main
        catalog = [
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
        ]
        original = main._products_raw
        main._products_raw = catalog
        yield catalog
        main._products_raw = original

    @pytest.fixture
    def conversation(self):
        from core.state import Conversation
        conv = Conversation(customer_id="+18091234567", channel="whatsapp")
        return conv

    @pytest.mark.asyncio
    async def test_returning_customer_skips_address(self, mock_products, conversation):
        """Returning customer with saved address skips address collection."""
        from main import _handle_checkout_flow

        conversation.history = [
            {"role": "assistant", "content": "Tenemos la Crema Facial Vitamina C a RD$890"},
        ]

        result = await _handle_checkout_flow(
            message="me la llevo",
            conversation=conversation,
            intent="purchase",
            customer_phone="+18091234567",
            customer_profile=RETURNING_CUSTOMER_PROFILE,
        )

        assert result is not None
        # Should show order summary directly (skipped address)
        assert "Confirmas" in result
        assert "Piantini" in result
        checkout = conversation.metadata.get("checkout", {})
        assert checkout["step"] == "order_confirm"

    @pytest.mark.asyncio
    async def test_new_customer_asks_address(self, mock_products, conversation):
        """New customer without saved address still asks for address."""
        from main import _handle_checkout_flow

        conversation.history = [
            {"role": "assistant", "content": "Tenemos la Crema Facial Vitamina C a RD$890"},
        ]

        result = await _handle_checkout_flow(
            message="me la llevo",
            conversation=conversation,
            intent="purchase",
            customer_phone="+18091234567",
            customer_profile=None,
        )

        assert result is not None
        assert "dirección" in result.lower()
        checkout = conversation.metadata.get("checkout", {})
        assert checkout["step"] == "address_collect"

    @pytest.mark.asyncio
    async def test_memory_learn_after_order(self, mock_products, conversation):
        """After order completion, customer profile is updated."""
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
             patch("main.db.save_chat_order", new_callable=AsyncMock), \
             patch("main.db.get_customer_profile", new_callable=AsyncMock, return_value=None) as mock_get_profile, \
             patch("main.db.upsert_customer_profile", new_callable=AsyncMock) as mock_upsert, \
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
                customer_profile=None,
            )

        assert result is not None
        assert "#1045" in result
        mock_upsert.assert_called_once()
        # Check the upsert was called with learned data
        call_args = mock_upsert.call_args
        assert call_args[0][0] == "+18091234567"  # phone
        updates = call_args[0][1]
        assert updates["total_orders"] == 1
        assert updates["total_spent"] == 890


# ═══════════════════════════════════════════════════════════════
# DATABASE METHODS TESTS
# ═══════════════════════════════════════════════════════════════

class TestCustomerProfileDB:
    """Test database layer for customer profiles."""

    @pytest.mark.asyncio
    async def test_get_profile_no_client(self):
        """If Supabase client not initialized, returns None."""
        with patch("database.get_supabase", return_value=None):
            result = await db_module.get_customer_profile("+18091234567")
            assert result is None

    @pytest.mark.asyncio
    async def test_upsert_profile_no_client(self):
        """If Supabase client not initialized, returns None."""
        with patch("database.get_supabase", return_value=None):
            result = await db_module.upsert_customer_profile("+18091234567", {"name": "Test"})
            assert result is None

    @pytest.mark.asyncio
    async def test_get_profile_success(self):
        """Successful profile lookup."""
        mock_client = MagicMock()
        mock_result = MagicMock()
        mock_result.data = [{"phone": "+18091234567", "name": "María"}]
        mock_client.table.return_value.select.return_value.eq.return_value.limit.return_value.execute.return_value = mock_result

        with patch("database.get_supabase", return_value=mock_client):
            result = await db_module.get_customer_profile("+18091234567")

        assert result is not None
        assert result["name"] == "María"

    @pytest.mark.asyncio
    async def test_get_profile_not_found(self):
        """Profile not found returns None."""
        mock_client = MagicMock()
        mock_result = MagicMock()
        mock_result.data = []
        mock_client.table.return_value.select.return_value.eq.return_value.limit.return_value.execute.return_value = mock_result

        with patch("database.get_supabase", return_value=mock_client):
            result = await db_module.get_customer_profile("+18091234567")

        assert result is None

    @pytest.mark.asyncio
    async def test_upsert_profile_success(self):
        """Successful profile upsert."""
        mock_client = MagicMock()
        mock_result = MagicMock()
        mock_result.data = [{"phone": "+18091234567", "name": "María"}]
        mock_client.table.return_value.upsert.return_value.execute.return_value = mock_result

        with patch("database.get_supabase", return_value=mock_client):
            result = await db_module.upsert_customer_profile("+18091234567", {"name": "María"})

        assert result is not None
        assert result["name"] == "María"


# Import database module for DB tests
import database as db_module
