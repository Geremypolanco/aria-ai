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