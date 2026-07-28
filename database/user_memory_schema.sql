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
-- (apps/core/config.py: SUPABASE_KEY) by default, and Postgres/Supabase's
-- service role BYPASSES Row-Level Security by design — no RLS policy can
-- prevent it from reading/writing any row over that connection. The
-- load-bearing isolation guarantee, always in force regardless of RLS
-- configuration, is enforced in application code: every read/write in
-- apps/core/memory/user_facts.py requires an explicit, server-verified
-- user_id (the signed-in user's email — see apps/core/auth.py) and every
-- query — including the vector-similarity RPC below — has that user_id
-- baked into its WHERE clause, so it is structurally impossible for a
-- lookup to return another user's rows regardless of the query text.
--
-- The RLS policy below is a SECOND, independent, DB-enforced layer — real,
-- not merely cosmetic — when SUPABASE_ANON_KEY and SUPABASE_JWT_SECRET are
-- both configured (see apps/core/config.py). In that case,
-- apps/core/memory/rls_client.py signs a short-lived JWT for the caller's
-- user_id and presents it with the ANON key instead of the service-role
-- key; the policy below checks that JWT's claims, so Postgres itself will
-- refuse a query whose JWT email doesn't match the row's user_id, even if
-- application code somewhere had a bug. Without those two settings
-- configured, the app falls back to the service-role client and this
-- policy is defense-in-depth only (protects the table if it's ever queried
-- some other way, e.g. a future direct-from-browser client) — never a
-- regression, since the application-code guarantee above holds either way.

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

-- Real, DB-enforced isolation when the caller presents a JWT signed with
-- SUPABASE_JWT_SECRET (via the ANON key — see apps/core/memory/
-- rls_client.py); defense-in-depth only otherwise — see the isolation-model
-- comment above. `current_setting('request.jwt.claims', true)` is
-- PostgREST's per-request JWT claims, NOT a session variable — unlike
-- `SET LOCAL app.current_user_id` (which never worked here: PostgREST is
-- stateless per request with no session continuity), this is populated by
-- PostgREST itself from the Bearer token on every single request. A caller
-- with no valid JWT (e.g. the app's normal service-role connection, or the
-- anon key with no/expired token) sees `NULL` here and this policy denies
-- everything under it — fine, because service-role bypasses RLS entirely
-- anyway and the anon key alone (no JWT) shouldn't be able to read anything.
CREATE POLICY "user_isolation" ON aria_user_memories
  FOR ALL
  USING (
    user_id = COALESCE(current_setting('request.jwt.claims', true)::json ->> 'email', '')
  )
  WITH CHECK (
    user_id = COALESCE(current_setting('request.jwt.claims', true)::json ->> 'email', '')
  );

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
