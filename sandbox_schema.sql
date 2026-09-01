-- Sandbox schema for Fish APP — generated 2026-08-30.
--
-- Mirrors the PRODUCTION Supabase schema exactly as read from
-- information_schema on 2026-08-30. Run this ONCE against the
-- fishing-log-sandbox project only. Never against production.
--
-- Deliberately matches production's CURRENT state, which means
-- sessions.trip_uuid is absent: migrations/003_trip_uuid.sql has not been
-- applied to production. That is the point — apply 003 here first and see
-- what happens before it ever runs against real trips.
--
-- Known difference from production: no row-level security and no
-- fishing_app / fishing_deploy roles (migrations/001_rls_least_privilege.sql).
-- The sandbox connects as the owner role, so RLS behaviour is NOT covered
-- here. Application-level user scoping (WHERE user_email = :email) works the
-- same either way.

create table if not exists sessions (
    id            bigserial primary key,
    user_email    text    not null,
    date          text    not null,
    start_time    text,
    end_time      text,
    hours_fished  real,
    location_name text    not null,
    latitude      real,
    longitude     real,
    weather       text,
    air_temp      real,
    water_temp    real,
    bait_lure     text,
    fishing_style text,
    num_anglers   integer not null default 1,
    dwr_filed     integer not null default 0,
    notes         text,
    moon_phase    text,
    dwr_filed_at  text
);

create table if not exists fish (
    id         bigserial primary key,
    session_id bigint  not null references sessions(id) on delete cascade,
    species    text    not null,
    length     real    not null default 0,
    weight     real    not null default 0,
    kept       integer not null default 0,
    depth      real
);

create table if not exists spots (
    id         bigserial primary key,
    session_id bigint  not null references sessions(id) on delete cascade,
    latitude   real    not null,
    longitude  real    not null,
    label      text,
    caught     integer not null default 0,
    fish_count integer
);

-- Every read is scoped by user_email, and both children are always looked up
-- by session_id, so these three carry essentially all query traffic.
create index if not exists idx_sessions_user_email on sessions (user_email);
create index if not exists idx_fish_session_id     on fish     (session_id);
create index if not exists idx_spots_session_id    on spots    (session_id);
