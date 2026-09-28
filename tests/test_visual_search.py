"""
Tests for Visual Product Search.

Tests: image analysis, product matching, response building,
webhook image URL extraction, MIME detection, edge cases.
"""

import pytest
from unittest.mock import AsyncMock, patch, MagicMock

from core.visual_search import (
    analyze_image,
    visual_search_products,
    build_visual_search_response,
    _detect_mime_type,
    _format_price,
    _availability,
    VISION_PROMPT,
    IMAGE_CAPTION_PROMPT,
)


# ═══════════════════════════════════════════════════════════════
# TEST DATA
# ═══════════════════════════════════════════════════════════════

SAMPLE_PRODUCTS = [
    {
        "shopify_id": "1",
        "name": "Faja Colombiana Reductora",
        "description": "Faja reductora colombiana de alta compresión",
        "category": "Fajas",
        "tags": "faja, colombiana, reductora, mujer",
        "price_min": 2500,
        "price_max": 2500,
        "currency": "DOP",
        "image_url": "https://cdn.shopify.com/faja.jpg",
        "handle": "faja-colombiana",
        "url": "https://trendyrd.com/products/faja-colombiana",
        "available": True,
        "variants": "[]",
        "options": "[]",
    },
    {
        "shopify_id": "2",
        "name": "Sérum Vitamina C",
        "description": "Sérum facial con vitamina C para iluminar la piel",
        "category": "Skincare",
        "tags": "sérum, vitamina, skincare, facial",
        "price_min": 1200,
        "price_max": 1200,
        "currency": "DOP",
        "image_url": "https://cdn.shopify.com/serum.jpg",
        "handle": "serum-vitamina-c",
        "url": "https://trendyrd.com/products/serum-vitamina-c",
        "available": True,
        "variants": "[]",
        "options": "[]",
    },
    {
        "shopify_id": "3",
        "name": "Zapatillas Deportivas Running",
        "description": "Zapatillas deportivas para correr, suela de gel",
        "category": "Zapatos",
        "tags": "zapatillas, deportivas, running, zapatos",
        "price_min": 3500,
        "price_max": 4200,
        "currency": "DOP",
        "image_url": "https://cdn.shopify.com/zapatillas.jpg",
        "handle": "zapatillas-running",
        "url": "https://trendyrd.com/products/zapatillas-running",
        "available": False,
        "variants": "[]",
        "options": "[]",
    },
]


# ═══════════════════════════════════════════════════════════════
# VISUAL SEARCH — Product Matching
# ═══════════════════════════════════════════════════════════════

class TestVisualSearchProducts:
    """Test catalog search from visual descriptions."""

    def test_finds_faja_from_description(self):
        matches = visual_search_products(
            "faja colombiana negra tipo cinturilla reductora",
            SAMPLE_PRODUCTS,
        )
        assert len(matches) >= 1
        assert matches[0]["name"] == "Faja Colombiana Reductora"

    def test_finds_serum_from_description(self):
        matches = visual_search_products(
            "sérum facial vitamina C skincare",
            SAMPLE_PRODUCTS,
        )
        assert len(matches) >= 1
        assert matches[0]["name"] == "Sérum Vitamina C"

    def test_finds_zapatillas_from_description(self):
        matches = visual_search_products(
            "zapatillas deportivas blancas running",
            SAMPLE_PRODUCTS,
        )
        assert len(matches) >= 1
        assert matches[0]["name"] == "Zapatillas Deportivas Running"

    def test_empty_description_returns_empty(self):
        matches = visual_search_products("", SAMPLE_PRODUCTS)
        assert matches == []

    def test_no_products_returns_empty(self):
        matches = visual_search_products("faja colombiana", [])
        assert matches == []

    def test_no_match_returns_empty(self):
        matches = visual_search_products(
            "televisor samsung 65 pulgadas",
            SAMPLE_PRODUCTS,
        )
        assert matches == []

    def test_respects_max_results(self):
        matches = visual_search_products(
            "faja colombiana reductora",
            SAMPLE_PRODUCTS,
            max_results=1,
        )
        assert len(matches) <= 1


