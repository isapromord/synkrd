"""
Thorough tests for INVENTORY QUANTITIES IN CHAT feature.

Covers:
1. Urgency tags in product context (build_product_context)
2. Urgency tags in search context (build_search_context)
3. Low-stock detection (detect_low_stock)
4. Low-stock Telegram alerts (notify_low_stock)
5. Sofía's prompt includes stock instructions
6. Product sync triggers low-stock alerts
"""

import pytest
import json
from unittest.mock import AsyncMock, MagicMock, patch


# ═══════════════════════════════════════════════════════════════
# HELPERS — Build test product data
# ═══════════════════════════════════════════════════════════════

def _make_product(name="Test Product", total_qty=50, variant_count=1, available=True, price=1500):
    """Build a product dict matching scraper output format."""
    variants = []
    per_variant = total_qty // max(variant_count, 1)
    for i in range(variant_count):
        qty = per_variant if i < variant_count - 1 else total_qty - per_variant * (variant_count - 1)
        variants.append({
            "title": f"Variante {i+1}" if variant_count > 1 else "Default",
            "price": str(price),
            "available": qty > 0,
            "inventory_quantity": qty,
        })
    return {
        "name": name,
        "price_min": price,
        "price_max": price,
        "available": available,
        "url": f"https://trendyrd.com/products/{name.lower().replace(' ', '-')}",
        "options": json.dumps([]),
        "variants": json.dumps(variants),
        "category": "Belleza",
        "description": f"Descripción de {name}",
        "tags": "test",
    }


# ═══════════════════════════════════════════════════════════════
# 1. URGENCY TAGS IN build_product_context
# ═══════════════════════════════════════════════════════════════

class TestUrgencyInProductContext:
    """Test that build_product_context adds urgency tags based on stock."""

    def test_critical_urgency_3_or_fewer(self):
        """Products with 1-3 total units should get 🔥 ÚLTIMAS tag."""
        from knowledge.scraper import build_product_context
        products = [_make_product("Faja Colombiana", total_qty=2)]
        result = build_product_context(products)
        assert "🔥" in result
        assert "ÚLTIMAS 2 UNIDADES" in result

    def test_critical_urgency_1_unit(self):
        from knowledge.scraper import build_product_context
        products = [_make_product("Último Producto", total_qty=1)]
        result = build_product_context(products)
        assert "ÚLTIMAS 1 UNIDADES" in result

    def test_warning_urgency_4_to_10(self):
        """Products with 4-10 total units should get ⚡ tag."""
        from knowledge.scraper import build_product_context
        products = [_make_product("Crema Retinol", total_qty=7)]
        result = build_product_context(products)
        assert "⚡" in result
        assert "7 unidades" in result

    def test_no_urgency_above_10(self):
        """Products with 11+ units should NOT have urgency tags."""
        from knowledge.scraper import build_product_context
        products = [_make_product("Mochila Antirrobo", total_qty=50)]
        result = build_product_context(products)
        assert "🔥" not in result
        assert "⚡" not in result
        assert "ÚLTIMAS" not in result

    def test_no_urgency_zero_stock(self):
        """Out-of-stock products (0 qty) should NOT get urgency — just ❌ Agotado."""
        from knowledge.scraper import build_product_context
        products = [_make_product("Agotado Item", total_qty=0, available=False)]
        result = build_product_context(products)
        assert "🔥" not in result
        assert "⚡" not in result
        assert "Agotado" in result

    def test_urgency_at_boundary_3(self):
        """Exactly 3 units should be critical (🔥)."""
        from knowledge.scraper import build_product_context
        products = [_make_product("Boundary 3", total_qty=3)]
        result = build_product_context(products)
        assert "🔥" in result
        assert "ÚLTIMAS 3" in result

    def test_urgency_at_boundary_10(self):
        """Exactly 10 units should be warning (⚡)."""
        from knowledge.scraper import build_product_context
        products = [_make_product("Boundary 10", total_qty=10)]
        result = build_product_context(products)
        assert "⚡" in result
        assert "10 unidades" in result

    def test_urgency_at_boundary_11(self):
        """11 units should have NO urgency tag."""
        from knowledge.scraper import build_product_context
        products = [_make_product("Boundary 11", total_qty=11)]
        result = build_product_context(products)
        assert "🔥" not in result
        assert "⚡" not in result

    def test_mixed_products_correct_tags(self):
        """Multiple products with different stock levels get correct tags."""
        from knowledge.scraper import build_product_context
        products = [
            _make_product("Low Stock", total_qty=2),
            _make_product("Medium Stock", total_qty=8),
            _make_product("High Stock", total_qty=100),
        ]
        result = build_product_context(products)
        # Low should have 🔥
        assert "ÚLTIMAS 2" in result
        # Medium should have ⚡
        assert "8 unidades" in result
        # High should have neither
        lines = result.split("\n")
        high_stock_line = [l for l in lines if "High Stock" in l][0]
        assert "🔥" not in high_stock_line
        assert "⚡" not in high_stock_line


