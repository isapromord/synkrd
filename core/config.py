"""
SynkDR Engine — Multi-Bot Platform
Core Configuration Module

All settings are loaded from environment variables or Supabase.
NEVER hardcode values — everything is config-driven for SynkDR Engine portability.
"""

import os
from dataclasses import dataclass, field
from typing import Optional
from dotenv import load_dotenv

load_dotenv()


@dataclass
class AIConfig:
    """AI engine configuration — hybrid Gemini + Claude."""
    # Gemini (Tier 1 — fast, cheap, 80% of queries)
    gemini_api_key: str = field(default_factory=lambda: os.getenv("GEMINI_API_KEY", ""))
    gemini_model: str = field(default_factory=lambda: os.getenv("GEMINI_MODEL", "gemini-2.5-flash"))

    # Claude (Tier 2 — complex conversations, 20% of queries)
    anthropic_api_key: str = field(default_factory=lambda: os.getenv("ANTHROPIC_API_KEY", ""))
    claude_model: str = field(default_factory=lambda: os.getenv("CLAUDE_MODEL", "claude-sonnet-4-20250514"))
    claude_fallback_model: str = field(default_factory=lambda: os.getenv("CLAUDE_FALLBACK_MODEL", "claude-3-5-haiku-20241022"))

    # Routing
    max_tokens: int = field(default_factory=lambda: int(os.getenv("AI_MAX_TOKENS", "500")))
    temperature: float = field(default_factory=lambda: float(os.getenv("AI_TEMPERATURE", "0.3")))


@dataclass
class ChannelConfig:
    """Communication channels configuration."""
    # WhatsApp via YCloud
    ycloud_api_key: str = field(default_factory=lambda: os.getenv("YCLOUD_API_KEY", ""))
    ycloud_webhook_secret: str = field(default_factory=lambda: os.getenv("YCLOUD_WEBHOOK_SECRET", ""))
    whatsapp_from_number: str = field(default_factory=lambda: os.getenv("WHATSAPP_FROM_NUMBER", ""))

    # Web Chat
    webchat_cors_origins: str = field(default_factory=lambda: os.getenv("WEBCHAT_CORS_ORIGINS", "https://synkdr.com"))


@dataclass
class DatabaseConfig:
    """Supabase database configuration."""
    supabase_url: str = field(default_factory=lambda: os.getenv("SUPABASE_URL", ""))
    supabase_key: str = field(default_factory=lambda: os.getenv("SUPABASE_KEY", ""))


@dataclass
class ShopifyConfig:
    """Shopify API configuration."""
    store_url: str = field(default_factory=lambda: os.getenv("SHOPIFY_STORE_URL", "trendyrd.com"))
    api_key: str = field(default_factory=lambda: os.getenv("SHOPIFY_API_KEY", ""))
    api_secret: str = field(default_factory=lambda: os.getenv("SHOPIFY_API_SECRET", ""))
    access_token: str = field(default_factory=lambda: os.getenv("SHOPIFY_ACCESS_TOKEN", ""))
    api_version: str = field(default_factory=lambda: os.getenv("SHOPIFY_API_VERSION", "2024-10"))

@dataclass
class MiCondoConfig:
    """Mi Condo Supabase configuration — separate from Sofia's."""
    supabase_url: str = field(default_factory=lambda: os.getenv("MICONDO_SUPABASE_URL", ""))
    supabase_key: str = field(default_factory=lambda: os.getenv("MICONDO_SUPABASE_KEY", ""))


@dataclass
class BotConfig:
    """Master bot configuration — aggregates all sub-configs."""
    platform_name: str = "SynkDR"
    bot_name: str = field(default_factory=lambda: os.getenv("BOT_NAME", "Sofía"))
    store_name: str = field(default_factory=lambda: os.getenv("STORE_NAME", "TrendyRD"))
    language: str = "es-DO"  # Dominican Spanish
    currency: str = "RD$"
    timezone: str = "America/Santo_Domingo"

    # Sub-configs
    ai: AIConfig = field(default_factory=AIConfig)
    channels: ChannelConfig = field(default_factory=ChannelConfig)
    database: DatabaseConfig = field(default_factory=DatabaseConfig)
    shopify: ShopifyConfig = field(default_factory=ShopifyConfig)
    micondo: MiCondoConfig = field(default_factory=MiCondoConfig)

    # Escalation
    escalation_telegram_chat_id: str = field(default_factory=lambda: os.getenv("TELEGRAM_CHAT_ID", ""))
    escalation_telegram_token: str = field(default_factory=lambda: os.getenv("TELEGRAM_BOT_TOKEN", ""))
    owner_name: str = field(default_factory=lambda: os.getenv("OWNER_NAME", "Howard"))

    # Lead filtering — when True, only respond to Meta Click-to-WhatsApp ad leads
    meta_ads_only: bool = field(default_factory=lambda: os.getenv("META_ADS_ONLY", "true").lower() in ("1", "true", "yes"))

    # Server
    host: str = field(default_factory=lambda: os.getenv("HOST", "0.0.0.0"))
    port: int = field(default_factory=lambda: int(os.getenv("PORT", "8002")))
    sync_key: str = field(default_factory=lambda: os.getenv("SYNC_KEY", ""))


# Singleton instance
settings = BotConfig()
