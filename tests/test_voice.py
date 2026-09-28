"""
Tests for Voice Module (hybrid TTS, smart routing, audio pipeline).

Tests: voice moment detection, text cleaning, audio pipeline,
transcription, WhatsApp audio sending.
"""

import pytest
from unittest.mock import AsyncMock, patch, MagicMock, mock_open
import os

from core.voice import (
    detect_voice_moment,
    VoiceMoment,
    VOICE_ENABLED,
    _clean_text_for_speech,
    pcm_to_wav,
    cleanup_temp_files,
    EMOTION_STYLES,
    VOICE_PERSONA,
    TEXT_ONLY_PATTERNS,
)


# ═══════════════════════════════════════════════════════════════
# VOICE MOMENT DETECTION — Smart Routing
# ═══════════════════════════════════════════════════════════════

class TestDetectVoiceMoment:
    """Test the hybrid routing: when to use voice vs text."""

    def test_voice_disabled_returns_none(self):
        """When VOICE_ENABLED is False, always return NONE."""
        with patch("core.voice.VOICE_ENABLED", False):
            result = detect_voice_moment(
                "¡Hola! Bienvenida a TrendyRD",
                intent="greeting",
                is_first_message=True,
            )
            assert result == VoiceMoment.NONE

    def test_first_message_returns_greeting(self):
        """First message should trigger voice greeting."""
        with patch("core.voice.VOICE_ENABLED", True):
            result = detect_voice_moment(
                "¡Hola! Soy Sofía, tu asistente de TrendyRD",
                intent="greeting",
                is_first_message=True,
            )
            assert result == VoiceMoment.GREETING

    def test_greeting_intent_returns_greeting(self):
        """Greeting intent should always trigger voice."""
        with patch("core.voice.VOICE_ENABLED", True):
            result = detect_voice_moment(
                "¡Hola! ¿Cómo te puedo ayudar?",
                intent="greeting",
            )
            assert result == VoiceMoment.GREETING

    def test_price_info_returns_none(self):
        """Response with pricing should use text, not voice."""
        with patch("core.voice.VOICE_ENABLED", True):
            result = detect_voice_moment(
                "La Faja Colombiana cuesta RD$2,500",
                intent="product_info",
            )
            assert result == VoiceMoment.NONE

    def test_address_info_returns_none(self):
        """Response with address data should use text."""
        with patch("core.voice.VOICE_ENABLED", True):
            result = detect_voice_moment(
                "Confirmas tu dirección: Calle Principal #5, Sector Naco",
                intent="checkout",
            )
            assert result == VoiceMoment.NONE

    def test_order_summary_returns_none(self):
        """Order summaries should be text (readable reference)."""
        with patch("core.voice.VOICE_ENABLED", True):
            result = detect_voice_moment(
                "📋 Resumen de tu pedido:\n📦 Orden: #1045",
                intent="checkout",
            )
            assert result == VoiceMoment.NONE

    def test_variant_selection_returns_none(self):
        """Variant/option selection should be text."""
        with patch("core.voice.VOICE_ENABLED", True):
            result = detect_voice_moment(
                "Tenemos estas variantes disponibles: S, M, L, XL",
                intent="product_info",
            )
            assert result == VoiceMoment.NONE

    def test_customer_audio_mirrors_voice(self):
        """If customer sends voice → mirror with voice response."""
        with patch("core.voice.VOICE_ENABLED", True):
            result = detect_voice_moment(
                "Claro que sí, te ayudo con eso",
                intent="general",
                customer_sent_audio=True,
            )
            assert result == VoiceMoment.GREETING

    def test_checkout_completed_returns_order_confirmed(self):
        """Order completion should trigger celebratory voice."""
        with patch("core.voice.VOICE_ENABLED", True):
            result = detect_voice_moment(
                "Tu pedido ha sido registrado exitosamente",
                intent="checkout",
                checkout_step="completed",
            )
            assert result == VoiceMoment.ORDER_CONFIRMED

    def test_escalation_returns_empathy(self):
        """Escalation/frustration should trigger empathetic voice."""
        with patch("core.voice.VOICE_ENABLED", True):
            result = detect_voice_moment(
                "Entiendo tu frustración, déjame conectarte con alguien",
                intent="escalation",
            )
            assert result == VoiceMoment.EMPATHY

    def test_general_response_returns_none(self):
        """Normal responses should use text, not voice."""
        with patch("core.voice.VOICE_ENABLED", True):
            result = detect_voice_moment(
                "Tenemos muchos productos disponibles",
                intent="browsing",
            )
            assert result == VoiceMoment.NONE

    def test_price_pattern_rd_dollar(self):
        """RD$ in response should force text."""
        with patch("core.voice.VOICE_ENABLED", True):
            result = detect_voice_moment(
                "El precio es RD$1,500 con envío gratis",
                intent="product_info",
                is_first_message=True,  # Even if first message
            )
            assert result == VoiceMoment.NONE

    def test_confirmacion_pattern_forces_text(self):
        """'Confirmas' pattern in response should force text."""
        with patch("core.voice.VOICE_ENABLED", True):
            result = detect_voice_moment(
                "Confirmas tu pedido de 2 unidades?",
                intent="checkout",
            )
            assert result == VoiceMoment.NONE

    def test_customer_audio_overrides_text_patterns(self):
        """Customer audio mirroring takes priority UNLESS response has structured data."""
        with patch("core.voice.VOICE_ENABLED", True):
            # Audio + price = text wins (structured data)
            result = detect_voice_moment(
                "La Faja cuesta RD$2,500",
                intent="product_info",
                customer_sent_audio=True,
            )
            assert result == VoiceMoment.NONE

    def test_checkout_completed_even_with_structured_data(self):
        """Order completion has structured data but should check patterns first."""
        with patch("core.voice.VOICE_ENABLED", True):
            # Completion with order number → text patterns win
            result = detect_voice_moment(
                "📦 Orden: #1045 registrada exitosamente",
                intent="checkout",
                checkout_step="completed",
            )
            # "📦 Orden:" matches TEXT_ONLY pattern → text wins
            assert result == VoiceMoment.NONE


