-- Bulk catch entry: record an observed SIZE RANGE for fish that were counted
-- but not individually measured.
--
-- Why this shape. On a twenty-fish day an angler measures a few notable fish
-- and eyeballs the rest as "23 to 30 inches". That range is a truthful
-- observation. What would NOT be truthful is turning it into twenty individual
-- lengths, so these columns deliberately sit ALONGSIDE `length` rather than
-- filling it in:
--
--   * individually measured fish -> length > 0, len_min/len_max NULL
--   * bulk-entered fish          -> length = 0, len_min/len_max set
--
-- Nothing anywhere may expand a range into per-fish lengths. The DWR sizes
-- string renders the range as a labelled clause ("plus 17 fish 23"-30" (range)")
-- so the biologist reading it knows exactly how the numbers were collected, and
-- analytics keeps excluding length = 0 from size statistics, which means
-- personal bests and average lengths stay measured-only for free.
--
-- Both columns are nullable and additive, so older code that never selects them
-- keeps working against a database where this has been applied (see the
-- rollback note in RUNBOOK.md).
--
-- Apply as fishing_deploy (or postgres), never as fishing_app.
--
-- SANDBOX FIRST. Run this against fishing-log-sandbox and exercise the bulk
-- entry screen before it goes anywhere near production.

ALTER TABLE public.fish ADD COLUMN IF NOT EXISTS len_min real;
ALTER TABLE public.fish ADD COLUMN IF NOT EXISTS len_max real;