# ═══════════════════════════════════════════════════════════════
# RESPONSE BUILDING
# ═══════════════════════════════════════════════════════════════

class TestBuildVisualSearchResponse:
    """Test visual search response formatting."""

    def test_no_matches_returns_fallback(self):
        result = build_visual_search_response([])
        assert "No encontré" in result
        assert "dime más" in result

    def test_single_match_formattted(self):
        result = build_visual_search_response([SAMPLE_PRODUCTS[0]])
        assert "Faja Colombiana Reductora" in result
        assert "RD$2,500" in result
        assert "Encontré" in result
        assert "¿Te interesa?" in result

    def test_multiple_matches_numbered(self):
        result = build_visual_search_response(SAMPLE_PRODUCTS[:2])
        assert "1." in result
        assert "2." in result
        assert "Faja Colombiana" in result
        assert "Sérum Vitamina C" in result
        assert "¿Cuál te gusta" in result

    def test_shows_availability(self):
        result = build_visual_search_response([SAMPLE_PRODUCTS[2]])  # Out of stock
        assert "Agotado" in result

    def test_price_range_displayed(self):
        result = build_visual_search_response([SAMPLE_PRODUCTS[2]])
        assert "RD$3,500" in result
        assert "RD$4,200" in result


# ═══════════════════════════════════════════════════════════════
# IMAGE ANALYSIS (mocked Gemini)
# ═══════════════════════════════════════════════════════════════

