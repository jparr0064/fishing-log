-- Per-fish bait and fishing style, so one trip can honestly record two
-- techniques.
--
-- The problem this fixes. sessions.bait_lure and sessions.fishing_style
-- describe a whole outing, so analytics credits every fish on the trip to one
-- method. On a day spent running live shad on downlines WHILE ripping spoons
-- off the bottom, that is not merely incomplete — it is wrong, and it has been
-- quietly skewing by_bait / by_fishing_style / best_conditions for exactly the
-- trips where the answer matters most.
--
-- NULL means "same as the trip". That is what makes this safe to add without a
-- backfill: every fish already logged keeps its meaning, analytics falls back
-- to the session's method whenever these are NULL, and a single-technique day
-- never has to fill anything in.
--
-- The session-level columns stay. They remain the trip's primary method, they
-- are what the per-fish dropdowns default to, and older code that reads only
-- them keeps working against a database where this has been applied.
--
-- Apply as fishing_deploy (or postgres), never as fishing_app.
--
-- SANDBOX FIRST.

ALTER TABLE public.fish ADD COLUMN IF NOT EXISTS bait_lure text;
ALTER TABLE public.fish ADD COLUMN IF NOT EXISTS fishing_style text;
