-- ============================================================
-- ARIA Agent System — Esquema de Base de Datos
-- PostgreSQL 16
-- ============================================================

-- ── Extensiones ──────────────────────────────────────────
CREATE EXTENSION IF NOT EXISTS "pgcrypto";      -- gen_random_uuid()
CREATE EXTENSION IF NOT EXISTS "btree_gist";     -- Exclusion constraints

-- ── Tipos Enumerados ─────────────────────────────────────
DO $$ BEGIN
    CREATE TYPE task_status AS ENUM (
        'pending',
        'planning',
        'running',
        'completed',
        'failed',
        'needs_review',
        'cancelled'
    );
EXCEPTION
    WHEN duplicate_object THEN null;
END $$;

DO $$ BEGIN
    CREATE TYPE agent_type AS ENUM (
        'planner',
        'execution',
        'verification',
        'orchestrator'
    );
EXCEPTION
    WHEN duplicate_object THEN null;
END $$;

DO $$ BEGIN
    CREATE TYPE log_level AS ENUM (
        'debug',
        'info',
        'warning',
        'error',
        'critical'
    );
EXCEPTION
    WHEN duplicate_object THEN null;
END $$;

-- ============================================================
-- TABLAS
-- ============================================================

-- ── Tareas ────────────────────────────────────────────────
CREATE TABLE IF NOT EXISTS tasks (
    id              UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    status          task_status NOT NULL DEFAULT 'pending',
    task_type       TEXT NOT NULL,
    title           TEXT NOT NULL DEFAULT '',
    input           JSONB NOT NULL DEFAULT '{}',
    plan            JSONB,                          -- Generado por PlannerAgent
    result          JSONB,                          -- Output final
    error_message   TEXT,
    priority        INT NOT NULL DEFAULT 5,          -- 1 (más alta) a 10 (más baja)
    max_retries     INT NOT NULL DEFAULT 3,
    retry_count     INT NOT NULL DEFAULT 0,
    created_by      TEXT,                            -- user_id, api_key o "system"
    assigned_agent  agent_type,
    session_id      TEXT,                            -- Para agrupar tareas relacionadas
    created_at      TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    started_at      TIMESTAMPTZ,
    completed_at    TIMESTAMPTZ,
    deadline        TIMESTAMPTZ,                     -- Opcional: tiempo límite

    CONSTRAINT chk_timestamps CHECK (
        completed_at IS NULL OR started_at IS NULL OR completed_at >= started_at
    ),
    CONSTRAINT chk_retries CHECK (retry_count <= max_retries)
);

CREATE INDEX idx_tasks_status ON tasks(status);
CREATE INDEX idx_tasks_created_at ON tasks(created_at DESC);
CREATE INDEX idx_tasks_session ON tasks(session_id);
CREATE INDEX idx_tasks_created_by ON tasks(created_by);

-- ── Logs de Auditoría por Paso ──────────────────────────
CREATE TABLE IF NOT EXISTS task_logs (
    id              UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    task_id         UUID NOT NULL REFERENCES tasks(id) ON DELETE CASCADE,
    agent_type      agent_type NOT NULL,
    step            INT NOT NULL DEFAULT 0,
    action          TEXT NOT NULL,
    input           JSONB,
    output          JSONB,
    status          TEXT NOT NULL DEFAULT 'success',
    duration_ms     INT,
    level           log_level NOT NULL DEFAULT 'info',
    message         TEXT,
    security_metadata JSONB,     -- {vault_token_id, user, ip, session_id}
    created_at      TIMESTAMPTZ NOT NULL DEFAULT NOW(),

    CONSTRAINT chk_step CHECK (step >= 0)
);

CREATE INDEX idx_task_logs_task ON task_logs(task_id);
CREATE INDEX idx_task_logs_created ON task_logs(created_at DESC);
CREATE INDEX idx_task_logs_agent ON task_logs(agent_type);

-- ── Memoria de Agentes ──────────────────────────────────
CREATE TABLE IF NOT EXISTS agent_memory (
    id              UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    agent_type      agent_type NOT NULL,
    memory_key      TEXT NOT NULL,
    memory_value    JSONB NOT NULL,
    ttl_seconds     INT,                              -- TTL en segundos, NULL = permanente
    tags            TEXT[] DEFAULT '{}',                -- Para búsqueda por categoría
    created_at      TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    expires_at      TIMESTAMPTZ,                       -- Calculado: created_at + ttl_seconds

    CONSTRAINT uq_agent_memory UNIQUE (agent_type, memory_key),
    CONSTRAINT chk_expiry CHECK (
        (ttl_seconds IS NULL AND expires_at IS NULL) OR
        (ttl_seconds IS NOT NULL AND expires_at IS NOT NULL)
    )
);

