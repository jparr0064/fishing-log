-- Per-spot fish counts, for the ×N badge on the route map.
--
-- This ran on every application startup as
--   ALTER TABLE spots ADD COLUMN IF NOT EXISTS fish_count integer
-- inside app.py's _bootstrap(). It is recorded here instead because CR-2 strips
-- DDL rights from the runtime role, and because a live app should not be
-- altering its own schema (CR-4, "controlled migrations").
--
-- Almost certainly ALREADY APPLIED — the startup hook has been running for a
-- while. It is idempotent, so running it again is harmless. app.py now checks
-- for this column at startup and names this file if it is missing.
--
-- Apply as fishing_deploy (or postgres), never as fishing_app.

ALTER TABLE public.spots ADD COLUMN IF NOT EXISTS fish_count integer;
