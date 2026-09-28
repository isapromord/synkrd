"""
Tests for Sofía's 5 Strategic Pillars:
1. GPS location pin processing & Google Maps link extraction.
2. Voice note processing pipeline.
3. Post-confirmation upsell & 15% volume discount fallback.
4. COD delivery reliability & anti-fraud scoring.
5. Bank transfer receipt verification targets.
"""

import pytest
from channels.whatsapp import WhatsAppChannel
from core.checkout import (
    extract_address_from_message,
    is_address_sufficient,
    build_product_confirm_message,
    build_order_summary_message,
    CheckoutSession,
    CheckoutStep,
)
from core.upsell import (
    build_volume_discount_upsell,
    build_upsell_response,
)
from core.customer_memory import calculate_customer_reliability
from core.receipt_validator import (
    OFFICIAL_BENEFICIARY,
    OFFICIAL_CEDULA,
    OFFICIAL_ACCOUNTS,
)
from bots.sofia.policies import STORE_POLICIES, get_bank_transfer_instructions


class TestPillar1GPSLocation:
    """Test Pillar 1: Location extraction and Google Maps integration."""

    def test_whatsapp_location_webhook_parsing(self):
        channel = WhatsAppChannel(api_key="test_key", from_number="+18090000000")
        payload = {
            "type": "whatsapp.inbound_message.received",
            "whatsappInboundMessage": {
                "from": "+18095551234",
                "type": "location",
                "location": {
                    "latitude": 18.4724,
                    "longitude": -69.9325,
                    "name": "Mi Casa",
                    "address": "Calle Las Flores 12, Piantini",
                },
                "timestamp": "1710000000",
            },
        }
        parsed = channel.parse_webhook(payload)
        assert parsed is not None
        assert parsed["message_type"] == "location"
        assert parsed["location"]["latitude"] == 18.4724
        assert parsed["location"]["longitude"] == -69.9325
        assert "google.com/maps" in parsed["location"]["maps_url"]
        assert "18.4724,-69.9325" in parsed["location"]["maps_url"]
        assert "📍" in parsed["message_text"]

    def test_extract_address_with_maps_link(self):
        msg = "Envíamelo a https://maps.google.com/?q=18.4861,-69.9312 en Santo Domingo"
        addr = extract_address_from_message(msg)
        assert "location_url" in addr
        assert "18.4861,-69.9312" in addr["location_url"]
        assert is_address_sufficient(addr) is True

    def test_checkout_summary_displays_gps(self):
        session = CheckoutSession(
            step=CheckoutStep.ORDER_CONFIRM,
            product_name="Faja Reloj de Arena",
            variant_title="M / Negro",
            price=2200,
            quantity=1,
            customer_name="María",
            customer_phone="+18095551234",
            address={
                "address1": "Calle Principal 5",
                "city": "Santo Domingo",
                "location_url": "https://maps.google.com/?q=18.48,-69.93",
            },
        )
        summary = build_order_summary_message(session)
        assert "Faja Reloj de Arena" in summary
        assert "Pin GPS: https://maps.google.com/?q=18.48,-69.93" in summary


class TestPillar3SmartUpsell:
    """Test Pillar 3: Post-confirmation upsell and volume discount fallback."""

    def test_volume_discount_upsell_calculation(self):
        unit_price = 1000.0
        text = build_volume_discount_upsell("Polo Clásico", unit_price)
        assert "15% de descuento" in text
        # 1000 + 850 = 1850
        assert "RD$1,850" in text
        assert "RD$2,000" in text

    def test_build_upsell_response_fallback_to_volume_discount(self):
        # Catalog has no complementary items for this product
        catalog = [
            {"shopify_id": "1", "name": "Zapato Formal", "tags": "zapatos", "available": True, "price_min": 2500}
        ]
        # Purchased item is in technology
        upsell = build_upsell_response(
            purchased_product_name="Smartwatch Pro",
            purchased_shopify_id="999",
            catalog=catalog,
            unit_price=2000.0,
        )
        # Should fallback to 15% discount on 2nd smartwatch
        assert "Smartwatch Pro" in upsell
        assert "15% de descuento" in upsell


class TestPillar4CODReliability:
    """Test Pillar 4: Anti-fraud & customer reliability scoring."""

    def test_vip_customer_scoring(self):
        orders = [
            {"status": "entregado"},
            {"status": "entregado"},
        ]
        rel = calculate_customer_reliability({}, past_orders=orders)
        assert rel["status"] == "VIP"
        assert rel["is_safe_cod"] is True
        assert "VIP" in rel["alert_note"]

    def test_high_risk_customer_scoring(self):
        orders = [
            {"status": "devuelto"},
            {"status": "devuelto"},
        ]
        rel = calculate_customer_reliability({}, past_orders=orders)
        assert rel["status"] == "HIGH_RISK"
        assert rel["is_safe_cod"] is False
        assert "Alto riesgo" in rel["alert_note"]

    def test_new_customer_scoring(self):
        rel = calculate_customer_reliability({}, past_orders=[])
        assert rel["status"] == "NEW_CUSTOMER"
        assert rel["is_safe_cod"] is True


class TestPillar5BankReceiptValidator:
    """Test Pillar 5: Official Dominican bank transfer accounts & instructions."""

    def test_official_beneficiary_configured(self):
        assert OFFICIAL_BENEFICIARY == "Howard Eduardo Luna Perez"
        assert OFFICIAL_CEDULA == "40226400022"
        assert OFFICIAL_ACCOUNTS["popular"] == "809372188"
        assert OFFICIAL_ACCOUNTS["bhd"] == "37472100011"
        assert OFFICIAL_ACCOUNTS["promerica"] == "21921000049373"

    def test_bank_transfer_instructions_text(self):
        text = get_bank_transfer_instructions()
        assert "Howard Eduardo Luna Perez" in text
        assert "40226400022" in text
        assert "809372188" in text
        assert "37472100011" in text
        assert "21921000049373" in text
        assert "Banco Popular" in text
        assert "Banco BHD" in text
        assert "Banco Promerica" in text
