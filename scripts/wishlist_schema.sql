-- ═══════════════════════════════════════════════════════════
-- Customer Wishlist — Track OOS demand for restock notifications
-- Run this in Supabase SQL Editor
-- ═══════════════════════════════════════════════════════════

CREATE TABLE IF NOT EXISTS customer_wishlist (
    id UUID DEFAULT gen_random_uuid() PRIMARY KEY,
    customer_id TEXT NOT NULL,           -- web_xxx or phone number
    product_name TEXT NOT NULL,
    variant_title TEXT NOT NULL DEFAULT '',   -- e.g. "Blanca / XL"
    shopify_product_id TEXT NOT NULL DEFAULT '',
    channel TEXT NOT NULL DEFAULT 'webchat',
    notified BOOLEAN NOT NULL DEFAULT FALSE,
    created_at TIMESTAMPTZ DEFAULT NOW(),
    updated_at TIMESTAMPTZ DEFAULT NOW(),

    -- One entry per customer per product+variant combo
    UNIQUE(customer_id, product_name, variant_title)
);

-- Index for the restock scheduler (find all waiting customers per variant)
CREATE INDEX IF NOT EXISTS idx_wishlist_variant
    ON customer_wishlist(product_name, variant_title)
    WHERE notified = FALSE;

-- Index for customer lookup
CREATE INDEX IF NOT EXISTS idx_wishlist_customer
    ON customer_wishlist(customer_id);

-- Enable RLS
ALTER TABLE customer_wishlist ENABLE ROW LEVEL SECURITY;

-- Service role can do everything (bot uses service key)
CREATE POLICY "service_role_all" ON customer_wishlist
    FOR ALL USING (auth.role() = 'service_role');
