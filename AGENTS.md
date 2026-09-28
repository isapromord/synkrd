# Sofía — SynkDR Customer Service Bot (SynkDR Engine v1)

> Agent instructions mirrored across CLAUDE.md, AGENTS.md, GEMINI.md

## Architecture
This is a SynkDR Engine v1 bot — the first plug-and-play bot template in the MBOS369 ecosystem.

### Directory Structure
```
shopify-bot/
├── .mbos/              ← MBOS369 memory persistence
├── core/               ← 🔌 REUSABLE (SynkDR Engine engine)
│   ├── brain.py        ← Hybrid AI (Gemini Flash + Claude Sonnet)
│   ├── router.py       ← Intent classifier → Tier routing
│   ├── state.py        ← Conversation state machine
│   ├── escalation.py   ← Handoff detection + gradual escalation
│   └── config.py       ← Settings loader
├── channels/           ← 🔌 REUSABLE channel adapters
│   ├── whatsapp.py     ← YCloud webhook handler
│   ├── webchat.py      ← REST API for web widget
│   └── voice.py        ← Gemini TTS (Dominican voice)
├── knowledge/          ← 🔧 PLUGGABLE per business
│   ├── shopify.py      ← Shopify API integration
│   ├── base.py         ← Abstract knowledge source
│   └── faq.py          ← FAQ retrieval from Supabase
├── bots/sofia/         ← 🔧 PLUGGABLE bot configs
│   ├── persona.py      ← Sofía's personality
│   ├── products.py     ← SynkDR product logic
│   └── policies.py     ← Store policies
├── main.py             ← FastAPI entry point
├── database.py         ← Supabase client
└── requirements.txt
```

### Key Rules
1. **ZERO TOUCH Laura/NexusRD** — This bot is completely separate
2. **core/ = Framework** — Changes here affect ALL future bots
3. **bots/sofia/ = Customization** — Sofía-specific logic
4. **Config-driven** — All settings from .env or Supabase, never hardcoded
5. **Test before claim** — Every change verified with proof

### MBOS Memory
- `.mbos/BRAIN.md` — Immutable rules (SAGRADO)
- `.mbos/MEMORY.md` — Append-only learning log
- `.mbos/HANDOFF.md` — Session state snapshot