CREATE INDEX idx_memory_agent ON agent_memory(agent_type);
CREATE INDEX idx_memory_expires ON agent_memory(expires_at) WHERE expires_at IS NOT NULL;
CREATE INDEX idx_memory_tags ON agent_memory USING GIN(tags);

-- ── Auditoría de Secrets ────────────────────────────────
CREATE TABLE IF NOT EXISTS secrets_audit (
    id              UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    action          TEXT NOT NULL,                     -- get | set | list | delete
    secret_path     TEXT NOT NULL,
    accessed_by     TEXT NOT NULL,
    task_id         UUID REFERENCES tasks(id),
    success         BOOLEAN NOT NULL,
    client_ip       INET,
    user_agent      TEXT,
    vault_token_accessor TEXT,                         -- Accessor del token Vault usado
    response_time_ms INT,
    created_at      TIMESTAMPTZ NOT NULL DEFAULT NOW(),

    CONSTRAINT chk_action CHECK (action IN ('get', 'set', 'list', 'delete'))
);

CREATE INDEX idx_secrets_audit_path ON secrets_audit(secret_path);
CREATE INDEX idx_secrets_audit_time ON secrets_audit(created_at DESC);
CREATE INDEX idx_secrets_audit_task ON secrets_audit(task_id);

-- ── Sesiones de Usuario ─────────────────────────────────
CREATE TABLE IF NOT EXISTS sessions (
    id              UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    user_id         TEXT NOT NULL,
    browser_profile TEXT,                              -- Perfil de navegador persistente
    metadata        JSONB DEFAULT '{}',
    is_active       BOOLEAN NOT NULL DEFAULT true,
    created_at      TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    last_active_at  TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    expires_at      TIMESTAMPTZ NOT NULL DEFAULT (NOW() + INTERVAL '24 hours')
);

CREATE INDEX idx_sessions_user ON sessions(user_id);
CREATE INDEX idx_sessions_active ON sessions(is_active) WHERE is_active = true;

-- ============================================================
-- VISTAS ÚTILES
-- ============================================================

-- Tareas activas con su último log
CREATE OR REPLACE VIEW v_tasks_active AS
SELECT
    t.id,
    t.status,
    t.task_type,
    t.title,
    t.priority,
    t.created_at,
    t.started_at,
    tl.action AS last_action,
    tl.agent_type AS last_agent,
    tl.created_at AS last_action_at
FROM tasks t
LEFT JOIN LATERAL (
    SELECT action, agent_type, created_at
    FROM task_logs
    WHERE task_id = t.id
    ORDER BY created_at DESC
    LIMIT 1
) tl ON true
WHERE t.status IN ('pending', 'planning', 'running')
ORDER BY t.priority ASC, t.created_at ASC;

-- Resumen de actividad por hora
CREATE OR REPLACE VIEW v_activity_summary AS
SELECT
    date_trunc('hour', created_at) AS hour,
    agent_type,
    status,
    COUNT(*) AS total,
    AVG(duration_ms)::INT AS avg_duration_ms
FROM task_logs
WHERE created_at >= NOW() - INTERVAL '24 hours'
GROUP BY 1, 2, 3
ORDER BY 1 DESC;

-- ============================================================
-- FUNCIONES
-- ============================================================

-- Actualizar estado de tarea con validación
CREATE OR REPLACE FUNCTION update_task_status(
    p_task_id UUID,
    p_new_status task_status,
    p_error_message TEXT DEFAULT NULL
) RETURNS BOOLEAN AS $$
DECLARE
    v_current_status task_status;
BEGIN
    SELECT status INTO v_current_status FROM tasks WHERE id = p_task_id;
    IF NOT FOUND THEN
        RAISE EXCEPTION 'Task not found: %', p_task_id;
    END IF;

    -- Validar transiciones permitidas
    IF NOT (
        (v_current_status = 'pending' AND p_new_status IN ('planning', 'cancelled')) OR
        (v_current_status = 'planning' AND p_new_status IN ('running', 'failed', 'cancelled')) OR
        (v_current_status = 'running' AND p_new_status IN ('completed', 'failed', 'needs_review', 'cancelled')) OR
        (v_current_status = 'needs_review' AND p_new_status IN ('running', 'completed', 'failed', 'cancelled'))
    ) THEN
        RAISE WARNING 'Invalid status transition: % → %', v_current_status, p_new_status;
        RETURN false;
    END IF;

    UPDATE tasks SET
        status = p_new_status,
        error_message = COALESCE(p_error_message, error_message),
        started_at = CASE WHEN p_new_status = 'running' AND started_at IS NULL THEN NOW() ELSE started_at END,
        completed_at = CASE WHEN p_new_status IN ('completed', 'failed', 'cancelled') THEN NOW() ELSE NULL END
    WHERE id = p_task_id;

    RETURN true;
