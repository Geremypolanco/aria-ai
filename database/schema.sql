-- ARIA AI — Schema completo v2: Gobernador Económico Multi-Sectorial
  -- Ejecutar en el SQL Editor de Supabase

  -- ── EXTENSIONES ───────────────────────────────────────────
  CREATE EXTENSION IF NOT EXISTS "uuid-ossp";
  CREATE EXTENSION IF NOT EXISTS "pg_trgm";  -- búsqueda de texto eficiente

  -- ══════════════════════════════════════════════════════════
  -- NÚCLEO EXISTENTE (preservado)
  -- ══════════════════════════════════════════════════════════

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
      agent_id     UUID REFERENCES agents(id) ON DELETE SET NULL,
      source       TEXT NOT NULL,
      amount_usd   NUMERIC(12,4) NOT NULL,
      currency     TEXT DEFAULT 'USD',
      description  TEXT DEFAULT '',
      metadata     JSONB DEFAULT '{}',
      created_at   TIMESTAMPTZ DEFAULT NOW()
  );

  -- ── LOGS DEL SISTEMA ──────────────────────────────────────
  CREATE TABLE IF NOT EXISTS system_logs (
      id         UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
      level      TEXT NOT NULL,
      agent      TEXT NOT NULL DEFAULT 'system',
      message    TEXT NOT NULL,
      metadata   JSONB DEFAULT '{}',
      created_at TIMESTAMPTZ DEFAULT NOW()
  );

  -- ── CICLOS ────────────────────────────────────────────────
  CREATE TABLE IF NOT EXISTS cycles (
      id           UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
      cycle_number INTEGER NOT NULL,
      status       TEXT DEFAULT 'running',
      missions     JSONB DEFAULT '[]',
      results      JSONB DEFAULT '{}',
      revenue_usd  NUMERIC(12,4) DEFAULT 0,
      duration_ms  INTEGER,
      started_at   TIMESTAMPTZ DEFAULT NOW(),
      completed_at TIMESTAMPTZ
  );

  -- ── PRODUCTOS ─────────────────────────────────────────────
  CREATE TABLE IF NOT EXISTS products (
      id          UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
      name        TEXT NOT NULL,
      type        TEXT NOT NULL,
      platform    TEXT,
      price_usd   NUMERIC(10,2) DEFAULT 0,
      url         TEXT,
      description TEXT DEFAULT '',
      metadata    JSONB DEFAULT '{}',
      created_at  TIMESTAMPTZ DEFAULT NOW()
  );

  -- ── MÉTRICAS DE AGENTES ───────────────────────────────────
  CREATE TABLE IF NOT EXISTS agent_metrics (
      id                 UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
      agent_name         TEXT NOT NULL,
      tasks_attempted    INTEGER DEFAULT 0,
      tasks_succeeded    INTEGER DEFAULT 0,
      tasks_failed       INTEGER DEFAULT 0,
      revenue_generated  NUMERIC(12,4) DEFAULT 0,
      avg_latency_ms     INTEGER DEFAULT 0,
      recorded_at        TIMESTAMPTZ DEFAULT NOW()
  );

  -- ── INVENTARIO DE APIS ────────────────────────────────────
  CREATE TABLE IF NOT EXISTS api_inventory (
      id           UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
      name         TEXT NOT NULL,
      category     TEXT NOT NULL,
      url          TEXT NOT NULL,
      free_tier    BOOLEAN DEFAULT TRUE,
      requires_key BOOLEAN DEFAULT FALSE,
      integrated   BOOLEAN DEFAULT FALSE,
      roi_score    NUMERIC(5,2) DEFAULT 0,
      benefit      TEXT DEFAULT '',
      metadata     JSONB DEFAULT '{}',
      added_at     TIMESTAMPTZ DEFAULT NOW()
  );

  -- ══════════════════════════════════════════════════════════
  -- NUEVO: ARQUITECTURA MULTI-SECTORIAL (Fase 1)
  -- ══════════════════════════════════════════════════════════

  -- ── REGISTRY DE AGENTES (registro dinámico) ───────────────
  CREATE TABLE IF NOT EXISTS agent_registry (
      id             UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
      agent_id       TEXT NOT NULL UNIQUE,
      name           TEXT NOT NULL,
      description    TEXT DEFAULT '',
      capabilities   JSONB DEFAULT '[]',
      sector_id      TEXT NOT NULL DEFAULT 'digital',
      domain_context JSONB DEFAULT '{}',
      status         TEXT DEFAULT 'active',
      last_heartbeat TIMESTAMPTZ DEFAULT NOW(),
      metrics        JSONB DEFAULT '{}',
      created_at     TIMESTAMPTZ DEFAULT NOW(),
      updated_at     TIMESTAMPTZ DEFAULT NOW()
  );

  CREATE INDEX IF NOT EXISTS idx_agent_registry_sector ON agent_registry(sector_id);
  CREATE INDEX IF NOT EXISTS idx_agent_registry_status ON agent_registry(status);

  -- ── SECTORES ECONÓMICOS ───────────────────────────────────
  CREATE TABLE IF NOT EXISTS sectors (
      id               UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
      sector_id        TEXT NOT NULL UNIQUE,
      name             TEXT NOT NULL,
      description      TEXT DEFAULT '',
      enabled          BOOLEAN DEFAULT FALSE,
      config           JSONB DEFAULT '{}',     -- parámetros operativos del sector
      legal_frameworks JSONB DEFAULT '[]',     -- normativas aplicables
      kpis             JSONB DEFAULT '{}',     -- indicadores clave por sector
      gdp_contribution NUMERIC(12,4),          -- contribución estimada al PIB circular
      created_at       TIMESTAMPTZ DEFAULT NOW(),
      updated_at       TIMESTAMPTZ DEFAULT NOW()
  );

  INSERT INTO sectors (sector_id, name, description, enabled) VALUES
    ('digital',       'Economía Digital',       'Productos y servicios digitales — sector origen de ARIA', TRUE),
    ('banking',       'Banca y Finanzas',       'Banca, microcréditos, inversiones, pagos', FALSE),
    ('legal',         'Marco Legal',            'Bufetes, contratos, asesoría, cumplimiento normativo', FALSE),
    ('logistics',     'Logística',              'Cadena de suministro, transporte, distribución', FALSE),
    ('manufacturing', 'Manufactura',            'Producción industrial, fábricas, procesos', FALSE),
    ('distribution',  'Distribución',           'Mayoristas, canales de distribución', FALSE),
    ('agriculture',   'Agricultura',            'Alimentos, cultivos, cadena agroalimentaria', FALSE),
    ('engineering',   'Ingeniería',             'Civil, industrial, infraestructura', FALSE),
    ('biochemistry',  'Bioquímica / Farmacia',  'Farmacéutica, biotecnología, salud', FALSE),
    ('education',     'Educación',              'Capacitación, e-learning, capital humano', FALSE),
    ('healthcare',    'Salud',                  'Telemedicina, hospitales, bienestar', FALSE),
    ('energy',        'Energía',                'Energías renovables, eficiencia energética', FALSE),
    ('real_estate',   'Bienes Raíces',          'Propiedades, alquiler, construcción', FALSE),
    ('retail',        'Comercio Minorista',     'Tiendas, e-commerce, consumidores', FALSE)
  ON CONFLICT (sector_id) DO NOTHING;

  -- ── RECURSOS (físicos y digitales) ───────────────────────
  CREATE TABLE IF NOT EXISTS resources (
      id            UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
      sector_id     TEXT NOT NULL REFERENCES sectors(sector_id) ON DELETE CASCADE,
      name          TEXT NOT NULL,
      resource_type TEXT NOT NULL,  -- 'physical', 'digital', 'financial', 'human', 'energy'
      quantity      NUMERIC(18,4) DEFAULT 0,
      unit          TEXT DEFAULT 'unit',
      unit_cost     NUMERIC(12,4) DEFAULT 0,
      currency      TEXT DEFAULT 'USD',
      location      TEXT,
      metadata      JSONB DEFAULT '{}',
      created_at    TIMESTAMPTZ DEFAULT NOW(),
      updated_at    TIMESTAMPTZ DEFAULT NOW()
  );

  CREATE INDEX IF NOT EXISTS idx_resources_sector ON resources(sector_id);
  CREATE INDEX IF NOT EXISTS idx_resources_type ON resources(resource_type);

  -- ── CADENAS DE SUMINISTRO ─────────────────────────────────
  CREATE TABLE IF NOT EXISTS supply_chains (
      id              UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
      name            TEXT NOT NULL,
      source_sector   TEXT REFERENCES sectors(sector_id),
      target_sector   TEXT REFERENCES sectors(sector_id),
      resource_ids    JSONB DEFAULT '[]',       -- recursos involucrados
      flow_type       TEXT DEFAULT 'goods',     -- 'goods', 'services', 'data', 'capital'
      volume_per_day  NUMERIC(18,4) DEFAULT 0,
      cost_per_unit   NUMERIC(12,4) DEFAULT 0,
      efficiency_pct  NUMERIC(5,2) DEFAULT 100, -- eficiencia actual (%)
      optimization    JSONB DEFAULT '{}',       -- sugerencias del ProcessOptimizationAgent
      status          TEXT DEFAULT 'active',
      created_at      TIMESTAMPTZ DEFAULT NOW(),
      updated_at      TIMESTAMPTZ DEFAULT NOW()
  );

  CREATE INDEX IF NOT EXISTS idx_supply_chain_source ON supply_chains(source_sector);
  CREATE INDEX IF NOT EXISTS idx_supply_chain_target ON supply_chains(target_sector);

  -- ── MARCOS LEGALES ────────────────────────────────────────
  CREATE TABLE IF NOT EXISTS legal_frameworks (
      id              UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
      sector_id       TEXT REFERENCES sectors(sector_id) ON DELETE CASCADE,
      jurisdiction    TEXT NOT NULL,            -- 'US', 'EU', 'LATAM', 'global'
      framework_name  TEXT NOT NULL,            -- 'GDPR', 'SOX', 'MiFID II', etc.
      description     TEXT DEFAULT '',
      compliance_req  JSONB DEFAULT '[]',       -- lista de requisitos
      documents       JSONB DEFAULT '[]',       -- contratos, términos generados
      risk_level      TEXT DEFAULT 'low',       -- 'low', 'medium', 'high', 'critical'
      last_reviewed   TIMESTAMPTZ,
      next_review     TIMESTAMPTZ,
      created_at      TIMESTAMPTZ DEFAULT NOW(),
      updated_at      TIMESTAMPTZ DEFAULT NOW()
  );

  CREATE INDEX IF NOT EXISTS idx_legal_frameworks_sector ON legal_frameworks(sector_id);
  CREATE INDEX IF NOT EXISTS idx_legal_frameworks_jurisdiction ON legal_frameworks(jurisdiction);

  -- ── RECURSOS HUMANOS ──────────────────────────────────────
  CREATE TABLE IF NOT EXISTS human_resources (
      id              UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
      sector_id       TEXT REFERENCES sectors(sector_id) ON DELETE SET NULL,
      employee_ref    TEXT,                     -- ID externo en sistema RRHH
      name            TEXT NOT NULL,
      role            TEXT NOT NULL,
      department      TEXT,
      skills          JSONB DEFAULT '[]',
      performance     JSONB DEFAULT '{}',       -- métricas de rendimiento
      salary_usd      NUMERIC(12,2),
      status          TEXT DEFAULT 'active',    -- 'active', 'training', 'inactive'
      assigned_tasks  JSONB DEFAULT '[]',
      training_plan   JSONB DEFAULT '{}',
      metadata        JSONB DEFAULT '{}',
      hired_at        TIMESTAMPTZ DEFAULT NOW(),
      updated_at      TIMESTAMPTZ DEFAULT NOW()
  );

  CREATE INDEX IF NOT EXISTS idx_hr_sector ON human_resources(sector_id);
  CREATE INDEX IF NOT EXISTS idx_hr_status ON human_resources(status);

  -- ── PROCESOS OPERATIVOS ───────────────────────────────────
  CREATE TABLE IF NOT EXISTS processes (
      id                UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
      sector_id         TEXT REFERENCES sectors(sector_id) ON DELETE CASCADE,
      name              TEXT NOT NULL,
      description       TEXT DEFAULT '',
      process_type      TEXT DEFAULT 'operational',  -- 'operational', 'financial', 'legal', 'hr'
      steps             JSONB DEFAULT '[]',           -- pasos del proceso
      kpis              JSONB DEFAULT '{}',           -- indicadores de éxito
      current_efficiency NUMERIC(5,2) DEFAULT 100,   -- eficiencia actual (%)
      target_efficiency  NUMERIC(5,2) DEFAULT 100,
      automation_level   NUMERIC(5,2) DEFAULT 0,     -- % automatizado por ARIA
      optimization_log   JSONB DEFAULT '[]',          -- historial de mejoras
      status            TEXT DEFAULT 'active',
      created_at        TIMESTAMPTZ DEFAULT NOW(),
      updated_at        TIMESTAMPTZ DEFAULT NOW()
  );

  CREATE INDEX IF NOT EXISTS idx_processes_sector ON processes(sector_id);
  CREATE INDEX IF NOT EXISTS idx_processes_type ON processes(process_type);

  -- ── GOBERNANZA ECONÓMICA ──────────────────────────────────
  CREATE TABLE IF NOT EXISTS economic_policies (
      id              UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
      policy_type     TEXT NOT NULL,            -- 'pricing', 'allocation', 'subsidy', 'reinvestment'
      sector_id       TEXT REFERENCES sectors(sector_id),
      name            TEXT NOT NULL,
      description     TEXT DEFAULT '',
      parameters      JSONB DEFAULT '{}',       -- parámetros de la política
      target_kpis     JSONB DEFAULT '{}',
      status          TEXT DEFAULT 'active',
      proposed_by     TEXT DEFAULT 'economic_governor',
      approved_by     TEXT,
      effective_from  TIMESTAMPTZ DEFAULT NOW(),
      effective_until TIMESTAMPTZ,
      impact_report   JSONB DEFAULT '{}',
      created_at      TIMESTAMPTZ DEFAULT NOW()
  );

  -- ── AUDITORÍA Y TRANSPARENCIA ─────────────────────────────
  CREATE TABLE IF NOT EXISTS audit_trail (
      id            UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
      agent_name    TEXT NOT NULL,
      sector_id     TEXT DEFAULT 'digital',
      action_type   TEXT NOT NULL,
      action_detail JSONB NOT NULL,
      rationale     TEXT DEFAULT '',           -- por qué ARIA tomó esta decisión
      impact        JSONB DEFAULT '{}',        -- impacto estimado/real
      reversible    BOOLEAN DEFAULT TRUE,
      reversed_at   TIMESTAMPTZ,
      created_at    TIMESTAMPTZ DEFAULT NOW()
  );

  CREATE INDEX IF NOT EXISTS idx_audit_agent ON audit_trail(agent_name);
  CREATE INDEX IF NOT EXISTS idx_audit_sector ON audit_trail(sector_id);
  CREATE INDEX IF NOT EXISTS idx_audit_action ON audit_trail(action_type);
  CREATE INDEX IF NOT EXISTS idx_audit_created ON audit_trail(created_at DESC);

  -- ── CAPITAL Y DISTRIBUCIÓN ────────────────────────────────
  CREATE TABLE IF NOT EXISTS capital_allocation (
      id              UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
      period_start    TIMESTAMPTZ NOT NULL,
      period_end      TIMESTAMPTZ NOT NULL,
      total_revenue   NUMERIC(14,4) DEFAULT 0,
      reinvested      NUMERIC(14,4) DEFAULT 0,
      reserved        NUMERIC(14,4) DEFAULT 0,
      community_fund  NUMERIC(14,4) DEFAULT 0,
      sector_breakdown JSONB DEFAULT '{}',    -- desglose por sector
      policy_id       UUID REFERENCES economic_policies(id),
      notes           TEXT DEFAULT '',
      created_at      TIMESTAMPTZ DEFAULT NOW()
  );

  -- ── ROW LEVEL SECURITY (básico) ───────────────────────────
  ALTER TABLE audit_trail ENABLE ROW LEVEL SECURITY;
  ALTER TABLE economic_policies ENABLE ROW LEVEL SECURITY;
  ALTER TABLE capital_allocation ENABLE ROW LEVEL SECURITY;

  -- Políticas: solo service_role puede escribir, lectura pública de auditoría
  CREATE POLICY IF NOT EXISTS "audit_read_all" ON audit_trail FOR SELECT USING (true);
  CREATE POLICY IF NOT EXISTS "economic_read_all" ON economic_policies FOR SELECT USING (true);
  CREATE POLICY IF NOT EXISTS "capital_read_all" ON capital_allocation FOR SELECT USING (true);

  -- ── FUNCIÓN: updated_at automático ────────────────────────
  CREATE OR REPLACE FUNCTION update_updated_at()
  RETURNS TRIGGER AS $$
  BEGIN
      NEW.updated_at = NOW();
      RETURN NEW;
  END;
  $$ LANGUAGE plpgsql;

  CREATE OR REPLACE TRIGGER trg_agent_registry_updated
      BEFORE UPDATE ON agent_registry
      FOR EACH ROW EXECUTE FUNCTION update_updated_at();

  CREATE OR REPLACE TRIGGER trg_sectors_updated
      BEFORE UPDATE ON sectors
      FOR EACH ROW EXECUTE FUNCTION update_updated_at();

  CREATE OR REPLACE TRIGGER trg_supply_chains_updated
      BEFORE UPDATE ON supply_chains
      FOR EACH ROW EXECUTE FUNCTION update_updated_at();
  