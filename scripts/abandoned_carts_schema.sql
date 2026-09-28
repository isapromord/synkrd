-- ═══════════════════════════════════════════════════════════════
-- Abandoned Cart Recovery — Schema Migration
-- Run this in Supabase SQL Editor
-- ═══════════════════════════════════════════════════════════════

-- Abandoned carts (captured from Shopify checkout webhooks)
CREATE TABLE IF NOT EXISTS public.abandoned_carts (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    shopify_checkout_id TEXT UNIQUE NOT NULL,
    customer_phone TEXT NOT NULL,
    customer_name TEXT,
    customer_email TEXT,
    total_price NUMERIC(10,2),
    currency TEXT DEFAULT 'DOP',
    line_items JSONB DEFAULT '[]',
    checkout_url TEXT,      -- Shopify magic link to restore cart
    status TEXT DEFAULT 'abandoned' CHECK (status IN ('abandoned', 'recovered', 'expired', 'opted_out')),
    followup_count INT DEFAULT 0,
    last_followup_at TIMESTAMPTZ,
    created_at TIMESTAMPTZ DEFAULT now(),
    updated_at TIMESTAMPTZ DEFAULT now()
);

-- Indexes for efficient querying
CREATE INDEX IF NOT EXISTS idx_abandoned_carts_status ON public.abandoned_carts(status);
CREATE INDEX IF NOT EXISTS idx_abandoned_carts_phone ON public.abandoned_carts(customer_phone);
CREATE INDEX IF NOT EXISTS idx_abandoned_carts_created ON public.abandoned_carts(created_at);

-- RLS
ALTER TABLE public.abandoned_carts ENABLE ROW LEVEL SECURITY;
CREATE POLICY "Allow all" ON public.abandoned_carts FOR ALL USING (true) WITH CHECK (true);

-- Auto-update timestamp
CREATE OR REPLACE FUNCTION update_abandoned_cart_timestamp()
RETURNS TRIGGER AS $$
BEGIN NEW.updated_at = now(); RETURN NEW; END;
$$ LANGUAGE plpgsql;

CREATE TRIGGER abandoned_carts_updated
    BEFORE UPDATE ON public.abandoned_carts
    FOR EACH ROW EXECUTE FUNCTION update_abandoned_cart_timestamp();