# ═══════════════════════════════════════════════════════════════
# TEXT CLEANING
# ═══════════════════════════════════════════════════════════════

class TestCleanTextForSpeech:
    """Test text cleaning for TTS input."""

    def test_removes_emojis(self):
        result = _clean_text_for_speech("¡Hola! 😊 ¿Cómo estás? 🎉")
        assert "😊" not in result
        assert "🎉" not in result
        assert "Hola" in result

    def test_removes_markdown_bold(self):
        result = _clean_text_for_speech("La **Faja Colombiana** está en oferta")
        assert "**" not in result
        assert "Faja Colombiana" in result

    def test_removes_markdown_italic(self):
        result = _clean_text_for_speech("*Envío gratis* a todo el país")
        assert "*" not in result
        assert "Envío gratis" in result

    def test_removes_bullet_points(self):
        result = _clean_text_for_speech("• Item 1\n- Item 2\n• Item 3")
        assert "•" not in result
        assert "- " not in result

    def test_collapses_whitespace(self):
        result = _clean_text_for_speech("Hola    amiga,   ¿cómo    estás?")
        assert "    " not in result

    def test_preserves_spanish_chars(self):
        result = _clean_text_for_speech("¿Cuánto cuesta la piña? ¡Dímelo!")
        assert "¿" in result
        assert "ñ" in result
        assert "¡" in result

    def test_empty_string(self):
        result = _clean_text_for_speech("")
        assert result == ""

    def test_emoji_only_returns_empty(self):
        result = _clean_text_for_speech("😊🎉👍")
        assert result.strip() == ""


# ═══════════════════════════════════════════════════════════════
# AUDIO PIPELINE
# ═══════════════════════════════════════════════════════════════

