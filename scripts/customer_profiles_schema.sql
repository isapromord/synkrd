-- Customer Profiles — Persistent memory for returning customers
-- Run this in Supabase SQL Editor

CREATE TABLE IF NOT EXISTS customer_profiles (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    phone TEXT UNIQUE NOT NULL,
    name TEXT,

    -- Shipping
    default_address JSONB DEFAULT '{}',       -- {address1, city, province, country}

    -- Purchase history summary
    total_orders INTEGER DEFAULT 0,
    total_spent NUMERIC(12,2) DEFAULT 0,
    last_order_date TIMESTAMPTZ,

    -- Preferences (auto-learned)
    preferred_sizes JSONB DEFAULT '{}',       -- {"faja": "M", "zapatos": "38"}
    preferred_categories TEXT[] DEFAULT '{}',  -- ["belleza", "tecnología"]
    product_history JSONB DEFAULT '[]',       -- [{name, variant, date, price}] last 10

    -- Engagement
    first_seen TIMESTAMPTZ DEFAULT now(),
    last_seen TIMESTAMPTZ DEFAULT now(),
    channel TEXT DEFAULT 'whatsapp',          -- primary channel
    notes TEXT DEFAULT '',                    -- manual notes from owner

    created_at TIMESTAMPTZ DEFAULT now(),
    updated_at TIMESTAMPTZ DEFAULT now()
);

-- Indexes
CREATE INDEX IF NOT EXISTS idx_cp_phone ON customer_profiles(phone);
CREATE INDEX IF NOT EXISTS idx_cp_last_seen ON customer_profiles(last_seen);
CREATE INDEX IF NOT EXISTS idx_cp_total_orders ON customer_profiles(total_orders DESC);
