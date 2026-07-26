-- CR-7 — stable trip identifiers for idempotent restore.
--
-- Apply as fishing_deploy (or postgres), never as fishing_app.
-- Safe to run on a live database: the column is nullable, nothing reads it
-- until the app is deployed, and existing rows are backfilled in place.
--
-- WHY
-- Restore currently decides "do I already have this trip?" by comparing
-- date + start_time + location_name. That heuristic is wrong in both
-- directions. Two trips to the same spot on the same morning with no start
-- time recorded look identical, so a real trip gets skipped. Rename the
-- location of a trip and restore the same backup again, and it comes back as a
-- duplicate. A stable per-trip id makes restore idempotent: the same backup
-- applied twice produces the same database.
--
-- The app tolerates this column being absent — it falls back to the old
-- heuristic — so deploying before or after this migration both work.

BEGIN;

ALTER TABLE public.sessions ADD COLUMN IF NOT EXISTS trip_uuid text;

-- Backfill existing trips. gen_random_uuid() is built in from PG13 (this is
-- PG17). Only touches rows that have no id yet, so re-running is harmless and
-- never rewrites an id already published in someone's backup file.
UPDATE public.sessions
   SET trip_uuid = gen_random_uuid()::text
 WHERE trip_uuid IS NULL;

-- Unique per owner, not globally: two anglers restoring the same shared backup
-- should each end up with their own copy. Partial, so legacy NULLs never clash.
CREATE UNIQUE INDEX IF NOT EXISTS sessions_user_trip_uuid_key
    ON public.sessions (user_email, trip_uuid)
 WHERE trip_uuid IS NOT NULL;

COMMIT;

-- Verify:
--   SELECT count(*) FILTER (WHERE trip_uuid IS NULL) AS missing,
--          count(*) AS total
--     FROM sessions;
-- `missing` should be 0.