class TestPcmToWav:
    """Test PCM to WAV conversion."""

    def test_creates_wav_file(self, tmp_path):
        """PCM data should create a valid WAV file."""
        # Generate fake PCM data (silence — 0.1 second of 24kHz 16-bit mono)
        pcm_data = b"\x00\x00" * 2400  # 0.1s at 24000 Hz
        
        with patch("tempfile.mktemp", return_value=str(tmp_path / "test.wav")):
            result = pcm_to_wav(pcm_data)
        
        assert result is not None
        assert result.endswith(".wav")
        assert os.path.exists(result)

    def test_wav_has_correct_format(self, tmp_path):
        """WAV file should be 24kHz, 16-bit, mono."""
        import wave
        pcm_data = b"\x00\x00" * 2400
        
        with patch("tempfile.mktemp", return_value=str(tmp_path / "test.wav")):
            result = pcm_to_wav(pcm_data)
        
        with wave.open(result, "rb") as wf:
            assert wf.getnchannels() == 1
            assert wf.getsampwidth() == 2
            assert wf.getframerate() == 24000


class TestCleanupTempFiles:
    """Test temp file cleanup."""

    def test_removes_existing_files(self, tmp_path):
        f = tmp_path / "test.wav"
        f.write_bytes(b"fake data")
        assert f.exists()
        cleanup_temp_files(str(f))
        assert not f.exists()

    def test_handles_nonexistent_files(self):
        """Should not raise on missing files."""
        cleanup_temp_files("/nonexistent/file.wav", None, "")

    def test_handles_none(self):
        cleanup_temp_files(None)


# ═══════════════════════════════════════════════════════════════
# TTS GENERATION (mocked)
# ═══════════════════════════════════════════════════════════════

class TestGenerateTts:
    """Test TTS generation with mocked Gemini."""

    def test_returns_none_when_disabled(self):
        from core.voice import generate_tts
        with patch("core.voice.VOICE_ENABLED", False):
            result = generate_tts("Hola amiga", VoiceMoment.GREETING)
            assert result is None

    def test_returns_none_for_short_text(self):
        from core.voice import generate_tts
        with patch("core.voice.VOICE_ENABLED", True):
            result = generate_tts("hi", VoiceMoment.GREETING)
            assert result is None

    @patch("core.voice.VOICE_ENABLED", True)
    def test_calls_gemini_with_correct_model(self):
        from core.voice import generate_tts

        mock_client = MagicMock()
        mock_part = MagicMock()
        mock_part.inline_data.data = b"fake_pcm_audio"
        mock_candidate = MagicMock()
        mock_candidate.content.parts = [mock_part]
        mock_client.models.generate_content.return_value = MagicMock(candidates=[mock_candidate])

        with patch("google.genai.Client", return_value=mock_client):
            with patch("core.config.settings") as mock_settings:
                mock_settings.ai.gemini_api_key = "test-key"
                result = generate_tts("Hola amiga, bienvenida", VoiceMoment.GREETING)

        assert result == b"fake_pcm_audio"
        call_args = mock_client.models.generate_content.call_args
        assert call_args.kwargs["model"] == "gemini-2.5-flash-preview-tts"

    @patch("core.voice.VOICE_ENABLED", True)
    def test_returns_none_on_error(self):
        from core.voice import generate_tts

        with patch("google.genai.Client", side_effect=Exception("API error")):
            with patch("core.config.settings") as mock_settings:
                mock_settings.ai.gemini_api_key = "test-key"
                result = generate_tts("Hola amiga", VoiceMoment.GREETING)

        assert result is None


# ═══════════════════════════════════════════════════════════════
# TRANSCRIPTION (mocked)
# ═══════════════════════════════════════════════════════════════

