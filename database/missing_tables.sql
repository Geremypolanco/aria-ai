-- =====================================================
  -- ARIA AI — Tablas FALTANTES en Supabase
  -- Pegar en: Supabase Dashboard → SQL Editor → Run
  -- Tablas: content_published, market_opportunities,
  --         revenue_events, self_improvements,
  --         content_articles, digital_products,
  --         affiliate_links, social_accounts
  -- =====================================================

  CREATE EXTENSION IF NOT EXISTS "uuid-ossp";

  -- ── content_published ────────────────────────────────
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

  -- ── market_opportunities ─────────────────────────────
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

  -- ── revenue_events ───────────────────────────────────
  CREATE TABLE IF NOT EXISTS revenue_events (
    id UUID DEFAULT uuid_generate_v4() PRIMARY KEY,
    created_at TIMESTAMPTZ DEFAULT NOW(),
    source TEXT NOT NULL,
    amount DECIMAL(10,2) NOT NULL,
    currency TEXT DEFAULT 'USD',
    description TEXT,
    metadata JSONB DEFAULT '{}'
  );

  -- ── self_improvements ────────────────────────────────
  CREATE TABLE IF NOT EXISTS self_improvements (
    id UUID DEFAULT uuid_generate_v4() PRIMARY KEY,
    created_at TIMESTAMPTZ DEFAULT NOW(),
    file_modified TEXT NOT NULL,
    description TEXT,
    diff_summary TEXT,
    applied BOOLEAN DEFAULT FALSE,
    approved_by TEXT
  );

  -- ── content_articles ─────────────────────────────────
  CREATE TABLE IF NOT EXISTS content_articles (
      id              UUID PRIMARY KEY DEFAULT gen_random_uuid(),
      title           TEXT NOT NULL,
      category        TEXT,
      language        VARCHAR(5) DEFAULT 'es',
      body            TEXT,
      meta_description TEXT,
      tags            TEXT[],
      platforms       TEXT[],
      published_urls  JSONB DEFAULT '[]',
      affiliate_links_count INTEGER DEFAULT 0,
      amazon_tag      TEXT,
      word_count      INTEGER,
      source_topic    TEXT,
      status          TEXT DEFAULT 'published',
      views_total     INTEGER DEFAULT 0,
      clicks_total    INTEGER DEFAULT 0,
      revenue_usd     NUMERIC(10,2) DEFAULT 0,
      created_at      TIMESTAMPTZ DEFAULT now(),
      updated_at      TIMESTAMPTZ DEFAULT now()
  );

  -- ── digital_products ─────────────────────────────────
  CREATE TABLE IF NOT EXISTS digital_products (
      id              UUID PRIMARY KEY DEFAULT gen_random_uuid(),
      name            TEXT NOT NULL,
      description     TEXT,
      platform        TEXT NOT NULL,
      platform_id     TEXT,
      url             TEXT,
      price_usd       NUMERIC(10,2) DEFAULT 0,
      sales_count     INTEGER DEFAULT 0,
      revenue_usd     NUMERIC(10,2) DEFAULT 0,
      status          TEXT DEFAULT 'active',
      category        TEXT,
      metadata        JSONB DEFAULT '{}',
      created_at      TIMESTAMPTZ DEFAULT now()
  );

  -- ── affiliate_links ──────────────────────────────────
  CREATE TABLE IF NOT EXISTS affiliate_links (
      id              UUID PRIMARY KEY DEFAULT gen_random_uuid(),
      platform        TEXT NOT NULL,
      product_id      TEXT,
      product_title   TEXT,
      affiliate_url   TEXT NOT NULL,
      category        TEXT,
      clicks          INTEGER DEFAULT 0,
      conversions     INTEGER DEFAULT 0,
      revenue_usd     NUMERIC(10,2) DEFAULT 0,
      article_id      UUID REFERENCES content_articles(id),
      created_at      TIMESTAMPTZ DEFAULT now()
  );

  -- ── social_accounts ──────────────────────────────────
  CREATE TABLE IF NOT EXISTS social_accounts (
      id              UUID PRIMARY KEY DEFAULT gen_random_uuid(),
      platform        TEXT NOT NULL,
      account_id      TEXT,
      username        TEXT,
      email           TEXT,
      access_token    TEXT NOT NULL,
      refresh_token   TEXT,
      expires_at      TIMESTAMPTZ,
      scopes          TEXT,
      is_active       BOOLEAN DEFAULT TRUE,
      created_at      TIMESTAMPTZ DEFAULT NOW(),
      updated_at      TIMESTAMPTZ DEFAULT NOW()
  );

  -- ── Índices ───────────────────────────────────────────
  CREATE INDEX IF NOT EXISTS idx_cycles_started ON autonomous_cycles(started_at DESC);
  CREATE INDEX IF NOT EXISTS idx_content_platform ON content_published(platform, created_at DESC);
  CREATE INDEX IF NOT EXISTS idx_revenue_source ON revenue_events(source, created_at DESC);
  CREATE INDEX IF NOT EXISTS idx_articles_status ON content_articles(status, created_at DESC);
  CREATE INDEX IF NOT EXISTS idx_affiliates_platform ON affiliate_links(platform, created_at DESC);
  CREATE UNIQUE INDEX IF NOT EXISTS social_accounts_platform_idx ON social_accounts(platform) WHERE is_active = TRUE;

  -- ── RLS ───────────────────────────────────────────────
  ALTER TABLE content_published ENABLE ROW LEVEL SECURITY;
  ALTER TABLE market_opportunities ENABLE ROW LEVEL SECURITY;
  ALTER TABLE revenue_events ENABLE ROW LEVEL SECURITY;
  ALTER TABLE self_improvements ENABLE ROW LEVEL SECURITY;
  ALTER TABLE content_articles ENABLE ROW LEVEL SECURITY;
  ALTER TABLE digital_products ENABLE ROW LEVEL SECURITY;
  ALTER TABLE affiliate_links ENABLE ROW LEVEL SECURITY;
  ALTER TABLE social_accounts ENABLE ROW LEVEL SECURITY;

  -- ── Trigger updated_at ───────────────────────────────
  CREATE OR REPLACE FUNCTION update_updated_at_column()
  RETURNS TRIGGER AS $$
  BEGIN NEW.updated_at = NOW(); RETURN NEW; END;
  $$ language 'plpgsql';

  CREATE OR REPLACE TRIGGER update_social_accounts_updated_at
      BEFORE UPDATE ON social_accounts
      FOR EACH ROW EXECUTE FUNCTION update_updated_at_column();
  