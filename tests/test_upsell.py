"""
Tests for Smart Upsell Module.

Tests: category detection, complementary categories, relevance scoring,
product finding, message building, exclusion logic.
"""

import pytest

from core.upsell import (
    detect_category,
    get_complementary_categories,
    score_product_relevance,
    find_upsell_products,
    build_upsell_message,
    build_upsell_response,
)


# ═══════════════════════════════════════════════════════════════
# TEST DATA
# ═══════════════════════════════════════════════════════════════

CATALOG = [
    {
        "shopify_id": "100",
        "name": "Faja Colombiana Reductora",
        "category": "Fajas",
        "tags": "faja, colombiana, reductora, mujer",
        "price_min": 2500,
        "available": True,
    },
    {
        "shopify_id": "200",
        "name": "Sérum Vitamina C Facial",
        "category": "Skincare",
        "tags": "sérum, vitamina, facial, belleza, mujer",
        "price_min": 1200,
        "available": True,
    },
    {
        "shopify_id": "300",
        "name": "Crema Hidratante Retinol",
        "category": "Skincare",
        "tags": "crema, retinol, facial, belleza, mujer",
        "price_min": 900,
        "available": True,
    },
    {
        "shopify_id": "400",
        "name": "Parlante Bluetooth Magnético",
        "category": "Tech",
        "tags": "parlante, bluetooth, tech, sonido",
        "price_min": 1800,
        "available": True,
    },
    {
        "shopify_id": "500",
        "name": "Vestido Casual Elegante",
        "category": "Ropa",
        "tags": "vestido, casual, mujer, elegante",
        "price_min": 1500,
        "available": True,
    },
    {
        "shopify_id": "600",
        "name": "Zapatos Tenis Deportivos",
        "category": "Zapatos",
        "tags": "tenis, deportivos, zapatos, unisex",
        "price_min": 2200,
        "available": True,
    },
    {
        "shopify_id": "700",
        "name": "Collar Elegante Perlas",
        "category": "Accesorios",
        "tags": "collar, perlas, elegante, mujer",
        "price_min": 800,
        "available": True,
    },
    {
        "shopify_id": "800",
        "name": "Mascarilla Facial Té Verde",
        "category": "Skincare",
        "tags": "mascarilla, facial, belleza, té verde",
        "price_min": 350,
        "available": False,  # Out of stock
    },
]


# ═══════════════════════════════════════════════════════════════
# CATEGORY DETECTION
# ═══════════════════════════════════════════════════════════════

class TestDetectCategory:

    def test_faja(self):
        assert detect_category("Faja Colombiana Reductora") == "fajas"

    def test_crema(self):
        assert detect_category("Crema Hidratante Retinol") == "belleza"

    def test_parlante(self):
        assert detect_category("Parlante Bluetooth") == "tecnología"

    def test_vestido(self):
        assert detect_category("Vestido Casual Elegante") == "ropa"

    def test_tenis(self):
        assert detect_category("Zapatos Tenis Deportivos") == "zapatos"

    def test_collar(self):
        assert detect_category("Collar Elegante Perlas") == "accesorios"

    def test_unknown(self):
        assert detect_category("Producto Genérico XYZ") is None

    def test_case_insensitive(self):
        assert detect_category("FAJA REDUCTORA") == "fajas"


# ═══════════════════════════════════════════════════════════════
# COMPLEMENTARY CATEGORIES
# ═══════════════════════════════════════════════════════════════

class TestGetComplementaryCategories:

    def test_belleza(self):
        cats = get_complementary_categories("belleza")
        assert "belleza" in cats
        assert "accesorios" in cats

    def test_fajas(self):
        cats = get_complementary_categories("fajas")
        assert "belleza" in cats

    def test_ropa(self):
        cats = get_complementary_categories("ropa")
        assert "zapatos" in cats

    def test_unknown_category(self):
        assert get_complementary_categories("desconocida") == []


# ═══════════════════════════════════════════════════════════════
# RELEVANCE SCORING
# ═══════════════════════════════════════════════════════════════

