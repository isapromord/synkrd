-- ═══════════════════════════════════════════════════════════════
-- Sofía SaaS Platform — Super Admin Schema
-- Run this in the PLATFORM Supabase project SQL Editor
-- This extends the existing project with multi-tenant management
-- ═══════════════════════════════════════════════════════════════

-- ─── Platform Admins (Super Admins) ────────────────────────────
CREATE TABLE IF NOT EXISTS public.platform_admins (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    auth_user_id UUID UNIQUE NOT NULL,  -- Supabase Auth user ID
    email TEXT UNIQUE NOT NULL,
    name TEXT NOT NULL,
    role TEXT DEFAULT 'super_admin' CHECK (role IN ('super_admin', 'support', 'viewer')),
    is_active BOOLEAN DEFAULT true,
    created_at TIMESTAMPTZ DEFAULT now(),
    last_login TIMESTAMPTZ
);

-- ─── Plans (Pricing Tiers) ────────────────────────────────────
CREATE TABLE IF NOT EXISTS public.tenant_plans (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    name TEXT UNIQUE NOT NULL,             -- 'starter', 'pro', 'enterprise'
    display_name TEXT NOT NULL,             -- 'Starter', 'Pro', 'Enterprise'
    max_conversations_mo INT NOT NULL,      -- Monthly conversation limit
    max_products INT DEFAULT 100,           -- Product catalog limit
    features JSONB DEFAULT '{}',            -- Feature flags: {"whatsapp": true, "voice": false, ...}
    price_usd NUMERIC(10,2) DEFAULT 0,     -- Monthly price
    is_active BOOLEAN DEFAULT true,
    created_at TIMESTAMPTZ DEFAULT now()
);

-- ─── Tenants (Connected Stores) ───────────────────────────────
CREATE TABLE IF NOT EXISTS public.tenants (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    name TEXT NOT NULL,                        -- "SynkDR", "MiTienda"
    slug TEXT UNIQUE NOT NULL,                 -- "SynkDR", "mitienda" (URL-safe)
    domain TEXT,                               -- "SynkDR.com"
    logo_url TEXT,
    
    -- Supabase connection (separate project per tenant)
    supabase_url TEXT NOT NULL,
    supabase_anon_key TEXT NOT NULL,
    supabase_service_key TEXT,                 -- Encrypted, for server-side ops
    
    -- AI Configuration
    ai_provider TEXT DEFAULT 'gemini' CHECK (ai_provider IN ('gemini', 'openai', 'anthropic')),
    ai_model TEXT DEFAULT 'gemini-2.5-flash',
    ai_fallback_model TEXT DEFAULT 'claude-sonnet-4-20250514',
    ai_temperature NUMERIC(2,1) DEFAULT 0.3,
    ai_max_tokens INT DEFAULT 500,
    
    -- API Keys (encrypted at rest)
    gemini_api_key TEXT,
    anthropic_api_key TEXT,
    openai_api_key TEXT,
    ycloud_api_key TEXT,
    whatsapp_from_number TEXT,
    
    -- Plan & Billing
    plan_id UUID REFERENCES public.tenant_plans(id),
    billing_email TEXT,
    billing_status TEXT DEFAULT 'trial' CHECK (billing_status IN ('trial', 'active', 'past_due', 'cancelled', 'suspended')),
    trial_ends_at TIMESTAMPTZ DEFAULT (now() + interval '14 days'),
    
    -- Status
    status TEXT DEFAULT 'active' CHECK (status IN ('active', 'setup', 'suspended', 'deleted')),
    owner_name TEXT,
    owner_email TEXT,
    
    -- Bot Configuration
    bot_name TEXT DEFAULT 'Sofía',
    store_url TEXT,
    webhook_secret TEXT,
    
    -- Metadata
    created_at TIMESTAMPTZ DEFAULT now(),
    updated_at TIMESTAMPTZ DEFAULT now(),
    last_sync_at TIMESTAMPTZ,
    metadata JSONB DEFAULT '{}'
);

-- ─── Platform Activity Log ────────────────────────────────────
CREATE TABLE IF NOT EXISTS public.platform_logs (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    admin_id UUID REFERENCES public.platform_admins(id),
    tenant_id UUID REFERENCES public.tenants(id),
    action TEXT NOT NULL,                  -- 'tenant.created', 'tenant.suspended', 'plan.changed'
    details JSONB DEFAULT '{}',
    ip_address TEXT,
    created_at TIMESTAMPTZ DEFAULT now()
);

-- ─── Tenant Stats Snapshots (daily aggregates) ───────────────
CREATE TABLE IF NOT EXISTS public.tenant_stats (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    tenant_id UUID REFERENCES public.tenants(id) ON DELETE CASCADE,
    date DATE NOT NULL,
    conversations_count INT DEFAULT 0,
    messages_count INT DEFAULT 0,
    escalations_count INT DEFAULT 0,
    avg_response_ms INT DEFAULT 0,
    resolution_rate NUMERIC(5,2) DEFAULT 0,
    products_synced INT DEFAULT 0,
    created_at TIMESTAMPTZ DEFAULT now(),
    UNIQUE(tenant_id, date)
);

