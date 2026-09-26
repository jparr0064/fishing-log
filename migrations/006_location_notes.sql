-- "Where you fished" as written notes, alongside or instead of map pins.
--
-- Some anglers don't want to drop pins at all; they would rather write
-- "north side of the Hales Ford bridge, 30 ft of water". Others use the map
-- and want to add a line of detail under it. Both are stored here. This is
-- kept separate from sessions.notes (general trip notes) so the trip view can
-- show it under "Where you fished" and so it can decide whether to show a map,
-- these notes, both, or nothing.
--
-- NULL means nothing was written. Every existing trip keeps its meaning with
-- no backfill: a trip with spots shows its map, a trip without shows nothing.
-- The app checks for this column before using it, so the code can ship on
-- either side of this migration, but the notes box only saves once it exists.
--
-- Apply as fishing_deploy (or postgres), never as fishing_app.
--
-- SANDBOX FIRST.

ALTER TABLE public.sessions ADD COLUMN IF NOT EXISTS location_notes text;
