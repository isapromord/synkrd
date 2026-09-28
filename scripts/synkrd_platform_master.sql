-- ═══════════════════════════════════════════════════════════════
-- SynkRD SaaS Platform — Master Database Schema & Migrations
-- Compatible with Supabase PostgreSQL
-- ═══════════════════════════════════════════════════════════════

-- 1. Storefront Templates Catalog (Themes)
CREATE TABLE IF NOT EXISTS public.storefront_templates (
    id TEXT PRIMARY KEY,                       -- 'apex-cod', 'classic-shrine'
    name TEXT NOT NULL,                        -- 'Apex COD ⚡'
    badge TEXT,                                -- '⭐ Recomendado • Alta Conversión RD'
    category TEXT DEFAULT 'High-Converting COD',
    description TEXT NOT NULL,
    preview_url TEXT NOT NULL,                 -- 'https://www.trendyrd.com'
    thumbnail_url TEXT,
    features JSONB DEFAULT '[]'::jsonb,
    default_config JSONB DEFAULT '{}'::jsonb,
    is_active BOOLEAN DEFAULT true,
    created_at TIMESTAMPTZ DEFAULT now()
);

-- Seed Templates
INSERT INTO public.storefront_templates (id, name, badge, category, description, preview_url, features, default_config) VALUES
(
    'apex-cod',
    'Apex COD ⚡',
    '⭐ Recomendado • Alta Conversión RD',
    'High-Converting COD',
    'Plantilla insignia optimizada para venta por impulso con Pago Contra Entrega en República Dominicana. Incluye Stories móviles, Split Hero Deal, Bento Grid, UGC Reviews, Sofía AI y escudo anti-robo de imágenes.',
    'https://www.trendyrd.com',
    '["Stories Circulares Móviles", "Split Hero con Spotlight Deal", "Bento Grid de Categorías", "Checkout COD de 1 Clic con WhatsApp", "Sofía AI Asistente de Ventas Integrado", "Escudo Anti-Copia / Anti-Robo de Imágenes", "Notificaciones Flotantes de Ventas en Vivo"]'::jsonb,
    '{"primary_color": "#002d4b", "accent_color": "#ed1515", "currency": "DOP", "currency_symbol": "RD$"}'::jsonb
),
(
    'classic-shrine',
    'Classic Shrine 🛍️',
    'Catálogo Estándar',
    'E-Commerce Clásico',
    'Diseño limpio y equilibrado para tiendas con catálogos amplios y navegación tradicional.',
    'https://www.trendyrd.com/?theme=shrine',
    '["Banner Hero Promocional", "Grid de Productos 4 Columnas", "Filtros de Colecciones", "Checkout Express"]'::jsonb,
    '{"primary_color": "#002d4b", "accent_color": "#ed1515", "currency": "DOP", "currency_symbol": "RD$"}'::jsonb
)
ON CONFLICT (id) DO UPDATE SET
    name = EXCLUDED.name,
    badge = EXCLUDED.badge,
    description = EXCLUDED.description,
    preview_url = EXCLUDED.preview_url,
    features = EXCLUDED.features;

-- 2. Platform Admins (Super Admins)
CREATE TABLE IF NOT EXISTS public.platform_admins (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    auth_user_id UUID UNIQUE,                  -- Supabase Auth user ID (optional if using standalone admin PIN)
    email TEXT UNIQUE NOT NULL,
    name TEXT NOT NULL,
    role TEXT DEFAULT 'super_admin' CHECK (role IN ('super_admin', 'support', 'viewer')),
    is_active BOOLEAN DEFAULT true,
    created_at TIMESTAMPTZ DEFAULT now(),
    last_login TIMESTAMPTZ
);

-- 3. Plans (Pricing Tiers)
CREATE TABLE IF NOT EXISTS public.tenant_plans (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    name TEXT UNIQUE NOT NULL,                 -- 'starter', 'pro', 'enterprise'
    display_name TEXT NOT NULL,                 -- 'Starter', 'Pro', 'Enterprise'
    max_conversations_mo INT NOT NULL,          -- Monthly conversation limit
    max_products INT DEFAULT 100,               -- Product catalog limit
    features JSONB DEFAULT '{}'::jsonb,        -- Feature flags
    price_usd NUMERIC(10,2) DEFAULT 0,         -- Monthly price in USD
    is_active BOOLEAN DEFAULT true,
    created_at TIMESTAMPTZ DEFAULT now()
);

