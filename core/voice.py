"""
SynkDR Engine — Voice Module

Hybrid voice strategy for e-commerce WhatsApp:
- TTS (Gemini Flash) for emotional moments (greetings, confirmations, thanks)
- Text for structured info (prices, product details, order summaries)
- Incoming voice transcription via Gemini (no extra dependency)

Pipeline: Text → Gemini TTS → PCM → WAV → OGG Opus → YCloud upload → send audio
"""

import os
import io
import wave
import logging
import tempfile
import subprocess
import shutil
from typing import Optional
from enum import Enum

logger = logging.getLogger("synkdr.voice")


# ═══════════════════════════════════════════════════════════════
# CONFIGURATION
# ═══════════════════════════════════════════════════════════════

VOICE_ENABLED = os.getenv("VOICE_ENABLED", "false").lower() == "true"
VOICE_NAME = os.getenv("VOICE_NAME", "Leda")  # Gemini prebuilt voice


class VoiceMoment(str, Enum):
    """Moments where voice adds value in e-commerce."""
    GREETING = "greeting"           # First contact / returning customer
    ORDER_CONFIRMED = "order_confirmed"  # Order placed successfully
    THANK_YOU = "thank_you"         # After purchase, follow-up
    EMPATHY = "empathy"             # Customer frustrated / problem
    NONE = "none"                   # Use text (product info, prices, etc.)


# Emotion → voice style mapping
EMOTION_STYLES = {
    VoiceMoment.GREETING: "Warm, welcoming, genuine smile in voice. Dominican casual friendliness.",
    VoiceMoment.ORDER_CONFIRMED: "Excited and celebratory. Genuine happiness for the customer.",
    VoiceMoment.THANK_YOU: "Grateful and warm. Sincere appreciation.",
    VoiceMoment.EMPATHY: "Soft, understanding, patient. Show genuine care.",
    VoiceMoment.NONE: "",
}

# Voice persona prompt (tells Gemini HOW to speak)
VOICE_PERSONA = """You are Sofía, a Dominican e-commerce assistant. 
Your voice is warm, natural, and friendly — like a trusted friend helping you shop.
You speak Dominican Spanish naturally, with casual warmth.
Never sound robotic or like a call center agent.
Never read emojis — skip them entirely.
Keep it conversational and brief.

### EMOTIONAL CONTEXT: {emotion_style}

### TEXT TO SPEAK:
"""


# ═══════════════════════════════════════════════════════════════
# SMART VOICE ROUTING — When to use voice vs text
# ═══════════════════════════════════════════════════════════════

# Patterns that indicate structured info (should be TEXT)
TEXT_ONLY_PATTERNS = [
    "RD$", "precio", "cuesta", "disponible", "talla",  # Product/pricing info
    "dirección", "Calle", "sector",                     # Address info
    "Confirmas", "📋", "📦 Orden:",                     # Order summaries
    "variantes", "opciones",                             # Variant selection
]


def detect_voice_moment(
    response_text: str,
    intent: str = "",
    is_first_message: bool = False,
    customer_sent_audio: bool = False,
    checkout_step: str = "",
) -> VoiceMoment:
    """
    Decide if a response should be sent as voice or text.

    Strategy:
    - Voice for emotional/personal moments (high impact)
    - Text for structured data (prices, addresses, options)
    - Mirror: if customer sent audio, respond with audio

    Returns VoiceMoment.NONE if text is better.
    """
    if not VOICE_ENABLED:
        return VoiceMoment.NONE

    # Rule 1: If response contains structured data → always text
    for pattern in TEXT_ONLY_PATTERNS:
        if pattern in response_text:
            return VoiceMoment.NONE

    # Rule 2: Mirror — customer sent voice note → respond with voice
    if customer_sent_audio:
        return VoiceMoment.GREETING  # Use friendly tone for mirrored responses

    # Rule 3: Checkout completion → celebrate
    if checkout_step == "completed":
        return VoiceMoment.ORDER_CONFIRMED

    # Rule 4: First message / greeting
    if is_first_message or intent == "greeting":
        return VoiceMoment.GREETING

    # Rule 5: Escalation / frustration
    if intent == "escalation":
        return VoiceMoment.EMPATHY

    # Default: text is more appropriate for e-commerce
    return VoiceMoment.NONE