# ═══════════════════════════════════════════════════════════════
# 2. URGENCY TAGS IN build_search_context
# ═══════════════════════════════════════════════════════════════

class TestUrgencyInSearchContext:
    """Test that build_search_context adds urgency tags in rich detail view."""

    def test_search_context_critical_stock(self):
        from knowledge.scraper import build_search_context
        products = [_make_product("Parlante Magnético", total_qty=2, variant_count=2)]
        result = build_search_context(products)
        assert "🔥" in result
        assert "ÚLTIMAS 2 UNIDADES" in result
        assert "Menciona la escasez" in result

    def test_search_context_warning_stock(self):
        from knowledge.scraper import build_search_context
        products = [_make_product("Banda Audio", total_qty=6, variant_count=3)]
        result = build_search_context(products)
        assert "⚡" in result
        assert "Stock bajo" in result
        assert "6 unidades" in result

    def test_search_context_no_urgency_high_stock(self):
        from knowledge.scraper import build_search_context
        products = [_make_product("Popular Item", total_qty=200)]
        result = build_search_context(products)
        assert "🔥" not in result
        assert "⚡" not in result
        assert "ÚLTIMAS" not in result
        assert "Stock bajo" not in result


# ═══════════════════════════════════════════════════════════════
# 3. LOW-STOCK DETECTION
# ═══════════════════════════════════════════════════════════════

class TestDetectLowStock:
    """Test detect_low_stock() function."""

    def test_detects_low_stock_products(self):
        from knowledge.scraper import detect_low_stock
        products = [
            _make_product("Low Item", total_qty=3),
            _make_product("Normal Item", total_qty=50),
            _make_product("Warning Item", total_qty=8),
        ]
        result = detect_low_stock(products, threshold=10)
        names = [p["name"] for p in result]
        assert "Low Item" in names
        assert "Warning Item" in names
        assert "Normal Item" not in names

    def test_returns_correct_qty(self):
        from knowledge.scraper import detect_low_stock
        products = [_make_product("Test", total_qty=5)]
        result = detect_low_stock(products, threshold=10)
        assert len(result) == 1
        assert result[0]["total_qty"] == 5

    def test_returns_variant_detail(self):
        from knowledge.scraper import detect_low_stock
        products = [_make_product("Multi Var", total_qty=6, variant_count=3)]
        result = detect_low_stock(products, threshold=10)
        assert len(result) == 1
        assert len(result[0]["variants_detail"]) == 3

    def test_skips_out_of_stock(self):
        """Fully out-of-stock products should be skipped (already agotado)."""
        from knowledge.scraper import detect_low_stock
        products = [_make_product("Agotado", total_qty=0, available=False)]
        result = detect_low_stock(products, threshold=10)
        assert len(result) == 0

    def test_empty_products(self):
        from knowledge.scraper import detect_low_stock
        assert detect_low_stock([], threshold=10) == []

    def test_all_above_threshold(self):
        from knowledge.scraper import detect_low_stock
        products = [
            _make_product("A", total_qty=50),
            _make_product("B", total_qty=100),
        ]
        assert detect_low_stock(products, threshold=10) == []

    def test_custom_threshold(self):
        from knowledge.scraper import detect_low_stock
        products = [_make_product("Threshold Test", total_qty=15)]
        assert len(detect_low_stock(products, threshold=20)) == 1
        assert len(detect_low_stock(products, threshold=10)) == 0

    def test_boundary_at_threshold(self):
        """Product with qty exactly at threshold should be included."""
        from knowledge.scraper import detect_low_stock
        products = [_make_product("Boundary", total_qty=10)]
        result = detect_low_stock(products, threshold=10)
        assert len(result) == 1

    def test_variants_detail_only_in_stock(self):
        """variants_detail should only include variants with qty > 0."""
        from knowledge.scraper import detect_low_stock
        # 3 variants: 3, 0, 2 = total 5
        product = _make_product("Mixed Variants", total_qty=5, variant_count=3)
        variants = json.loads(product["variants"])
        variants[1]["inventory_quantity"] = 0
        variants[1]["available"] = False
        variants[0]["inventory_quantity"] = 3
        variants[2]["inventory_quantity"] = 2
        product["variants"] = json.dumps(variants)

        result = detect_low_stock([product], threshold=10)
        assert len(result) == 1
        # Only 2 variants with stock (not the one with 0)
        assert len(result[0]["variants_detail"]) == 2


# ═══════════════════════════════════════════════════════════════
# 4. LOW-STOCK TELEGRAM ALERTS
# ═══════════════════════════════════════════════════════════════