-- ═══════════════════════════════════════════════════════════════
-- INDEXES
-- ═══════════════════════════════════════════════════════════════
CREATE INDEX IF NOT EXISTS idx_tenants_slug ON public.tenants(slug);
CREATE INDEX IF NOT EXISTS idx_tenants_status ON public.tenants(status);
CREATE INDEX IF NOT EXISTS idx_platform_logs_tenant ON public.platform_logs(tenant_id);
CREATE INDEX IF NOT EXISTS idx_platform_logs_created ON public.platform_logs(created_at);
CREATE INDEX IF NOT EXISTS idx_tenant_stats_tenant_date ON public.tenant_stats(tenant_id, date);
CREATE INDEX IF NOT EXISTS idx_platform_admins_auth ON public.platform_admins(auth_user_id);

-- ═══════════════════════════════════════════════════════════════
-- RLS
-- ═══════════════════════════════════════════════════════════════
ALTER TABLE public.platform_admins ENABLE ROW LEVEL SECURITY;
ALTER TABLE public.tenants ENABLE ROW LEVEL SECURITY;
ALTER TABLE public.tenant_plans ENABLE ROW LEVEL SECURITY;
ALTER TABLE public.platform_logs ENABLE ROW LEVEL SECURITY;
ALTER TABLE public.tenant_stats ENABLE ROW LEVEL SECURITY;

-- Platform admins can access everything (they authenticate via service_role or verified JWT)
CREATE POLICY "platform_admins_all" ON public.platform_admins FOR ALL USING (true) WITH CHECK (true);
CREATE POLICY "tenants_all" ON public.tenants FOR ALL USING (true) WITH CHECK (true);
CREATE POLICY "plans_all" ON public.tenant_plans FOR ALL USING (true) WITH CHECK (true);
CREATE POLICY "logs_all" ON public.platform_logs FOR ALL USING (true) WITH CHECK (true);
CREATE POLICY "stats_all" ON public.tenant_stats FOR ALL USING (true) WITH CHECK (true);

-- ═══════════════════════════════════════════════════════════════
-- SEED: Default Plans (21-feature system)
-- ═══════════════════════════════════════════════════════════════
INSERT INTO public.tenant_plans (name, display_name, max_conversations_mo, max_products, price_usd, features) VALUES
    ('starter', 'Starter', 500, 50, 29.00, '{"webchat": true, "whatsapp": true, "voice": false, "ai_conversational": true, "smart_catalog": true, "custom_persona": false, "spanish_localization": true, "in_chat_checkout": false, "smart_upsell": false, "abandoned_cart_recovery": false, "price_drop_alerts": false, "customer_memory": false, "visual_search": false, "reengagement": false, "analytics": true, "escalation": true, "shipping_notifications": false, "discount_codes": false, "api_access": false, "custom_domain": false, "dedicated_support": false}'),
    ('pro', 'Pro', 2000, 200, 59.00, '{"webchat": true, "whatsapp": true, "voice": true, "ai_conversational": true, "smart_catalog": true, "custom_persona": true, "spanish_localization": true, "in_chat_checkout": true, "smart_upsell": true, "abandoned_cart_recovery": false, "price_drop_alerts": false, "customer_memory": true, "visual_search": false, "reengagement": true, "analytics": true, "escalation": true, "shipping_notifications": true, "discount_codes": true, "api_access": false, "custom_domain": false, "dedicated_support": false}'),
    ('enterprise', 'Enterprise', 10000, 1000, 99.00, '{"webchat": true, "whatsapp": true, "voice": true, "ai_conversational": true, "smart_catalog": true, "custom_persona": true, "spanish_localization": true, "in_chat_checkout": true, "smart_upsell": true, "abandoned_cart_recovery": true, "price_drop_alerts": true, "customer_memory": true, "visual_search": true, "reengagement": true, "analytics": true, "escalation": true, "shipping_notifications": true, "discount_codes": true, "api_access": true, "custom_domain": true, "dedicated_support": true}')
ON CONFLICT (name) DO NOTHING;

-- ═══════════════════════════════════════════════════════════════
-- AUTO-UPDATE updated_at
-- ═══════════════════════════════════════════════════════════════
CREATE OR REPLACE FUNCTION update_tenant_timestamp()
RETURNS TRIGGER AS $$
BEGIN NEW.updated_at = now(); RETURN NEW; END;
$$ LANGUAGE plpgsql;

CREATE TRIGGER tenants_updated_at
    BEFORE UPDATE ON public.tenants
    FOR EACH ROW EXECUTE FUNCTION update_tenant_timestamp();