END;
$$ LANGUAGE plpgsql;

-- Limpiar memoria expirada
CREATE OR REPLACE FUNCTION clean_expired_memory() RETURNS INT AS $$
DECLARE
    v_deleted INT;
BEGIN
    DELETE FROM agent_memory WHERE expires_at IS NOT NULL AND expires_at < NOW();
    GET DIAGNOSTICS v_deleted = ROW_COUNT;
    RETURN v_deleted;
END;
$$ LANGUAGE plpgsql;

-- ============================================================
-- ÍNDICES ADICIONALES (rendimiento)
-- ============================================================

-- Para búsqueda en JSONB de planes
CREATE INDEX IF NOT EXISTS idx_tasks_plan ON tasks USING GIN (plan jsonb_path_ops);
CREATE INDEX IF NOT EXISTS idx_tasks_input ON tasks USING GIN (input jsonb_path_ops);

-- Para limpieza programada
CREATE INDEX IF NOT EXISTS idx_tasks_old_completed ON tasks(completed_at) WHERE status IN ('completed', 'failed', 'cancelled');
CREATE INDEX IF NOT EXISTS idx_logs_old ON task_logs(created_at) WHERE created_at < NOW() - INTERVAL '90 days';


-- ============================================================
-- FASE 8: Resiliencia — Intervention Queue, Archive, Circuit Breakers
-- ============================================================

-- ── ARIA Agent System — Resilience Database Tables ─────
-- Tablas para circuit breakers, cola de intervención y archive

-- ── Cola de Intervención Humana ────────────────────────
CREATE TABLE IF NOT EXISTS intervention_queue (
    id              UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    task_id         TEXT NOT NULL,
    reason          TEXT NOT NULL,
    task_data       JSONB NOT NULL DEFAULT '{}',
    status          TEXT NOT NULL DEFAULT 'pending',
    session_id      TEXT,
    resolution_note TEXT,
    resolved_at     TIMESTAMPTZ,
    created_at      TIMESTAMPTZ NOT NULL DEFAULT NOW(),

    CONSTRAINT chk_status CHECK (status IN ('pending', 'retry', 'modify', 'cancel', 'approve'))
);

CREATE INDEX IF NOT EXISTS idx_intervention_pending ON intervention_queue(status) WHERE status = 'pending';
CREATE INDEX IF NOT EXISTS idx_intervention_task ON intervention_queue(task_id);
CREATE INDEX IF NOT EXISTS idx_intervention_created ON intervention_queue(created_at);

-- ── Archive de Logs (tarea programada) ─────────────────
CREATE TABLE IF NOT EXISTS task_logs_archive (
    LIKE task_logs INCLUDING ALL,
    archived_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS idx_logs_archive_created ON task_logs_archive(created_at);
CREATE INDEX IF NOT EXISTS idx_logs_archive_task ON task_logs_archive(task_id);

-- ── Archive de Tareas (tarea programada) ───────────────
CREATE TABLE IF NOT EXISTS tasks_archive (
    LIKE tasks INCLUDING ALL,
    archived_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS idx_tasks_archive_created ON tasks_archive(created_at);
CREATE INDEX IF NOT EXISTS idx_tasks_archive_status ON tasks_archive(status);

-- ── Historial de Circuit Breakers ──────────────────────
CREATE TABLE IF NOT EXISTS circuit_breaker_events (
    id              UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    breaker_name    TEXT NOT NULL,
    from_state      TEXT NOT NULL,
    to_state        TEXT NOT NULL,
    failure_count   INT NOT NULL DEFAULT 0,
    error_message   TEXT,
    created_at      TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS idx_cb_events_name ON circuit_breaker_events(breaker_name);
CREATE INDEX IF NOT EXISTS idx_cb_events_created ON circuit_breaker_events(created_at);

-- ── Función para limpiar contenedores huérfanos ───────
CREATE OR REPLACE FUNCTION janitor_report() RETURNS TABLE (
    action TEXT,
    count INT
) AS $$
BEGIN
    -- Esta función es llamada por el JanitorService
    -- Los conteos se registran vía aplicación
    RETURN QUERY
    SELECT 'containers_destroyed'::TEXT, 0::INT;
END;
$$ LANGUAGE plpgsql;