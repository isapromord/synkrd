-- ═══════════════════════════════════════════════════════════════
-- Sofía SynkDR — Database Schema
-- Run this in Supabase SQL Editor (https://supabase.com/dashboard/project/votyvfjbrjmcghekaatk/sql)
-- ═══════════════════════════════════════════════════════════════

-- Customers (WhatsApp contacts)
CREATE TABLE public.customers (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    phone TEXT UNIQUE NOT NULL,
    name TEXT,
    whatsapp_name TEXT,
    language TEXT DEFAULT 'es',
    first_contact TIMESTAMPTZ DEFAULT now(),
    last_contact TIMESTAMPTZ DEFAULT now(),
    total_conversations INT DEFAULT 0,
    metadata JSONB DEFAULT '{}'
);

-- Conversations
CREATE TABLE public.conversations (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    customer_id UUID REFERENCES public.customers(id) ON DELETE CASCADE,
    channel TEXT NOT NULL DEFAULT 'whatsapp' CHECK (channel IN ('whatsapp', 'webchat')),
    state TEXT DEFAULT 'active' CHECK (state IN ('active', 'escalated', 'closed')),
    status TEXT DEFAULT 'active' CHECK (status IN ('active', 'won', 'lost')),
    intent TEXT,
    started_at TIMESTAMPTZ DEFAULT now(),
    last_message_at TIMESTAMPTZ DEFAULT now(),
    messages_count INT DEFAULT 0,
    escalated_to TEXT,
    metadata JSONB DEFAULT '{}'
);

-- Messages
CREATE TABLE public.messages (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    conversation_id UUID REFERENCES public.conversations(id) ON DELETE CASCADE,
    role TEXT NOT NULL CHECK (role IN ('customer', 'assistant', 'system')),
    content TEXT NOT NULL,
    intent TEXT,
    ai_model TEXT,
    ai_tier INT,
    tokens_used INT,
    latency_ms INT,
    created_at TIMESTAMPTZ DEFAULT now()
);

-- Products (synced from SynkDR.com)
CREATE TABLE public.products (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    shopify_id TEXT UNIQUE,
    name TEXT NOT NULL,
    description TEXT,
    category TEXT,
    tags TEXT,
    price_min NUMERIC(10,2),
    price_max NUMERIC(10,2),
    currency TEXT DEFAULT 'DOP',
    image_url TEXT,
    handle TEXT,
    url TEXT,
    available BOOLEAN DEFAULT true,
    variants JSONB DEFAULT '[]',
    options JSONB DEFAULT '[]',
    synced_at TIMESTAMPTZ DEFAULT now()
);

-- Bot Settings (Sofía HQ)
CREATE TABLE public.bot_settings (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    key TEXT UNIQUE NOT NULL,
    value TEXT NOT NULL,
    description TEXT,
    updated_at TIMESTAMPTZ DEFAULT now()
);

-- Training Data / RAG Corrections (Sofía HQ)
CREATE TABLE public.training_data (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    user_message TEXT NOT NULL,
    ideal_response TEXT NOT NULL,
    context JSONB DEFAULT '{}',
    created_at TIMESTAMPTZ DEFAULT now()
);

-- Indexes
CREATE INDEX idx_customers_phone ON public.customers(phone);
CREATE INDEX idx_conversations_customer ON public.conversations(customer_id);
CREATE INDEX idx_conversations_state ON public.conversations(state);
CREATE INDEX idx_messages_conversation ON public.messages(conversation_id);
CREATE INDEX idx_messages_created ON public.messages(created_at);
CREATE INDEX idx_products_available ON public.products(available);
CREATE INDEX idx_products_handle ON public.products(handle);

-- RLS (enabled but open — bot uses service_role key which bypasses RLS)
ALTER TABLE public.customers ENABLE ROW LEVEL SECURITY;
ALTER TABLE public.conversations ENABLE ROW LEVEL SECURITY;
ALTER TABLE public.messages ENABLE ROW LEVEL SECURITY;
ALTER TABLE public.products ENABLE ROW LEVEL SECURITY;
ALTER TABLE public.bot_settings ENABLE ROW LEVEL SECURITY;
ALTER TABLE public.training_data ENABLE ROW LEVEL SECURITY;

-- Policies — allow anon access for now (tighten later in production)
CREATE POLICY "Allow all" ON public.customers FOR ALL USING (true) WITH CHECK (true);
CREATE POLICY "Allow all" ON public.conversations FOR ALL USING (true) WITH CHECK (true);
CREATE POLICY "Allow all" ON public.messages FOR ALL USING (true) WITH CHECK (true);
CREATE POLICY "Allow all" ON public.products FOR ALL USING (true) WITH CHECK (true);
CREATE POLICY "Allow all" ON public.bot_settings FOR ALL USING (true) WITH CHECK (true);
CREATE POLICY "Allow all" ON public.training_data FOR ALL USING (true) WITH CHECK (true);

-- Auto-update last_contact timestamp
CREATE OR REPLACE FUNCTION update_last_contact()
RETURNS TRIGGER AS $$
BEGIN NEW.last_contact = now(); RETURN NEW; END;
$$ LANGUAGE plpgsql;

CREATE TRIGGER customers_last_contact
    BEFORE UPDATE ON public.customers
    FOR EACH ROW EXECUTE FUNCTION update_last_contact();
