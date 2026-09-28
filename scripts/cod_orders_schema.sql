-- ═══════════════════════════════════════════════════════════
-- sofia_cod_orders — COD delivery lifecycle tracking
-- Powers the automated follow-up templates:
--   stage 0: confirmacion_cod  (Día 0, on order)
--   stage 1: pedido_en_camino  (~Día 1)
--   stage 2: entrega_hoy       (~Día 4)
--   stage 3: post_entrega      (~Día 5)
-- Run this in Supabase SQL Editor.
-- ═══════════════════════════════════════════════════════════

CREATE TABLE IF NOT EXISTS sofia_cod_orders (
    order_id        TEXT PRIMARY KEY,           -- Shopify order id (or order_number)
    order_name      TEXT DEFAULT '',            -- #1024
    phone           TEXT DEFAULT '',            -- E.164 customer phone
    first_name      TEXT DEFAULT '',
    items_str       TEXT DEFAULT '',
    total           NUMERIC DEFAULT 0,
    currency        TEXT DEFAULT 'DOP',

    stage           INT DEFAULT 0,              -- last lifecycle template sent
    status          TEXT DEFAULT 'active',      -- active | received | not_received | rescheduled | done
    confirmed       BOOLEAN DEFAULT FALSE,      -- customer tapped "Sí, confirmo"

    created_at      TIMESTAMPTZ DEFAULT NOW(),
    last_stage_at   TIMESTAMPTZ DEFAULT NOW()
);

-- Lifecycle sweep: active orders ordered by age
CREATE INDEX IF NOT EXISTS idx_sofia_cod_orders_active
    ON sofia_cod_orders(status, created_at);

-- Reverse lookup by phone (button taps arrive by phone, not order_id)
CREATE INDEX IF NOT EXISTS idx_sofia_cod_orders_phone
    ON sofia_cod_orders(phone) WHERE phone != '';

ALTER TABLE sofia_cod_orders ENABLE ROW LEVEL SECURITY;

CREATE POLICY "anon_all" ON sofia_cod_orders
    FOR ALL USING (true) WITH CHECK (true);
