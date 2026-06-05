-- ARIA AI — Schema completo de Supabase
-- Ejecutar en el SQL Editor de Supabase

-- ── EXTENSIONES ───────────────────────────────────────────
CREATE EXTENSION IF NOT EXISTS "uuid-ossp";

-- ── AGENTES ───────────────────────────────────────────────
CREATE TABLE IF NOT EXISTS agents (
    id           UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    name         TEXT NOT NULL UNIQUE,
    type         TEXT NOT NULL,
    description  TEXT DEFAULT '',
    capabilities JSONB DEFAULT '[]',
    status       TEXT DEFAULT 'idle',
    metadata     JSONB DEFAULT '{}',
    created_at   TIMESTAMPTZ DEFAULT NOW(),
    updated_at   TIMESTAMPTZ DEFAULT NOW()
);

-- ── TAREAS ────────────────────────────────────────────────
CREATE TABLE IF NOT EXISTS tasks (
    id                UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    agent_id          UUID REFERENCES agents(id) ON DELETE SET NULL,
    type              TEXT NOT NULL,
    status            TEXT DEFAULT 'pending',
    priority          INTEGER DEFAULT 5,
    input             JSONB DEFAULT '{}',
    output            JSONB DEFAULT '{}',
    error             TEXT,
    requires_approval BOOLEAN DEFAULT FALSE,
    duration_ms       INTEGER,
    created_at        TIMESTAMPTZ DEFAULT NOW(),
    started_at        TIMESTAMPTZ,
    completed_at      TIMESTAMPTZ
);

-- ── APROBACIONES ──────────────────────────────────────────
CREATE TABLE IF NOT EXISTS approvals (
    id          UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    agent_id    UUID REFERENCES agents(id) ON DELETE SET NULL,
    agent_name  TEXT NOT NULL,
    action_type TEXT NOT NULL,
    detail      TEXT DEFAULT '',
    amount_usd  NUMERIC(10,2) DEFAULT 0,
    status      TEXT DEFAULT 'pending',
    decided_at  TIMESTAMPTZ,
    metadata    JSONB DEFAULT '{}',
    created_at  TIMESTAMPTZ DEFAULT NOW()
);

-- ── INGRESOS ──────────────────────────────────────────────
CREATE TABLE IF NOT EXISTS revenue (
    id           UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    platform     TEXT NOT NULL,
    product_name TEXT NOT NULL,
    product_id   TEXT,
    amount       NUMERIC(10,2) NOT NULL,
    currency     TEXT DEFAULT 'USD',
    customer_id  TEXT,
    metadata     JSONB DEFAULT '{}',
    created_at   TIMESTAMPTZ DEFAULT NOW()
);

-- ── PRODUCTOS DIGITALES ───────────────────────────────────
CREATE TABLE IF NOT EXISTS products (
    id           UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    name         TEXT NOT NULL,
    description  TEXT DEFAULT '',
    niche        TEXT DEFAULT '',
    platform     TEXT NOT NULL,
    external_id  TEXT,
    price_usd    NUMERIC(10,2) DEFAULT 0,
    status       TEXT DEFAULT 'active',
    sales_count  INTEGER DEFAULT 0,
    revenue_usd  NUMERIC(10,2) DEFAULT 0,
    url          TEXT,
    metadata     JSONB DEFAULT '{}',
    created_at   TIMESTAMPTZ DEFAULT NOW(),
    updated_at   TIMESTAMPTZ DEFAULT NOW()
);

-- ── SITIOS WEB ────────────────────────────────────────────
CREATE TABLE IF NOT EXISTS websites (
    id           UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    name         TEXT NOT NULL,
    domain       TEXT,
    platform     TEXT NOT NULL,
    niche        TEXT DEFAULT '',
    status       TEXT DEFAULT 'active',
    monthly_visitors INTEGER DEFAULT 0,
    revenue_usd  NUMERIC(10,2) DEFAULT 0,
    metadata     JSONB DEFAULT '{}',
    created_at   TIMESTAMPTZ DEFAULT NOW(),
    updated_at   TIMESTAMPTZ DEFAULT NOW()
);

-- ── LOGS DEL SISTEMA ──────────────────────────────────────
CREATE TABLE IF NOT EXISTS system_logs (
    id         UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    level      TEXT NOT NULL DEFAULT 'INFO',
    agent      TEXT NOT NULL DEFAULT 'system',
    message    TEXT NOT NULL,
    metadata   JSONB DEFAULT '{}',
    created_at TIMESTAMPTZ DEFAULT NOW()
);

-- ── INTELIGENCIA DE MERCADO ───────────────────────────────
CREATE TABLE IF NOT EXISTS market_intelligence (
    id                    UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    niche                 TEXT NOT NULL,
    language              TEXT DEFAULT 'en',
    demand_score          INTEGER DEFAULT 0,
    competition_score     INTEGER DEFAULT 0,
    opportunity_score     INTEGER DEFAULT 0,
    monetization_potential TEXT DEFAULT 'medio',
    recommended_products  JSONB DEFAULT '[]',
    keywords              JSONB DEFAULT '[]',
    insights              JSONB DEFAULT '{}',
    created_at            TIMESTAMPTZ DEFAULT NOW()
);

