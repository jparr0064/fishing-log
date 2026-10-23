-- "Other baits & styles used today": everything fished on a trip besides
-- the primary bait and style.
--
-- A day is rarely one technique. sessions.bait_lure / fishing_style stay the
-- trip's single PRIMARY method (what the per-fish dropdowns default to, and
-- what a skunked trip is filed under). These two columns list the rest, so the
-- app can tell a single-method day from a mixed one and can report methods
-- that were tried and caught nothing.
--
-- Stored as a JSON array of strings in a text column, e.g.
--   ["Jigging Spoon", "Umbrella Rig"]
-- Text rather than text[] so the SQLite test suite can use the same schema.
--
-- NULL means nothing else was used. Every existing trip keeps its meaning with
-- no backfill. The app checks for these columns before using them, so the code
-- can ship on either side of this migration; the pick-lists only appear once
-- it has been applied.
--
-- Apply as fishing_deploy (or postgres), never as fishing_app.
--
-- SANDBOX FIRST.

ALTER TABLE public.sessions ADD COLUMN IF NOT EXISTS other_baits text;
ALTER TABLE public.sessions ADD COLUMN IF NOT EXISTS other_styles text;