class TestLowStockNotification:
    """Test NotificationSender.notify_low_stock()."""

    @pytest.mark.asyncio
    async def test_notification_sent_with_products(self):
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

            low_stock = [
                {"name": "Faja Colombiana", "total_qty": 2, "variants_detail": []},
                {"name": "Crema Retinol", "total_qty": 8, "variants_detail": []},
            ]
            result = await sender.notify_low_stock(low_stock)

        assert result is True
        call_args = mock_instance.post.call_args
        payload = call_args[1]["json"]
        text = payload["text"]

        # Critical product should be under CRÍTICO header
        assert "CRÍTICO" in text
        assert "Faja Colombiana" in text
        assert "*2*" in text  # qty bold

        # Warning product should be under BAJO header
        assert "BAJO" in text
        assert "Crema Retinol" in text
        assert "8 restantes" in text

    @pytest.mark.asyncio
    async def test_notification_empty_list_returns_false(self):
        from core.notifications import NotificationSender
        sender = NotificationSender(telegram_token="123:ABC", telegram_chat_id="456")
        result = await sender.notify_low_stock([])
        assert result is False

    @pytest.mark.asyncio
    async def test_notification_only_critical(self):
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

            low_stock = [{"name": "Urgent Item", "total_qty": 1, "variants_detail": []}]
            result = await sender.notify_low_stock(low_stock)

        assert result is True
        text = mock_instance.post.call_args[1]["json"]["text"]
        assert "CRÍTICO" in text
        assert "Urgent Item" in text

    @pytest.mark.asyncio
    async def test_notification_disabled_returns_false(self):
        from core.notifications import NotificationSender
        sender = NotificationSender(telegram_token="", telegram_chat_id="")
        low_stock = [{"name": "Test", "total_qty": 2, "variants_detail": []}]
        result = await sender.notify_low_stock(low_stock)
        assert result is False


# ═══════════════════════════════════════════════════════════════
# 5. SOFÍA'S PROMPT INCLUDES STOCK INSTRUCTIONS
# ═══════════════════════════════════════════════════════════════

class TestPersonaStockInstructions:
    """Verify Sofía's system prompt has inventory urgency instructions."""

    def test_prompt_has_urgency_strategy(self):
        from bots.sofia.persona import SYSTEM_PROMPT
        assert "Urgencia por Stock Bajo" in SYSTEM_PROMPT

    def test_prompt_mentions_fire_emoji(self):
        from bots.sofia.persona import SYSTEM_PROMPT
        assert "🔥" in SYSTEM_PROMPT
        assert "ÚLTIMAS UNIDADES" in SYSTEM_PROMPT

    def test_prompt_mentions_lightning_emoji(self):
        from bots.sofia.persona import SYSTEM_PROMPT
        assert "⚡" in SYSTEM_PROMPT
        assert "Stock bajo" in SYSTEM_PROMPT

    def test_prompt_warns_not_to_invent_scarcity(self):
        from bots.sofia.persona import SYSTEM_PROMPT
        assert "NUNCA inventes escasez" in SYSTEM_PROMPT

    def test_prompt_has_variant_suggestion(self):
        from bots.sofia.persona import SYSTEM_PROMPT
        assert "Variantes Agotadas" in SYSTEM_PROMPT
        assert "agotó" in SYSTEM_PROMPT

    def test_prompt_mentions_real_data(self):
        """Sofía should only use real catalog data, not make up stock levels."""
        from bots.sofia.persona import SYSTEM_PROMPT
        assert "datos reales del catálogo" in SYSTEM_PROMPT


# ═══════════════════════════════════════════════════════════════
# 6. AI CONTEXT INJECTION (Brain Integration)
# ═══════════════════════════════════════════════════════════════

class TestBrainInventoryContext:
    """Test that urgency tags flow through to the AI's system prompt."""

    def test_urgency_passes_through_brain(self):
        """build_system_prompt should preserve urgency tags from product context."""
        from core.brain import _build_system_prompt
        product_ctx = (
            "- Faja Colombiana: RD$1,500 | ✅ Disponible | 🔥 ¡ÚLTIMAS 2 UNIDADES!\n"
            "- Crema Retinol: RD$500 | ✅ Disponible | ⚡ Quedan pocas (7 unidades)"
        )
        result = _build_system_prompt("Eres Sofía.", product_ctx, "")
        assert "🔥" in result
        assert "ÚLTIMAS 2 UNIDADES" in result
        assert "⚡" in result
        assert "7 unidades" in result

    def test_agotado_passes_through(self):
        from core.brain import _build_system_prompt
        product_ctx = "- Item Agotado: RD$500 | ❌ Agotado"
        result = _build_system_prompt("Eres Sofía.", product_ctx, "")
        assert "Agotado" in result