-- ── CICLOS AUTÓNOMOS ──────────────────────────────────────
CREATE TABLE IF NOT EXISTS autonomous_cycles (
    id           UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    cycle_number INTEGER NOT NULL,
    status       TEXT DEFAULT 'running',
    missions     JSONB DEFAULT '{}',
    revenue_gen  NUMERIC(10,2) DEFAULT 0,
    duration_ms  INTEGER,
    started_at   TIMESTAMPTZ DEFAULT NOW(),
    completed_at TIMESTAMPTZ
);

-- ── CAMPAÑAS DE MARKETING ─────────────────────────────────
CREATE TABLE IF NOT EXISTS marketing_campaigns (
    id            UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    name          TEXT NOT NULL,
    platform      TEXT NOT NULL,
    type          TEXT NOT NULL,
    status        TEXT DEFAULT 'draft',
    content       TEXT DEFAULT '',
    target_niche  TEXT DEFAULT '',
    impressions   INTEGER DEFAULT 0,
    clicks        INTEGER DEFAULT 0,
    conversions   INTEGER DEFAULT 0,
    revenue_usd   NUMERIC(10,2) DEFAULT 0,
    metadata      JSONB DEFAULT '{}',
    created_at    TIMESTAMPTZ DEFAULT NOW(),
    published_at  TIMESTAMPTZ
);

-- ── ÍNDICES ───────────────────────────────────────────────
CREATE INDEX IF NOT EXISTS idx_tasks_status ON tasks(status);
CREATE INDEX IF NOT EXISTS idx_tasks_agent_id ON tasks(agent_id);
CREATE INDEX IF NOT EXISTS idx_tasks_created_at ON tasks(created_at DESC);
CREATE INDEX IF NOT EXISTS idx_approvals_status ON approvals(status);
CREATE INDEX IF NOT EXISTS idx_revenue_created_at ON revenue(created_at DESC);
CREATE INDEX IF NOT EXISTS idx_revenue_platform ON revenue(platform);
CREATE INDEX IF NOT EXISTS idx_system_logs_created_at ON system_logs(created_at DESC);
CREATE INDEX IF NOT EXISTS idx_system_logs_level ON system_logs(level);
CREATE INDEX IF NOT EXISTS idx_market_intelligence_niche ON market_intelligence(niche);
CREATE INDEX IF NOT EXISTS idx_autonomous_cycles_number ON autonomous_cycles(cycle_number DESC);

-- ── ROW LEVEL SECURITY (RLS) ──────────────────────────────
-- Solo el service_role (backend) puede leer/escribir
ALTER TABLE agents              ENABLE ROW LEVEL SECURITY;
ALTER TABLE tasks               ENABLE ROW LEVEL SECURITY;
ALTER TABLE approvals           ENABLE ROW LEVEL SECURITY;
ALTER TABLE revenue             ENABLE ROW LEVEL SECURITY;
ALTER TABLE products            ENABLE ROW LEVEL SECURITY;
ALTER TABLE websites            ENABLE ROW LEVEL SECURITY;
ALTER TABLE system_logs         ENABLE ROW LEVEL SECURITY;
ALTER TABLE market_intelligence ENABLE ROW LEVEL SECURITY;
ALTER TABLE autonomous_cycles   ENABLE ROW LEVEL SECURITY;
ALTER TABLE marketing_campaigns ENABLE ROW LEVEL SECURITY;

-- Policy: service_role bypasses RLS automáticamente en Supabase
-- Para dashboard futuro, agregar políticas con auth.uid()

-- ── DATOS INICIALES: AGENTES ──────────────────────────────
INSERT INTO agents (name, type, description, capabilities) VALUES
('orchestrator',    'orchestrator', 'Director central',              '["planning","coordination","reporting"]'),
('pm_agent',        'pm',          'Análisis de mercado',            '["niche_analysis","keyword_research","affiliate_research"]'),
('cfo_agent',       'cfo',         'Finanzas y monetización',        '["product_creation","payment_processing","revenue_tracking"]'),
('dev_agent',       'dev',         'Desarrollo de productos',        '["code_generation","web_development","deployment"]'),
('marketing_agent', 'marketing',   'Marketing y redes sociales',     '["content_creation","social_posting","email_campaigns"]'),
('support_agent',   'support',     'Soporte al cliente',             '["inquiry_handling","dispute_resolution","review_monitoring"]'),
('evolution_agent', 'evolution',   'Auto-evolución del sistema',     '["performance_analysis","strategy_optimization"]')
ON CONFLICT (name) DO NOTHING;

-- Schema aplicado exitosamente en Supabase ✅