class TestTranscribeAudio:
    """Test audio transcription with mocked Gemini."""

    @patch("core.voice.VOICE_ENABLED", True)
    def test_transcribes_audio_successfully(self):
        from core.voice import transcribe_audio_from_url

        mock_response = MagicMock()
        mock_response.text = "Quiero ver las fajas colombianas"

        mock_client = MagicMock()
        mock_client.files.upload.return_value = MagicMock()
        mock_client.models.generate_content.return_value = mock_response

        mock_http_response = MagicMock()
        mock_http_response.status_code = 200
        mock_http_response.content = b"fake_audio_bytes_longer_than_100_" * 5

        with patch("httpx.Client") as MockHttpClient:
            MockHttpClient.return_value.__enter__ = MagicMock(return_value=MagicMock(
                get=MagicMock(return_value=mock_http_response)
            ))
            MockHttpClient.return_value.__exit__ = MagicMock(return_value=False)
            with patch("google.genai.Client", return_value=mock_client):
                with patch("core.config.settings") as mock_settings:
                    mock_settings.ai.gemini_api_key = "test-key"
                    result = transcribe_audio_from_url(
                        "https://example.com/audio.ogg",
                        ycloud_api_key="test-ycloud-key",
                    )

        assert result == "Quiero ver las fajas colombianas"

    def test_returns_none_on_download_failure(self):
        from core.voice import transcribe_audio_from_url

        mock_http_response = MagicMock()
        mock_http_response.status_code = 404

        with patch("httpx.Client") as MockHttpClient:
            MockHttpClient.return_value.__enter__ = MagicMock(return_value=MagicMock(
                get=MagicMock(return_value=mock_http_response)
            ))
            MockHttpClient.return_value.__exit__ = MagicMock(return_value=False)
            with patch("core.config.settings") as mock_settings:
                mock_settings.ai.gemini_api_key = "test-key"
                result = transcribe_audio_from_url(
                    "https://example.com/audio.ogg",
                    ycloud_api_key="test-key",
                )

        assert result is None

    def test_returns_none_on_small_audio(self):
        from core.voice import transcribe_audio_from_url

        mock_http_response = MagicMock()
        mock_http_response.status_code = 200
        mock_http_response.content = b"tiny"

        with patch("httpx.Client") as MockHttpClient:
            MockHttpClient.return_value.__enter__ = MagicMock(return_value=MagicMock(
                get=MagicMock(return_value=mock_http_response)
            ))
            MockHttpClient.return_value.__exit__ = MagicMock(return_value=False)
            with patch("core.config.settings") as mock_settings:
                mock_settings.ai.gemini_api_key = "test-key"
                result = transcribe_audio_from_url(
                    "https://example.com/audio.ogg",
                    ycloud_api_key="test-key",
                )

        assert result is None


# ═══════════════════════════════════════════════════════════════
# WHATSAPP AUDIO SENDING
# ═══════════════════════════════════════════════════════════════

class TestWhatsAppAudioSend:
    """Test WhatsApp channel audio upload + send."""

    @pytest.mark.asyncio
    async def test_upload_media_success(self):
        from channels.whatsapp import WhatsAppChannel
        
        channel = WhatsAppChannel(
            api_key="test-key",
            from_number="+18294554783",
        )

        mock_response = MagicMock()
        mock_response.status_code = 200
        mock_response.json.return_value = {"id": "media-123"}

        with patch("os.getenv", return_value="waba-test-id"):
            with patch("httpx.AsyncClient") as MockClient:
                mock_client_instance = AsyncMock()
                mock_client_instance.post.return_value = mock_response
                MockClient.return_value.__aenter__ = AsyncMock(return_value=mock_client_instance)
                MockClient.return_value.__aexit__ = AsyncMock(return_value=False)

                with patch("builtins.open", mock_open(read_data=b"fake_audio")):
                    result = await channel.upload_media("/tmp/test.ogg", "audio/ogg")

        assert result == "media-123"

    @pytest.mark.asyncio
    async def test_upload_media_no_waba_id(self):
        from channels.whatsapp import WhatsAppChannel
        
        channel = WhatsAppChannel(api_key="test-key", from_number="+18294554783")

        with patch("os.getenv", return_value=""):
            result = await channel.upload_media("/tmp/test.ogg")

        assert result is None

    @pytest.mark.asyncio
    async def test_send_audio_full_pipeline(self):
        from channels.whatsapp import WhatsAppChannel
        
        channel = WhatsAppChannel(api_key="test-key", from_number="+18294554783")

        # Mock upload returning media ID
        channel.upload_media = AsyncMock(return_value="media-456")

        mock_response = MagicMock()
        mock_response.status_code = 200

        with patch("httpx.AsyncClient") as MockClient:
            mock_client_instance = AsyncMock()
            mock_client_instance.post.return_value = mock_response
            MockClient.return_value.__aenter__ = AsyncMock(return_value=mock_client_instance)
            MockClient.return_value.__aexit__ = AsyncMock(return_value=False)

            result = await channel.send_audio("+18091234567", "/tmp/voice.ogg")

        assert result is True
        channel.upload_media.assert_called_once_with("/tmp/voice.ogg", "audio/ogg")

    @pytest.mark.asyncio
    async def test_send_audio_upload_fails(self):
        from channels.whatsapp import WhatsAppChannel
        
        channel = WhatsAppChannel(api_key="test-key", from_number="+18294554783")
        channel.upload_media = AsyncMock(return_value=None)

        result = await channel.send_audio("+18091234567", "/tmp/voice.ogg")

        assert result is False