class TestAnalyzeImage:
    """Test image analysis with mocked Gemini + httpx."""

    @pytest.mark.asyncio
    async def test_successful_analysis(self):
        mock_response = MagicMock()
        mock_response.text = "faja colombiana negra tipo cinturilla"

        mock_client = MagicMock()
        mock_client.models.generate_content.return_value = mock_response

        mock_http_response = MagicMock()
        mock_http_response.status_code = 200
        mock_http_response.content = b"fake_image_bytes" * 100
        mock_http_response.headers = {"content-type": "image/jpeg"}

        with patch("httpx.AsyncClient") as MockClient:
            mock_instance = AsyncMock()
            mock_instance.get.return_value = mock_http_response
            MockClient.return_value.__aenter__ = AsyncMock(return_value=mock_instance)
            MockClient.return_value.__aexit__ = AsyncMock(return_value=False)
            with patch("core.brain.get_gemini_client", return_value=mock_client):
                result = await analyze_image("https://example.com/faja.jpg")

        assert result == "faja colombiana negra tipo cinturilla"

    @pytest.mark.asyncio
    async def test_no_product_detected(self):
        mock_response = MagicMock()
        mock_response.text = "NO_PRODUCT"

        mock_client = MagicMock()
        mock_client.models.generate_content.return_value = mock_response

        mock_http_response = MagicMock()
        mock_http_response.status_code = 200
        mock_http_response.content = b"fake_image_bytes" * 100
        mock_http_response.headers = {"content-type": "image/jpeg"}

        with patch("httpx.AsyncClient") as MockClient:
            mock_instance = AsyncMock()
            mock_instance.get.return_value = mock_http_response
            MockClient.return_value.__aenter__ = AsyncMock(return_value=mock_instance)
            MockClient.return_value.__aexit__ = AsyncMock(return_value=False)
            with patch("core.brain.get_gemini_client", return_value=mock_client):
                result = await analyze_image("https://example.com/selfie.jpg")

        assert result is None

    @pytest.mark.asyncio
    async def test_download_failure(self):
        mock_http_response = MagicMock()
        mock_http_response.status_code = 404

        with patch("httpx.AsyncClient") as MockClient:
            mock_instance = AsyncMock()
            mock_instance.get.return_value = mock_http_response
            MockClient.return_value.__aenter__ = AsyncMock(return_value=mock_instance)
            MockClient.return_value.__aexit__ = AsyncMock(return_value=False)
            result = await analyze_image("https://example.com/missing.jpg")

        assert result is None

    @pytest.mark.asyncio
    async def test_small_image_rejected(self):
        mock_http_response = MagicMock()
        mock_http_response.status_code = 200
        mock_http_response.content = b"tiny"
        mock_http_response.headers = {}

        with patch("httpx.AsyncClient") as MockClient:
            mock_instance = AsyncMock()
            mock_instance.get.return_value = mock_http_response
            MockClient.return_value.__aenter__ = AsyncMock(return_value=mock_instance)
            MockClient.return_value.__aexit__ = AsyncMock(return_value=False)
            result = await analyze_image("https://example.com/tiny.jpg")

        assert result is None

    @pytest.mark.asyncio
    async def test_with_caption(self):
        mock_response = MagicMock()
        mock_response.text = "faja colombiana como la de Instagram"

        mock_client = MagicMock()
        mock_client.models.generate_content.return_value = mock_response

        mock_http_response = MagicMock()
        mock_http_response.status_code = 200
        mock_http_response.content = b"fake_image_bytes" * 100
        mock_http_response.headers = {"content-type": "image/jpeg"}

        with patch("httpx.AsyncClient") as MockClient:
            mock_instance = AsyncMock()
            mock_instance.get.return_value = mock_http_response
            MockClient.return_value.__aenter__ = AsyncMock(return_value=mock_instance)
            MockClient.return_value.__aexit__ = AsyncMock(return_value=False)
            with patch("core.brain.get_gemini_client", return_value=mock_client):
                result = await analyze_image(
                    "https://example.com/faja.jpg",
                    caption="¿Tienen algo así?",
                )

        assert result is not None

    @pytest.mark.asyncio
    async def test_gemini_error_returns_none(self):
        mock_http_response = MagicMock()
        mock_http_response.status_code = 200
        mock_http_response.content = b"fake_image_bytes" * 100
        mock_http_response.headers = {"content-type": "image/jpeg"}

        with patch("httpx.AsyncClient") as MockClient:
            mock_instance = AsyncMock()
            mock_instance.get.return_value = mock_http_response
            MockClient.return_value.__aenter__ = AsyncMock(return_value=mock_instance)
            MockClient.return_value.__aexit__ = AsyncMock(return_value=False)
            with patch("core.brain.get_gemini_client", return_value=None):
                result = await analyze_image("https://example.com/img.jpg")

        assert result is None


# ═══════════════════════════════════════════════════════════════
# MIME TYPE DETECTION
# ═══════════════════════════════════════════════════════════════

class TestMimeDetection:
    """Test MIME type detection from headers and URLs."""

    def test_jpeg_from_header(self):
        assert _detect_mime_type("image/jpeg", "") == "image/jpeg"

    def test_png_from_header(self):
        assert _detect_mime_type("image/png", "") == "image/png"

    def test_webp_from_header(self):
        assert _detect_mime_type("image/webp", "") == "image/webp"

    def test_gif_from_header(self):
        assert _detect_mime_type("image/gif", "") == "image/gif"

    def test_jpg_from_header(self):
        assert _detect_mime_type("image/jpg; charset=utf-8", "") == "image/jpeg"

    def test_png_from_url(self):
        assert _detect_mime_type("application/octet-stream", "https://example.com/photo.png") == "image/png"

    def test_webp_from_url(self):
        assert _detect_mime_type("", "https://example.com/photo.webp") == "image/webp"

    def test_default_jpeg(self):
        assert _detect_mime_type("", "https://example.com/unknown") == "image/jpeg"


# ═══════════════════════════════════════════════════════════════
# PRICE FORMATTING
# ═══════════════════════════════════════════════════════════════

class TestFormatPrice:
    """Test price formatting helpers."""

    def test_single_price(self):
        assert _format_price({"price_min": 2500, "price_max": 2500}) == "RD$2,500"

    def test_price_range(self):
        result = _format_price({"price_min": 3500, "price_max": 4200})
        assert "RD$3,500" in result
        assert "RD$4,200" in result
        assert "-" in result

    def test_zero_price(self):
        assert _format_price({"price_min": 0, "price_max": 0}) == "RD$0"