# ═══════════════════════════════════════════════════════════════
# TTS GENERATION — Gemini Flash
# ═══════════════════════════════════════════════════════════════

def generate_tts(text: str, moment: VoiceMoment = VoiceMoment.GREETING) -> Optional[bytes]:
    """
    Generate voice audio from text using Gemini TTS.

    Args:
        text: Text for Sofía to speak
        moment: Emotional context for voice style

    Returns:
        Raw PCM audio bytes (24kHz, 16-bit, mono) or None
    """
    if not VOICE_ENABLED:
        return None

    try:
        from google import genai
        from google.genai import types
        from core.config import settings

        api_key = settings.ai.gemini_api_key
        if not api_key:
            logger.error("❌ No Gemini API key for TTS")
            return None

        # Clean text for speech (remove emojis, markdown)
        clean_text = _clean_text_for_speech(text)
        if len(clean_text) < 5:
            return None

        # Build prompt with emotion
        emotion_style = EMOTION_STYLES.get(moment, EMOTION_STYLES[VoiceMoment.GREETING])
        prompt = VOICE_PERSONA.format(emotion_style=emotion_style) + clean_text

        logger.info(f"🎙️ Generating TTS ({moment.value}): '{clean_text[:50]}...'")

        client = genai.Client(api_key=api_key)
        response = client.models.generate_content(
            model="gemini-2.5-flash-preview-tts",
            contents=prompt,
            config=types.GenerateContentConfig(
                response_modalities=["AUDIO"],
                speech_config=types.SpeechConfig(
                    voice_config=types.VoiceConfig(
                        prebuilt_voice_config=types.PrebuiltVoiceConfig(
                            voice_name=VOICE_NAME,
                        )
                    )
                ),
            ),
        )

        audio_data = response.candidates[0].content.parts[0].inline_data.data
        logger.info(f"✅ TTS generated: {len(audio_data)} bytes")
        return audio_data

    except Exception as e:
        logger.error(f"❌ TTS generation failed: {e}")
        return None


# ═══════════════════════════════════════════════════════════════
# AUDIO PROCESSING — PCM → WAV → OGG Opus
# ═══════════════════════════════════════════════════════════════

def pcm_to_wav(pcm_data: bytes) -> Optional[str]:
    """Save raw PCM bytes to a WAV file. Returns temp file path."""
    try:
        path = tempfile.mktemp(suffix=".wav")
        with wave.open(path, "wb") as wf:
            wf.setnchannels(1)        # Mono
            wf.setsampwidth(2)        # 16-bit
            wf.setframerate(24000)    # 24kHz (Gemini TTS output rate)
            wf.writeframes(pcm_data)
        return path
    except Exception as e:
        logger.error(f"❌ WAV save failed: {e}")
        return None


def wav_to_ogg(wav_path: str) -> str:
    """
    Convert WAV to OGG Opus for WhatsApp (smaller, optimized for voice).
    Falls back to WAV if ffmpeg unavailable.
    """
    if not shutil.which("ffmpeg"):
        logger.warning("⚠️ ffmpeg not found — sending WAV (larger)")
        return wav_path

    ogg_path = wav_path.replace(".wav", ".ogg")
    try:
        result = subprocess.run(
            [
                "ffmpeg", "-y",
                "-i", wav_path,
                "-c:a", "libopus",
                "-b:a", "32k",          # 32kbps — ideal for voice
                "-ar", "24000",          # 24kHz
                "-ac", "1",              # Mono
                "-application", "voip",  # Voice optimization
                ogg_path,
            ],
            capture_output=True,
            timeout=30,
        )
        if result.returncode == 0:
            return ogg_path
        logger.warning(f"⚠️ OGG conversion failed, using WAV")
        return wav_path
    except Exception as e:
        logger.warning(f"⚠️ OGG conversion error: {e}")
        return wav_path