# ═══════════════════════════════════════════════════════════════
# WEBHOOK AUDIO URL EXTRACTION
# ═══════════════════════════════════════════════════════════════

class TestWebhookAudioParsing:
    """Test that WhatsApp webhook correctly extracts audio URLs."""

    def test_audio_message_extracts_url(self):
        from channels.whatsapp import WhatsAppChannel
        
        channel = WhatsAppChannel(api_key="k", from_number="+1")
        
        payload = {
            "type": "whatsapp.inbound_message.received",
            "whatsappInboundMessage": {
                "from": "+18091234567",
                "type": "audio",
                "audio": {"link": "https://ycloud.com/media/audio123.ogg"},
                "id": "msg-1",
                "timestamp": "2025-01-01T00:00:00Z",
                "customerProfile": {"name": "Maria"},
            },
        }

        result = channel.parse_webhook(payload)
        assert result is not None
        assert result["message_type"] == "audio"
        assert result["audio_url"] == "https://ycloud.com/media/audio123.ogg"
        assert result["message_text"] == "[Audio recibido]"

    def test_text_message_has_empty_audio_url(self):
        from channels.whatsapp import WhatsAppChannel
        
        channel = WhatsAppChannel(api_key="k", from_number="+1")
        
        payload = {
            "type": "whatsapp.inbound_message.received",
            "whatsappInboundMessage": {
                "from": "+18091234567",
                "type": "text",
                "text": {"body": "Hola"},
                "id": "msg-2",
                "timestamp": "2025-01-01T00:00:00Z",
                "customerProfile": {"name": "Pedro"},
            },
        }

        result = channel.parse_webhook(payload)
        assert result is not None
        assert result["audio_url"] == ""

    def test_audio_without_link(self):
        from channels.whatsapp import WhatsAppChannel
        
        channel = WhatsAppChannel(api_key="k", from_number="+1")
        
        payload = {
            "type": "whatsapp.inbound_message.received",
            "whatsappInboundMessage": {
                "from": "+18091234567",
                "type": "audio",
                "audio": {},
                "id": "msg-3",
                "timestamp": "2025-01-01T00:00:00Z",
                "customerProfile": {},
            },
        }

        result = channel.parse_webhook(payload)
        assert result is not None
        assert result["audio_url"] == ""


# ═══════════════════════════════════════════════════════════════
# VOICE MOMENT ENUM & CONSTANTS
# ═══════════════════════════════════════════════════════════════

