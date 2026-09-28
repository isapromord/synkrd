"""
Tests for Re-engagement Module.

Tests: ghosted detection, product interest extraction,
candidate filtering, message building, DB wiring.
"""

import pytest
from unittest.mock import AsyncMock, patch, MagicMock

from core.reengagement import (
    is_conversation_ghosted,
    get_top_product_interest,
    filter_reengagement_candidates,
    build_reengagement_text,
    build_reengagement_template_params,
)


# ═══════════════════════════════════════════════════════════════
# TEST DATA
# ═══════════════════════════════════════════════════════════════

def _make_conv(phone, history_last_role="assistant", interests=None, conv_id="c1"):
    """Helper to build a conversation dict for testing."""
    history = []
    if history_last_role:
        history = [
            {"role": "user", "content": "¿Tienen fajas?"},
            {"role": "assistant", "content": "¡Sí! Tenemos la Faja Colombiana."},
        ]
        if history_last_role == "user":
            history.append({"role": "user", "content": "Ok gracias"})

    return {
        "id": conv_id,
        "phone": phone,
        "metadata": {
            "history": history,
            "product_interests": interests or [],
        },
    }


# ═══════════════════════════════════════════════════════════════
# GHOSTED DETECTION
# ═══════════════════════════════════════════════════════════════

class TestIsConversationGhosted:
    """Check if last message was from the bot (customer left on read)."""

    def test_last_message_from_assistant(self):
        meta = {"history": [
            {"role": "user", "content": "Hola"},
            {"role": "assistant", "content": "¡Hola! ¿En qué te ayudo?"},
        ]}
        assert is_conversation_ghosted(meta) is True

    def test_last_message_from_user(self):
        meta = {"history": [
            {"role": "user", "content": "Hola"},
            {"role": "assistant", "content": "¡Hola!"},
            {"role": "user", "content": "Gracias, bye"},
        ]}
        assert is_conversation_ghosted(meta) is False

    def test_empty_history(self):
        assert is_conversation_ghosted({"history": []}) is False

    def test_no_history_key(self):
        assert is_conversation_ghosted({}) is False

    def test_single_assistant_message(self):
        meta = {"history": [{"role": "assistant", "content": "¡Bienvenid@!"}]}
        assert is_conversation_ghosted(meta) is True


# ═══════════════════════════════════════════════════════════════
# PRODUCT INTEREST EXTRACTION
# ═══════════════════════════════════════════════════════════════

class TestGetTopProductInterest:

    def test_returns_first_interest(self):
        meta = {"product_interests": ["Faja Colombiana", "Sérum Vitamina C"]}
        assert get_top_product_interest(meta) == "Faja Colombiana"

    def test_single_interest(self):
        meta = {"product_interests": ["Crema Hidratante"]}
        assert get_top_product_interest(meta) == "Crema Hidratante"

    def test_empty_interests(self):
        assert get_top_product_interest({"product_interests": []}) is None

    def test_no_key(self):
        assert get_top_product_interest({}) is None


# ═══════════════════════════════════════════════════════════════
# CANDIDATE FILTERING
# ═══════════════════════════════════════════════════════════════

class TestFilterReengagementCandidates:

    def test_valid_candidate(self):
        convs = [_make_conv("+18091234567", interests=["Faja Colombiana"])]
        result = filter_reengagement_candidates(convs, set(), set())
        assert len(result) == 1
        assert result[0]["phone"] == "+18091234567"
        assert result[0]["product_name"] == "Faja Colombiana"

    def test_excludes_recent_orders(self):
        convs = [_make_conv("+18091234567", interests=["Faja"])]
        result = filter_reengagement_candidates(convs, {"+18091234567"}, set())
        assert len(result) == 0

    def test_excludes_recently_reengaged(self):
        convs = [_make_conv("+18091234567", interests=["Faja"])]
        result = filter_reengagement_candidates(convs, set(), {"+18091234567"})
        assert len(result) == 0

    def test_excludes_non_ghosted(self):
        """Customer replied last — not ghosted."""
        convs = [_make_conv("+18091234567", history_last_role="user", interests=["Faja"])]
        result = filter_reengagement_candidates(convs, set(), set())
        assert len(result) == 0

    def test_excludes_no_product_interest(self):
        convs = [_make_conv("+18091234567", interests=[])]
        result = filter_reengagement_candidates(convs, set(), set())
        assert len(result) == 0

    def test_excludes_empty_phone(self):
        convs = [_make_conv("", interests=["Faja"])]
        result = filter_reengagement_candidates(convs, set(), set())
        assert len(result) == 0

    def test_multiple_candidates(self):
        convs = [
            _make_conv("+18091111111", interests=["Faja"], conv_id="c1"),
            _make_conv("+18092222222", interests=["Sérum"], conv_id="c2"),
            _make_conv("+18093333333", history_last_role="user", interests=["Crema"], conv_id="c3"),
        ]
        result = filter_reengagement_candidates(convs, set(), set())
        assert len(result) == 2
        phones = {r["phone"] for r in result}
        assert "+18091111111" in phones
        assert "+18092222222" in phones

    def test_mixed_exclusions(self):
        convs = [
            _make_conv("+1001", interests=["P1"], conv_id="c1"),  # Valid
            _make_conv("+1002", interests=["P2"], conv_id="c2"),  # Ordered
            _make_conv("+1003", interests=["P3"], conv_id="c3"),  # Reengaged
        ]
        result = filter_reengagement_candidates(convs, {"+1002"}, {"+1003"})
        assert len(result) == 1
        assert result[0]["phone"] == "+1001"


# ═══════════════════════════════════════════════════════════════
# MESSAGE BUILDERS
# ═══════════════════════════════════════════════════════════════

class TestBuildReengagementText:

    def test_with_name(self):
        msg = build_reengagement_text("María", "Faja Colombiana", "TrendyRD")
        assert "María" in msg
        assert "Faja Colombiana" in msg
        assert "TrendyRD" in msg

    def test_without_name(self):
        msg = build_reengagement_text("", "Sérum", "TrendyRD")
        assert "amig@" in msg
        assert "Sérum" in msg

    def test_contains_question(self):
        msg = build_reengagement_text("Pedro", "Faja", "TrendyRD")
        assert "?" in msg


class TestBuildReengagementTemplateParams:

    def test_with_name(self):
        params = build_reengagement_template_params("María", "Faja Colombiana")
        assert params == ["María", "Faja Colombiana"]

    def test_without_name(self):
        params = build_reengagement_template_params("", "Sérum")
        assert params == ["amig@", "Sérum"]

    def test_returns_list_of_two(self):
        params = build_reengagement_template_params("X", "Y")
        assert len(params) == 2