-- Seed Plans
INSERT INTO public.tenant_plans (name, display_name, max_conversations_mo, max_products, price_usd, features) VALUES
(
    'starter', 'Starter', 500, 50, 29.00,
    '{"webchat": true, "whatsapp": true, "voice": false, "ai_conversational": true, "smart_catalog": true, "custom_persona": false, "spanish_localization": true, "in_chat_checkout": false, "smart_upsell": false, "abandoned_cart_recovery": false, "price_drop_alerts": false, "customer_memory": false, "visual_search": false, "reengagement": false, "analytics": true, "escalation": true, "shipping_notifications": false, "discount_codes": false, "api_access": false, "custom_domain": false, "dedicated_support": false}'::jsonb
),
(
    'pro', 'Pro', 2000, 200, 59.00,
    '{"webchat": true, "whatsapp": true, "voice": true, "ai_conversational": true, "smart_catalog": true, "custom_persona": true, "spanish_localization": true, "in_chat_checkout": true, "smart_upsell": true, "abandoned_cart_recovery": false, "price_drop_alerts": false, "customer_memory": true, "visual_search": false, "reengagement": true, "analytics": true, "escalation": true, "shipping_notifications": true, "discount_codes": true, "api_access": false, "custom_domain": false, "dedicated_support": false}'::jsonb
),
(
    'enterprise', 'Enterprise', 10000, 1000, 99.00,
    '{"webchat": true, "whatsapp": true, "voice": true, "ai_conversational": true, "smart_catalog": true, "custom_persona": true, "spanish_localization": true, "in_chat_checkout": true, "smart_upsell": true, "abandoned_cart_recovery": true, "price_drop_alerts": true, "customer_memory": true, "visual_search": true, "reengagement": true, "analytics": true, "escalation": true, "shipping_notifications": true, "discount_codes": true, "api_access": true, "custom_domain": true, "dedicated_support": true}'::jsonb
)
ON CONFLICT (name) DO NOTHING;

-- 4. Tenants (Connected Stores)
CREATE TABLE IF NOT EXISTS public.tenants (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    name TEXT NOT NULL,                        -- "TrendyRD"
    slug TEXT UNIQUE NOT NULL,                 -- "trendyrd"
    domain TEXT,                               -- "trendyrd.com"
    logo_url TEXT,
    selected_template_id TEXT REFERENCES public.storefront_templates(id) DEFAULT 'apex-cod',
    
    -- Supabase connection
    supabase_url TEXT,
    supabase_anon_key TEXT,
    supabase_service_key TEXT,
    
    -- AI Configuration
    ai_provider TEXT DEFAULT 'openai',
    ai_model TEXT DEFAULT 'gpt-4o-mini',
    ai_temperature NUMERIC(2,1) DEFAULT 0.5,
    ai_max_tokens INT DEFAULT 300,
    
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
    metadata JSONB DEFAULT '{}'::jsonb
);

-- 5. Platform Activity Logs
CREATE TABLE IF NOT EXISTS public.platform_logs (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    admin_id UUID REFERENCES public.platform_admins(id),
    tenant_id UUID REFERENCES public.tenants(id),
    action TEXT NOT NULL,
    details JSONB DEFAULT '{}'::jsonb,
    ip_address TEXT,
    created_at TIMESTAMPTZ DEFAULT now()
);

-- 6. Tenant Stats Snapshots
CREATE TABLE IF NOT EXISTS public.tenant_stats (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    tenant_id UUID REFERENCES public.tenants(id) ON DELETE CASCADE,
    date DATE NOT NULL,
    conversations_count INT DEFAULT 0,
    messages_count INT DEFAULT 0,
    escalations_count INT DEFAULT 0,
    orders_count INT DEFAULT 0,
    orders_revenue_dop NUMERIC(12,2) DEFAULT 0,
    products_synced INT DEFAULT 0,
    created_at TIMESTAMPTZ DEFAULT now(),
    UNIQUE(tenant_id, date)
);

-- Indexes
CREATE INDEX IF NOT EXISTS idx_tenants_slug ON public.tenants(slug);
CREATE INDEX IF NOT EXISTS idx_tenants_status ON public.tenants(status);
CREATE INDEX IF NOT EXISTS idx_tenants_template ON public.tenants(selected_template_id);
CREATE INDEX IF NOT EXISTS idx_platform_logs_tenant ON public.platform_logs(tenant_id);
CREATE INDEX IF NOT EXISTS idx_tenant_stats_tenant_date ON public.tenant_stats(tenant_id, date);
