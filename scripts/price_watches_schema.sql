-- ═══════════════════════════════════════════════════════════
-- Price Watches — Track customer interest for price drop alerts
-- Run this in Supabase SQL Editor
-- ═══════════════════════════════════════════════════════════

CREATE TABLE IF NOT EXISTS price_watches (
    id UUID DEFAULT gen_random_uuid() PRIMARY KEY,
    phone TEXT NOT NULL,
    product_shopify_id TEXT NOT NULL,
    product_name TEXT NOT NULL DEFAULT '',
    price_at_watch NUMERIC(10,2) NOT NULL DEFAULT 0,
    notified BOOLEAN NOT NULL DEFAULT FALSE,
    created_at TIMESTAMPTZ DEFAULT NOW(),
    updated_at TIMESTAMPTZ DEFAULT NOW(),
    
    -- One watch per customer per product
    UNIQUE(phone, product_shopify_id)
);

-- Index for the scheduler query (active watches)
CREATE INDEX IF NOT EXISTS idx_price_watches_active 
    ON price_watches(notified) WHERE notified = FALSE;

-- Index for customer lookups
CREATE INDEX IF NOT EXISTS idx_price_watches_phone
    ON price_watches(phone);

-- Enable RLS
ALTER TABLE price_watches ENABLE ROW LEVEL SECURITY;

-- Allow service role full access
CREATE POLICY "Service role full access on price_watches"
    ON price_watches
    FOR ALL
    USING (true)
    WITH CHECK (true);
