-- ARIA AI — Supabase Schema
-- Pegar en: Supabase Dashboard → SQL Editor → New query → Run

CREATE EXTENSION IF NOT EXISTS "uuid-ossp";

CREATE TABLE IF NOT EXISTS autonomous_cycles (
  id UUID DEFAULT uuid_generate_v4() PRIMARY KEY,
  started_at TIMESTAMPTZ DEFAULT NOW(),
  completed_at TIMESTAMPTZ,
  status TEXT DEFAULT 'running',
  revenue_generated DECIMAL(10,2) DEFAULT 0,
  articles_published INT DEFAULT 0,
  products_created INT DEFAULT 0,
  errors TEXT[] DEFAULT '{}',
  summary JSONB DEFAULT '{}'
);

CREATE TABLE IF NOT EXISTS content_published (
  id UUID DEFAULT uuid_generate_v4() PRIMARY KEY,
  created_at TIMESTAMPTZ DEFAULT NOW(),
  title TEXT NOT NULL,
  platform TEXT NOT NULL,
  url TEXT,
  topic TEXT,
  affiliate_links JSONB DEFAULT '[]',
  estimated_revenue DECIMAL(10,2) DEFAULT 0,
  views INT DEFAULT 0,
  cycle_id UUID REFERENCES autonomous_cycles(id)
);

CREATE TABLE IF NOT EXISTS products (
  id UUID DEFAULT uuid_generate_v4() PRIMARY KEY,
  created_at TIMESTAMPTZ DEFAULT NOW(),
  name TEXT NOT NULL,
  platform TEXT NOT NULL,
  product_id TEXT,
  price DECIMAL(10,2),
  sales_count INT DEFAULT 0,
  revenue DECIMAL(10,2) DEFAULT 0,
  url TEXT,
  status TEXT DEFAULT 'active'
);

CREATE TABLE IF NOT EXISTS market_opportunities (
  id UUID DEFAULT uuid_generate_v4() PRIMARY KEY,
  detected_at TIMESTAMPTZ DEFAULT NOW(),
  title TEXT NOT NULL,
  category TEXT,
  score DECIMAL(5,2),
  action_taken TEXT,
  source TEXT,
  metadata JSONB DEFAULT '{}'
);

CREATE TABLE IF NOT EXISTS system_logs (
  id UUID DEFAULT uuid_generate_v4() PRIMARY KEY,
  created_at TIMESTAMPTZ DEFAULT NOW(),
  level TEXT NOT NULL,
  module TEXT,
  message TEXT NOT NULL,
  metadata JSONB DEFAULT '{}'
);

CREATE TABLE IF NOT EXISTS revenue_events (
  id UUID DEFAULT uuid_generate_v4() PRIMARY KEY,
  created_at TIMESTAMPTZ DEFAULT NOW(),
  source TEXT NOT NULL,
  amount DECIMAL(10,2) NOT NULL,
  currency TEXT DEFAULT 'USD',
  description TEXT,
  metadata JSONB DEFAULT '{}'
);

CREATE TABLE IF NOT EXISTS self_improvements (
  id UUID DEFAULT uuid_generate_v4() PRIMARY KEY,
  created_at TIMESTAMPTZ DEFAULT NOW(),
  file_modified TEXT NOT NULL,
  description TEXT,
  diff_summary TEXT,
  applied BOOLEAN DEFAULT FALSE,
  approved_by TEXT
);

-- Per-user memory across sessions (apps/core/cognition/episodic_memory.py).
-- Redis (aria:memory:{user_id}) is the live, load-bearing store; this table is
-- a best-effort secondary copy for durability/analytics and is never required
-- for the feature to work — the app degrades gracefully if this table (or
-- Supabase itself) is unavailable.
CREATE TABLE IF NOT EXISTS aria_episodic_memory (
  id UUID DEFAULT uuid_generate_v4() PRIMARY KEY,
  created_at TIMESTAMPTZ DEFAULT NOW(),
  episode_id TEXT NOT NULL,
  user_id TEXT NOT NULL,
  episode_type TEXT NOT NULL,
  content TEXT NOT NULL,
  metadata JSONB DEFAULT '{}'
);

-- Indexes for performance
CREATE INDEX IF NOT EXISTS idx_cycles_started ON autonomous_cycles(started_at DESC);
CREATE INDEX IF NOT EXISTS idx_content_platform ON content_published(platform, created_at DESC);
CREATE INDEX IF NOT EXISTS idx_revenue_source ON revenue_events(source, created_at DESC);
CREATE INDEX IF NOT EXISTS idx_episodic_memory_user ON aria_episodic_memory(user_id, created_at DESC);

-- Row Level Security (optional, disable for service role)
ALTER TABLE autonomous_cycles ENABLE ROW LEVEL SECURITY;
ALTER TABLE content_published ENABLE ROW LEVEL SECURITY;
ALTER TABLE products ENABLE ROW LEVEL SECURITY;
ALTER TABLE market_opportunities ENABLE ROW LEVEL SECURITY;
ALTER TABLE system_logs ENABLE ROW LEVEL SECURITY;
ALTER TABLE revenue_events ENABLE ROW LEVEL SECURITY;
ALTER TABLE self_improvements ENABLE ROW LEVEL SECURITY;
ALTER TABLE aria_episodic_memory ENABLE ROW LEVEL SECURITY;

-- Allow service role full access
CREATE POLICY "service_role_all" ON autonomous_cycles FOR ALL USING (true);
CREATE POLICY "service_role_all" ON content_published FOR ALL USING (true);
CREATE POLICY "service_role_all" ON products FOR ALL USING (true);
CREATE POLICY "service_role_all" ON market_opportunities FOR ALL USING (true);
CREATE POLICY "service_role_all" ON system_logs FOR ALL USING (true);
CREATE POLICY "service_role_all" ON revenue_events FOR ALL USING (true);
CREATE POLICY "service_role_all" ON self_improvements FOR ALL USING (true);
CREATE POLICY "service_role_all" ON aria_episodic_memory FOR ALL USING (true);

SELECT 'ARIA schema creado exitosamente' as resultado;