def prepare_audio_file(pcm_data: bytes) -> Optional[tuple]:
    """
    Full pipeline: PCM → WAV → OGG.
    Returns (file_path, mime_type, filename) or None.
    """
    wav_path = pcm_to_wav(pcm_data)
    if not wav_path:
        return None

    audio_path = wav_to_ogg(wav_path)
    if audio_path.endswith(".ogg"):
        mime_type = "audio/ogg"
        filename = "sofia_voice.ogg"
    else:
        mime_type = "audio/wav"
        filename = "sofia_voice.wav"

    return audio_path, mime_type, filename


# ═══════════════════════════════════════════════════════════════
# INCOMING VOICE TRANSCRIPTION — Gemini
# ═══════════════════════════════════════════════════════════════

def transcribe_audio_from_url(audio_url: str, ycloud_api_key: str = "") -> Optional[str]:
    """
    Download and transcribe an incoming WhatsApp voice note using Gemini.

    Args:
        audio_url: URL to the audio file (from YCloud webhook)
        ycloud_api_key: API key for authenticated download

    Returns:
        Transcribed text or None
    """
    try:
        import httpx
        from google import genai
        from google.genai import types
        from core.config import settings

        # Download audio
        headers = {"X-API-Key": ycloud_api_key} if ycloud_api_key else {}
        with httpx.Client(timeout=30) as client:
            resp = client.get(audio_url, headers=headers, follow_redirects=True)
            if resp.status_code != 200:
                logger.error(f"❌ Audio download failed: {resp.status_code}")
                return None
            audio_bytes = resp.content

        if not audio_bytes or len(audio_bytes) < 100:
            logger.warning("⚠️ Audio file too small or empty")
            return None

        # Save to temp file for Gemini
        temp_path = tempfile.mktemp(suffix=".ogg")
        with open(temp_path, "wb") as f:
            f.write(audio_bytes)

        # Transcribe using Gemini
        gemini_client = genai.Client(api_key=settings.ai.gemini_api_key)

        audio_file = gemini_client.files.upload(file=temp_path)
        response = gemini_client.models.generate_content(
            model="gemini-2.5-flash",
            contents=[
                "Transcribe this audio exactly as spoken. Return ONLY the transcription, nothing else. "
                "If it's in Spanish, return the Spanish text. If unintelligible, return '[audio no claro]'.",
                audio_file,
            ],
        )

        # Cleanup
        try:
            os.remove(temp_path)
        except OSError:
            pass

        transcript = response.text.strip()
        if transcript:
            logger.info(f"🎙️ Transcribed: '{transcript[:80]}...'")
            return transcript

        return None

    except Exception as e:
        logger.error(f"❌ Transcription failed: {e}")
        return None


# ═══════════════════════════════════════════════════════════════
# HELPERS
# ═══════════════════════════════════════════════════════════════

import re

# Emoji pattern for cleaning
_EMOJI_PATTERN = re.compile(
    "["
    "\U0001F600-\U0001F64F"  # Emoticons
    "\U0001F300-\U0001F5FF"  # Symbols & pictographs
    "\U0001F680-\U0001F6FF"  # Transport & map
    "\U0001F1E0-\U0001F1FF"  # Flags
    "\U00002702-\U000027B0"
    "\U000024C2-\U0001F251"
    "\U0001f926-\U0001f937"
    "\U0001F900-\U0001F9FF"  # Supplemental
    "\u200d\u2640-\u2642\ufe0f"
    "]+",
    flags=re.UNICODE,
)


def _clean_text_for_speech(text: str) -> str:
    """Remove emojis, markdown, and formatting from text for TTS."""
    # Remove emojis
    clean = _EMOJI_PATTERN.sub("", text)
    # Remove markdown bold/italic
    clean = re.sub(r"\*+([^*]+)\*+", r"\1", clean)
    # Remove bullet points
    clean = re.sub(r"^[•\-]\s*", "", clean, flags=re.MULTILINE)
    # Collapse whitespace
    clean = re.sub(r"\s+", " ", clean).strip()
    return clean


def cleanup_temp_files(*paths):
    """Safely remove temp audio files."""
    for path in paths:
        if path:
            try:
                if os.path.exists(path):
                    os.remove(path)
            except OSError:
                pass
