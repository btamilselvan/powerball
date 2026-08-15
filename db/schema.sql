-- Schema for powerball.auth (src/powerball/auth/db.py).
--
-- app_user is assumed to already exist (per the original request) — shown here commented out
-- for reference only, so this file documents the full picture in one place. If you haven't
-- created it yet, uncomment and run it too.
--
-- create table app_user (
--     user_id     uuid primary key default gen_random_uuid(),
--     email       text not null unique,
--     password    text not null,               -- bcrypt hash, never plaintext
--     created_on  timestamptz not null default now(),
--     deleted     boolean not null default false
-- );

create table refresh_tokens (
    token_id     uuid primary key default gen_random_uuid(),
    user_id      uuid not null references app_user(user_id),
    token_hash   text not null unique,           -- sha256 hex digest of the raw refresh token;
                                                  -- the raw token itself is never stored
    created_at   timestamptz not null default now(),
    expires_at   timestamptz not null,
    revoked_at   timestamptz,                    -- null = active; set on logout or rotation
    replaced_by  uuid references refresh_tokens(token_id)  -- rotation chain, nullable
);

-- Fast lookup of the (usually one) active token for a given hash.
create index refresh_tokens_active_hash_idx on refresh_tokens (token_hash) where revoked_at is null;

-- Fast "all of this user's tokens" lookups (e.g. a future "log out everywhere").
create index refresh_tokens_user_id_idx on refresh_tokens (user_id);

-- Note: if app_user.user_id is a serial/int primary key rather than uuid in your actual table,
-- change refresh_tokens.user_id's type to match (and drop the `uuid` default above) — no
-- application code changes are needed either way, psycopg adapts both automatically.
