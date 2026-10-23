# Fish App — Ideas & Planned Changes

A running notepad for changes we're thinking about. Nothing here is built yet.
Items marked **Decided** have the direction agreed; details can still change before
coding. Started 2026-10-16.

**Status 2026-10-22: ideas 1–7 are all BUILT** on branch `staging` (not yet
committed or deployed). #4 also needs `migrations/007_other_methods.sql` run in
Supabase (sandbox first) before its pick-lists appear.

---

## 1. Journal Notes page — read all trip notes in one place
_(added 2026-10-16 · **Decided**: build it)_

**The want:** Read all my trip notes at once, in date order, without opening each
trip. Pick a date range and scroll from trip to trip. Read in order, good notes show
what each day was like, when things started changing, and my impressions. It brings
back the old paper fishing-journal feel.

**Decided:**
- New sidebar page called **Journal Notes**.
- One entry per trip: a **short** header, then the note in full. Keep the header
  light so it doesn't turn into the full trip view. Fish caught is a must.
- **"View trip →"** on each entry for the full detail.
- **Word search** (e.g. "gulls", "shad", "bait pods").
- **Hide trips with no notes** (on by default).
- **Same month / same weeks last year** quick button for comparing seasons.
- Date-range picker with quick buttons (This month, Last 3 months, This season).

**Proposed header line** (keep it to one line):
`Tue Oct 15, 2026 · 🐟 3 fish` (or `🦨 skunked`)
Maybe add water temp, since it's the number that best explains "when things changed".
Everything else (air temp, weather, bait, style) stays behind View trip.

**Still open:**
- Newest first or oldest first? (Oldest first reads like the story of a season.)
- Include water temp in the header, or fish count only?
- Phone or computer: where will this be read most?
- Later maybe: download the notes as a text/PDF file.

**Effort:** Small to medium. No database change; notes are already stored per trip.

## 2. Pull Notes out of "More detail (optional)"
_(added 2026-10-16 · **Decided**)_

**Decided:**
- Move **Notes** out of the collapsed section so it's always visible on Log a Session
  (and the same on Edit trip).
- The collapsed section keeps only air and water temp for now. Rename it to fit,
  e.g. **"Temperatures (optional)"**, and keep it as the home for future optional
  trip fields.
- Possibly add a one-line hint under Notes like "What did you see? Bait, birds,
  where they were, what changed" to encourage the notes the Journal page is built for.

**Effort:** Small.

## 3. Click a calendar day to open that trip
_(added 2026-10-16 · **Decided**: do last, if at all)_

**The want:** Click a day on the Calendar and have that trip open, instead of
scrolling to "Trips this month" and clicking View →.

**Notes:** The calendar grid is drawn as a static picture, so its days can't be
clicked yet. Options: rebuild the grid from real buttons; make trip days links (a
link reloads the page, which needs care); or a middle ground where clicking a day
opens it in the list below.

