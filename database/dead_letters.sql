-- ARIA AI — persistent dead-letter sink (cuspide wave 3).
--
-- The LLM-contracts dead-letter queue (apps/core/llm/contracts/dead_letter.py)
-- used to live only in process memory: quarantined outputs were lost across
-- worker restarts and invisible to sibling workers. This table is the
-- durable sink; the in-memory queue stays as the L1 fast path.
--
-- Apply manually in the Supabase SQL editor (repo convention: database/*.sql
-- are applied by hand, never by the app).
--
-- Required env vars (blocked for local dev until Geremy provides them):
--   SUPABASE_URL   e.g. https://xyzcompany.supabase.co
--   SUPABASE_KEY   service_role key (server-side only, never the anon key
--                  in a client, never committed)

create table if not exists dead_letters (
    id          text primary key,
    at          timestamptz not null default now(),
    schema      text not null default 'unknown',
    errors      jsonb not null default '[]'::jsonb,
    attempts    integer not null default 0,
    agent       text not null default '',
    created_at  timestamptz not null default now()
);

create index if not exists dead_letters_at_idx on dead_letters (at desc);
create index if not exists dead_letters_schema_idx on dead_letters (schema);

-- Retention: keep 90 days of dead letters; operators triage from the health
-- summary and the table, not from infinite history.
-- (Run as a scheduled pg_cron job or manually.)
-- delete from dead_letters where at < now() - interval '90 days';
