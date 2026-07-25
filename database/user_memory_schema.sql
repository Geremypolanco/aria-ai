-- ARIA AI — Long-term per-user semantic memory (facts/preferences), pgvector-backed.
-- Paste in: Supabase Dashboard → SQL Editor → New query → Run
--
-- This is deliberately a SEPARATE table from aria_episodic_memory (raw
-- conversation snippets, Redis-primary, 180-day TTL) and from
-- apps/core/memory/semantic_memory.py's Fact model (ARIA's own global
-- operational knowledge, not user-scoped, in-process/Redis-primary — do not
-- confuse the two). This table is what "long-term, must-never-be-silently-
-- forgotten, per-user" memory actually needs: a durable store with no TTL
-- and no per-machine/in-process state, so it survives Fly.io's multi-machine
-- autoscaling and never expires on its own.
--
-- ISOLATION MODEL (read before changing anything here):
-- ARIA's application backend connects to Supabase with the SERVICE ROLE key
-- (apps/core/config.py: SUPABASE_KEY), and Postgres/Supabase's service role
-- BYPASSES Row-Level Security by design — no RLS policy can prevent it from
-- reading/writing any row. The RLS policy below is therefore DEFENSE IN
-- DEPTH ONLY (it protects this table if it's ever queried with a
-- non-service-role key — e.g. a future direct-from-browser Supabase client),
-- NOT the primary isolation guarantee. The actual, load-bearing isolation
-- guarantee is enforced in application code: every read/write in
-- apps/core/memory/user_facts.py requires an explicit, server-verified
-- user_id (the signed-in user's email — see apps/core/auth.py) and every
-- query — including the vector-similarity RPC below — has that user_id
-- baked into its WHERE clause, so it is structurally impossible for a
-- lookup to return another user's rows regardless of the query text.

CREATE EXTENSION IF NOT EXISTS "uuid-ossp";
CREATE EXTENSION IF NOT EXISTS vector;

-- sentence-transformers/all-MiniLM-L6-v2 (same model already used by
-- episodic_memory.py and semantic_memory.py) produces 384-dim embeddings.
CREATE TABLE IF NOT EXISTS aria_user_memories (
  id UUID DEFAULT uuid_generate_v4() PRIMARY KEY,
  created_at TIMESTAMPTZ DEFAULT NOW(),
  updated_at TIMESTAMPTZ DEFAULT NOW(),
  user_id TEXT NOT NULL,             -- the signed-in user's email, lowercased
  content TEXT NOT NULL,
  category TEXT NOT NULL DEFAULT 'fact',   -- 'fact' | 'preference' | 'constraint'
  importance REAL NOT NULL DEFAULT 0.5,
  embedding vector(384),             -- NULL when the embedding call failed; row is
                                      -- still kept and still reachable via keyword
                                      -- fallback search in application code.
  metadata JSONB DEFAULT '{}'
);

CREATE INDEX IF NOT EXISTS idx_user_memories_user ON aria_user_memories(user_id, created_at DESC);

-- ivfflat requires at least a few dozen rows to be useful; harmless (just
-- unused) below that. lists=100 is a reasonable default for a table this
-- size — revisit if the table grows past ~100k rows.
CREATE INDEX IF NOT EXISTS idx_user_memories_embedding
  ON aria_user_memories USING ivfflat (embedding vector_cosine_ops) WITH (lists = 100);

ALTER TABLE aria_user_memories ENABLE ROW LEVEL SECURITY;

-- Defense-in-depth only — see the isolation-model comment above. Scopes rows
-- to whatever the caller sets via `SET LOCAL app.current_user_id` for the
-- duration of a transaction; a caller that never sets it (e.g. the app's
-- normal service-role connection) sees nothing under this policy alone,
-- which is fine because service-role bypasses RLS entirely anyway.
CREATE POLICY "user_isolation" ON aria_user_memories
  FOR ALL
  USING (user_id = current_setting('app.current_user_id', true))
  WITH CHECK (user_id = current_setting('app.current_user_id', true));

CREATE POLICY "service_role_all" ON aria_user_memories FOR ALL USING (true);

-- The one and only vector-similarity entry point for this table. PostgREST
-- (what supabase-py's REST client talks to) can't express a `<->` ORDER BY
-- over the wire, so similarity search has to go through an RPC function —
-- which also means the user_id filter lives in SQL, not in
-- application-constructed query text, closing off any risk of a caller
-- forgetting to filter by user.
CREATE OR REPLACE FUNCTION match_user_memories(
  p_user_id TEXT,
  p_query_embedding vector(384),
  p_match_count INT DEFAULT 5,
  p_category TEXT DEFAULT NULL
)
RETURNS TABLE (
  id UUID,
  content TEXT,
  category TEXT,
  importance REAL,
  metadata JSONB,
  created_at TIMESTAMPTZ,
  similarity REAL
)
LANGUAGE sql STABLE
AS $$
  SELECT
    m.id,
    m.content,
    m.category,
    m.importance,
    m.metadata,
    m.created_at,
    1 - (m.embedding <=> p_query_embedding) AS similarity
  FROM aria_user_memories m
  WHERE m.user_id = p_user_id
    AND m.embedding IS NOT NULL
    AND (p_category IS NULL OR m.category = p_category)
  ORDER BY m.embedding <=> p_query_embedding
  LIMIT p_match_count;
$$;

SELECT 'aria_user_memories schema created successfully' AS result;
