-- ═══════════════════════════════════════════════════════════
-- SynkDR Engine — In-Chat Checkout Orders
-- Tracks orders created through WhatsApp/webchat checkout flow
-- ═══════════════════════════════════════════════════════════

CREATE TABLE IF NOT EXISTS chat_orders (
    id UUID DEFAULT gen_random_uuid() PRIMARY KEY,
    customer_phone TEXT NOT NULL,
    customer_name TEXT DEFAULT '',
    product_name TEXT NOT NULL,
    variant_id TEXT DEFAULT '',
    variant_title TEXT DEFAULT '',
    price NUMERIC(10, 2) DEFAULT 0,
    quantity INTEGER DEFAULT 1,
    address JSONB DEFAULT '{}',
    draft_order_id TEXT DEFAULT '',
    shopify_order_id TEXT DEFAULT '',
    order_name TEXT DEFAULT '',
    status TEXT DEFAULT 'confirmed',  -- confirmed, completed, cancelled
    channel TEXT DEFAULT 'whatsapp',
    created_at TIMESTAMPTZ DEFAULT NOW(),
    updated_at TIMESTAMPTZ DEFAULT NOW()
);

-- Index for quick lookups
CREATE INDEX IF NOT EXISTS idx_chat_orders_phone ON chat_orders(customer_phone);
CREATE INDEX IF NOT EXISTS idx_chat_orders_status ON chat_orders(status);
CREATE INDEX IF NOT EXISTS idx_chat_orders_draft ON chat_orders(draft_order_id);
