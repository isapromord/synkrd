-- ═══════════════════════════════════════════════════════════
-- SynkDR Engine — Re-engagement Log
-- Tracks outbound re-engagement messages to avoid spamming
-- customers who ghosted after showing product interest.
-- ═══════════════════════════════════════════════════════════

CREATE TABLE IF NOT EXISTS reengagement_log (
    id UUID DEFAULT gen_random_uuid() PRIMARY KEY,
    phone TEXT NOT NULL,
    type TEXT NOT NULL DEFAULT 'ghosted',  -- ghosted, no_purchase, price_drop
    product_name TEXT DEFAULT '',
    conversation_id UUID,
    created_at TIMESTAMPTZ DEFAULT NOW()
);

-- Prevent spamming: quick lookup by phone + recency
CREATE INDEX IF NOT EXISTS idx_reengagement_phone ON reengagement_log(phone);
CREATE INDEX IF NOT EXISTS idx_reengagement_created ON reengagement_log(created_at DESC);

-- Enable RLS
ALTER TABLE reengagement_log ENABLE ROW LEVEL SECURITY;
