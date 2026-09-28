"""Tests for the Meta Ads-only lead gate and referral parsing."""

from core.lead_filter import evaluate_ad_gate, META_AD_SOURCE
from channels.whatsapp import WhatsAppChannel


def test_evaluate_ad_gate():
    # 1. Fresh ad click → respond + tag as meta_ad + is_new_ad_lead
    should, tag, is_new = evaluate_ad_gate("120210xxxad", "", True)
    assert should is True and tag == META_AD_SOURCE and is_new is True

    # 2. Returning customer already tagged as ad lead, no new referral → respond, no re-tag
    should, tag, is_new = evaluate_ad_gate("", "meta_ad", True)
    assert should is True and tag is None and is_new is False

    # 3. Unknown sender, no referral, filter ON → IGNORE
    should, tag, is_new = evaluate_ad_gate("", "", True)
    assert should is False and is_new is False

    # 4. Filter OFF → always respond even without referral
    should, tag, is_new = evaluate_ad_gate("", "", False)
    assert should is True and is_new is False

    # 5. Ad click always wins even if filter is OFF (still tags)
    should, tag, is_new = evaluate_ad_gate("ad123", "", False)
    assert should is True and tag == META_AD_SOURCE and is_new is True

    print("✅ evaluate_ad_gate: 5/5 passed")


def test_parse_webhook_referral():
    ch = WhatsAppChannel(api_key="x", from_number="+1809", webhook_secret="")

    # Message WITH ad referral (Click-to-WhatsApp first contact)
    payload_ad = {
        "type": "whatsapp.inbound_message.received",
        "whatsappInboundMessage": {
            "from": "+18091112222",
            "type": "text",
            "id": "wamid.1",
            "text": {"body": "Hola vi su anuncio"},
            "referral": {
                "source_id": "120210000000ADID",
                "headline": "Oferta especial TrendyRD",
                "source_url": "https://fb.com/ad",
            },
        },
    }
    parsed = ch.parse_webhook(payload_ad)
    assert parsed is not None
    assert parsed["referral_source_id"] == "120210000000ADID"
    assert parsed["referral_headline"] == "Oferta especial TrendyRD"

    # Message WITHOUT referral (organic / personal contact)
    payload_organic = {
        "type": "whatsapp.inbound_message.received",
        "whatsappInboundMessage": {
            "from": "+18093334444",
            "type": "text",
            "id": "wamid.2",
            "text": {"body": "Ten buen dia corazon"},
        },
    }
    parsed2 = ch.parse_webhook(payload_organic)
    assert parsed2 is not None
    assert parsed2["referral_source_id"] == ""

    print("✅ parse_webhook referral: 2/2 passed")


if __name__ == "__main__":
    test_evaluate_ad_gate()
    test_parse_webhook_referral()
    print("\n🎉 ALL TESTS PASSED")
