"""
Lead source filtering — decide whether Sofía should respond to an inbound message.

Business rule (META_ADS_ONLY mode):
Sofía only auto-responds to customers who arrived via a Meta (Facebook/Instagram)
Click-to-WhatsApp ad. WhatsApp attaches a `referral.source_id` to the FIRST message
right after the ad click. Only that first message carries it, so once we detect it we
tag the conversation as ad-originated ("meta_ad") and keep answering follow-up messages
from that same customer.
"""

from typing import Optional, Tuple

META_AD_SOURCE = "meta_ad"


def evaluate_ad_gate(
    referral_source_id: str,
    existing_source: str,
    meta_ads_only: bool,
) -> Tuple[bool, Optional[str], bool]:
    """
    Decide whether to respond to an inbound WhatsApp message.

    Args:
        referral_source_id: Meta ad id attached to THIS message (empty if none).
        existing_source: source tag already stored on the conversation (e.g. "meta_ad").
        meta_ads_only: master toggle. When False, always respond (filter disabled).

    Returns:
        (should_respond, source_tag, is_new_ad_lead)
        - should_respond: whether Sofía should generate/send a reply.
        - source_tag: the source value to persist on the conversation (or None to leave as-is).
        - is_new_ad_lead: True only when this message is a fresh ad click (first contact).
    """
    # Fresh Click-to-WhatsApp click — always allowed, and we tag the conversation.
    if referral_source_id:
        return True, META_AD_SOURCE, True

    # Filter disabled — behave like before (respond to everyone).
    if not meta_ads_only:
        return True, None, False

    # Returning customer already known to have come from an ad — keep answering.
    if existing_source == META_AD_SOURCE:
        return True, None, False

    # Not from an ad and not a known ad lead — ignore.
    return False, None, False
