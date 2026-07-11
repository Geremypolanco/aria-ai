-- voice_identity — cloned voice + brand style profile, coupled to a user.
-- Mirrors apps/core/services/identity_profile_service.py :: VoiceIdentity.
-- Apply in Supabase/Postgres. The service also caches this in Redis, so the
-- table is the durable source of truth when Supabase is configured.

create table if not exists voice_identity (
    id                bigint generated always as identity primary key,
    user_email        text        not null unique,
    voice_id          text        not null default '',
    provider          text        not null default 'elevenlabs',
    sample_filename   text        not null default '',
    style_guidelines  text        not null default '',   -- long-form brand voice rules / idioms
    created_at        timestamptz not null default now(),
    updated_at        timestamptz not null default now()
    -- If a `users` table exists, couple explicitly:
    -- , constraint fk_voice_user foreign key (user_email) references users(email) on delete cascade
);

create index if not exists idx_voice_identity_email on voice_identity (user_email);
