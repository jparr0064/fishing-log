-- CR-2 — Enforce user isolation in PostgreSQL
--
-- Run this in the Supabase SQL editor (Dashboard -> SQL Editor -> New query).
-- Safe to run while the app is live: the app keeps connecting as `postgres`,
-- which bypasses RLS, so behaviour does not change until you switch the
-- connection string in step 6 below. Re-running is safe (idempotent).
--
-- WHY THIS IS NEEDED
-- Today the runtime connects as `postgres`, which bypasses row-level security
-- two different ways: it has rolbypassrls = true, AND it owns the tables (an
-- owner bypasses RLS unless FORCE ROW LEVEL SECURITY is set). RLS is switched
-- on for sessions/fish/spots/photos, but there are ZERO policies. The net
-- effect is that user isolation depends entirely on every application query
-- remembering `WHERE user_email = ...`. One missed predicate leaks one club
-- member's trips — and their exact fishing coordinates — to another.
--
-- WHAT THIS DOES
--   * creates a least-privilege runtime role that cannot bypass RLS and cannot
--     run DDL
--   * creates a separate deployment role that CAN run DDL, for migrations
--   * writes policies keyed to a per-transaction setting, app.user_email
--   * forces RLS so even a table owner is subject to the policies
--
-- ORDER OF OPERATIONS — do not skip step 5.
--   1. Set a password below, run this whole script.
--   2. Deploy the application change that issues SET LOCAL app.user_email.
--   3. Verify on staging, or with a throwaway account.
--   4. Update database_url to the fishing_app role.
--   5. VERIFY the app still reads and writes. If it returns empty everywhere,
--      the GUC is not being set — revert database_url to postgres and fix the
--      app before trying again.
--   6. Only then consider revoking rolbypassrls elsewhere.

BEGIN;

-- ---------------------------------------------------------------------------
-- 1. Roles
-- ---------------------------------------------------------------------------

-- Runtime role. NOBYPASSRLS is the point of the exercise. No CREATEDB, no
-- CREATEROLE, no DDL — it can only read and write rows it is allowed to see.
--
-- REPLACE THE PASSWORD BELOW before running, and put the same value in the
-- database_url secret. Do not commit the real password to git.
DO $$
BEGIN
  IF NOT EXISTS (SELECT 1 FROM pg_roles WHERE rolname = 'fishing_app') THEN
    CREATE ROLE fishing_app LOGIN PASSWORD 'REPLACE_ME_RUNTIME_PASSWORD'
      NOBYPASSRLS NOCREATEDB NOCREATEROLE NOSUPERUSER NOINHERIT;
  ELSE
    -- Re-assert the security-relevant attributes in case they drifted.
    ALTER ROLE fishing_app NOBYPASSRLS NOCREATEDB NOCREATEROLE NOSUPERUSER;
  END IF;
END $$;

-- Deployment role for migrations only. Not used by the running app, so its
-- credential lives in your hands rather than in Streamlit secrets.
DO $$
BEGIN
  IF NOT EXISTS (SELECT 1 FROM pg_roles WHERE rolname = 'fishing_deploy') THEN
    CREATE ROLE fishing_deploy LOGIN PASSWORD 'REPLACE_ME_DEPLOY_PASSWORD'
      NOBYPASSRLS NOCREATEDB NOCREATEROLE NOSUPERUSER NOINHERIT;
  ELSE
    ALTER ROLE fishing_deploy NOBYPASSRLS NOCREATEDB NOCREATEROLE NOSUPERUSER;
  END IF;
END $$;

-- ---------------------------------------------------------------------------
-- 2. Privileges — runtime role gets DML only, never DDL
-- ---------------------------------------------------------------------------

GRANT USAGE ON SCHEMA public TO fishing_app, fishing_deploy;

-- Start from nothing so a re-run cannot silently widen access.
REVOKE ALL ON ALL TABLES IN SCHEMA public FROM fishing_app;

GRANT SELECT, INSERT, UPDATE, DELETE ON public.sessions TO fishing_app;
GRANT SELECT, INSERT, UPDATE, DELETE ON public.fish     TO fishing_app;
GRANT SELECT, INSERT, UPDATE, DELETE ON public.spots    TO fishing_app;

-- Needed for the id columns' underlying sequences on INSERT.
GRANT USAGE, SELECT ON ALL SEQUENCES IN SCHEMA public TO fishing_app;