class TestAvailability:
    """Test availability display."""

    def test_available(self):
        assert "Disponible" in _availability({"available": True})

    def test_out_of_stock(self):
        assert "Agotado" in _availability({"available": False})

    def test_missing_field(self):
        assert "Agotado" in _availability({})


# ═══════════════════════════════════════════════════════════════
# WEBHOOK IMAGE URL EXTRACTION
# ═══════════════════════════════════════════════════════════════

class TestWebhookImageParsing:
    """Test WhatsApp webhook correctly extracts image data."""

    def test_image_with_link_and_caption(self):
        from channels.whatsapp import WhatsAppChannel

        channel = WhatsAppChannel(api_key="k", from_number="+1")
        payload = {
            "type": "whatsapp.inbound_message.received",
            "whatsappInboundMessage": {
                "from": "+18091234567",
                "type": "image",
                "image": {
                    "link": "https://ycloud.com/media/img123.jpg",
                    "caption": "¿Tienen esto?",
                },
                "id": "msg-1",
                "timestamp": "2025-01-01T00:00:00Z",
                "customerProfile": {"name": "Maria"},
            },
        }

        result = channel.parse_webhook(payload)
        assert result is not None
        assert result["message_type"] == "image"
        assert result["image_url"] == "https://ycloud.com/media/img123.jpg"
        assert result["message_text"] == "¿Tienen esto?"

    def test_image_without_caption(self):
        from channels.whatsapp import WhatsAppChannel

        channel = WhatsAppChannel(api_key="k", from_number="+1")
        payload = {
            "type": "whatsapp.inbound_message.received",
            "whatsappInboundMessage": {
                "from": "+18091234567",
                "type": "image",
                "image": {"link": "https://ycloud.com/media/img456.jpg"},
                "id": "msg-2",
                "timestamp": "2025-01-01T00:00:00Z",
                "customerProfile": {},
            },
        }

        result = channel.parse_webhook(payload)
        assert result is not None
        assert result["image_url"] == "https://ycloud.com/media/img456.jpg"
        assert result["message_text"] == "[Imagen recibida]"

    def test_image_without_link(self):
        from channels.whatsapp import WhatsAppChannel

        channel = WhatsAppChannel(api_key="k", from_number="+1")
        payload = {
            "type": "whatsapp.inbound_message.received",
            "whatsappInboundMessage": {
                "from": "+18091234567",
                "type": "image",
                "image": {},
                "id": "msg-3",
                "timestamp": "2025-01-01T00:00:00Z",
                "customerProfile": {},
            },
        }

        result = channel.parse_webhook(payload)
        assert result is not None
        assert result["image_url"] == ""

    def test_text_message_has_empty_image_url(self):
        from channels.whatsapp import WhatsAppChannel

        channel = WhatsAppChannel(api_key="k", from_number="+1")
        payload = {
            "type": "whatsapp.inbound_message.received",
            "whatsappInboundMessage": {
                "from": "+18091234567",
                "type": "text",
                "text": {"body": "Hola"},
                "id": "msg-4",
                "timestamp": "2025-01-01T00:00:00Z",
                "customerProfile": {},
            },
        }

        result = channel.parse_webhook(payload)
        assert result is not None
        assert result["image_url"] == ""


# ═══════════════════════════════════════════════════════════════
# CONSTANTS
# ═══════════════════════════════════════════════════════════════

class TestVisualSearchConstants:
    """Test module constants are properly defined."""

    def test_vision_prompt_not_empty(self):
        assert len(VISION_PROMPT) > 50

    def test_vision_prompt_has_no_product(self):
        assert "NO_PRODUCT" in VISION_PROMPT

    def test_caption_prompt_has_placeholder(self):
        assert "{caption}" in IMAGE_CAPTION_PROMPT
