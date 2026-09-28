-- ═══════════════════════════════════════════════════════════
-- sofia_customers — CRM: every customer Sofía ever talked to
-- Run this in Supabase SQL Editor
-- ═══════════════════════════════════════════════════════════

CREATE TABLE IF NOT EXISTS sofia_customers (
    customer_id         TEXT PRIMARY KEY,           -- web_xxx or phone number
    name                TEXT DEFAULT '',
    phone               TEXT DEFAULT '',
    email               TEXT DEFAULT '',
    channel             TEXT DEFAULT 'webchat',     -- first channel used
    channels_used       TEXT[] DEFAULT '{}',        -- all channels seen

    -- Engagement
    first_seen          TIMESTAMPTZ DEFAULT NOW(),
    last_seen           TIMESTAMPTZ DEFAULT NOW(),
    total_messages      INT DEFAULT 0,

    -- Sales funnel signals
    purchase_intent     BOOLEAN DEFAULT FALSE,      -- ever said "lo quiero" / asked price
    last_interested_product TEXT DEFAULT '',         -- last product they asked about
    has_order           BOOLEAN DEFAULT FALSE,      -- completed at least 1 order in chat
    last_order_product  TEXT DEFAULT '',
    total_orders        INT DEFAULT 0,

    -- Admin
    tags                TEXT[] DEFAULT '{}',
    notes               TEXT DEFAULT '',
    created_at          TIMESTAMPTZ DEFAULT NOW(),
    updated_at          TIMESTAMPTZ DEFAULT NOW()
);

-- Fast lookup by phone (for WhatsApp customers)
CREATE INDEX IF NOT EXISTS idx_sofia_customers_phone
    ON sofia_customers(phone) WHERE phone != '';

-- Abandoned cart query: purchase_intent = true AND has_order = false
CREATE INDEX IF NOT EXISTS idx_sofia_customers_funnel
    ON sofia_customers(purchase_intent, has_order, last_seen DESC);

-- Enable RLS
ALTER TABLE sofia_customers ENABLE ROW LEVEL SECURITY;

-- Allow the bot backend (anon key) to read and write
-- Reads from the admin API are protected by FastAPI JWT auth, not Supabase RLS
CREATE POLICY "anon_all" ON sofia_customers
    FOR ALL USING (true) WITH CHECK (true);

-- ═══════════════════════════════════════════════════════════
-- Function to auto-update updated_at
-- ═══════════════════════════════════════════════════════════
CREATE OR REPLACE FUNCTION update_sofia_customers_updated_at()
RETURNS TRIGGER AS $$
BEGIN
    NEW.updated_at = NOW();
    RETURN NEW;
END;
$$ LANGUAGE plpgsql;

CREATE OR REPLACE TRIGGER sofia_customers_updated_at
    BEFORE UPDATE ON sofia_customers
    FOR EACH ROW
    EXECUTE FUNCTION update_sofia_customers_updated_at();
