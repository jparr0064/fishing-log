-- Separate trolling runs, plus single stand-alone spots, on one trip's map.
--
-- A trolling day is often several runs: troll one stretch, pack up, run to
-- another part of the lake, troll again. Every pin on a trip used to be one
-- ordered list joined by one line, so the map drew a line across land from the
-- end of one run to the start of the next. And a spot that was simply fished
-- (sitting on downlines) had to pretend to be part of a troll.
--
--   run_no  which run a pin belongs to (1, 2, ...). Pins of the same run are
--           joined in order; different runs are never joined.
--   kind    'run'  - part of a trolling run (joined by a line)
--           'spot' - a single stand-alone spot (no line); run_no is NULL
--
-- NULL in both means "run 1", which is exactly how every existing pin was
-- drawn, so old trips look the same with no backfill. The app checks for these
-- columns before using them; until they exist it keeps the single-route picker.
--
-- Apply as fishing_deploy (or postgres), never as fishing_app.
--
-- SANDBOX FIRST.

ALTER TABLE public.spots ADD COLUMN IF NOT EXISTS run_no integer;
ALTER TABLE public.spots ADD COLUMN IF NOT EXISTS kind text;
