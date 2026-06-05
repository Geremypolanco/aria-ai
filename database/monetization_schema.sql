-- =====================================================
  -- ARIA AI — Schema de tablas para monetización
  -- Ejecutar en Supabase SQL Editor
  -- =====================================================

  -- ── ARTÍCULOS PUBLICADOS ─────────────────────────────
  CREATE TABLE IF NOT EXISTS content_articles (
      id              UUID PRIMARY KEY DEFAULT gen_random_uuid(),
      title           TEXT NOT NULL,
      category        TEXT,
      language        VARCHAR(5) DEFAULT 'es',
      body            TEXT,
      meta_description TEXT,
      tags            TEXT[],
      platforms       TEXT[],          -- ['medium', 'devto', 'hashnode']
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

  -- ── PRODUCTOS DIGITALES ──────────────────────────────
  CREATE TABLE IF NOT EXISTS digital_products (
      id              UUID PRIMARY KEY DEFAULT gen_random_uuid(),
      name            TEXT NOT NULL,
      description     TEXT,
      platform        TEXT NOT NULL,   -- 'gumroad', 'lemonsqueezy', 'stripe'
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

  -- ── LINKS DE AFILIADO ────────────────────────────────
  CREATE TABLE IF NOT EXISTS affiliate_links (
      id              UUID PRIMARY KEY DEFAULT gen_random_uuid(),
      platform        TEXT NOT NULL,   -- 'amazon', 'clickbank', 'hotmart', 'gumroad'
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

  -- ── SUSCRIPTORES EMAIL ───────────────────────────────
  CREATE TABLE IF NOT EXISTS email_subscribers (
      id              UUID PRIMARY KEY DEFAULT gen_random_uuid(),
      email           TEXT UNIQUE NOT NULL,
      name            TEXT,
      source          TEXT,            -- 'newsletter', 'landing', 'blog'
      tags            TEXT[],
      provider        TEXT,            -- 'mailchimp', 'convertkit', 'resend'
      status          TEXT DEFAULT 'active',
      created_at      TIMESTAMPTZ DEFAULT now()
  );

  -- ── RENDIMIENTO DE CONTENIDO ─────────────────────────
  CREATE TABLE IF NOT EXISTS content_performance (
      id              UUID PRIMARY KEY DEFAULT gen_random_uuid(),
      article_id      UUID REFERENCES content_articles(id),
      platform        TEXT,
      date            DATE DEFAULT CURRENT_DATE,
      views           INTEGER DEFAULT 0,
      clicks          INTEGER DEFAULT 0,
      shares          INTEGER DEFAULT 0,
      revenue_usd     NUMERIC(10,2) DEFAULT 0,
      recorded_at     TIMESTAMPTZ DEFAULT now()
  );

  -- ── ÍNDICES ──────────────────────────────────────────
  CREATE INDEX IF NOT EXISTS idx_content_articles_category ON content_articles(category);
  CREATE INDEX IF NOT EXISTS idx_content_articles_created ON content_articles(created_at DESC);
  CREATE INDEX IF NOT EXISTS idx_digital_products_platform ON digital_products(platform);
  CREATE INDEX IF NOT EXISTS idx_affiliate_links_platform ON affiliate_links(platform);

  -- ── VISTA: INGRESOS TOTALES ──────────────────────────
  CREATE OR REPLACE VIEW aria_revenue_summary AS
  SELECT
      'content_articles' AS source,
      COUNT(*) AS count,
      SUM(revenue_usd) AS total_revenue_usd
  FROM content_articles
  UNION ALL
  SELECT
      'digital_products',
      COUNT(*),
      SUM(revenue_usd)
  FROM digital_products
  UNION ALL
  SELECT
      'affiliate_links',
      COUNT(*),
      SUM(revenue_usd)
  FROM affiliate_links;

  -- ── RLS: Solo el servidor puede leer/escribir ────────
  ALTER TABLE content_articles    ENABLE ROW LEVEL SECURITY;
  ALTER TABLE digital_products    ENABLE ROW LEVEL SECURITY;
  ALTER TABLE affiliate_links     ENABLE ROW LEVEL SECURITY;
  ALTER TABLE email_subscribers   ENABLE ROW LEVEL SECURITY;
  ALTER TABLE content_performance ENABLE ROW LEVEL SECURITY;
  