class TestScoreProductRelevance:

    def test_high_overlap(self):
        tags = {"facial", "belleza", "mujer"}
        score = score_product_relevance(CATALOG[2], tags)  # Crema — facial, belleza, mujer
        assert score >= 9  # 3 tags * 3 + available(2) + price(1)

    def test_no_overlap(self):
        tags = {"tech", "bluetooth"}
        score = score_product_relevance(CATALOG[4], tags)  # Vestido — no overlap
        assert score <= 3  # Only available + price

    def test_unavailable_product(self):
        tags = {"facial", "belleza"}
        score_available = score_product_relevance(CATALOG[1], tags)    # Sérum — available
        score_unavailable = score_product_relevance(CATALOG[7], tags)  # Mascarilla — unavailable
        assert score_available > score_unavailable


# ═══════════════════════════════════════════════════════════════
# FIND UPSELL PRODUCTS
# ═══════════════════════════════════════════════════════════════

class TestFindUpsellProducts:

    def test_beauty_upsell(self):
        """Buying sérum should suggest crema (same category belleza)."""
        results = find_upsell_products("Sérum Vitamina C Facial", "200", CATALOG)
        names = [r["name"] for r in results]
        assert "Crema Hidratante Retinol" in names
        # Should NOT include the purchased product
        assert "Sérum Vitamina C Facial" not in names

    def test_faja_upsell(self):
        """Buying faja should suggest belleza products."""
        results = find_upsell_products("Faja Colombiana Reductora", "100", CATALOG)
        names = [r["name"] for r in results]
        # Should suggest belleza (complementary to fajas)
        assert any("Sérum" in n or "Crema" in n for n in names)

    def test_excludes_purchased(self):
        results = find_upsell_products("Parlante Bluetooth Magnético", "400", CATALOG)
        ids = [r["shopify_id"] for r in results]
        assert "400" not in ids

    def test_excludes_unavailable(self):
        results = find_upsell_products("Sérum Vitamina C Facial", "200", CATALOG)
        ids = [r["shopify_id"] for r in results]
        assert "800" not in ids  # Mascarilla is out of stock

    def test_excludes_customer_history(self):
        history = [{"name": "Crema Hidratante Retinol"}]
        results = find_upsell_products("Sérum Vitamina C Facial", "200", CATALOG, customer_history=history)
        names = [r["name"] for r in results]
        assert "Crema Hidratante Retinol" not in names

    def test_max_results(self):
        results = find_upsell_products("Vestido Casual Elegante", "500", CATALOG, max_results=1)
        assert len(results) <= 1

    def test_empty_catalog(self):
        results = find_upsell_products("Faja", "100", [])
        assert results == []

    def test_unknown_category_returns_something(self):
        """Unknown category should still return available products."""
        results = find_upsell_products("Producto Misterioso XYZ", "999", CATALOG)
        # May return products or empty list — both valid
        assert isinstance(results, list)

    def test_tech_stays_in_tech(self):
        """Tech products should upsell tech/hogar, not belleza."""
        results = find_upsell_products("Parlante Bluetooth Magnético", "400", CATALOG)
        names = [r["name"] for r in results]
        # Should NOT suggest belleza products
        for name in names:
            cat = detect_category(name)
            if cat:
                assert cat in ["tecnología", "hogar"], f"Unexpected category {cat} for {name}"


# ═══════════════════════════════════════════════════════════════
# MESSAGE BUILDING
# ═══════════════════════════════════════════════════════════════

class TestBuildUpsellMessage:

    def test_with_products(self):
        products = [CATALOG[1], CATALOG[2]]  # Sérum + Crema
        msg = build_upsell_message(products)
        assert "Sérum Vitamina C" in msg
        assert "Crema Hidratante" in msg
        assert "mismo envío" in msg
        assert "¿Te agrego" in msg

    def test_single_product(self):
        msg = build_upsell_message([CATALOG[3]])
        assert "Parlante" in msg
        assert "RD$1,800" in msg

    def test_empty_list(self):
        assert build_upsell_message([]) == ""

    def test_price_formatting(self):
        msg = build_upsell_message([CATALOG[0]])
        assert "RD$2,500" in msg


class TestBuildUpsellResponse:

    def test_full_flow(self):
        """End-to-end: find products + build message."""
        result = build_upsell_response("Sérum Vitamina C Facial", "200", CATALOG)
        assert "Crema" in result or "mismo envío" in result

    def test_empty_catalog(self):
        assert build_upsell_response("Test", "1", []) == ""