## 4. More than one bait / style per trip
_(added 2026-10-16 · user request · **Decided: Option A**, pending John's check
of the report to confirm it's worth the effort)_

**Decided (2026-10-16):** Keep the Primary bait and style at the top. Add a multi-pick
underneath with a label like **"Other baits & styles used today"**, as many as you
like. **Correction:** the DWR report does *not* use bait or style at all (checked
`dwr_report.py`), so this can't affect it. Only the app's own stats (Analytics
"what's working" by bait/style) use the primary, and Option A leaves that untouched.
John is double-checking the report anyway.
If it isn't worth it, the answer to the requester is "use the per-fish Bait/Style
columns and counted groups."

**The want:** People don't fish just one way all day. They want to record more than
one style (and bait) for a trip.

**How it works today:**
- The trip has **one** primary Bait/lure and **one** Style of fishing.
- Each measured fish has its own Bait and Style columns, which start on the trip's
  primary method and can be changed per fish.
- "Add a bait or style that isn't in the list" adds to your personal list. (Keep this.)

**Options:**
- **A. Primary + "also used today" (recommended).** Keep the single **Primary** bait
  and style, then add an **"Also used today"** multi-pick for each, as many as you
  like. The per-fish Bait/Style dropdowns list today's methods first, so picking one
  per fish is quick.
  - Keeps the primary method, which the existing Analytics stats rely on.
  - Bonus insight: records what you **tried and caught nothing on**, which the app
    can't tell you today ("tried umbrella rigs 6 trips, 0 fish").
- **B. One multi-pick list, no primary.** Simpler to look at, but every stat and
  the DWR report would need a rule for which one counts as "the" method.
- **C. Primary / Secondary only.** Easy, but caps you at two, and people will want three.

**Effort:** Medium. Needs a small database addition (a list of methods per trip), plus
updates to Log a Session, Edit trip, trip detail, the backup/restore export, and tests.

## 5. Mark which catch columns are optional
_(added 2026-10-16 · **Decided**: Claude's call on the wording/approach)_

**Goal:** Nobody should think they have to fill everything in to save. Only a
couple of things are required.

**The want:** In "What you caught", people don't know what they have to fill in.
Make it clear that Depth, Weight, Bait, and Style are optional.

**Notes:**
- What is actually required: **Species** plus **Length or Weight**. Kept? is a
  checkbox that defaults to "released", so it's never blank. It matters for the DWR
  report but never blocks saving.
- Streamlit's table can't draw a grouped "Optional" header row above some columns.
  Workable alternatives:
  - Label the column headers directly: `Depth (ft) · optional`, `Bait · optional`.
  - A line above the table: **"Required: species and a length or weight.
    Everything else is optional."**
  - Hover help (?) on each column header explaining it.
  - Recommend the line above the table **plus** hover help. Keeps headers short on a phone.

## 6. Bait / style for "Fish you counted but didn't measure"
_(added 2026-10-16 · **Decided: leave the groups as they are.** Splitting into
groups already handles it. At most, add the "add a group for each" hint.)_

**The want:** A group of e.g. 20 small fish may have been caught on 3–4 different
techniques, so the group needs to allow several.

**Already possible today:** each counted group already has its own Bait and Style
dropdowns, and you can add more than one group. So 20 fish on mixed methods can be
entered as, say, **12 on Live Shad / Downlines** and **8 on Umbrella rig / Trolling**.
- If people aren't finding that, the fix may just be wording, e.g. a hint:
  "Caught them different ways? Add a group for each."
- Giving one group several baits at once would lose which fish came on which method,
  so the stats couldn't use it. Splitting into groups keeps that information.
- If idea #4 lands, these dropdowns would also list today's methods first.

## 7. Make Analytics credit bait/style from the fish, not the trip
_(added 2026-10-16 · goes with #4 · **Decided 2026-10-17**: adopt the proposal below,
plus explain it in plain language in the app)_

**Explain it to users (decided):** people need to understand that the more they
enter, the better the analytics get, and that per-fish bait/style is what makes
per-fish analysis possible. Draft wording:

- **On Log a Session, under the catch table** (short):
  > Bait and Style per fish are optional. Leave them blank and we'll assume your
  > primary bait and style. Fill them in when a fish came on something else, and
  > Analytics can show what actually caught your fish.
- **At the top of Analytics** (a small "How these numbers work" note):
  > The more you log, the sharper these get. Each fish is credited to the bait and
  > style you entered for it. If you left those blank, it's credited to that trip's
  > primary. Fish-per-hour only uses trips where you fished one method, because a
  > mixed day can't be split fairly.
- Next to any stat built on only 1–2 trips, keep the existing "early signal" label,
  so thin numbers read as thin.

**The question:** If the primary is Live Shad / Downlines and I caught 10 fish, does
Analytics assume all 10 came on the primary, or does it use the per-fish Bait/Style?

**How it works today:** the app has both kinds, which is confusing:
- **Per-fish, the right one.** The "What actually caught them, by bait / by style"
  charts (`analytics.by_method`) credit each fish to **its own** Bait/Style. A fish
  left blank falls back to the trip's primary. Fish-per-hour is calculated only from
  trips where one method was used, since the hours can't be split fairly on a mixed day.
- **Per-trip, the misleading one.** The "Fishing style" and "Bait / lure" rows in the
  "what's working" conditions section, plus the **Best conditions** headline
  (`by_fishing_style` / `by_bait` / `best_conditions`), credit **every** fish on the
  trip to the primary.

**Proposal:**
- The per-fish rule becomes the only rule: "use what the fish says; if blank, assume
  the primary." The per-fish columns stay optional, and filling them in just makes
  the stats sharper.
- Switch the bait/style rows in "what's working" and Best conditions to the per-fish
  numbers (or drop them there and point to the "What actually caught them" charts).
- With #4: a trip with "Other baits & styles used today" counts as a mixed-method
  trip, so it never inflates a method's fish-per-hour. It also unlocks
  **"tried but caught nothing"**, e.g. "Umbrella rig: used on 6 trips, 0 fish."
- **DWR report unaffected:** it never uses bait or style.

---

## Parked (maybe later / not now)