-- `photos` is a leftover from the removed photo feature (database.insert_photo
-- raises NotImplementedError). Deliberately NOT granted — the runtime role
-- should have no access at all. Left in place rather than dropped, because
-- dropping a table is irreversible; confirm it is empty and drop it separately.

-- The deployment role owns schema change rights, and nothing else.
GRANT CREATE ON SCHEMA public TO fishing_deploy;
GRANT SELECT, INSERT, UPDATE, DELETE, REFERENCES, TRIGGER
  ON ALL TABLES IN SCHEMA public TO fishing_deploy;

-- Belt and braces on the Supabase auto-API roles. RLS with no policy already
-- denies them, but an accidental future policy written FOR ALL would not.
REVOKE ALL ON ALL TABLES IN SCHEMA public FROM anon, authenticated;

-- ---------------------------------------------------------------------------
-- 3. Policies
-- ---------------------------------------------------------------------------
--
-- Identity comes from a per-transaction setting the app issues as
--   SET LOCAL app.user_email = '<verified email>'
-- inside every transaction. SET LOCAL is transaction-scoped, so it cannot leak
-- between pooled connections the way a plain SET would.
--
-- current_setting(..., true) returns NULL when unset, and `col = NULL` is NULL,
-- which the policy treats as false. An app that forgets to set the GUC sees
-- nothing rather than everything — it fails closed.

DROP POLICY IF EXISTS sessions_own ON public.sessions;
CREATE POLICY sessions_own ON public.sessions
  FOR ALL
  TO fishing_app
  USING      (user_email = current_setting('app.user_email', true))
  WITH CHECK (user_email = current_setting('app.user_email', true));

-- fish and spots carry no user_email of their own; ownership is inherited from
-- the parent session. The EXISTS below is additionally filtered by the
-- sessions policy above, so this is defence in depth rather than the only gate.

DROP POLICY IF EXISTS fish_own ON public.fish;
CREATE POLICY fish_own ON public.fish
  FOR ALL
  TO fishing_app
  USING (EXISTS (
    SELECT 1 FROM public.sessions s
    WHERE s.id = fish.session_id
      AND s.user_email = current_setting('app.user_email', true)
  ))
  WITH CHECK (EXISTS (
    SELECT 1 FROM public.sessions s
    WHERE s.id = fish.session_id
      AND s.user_email = current_setting('app.user_email', true)
  ));

DROP POLICY IF EXISTS spots_own ON public.spots;
CREATE POLICY spots_own ON public.spots
  FOR ALL
  TO fishing_app
  USING (EXISTS (
    SELECT 1 FROM public.sessions s
    WHERE s.id = spots.session_id
      AND s.user_email = current_setting('app.user_email', true)
  ))
  WITH CHECK (EXISTS (
    SELECT 1 FROM public.sessions s
    WHERE s.id = spots.session_id
      AND s.user_email = current_setting('app.user_email', true)
  ));

-- ---------------------------------------------------------------------------
-- 4. Force RLS
-- ---------------------------------------------------------------------------
-- Without FORCE, the table owner (postgres) bypasses every policy above. With
-- it, even an owner connection is filtered — so a maintenance script that
-- forgets its WHERE clause cannot quietly touch someone else's trips.
--
-- NOTE: this makes owner connections subject to app.user_email too. Set the
-- GUC in maintenance scripts, or use fishing_deploy, which is not the owner.

ALTER TABLE public.sessions FORCE ROW LEVEL SECURITY;
ALTER TABLE public.fish     FORCE ROW LEVEL SECURITY;
ALTER TABLE public.spots    FORCE ROW LEVEL SECURITY;

COMMIT;

-- ---------------------------------------------------------------------------
-- 5. Verify — expect isolation to hold even with NO application predicate
-- ---------------------------------------------------------------------------
--
-- Run these as fishing_app (Supabase SQL editor runs as postgres, so use a
-- psql connection with the fishing_app credential):
--
--   BEGIN;
--   SET LOCAL app.user_email = 'someone@example.com';
--   SELECT count(*) FROM sessions;              -- only that user's trips
--   SELECT count(*) FROM fish;                  -- only that user's fish
--   ROLLBACK;
--
--   BEGIN;                                       -- GUC deliberately unset
--   SELECT count(*) FROM sessions;              -- MUST be 0, not everything
--   ROLLBACK;
--
-- The second block is the real test. If it returns a non-zero count, the
-- runtime role is still bypassing RLS — stop and recheck rolbypassrls and
-- table ownership before switching the app over.