class TestVoiceConstants:
    """Test voice module constants and enums."""

    def test_all_moments_have_emotion_styles(self):
        for moment in VoiceMoment:
            assert moment in EMOTION_STYLES

    def test_voice_persona_has_placeholder(self):
        assert "{emotion_style}" in VOICE_PERSONA

    def test_text_only_patterns_not_empty(self):
        assert len(TEXT_ONLY_PATTERNS) > 0

    def test_voice_moment_values(self):
        assert VoiceMoment.GREETING.value == "greeting"
        assert VoiceMoment.ORDER_CONFIRMED.value == "order_confirmed"
        assert VoiceMoment.THANK_YOU.value == "thank_you"
        assert VoiceMoment.EMPATHY.value == "empathy"
        assert VoiceMoment.NONE.value == "none"


# ═══════════════════════════════════════════════════════════════
# WAV TO OGG CONVERSION (mocked ffmpeg)
# ═══════════════════════════════════════════════════════════════

class TestWavToOgg:
    """Test WAV to OGG conversion."""

    def test_falls_back_to_wav_when_no_ffmpeg(self):
        from core.voice import wav_to_ogg
        
        with patch("shutil.which", return_value=None):
            result = wav_to_ogg("/tmp/test.wav")
        
        assert result == "/tmp/test.wav"

    def test_calls_ffmpeg_with_correct_args(self):
        from core.voice import wav_to_ogg
        
        mock_result = MagicMock()
        mock_result.returncode = 0
        
        with patch("shutil.which", return_value="/usr/bin/ffmpeg"):
            with patch("subprocess.run", return_value=mock_result) as mock_run:
                result = wav_to_ogg("/tmp/test.wav")
        
        assert result == "/tmp/test.ogg"
        call_args = mock_run.call_args[0][0]
        assert "ffmpeg" in call_args
        assert "libopus" in call_args
        assert "32k" in call_args
        assert "voip" in call_args

    def test_falls_back_on_ffmpeg_error(self):
        from core.voice import wav_to_ogg
        
        mock_result = MagicMock()
        mock_result.returncode = 1
        
        with patch("shutil.which", return_value="/usr/bin/ffmpeg"):
            with patch("subprocess.run", return_value=mock_result):
                result = wav_to_ogg("/tmp/test.wav")
        
        assert result == "/tmp/test.wav"


# ═══════════════════════════════════════════════════════════════
# PREPARE AUDIO FILE (full pipeline)
# ═══════════════════════════════════════════════════════════════

class TestPrepareAudioFile:
    """Test the full PCM → WAV → OGG pipeline."""

    def test_returns_ogg_when_ffmpeg_available(self, tmp_path):
        from core.voice import prepare_audio_file
        
        pcm_data = b"\x00\x00" * 2400
        wav_path = str(tmp_path / "test.wav")
        ogg_path = str(tmp_path / "test.ogg")
        
        mock_result = MagicMock()
        mock_result.returncode = 0
        
        with patch("tempfile.mktemp", return_value=wav_path):
            with patch("shutil.which", return_value="/usr/bin/ffmpeg"):
                with patch("subprocess.run", return_value=mock_result):
                    # Create fake ogg file
                    open(ogg_path, "wb").close()
                    result = prepare_audio_file(pcm_data)
        
        assert result is not None
        path, mime, filename = result
        assert mime == "audio/ogg"
        assert filename == "sofia_voice.ogg"

    def test_returns_wav_when_no_ffmpeg(self, tmp_path):
        from core.voice import prepare_audio_file
        
        pcm_data = b"\x00\x00" * 2400
        wav_path = str(tmp_path / "test.wav")
        
        with patch("tempfile.mktemp", return_value=wav_path):
            with patch("shutil.which", return_value=None):
                result = prepare_audio_file(pcm_data)
        
        assert result is not None
        path, mime, filename = result
        assert mime == "audio/wav"
        assert filename == "sofia_voice.wav"

    def test_returns_none_on_pcm_failure(self):
        from core.voice import prepare_audio_file
        
        with patch("core.voice.pcm_to_wav", return_value=None):
            result = prepare_audio_file(b"bad data")
        
        assert result is None
