"""Generate the Fishing Log user guide PDF (Fishing_Log_User_Guide.pdf)."""
from reportlab.lib.pagesizes import letter
from reportlab.lib.styles import getSampleStyleSheet, ParagraphStyle
from reportlab.lib.units import inch
from reportlab.lib.colors import HexColor, white
from reportlab.platypus import (
    SimpleDocTemplate, Paragraph, Spacer, Table, TableStyle, PageBreak,
)

TEAL = HexColor("#0e7490")
DARK = HexColor("#0f3a4d")
GRAY = HexColor("#51606b")
LIGHT = HexColor("#e8f4f8")

styles = getSampleStyleSheet()

title_style = ParagraphStyle(
    "GuideTitle", parent=styles["Title"], textColor=white,
    fontSize=26, leading=32, alignment=0, spaceAfter=2,
)
subtitle_style = ParagraphStyle(
    "GuideSub", parent=styles["Normal"], textColor=HexColor("#cdeef0"),
    fontSize=12, leading=16,
)
h1 = ParagraphStyle(
    "H1", parent=styles["Heading1"], textColor=DARK, fontSize=16,
    spaceBefore=18, spaceAfter=6,
)
h2 = ParagraphStyle(
    "H2", parent=styles["Heading2"], textColor=TEAL, fontSize=12.5,
    spaceBefore=10, spaceAfter=4,
)
body = ParagraphStyle(
    "Body", parent=styles["Normal"], fontSize=10.5, leading=15,
    spaceAfter=6, textColor=HexColor("#222222"),
)
tip = ParagraphStyle(
    "Tip", parent=body, backColor=LIGHT, borderPadding=6,
    leftIndent=4, spaceBefore=4, spaceAfter=8,
)
bullet = ParagraphStyle("Bullet", parent=body, leftIndent=16, bulletIndent=4, spaceAfter=3)

doc = SimpleDocTemplate(
    "Fishing_Log_User_Guide.pdf", pagesize=letter,
    leftMargin=0.85 * inch, rightMargin=0.85 * inch,
    topMargin=0.7 * inch, bottomMargin=0.7 * inch,
    title="Fishing Log — User Guide", author="Fishing Log",
)
story = []


def B(text):
    story.append(Paragraph("•&nbsp;&nbsp;" + text, bullet))


# ---- Cover banner ----
banner = Table(
    [[Paragraph("Fishing Log — User Guide", title_style)],
     [Paragraph("Smith Mountain Lake &nbsp;·&nbsp; A Private Fishing Log for Our Crew", subtitle_style)],
     [Paragraph("Version 3.0 &nbsp;·&nbsp; Created by John Parrent", ParagraphStyle(
         "GuideVer", parent=subtitle_style, fontSize=9.5, spaceBefore=4))]],
    colWidths=[6.8 * inch],
)
banner.setStyle(TableStyle([
    ("BACKGROUND", (0, 0), (-1, -1), TEAL),
    ("LEFTPADDING", (0, 0), (-1, -1), 18),
    ("RIGHTPADDING", (0, 0), (-1, -1), 18),
    ("TOPPADDING", (0, 0), (0, 0), 24),
    ("BOTTOMPADDING", (0, -1), (0, -1), 16),
]))
story.append(banner)
story.append(Spacer(1, 14))

story.append(Paragraph(
    "Fishing Log is a free web app for logging your Smith Mountain Lake striper trips — "
    "what you caught, where, and under what conditions. Over time it builds YOUR playbook: "
    "which water temps, baits, moon phases, and spots actually produce. It runs in any web "
    "browser on your computer or phone. There is nothing to install.", body))
story.append(Paragraph(
    "<b>Web address:</b> https://fishing-log-fmvre8u5mrqhfsgsfhxroj.streamlit.app", tip))

# ---- Signing in ----
story.append(Paragraph("1. Signing in", h1))
story.append(Paragraph(
    "Open the web address above and click <b>Sign in with Google</b>. You'll use your "
    "regular Google account — there is no separate password to remember. Your trips are "
    "private to your email address: nobody else in the club can see your data, and you "
    "can't see theirs.", body))
story.append(Paragraph(
    "<b>First-time heads-up:</b> most people go straight through, but Google MAY show a "
    "one-time screen that says \"Google hasn't verified this app.\" If you see it, click "
    "<b>Advanced</b>, then <b>Go to Fishing Log</b>, then <b>Continue</b>. Google shows that "
    "notice only because our app hasn't gone through their formal (paid) verification "
    "process. The app itself is private, and you'll never see the screen again.", tip))
story.append(Paragraph(
    "If sign-in tells you that you don't have access yet, your email hasn't been added to the "
    "approved list — just ask John Parrent (Striper Club Member) to add you.", body))
story.append(Paragraph("Want to look around first?", h2))
story.append(Paragraph(
    "Click <b>Try the Demo</b> on the sign-in page. You'll get a read-only tour with 15 sample "
    "trips already loaded so you can click through every page. Nothing you do in the demo can "
    "break anything.", body))

# ---- Log a Session ----
story.append(Paragraph("2. Logging a trip (Log a Session)", h1))
story.append(Paragraph(
    "This is the page you'll use most, and it works the same on a phone as on a computer. "
    "It's in three numbered sections — <b>1 The trip</b>, <b>2 Where you fished</b>, "
    "<b>3 What you caught</b> — and <b>one Save button at the very bottom</b> that saves all "
    "of it together. Work down the page, hit Save once, done. It takes about a minute.", body))
story.append(Paragraph(
    "<b>Only two things are actually required:</b> the date and the location. Everything else "
    "is optional. Fill in what you know and skip the rest.", tip))

story.append(Paragraph("1 · The trip", h2))
B("Date and location (location is pre-filled with Smith Mountain Lake).")
B("Start and end time — dropdowns in 15-minute steps. Hours fished works itself out.")
B("Weather and number of anglers (anglers is used for your DWR report).")
B("<b>More detail</b> holds air temp, water temp and notes. Open it if you took readings; "
  "ignore it if you didn't.")
story.append(Paragraph("Primary fishing method used this day", h2))
story.append(Paragraph(
    "Pick the <b>one</b> bait and the <b>one</b> style the day was mostly about. This matters "
    "for two reasons: every fish you log below starts out set to it, so you rarely have to "
    "touch it again; and on a day you catch nothing it's the only record of how you fished. "
    "Any other technique you tried can be set on the individual fish further down.", body))
story.append(Paragraph(
    "Using something that isn't in the list? Open <b>Add a bait or style that isn't in the "
    "list</b> and type it. Once you log a fish with it, it stays in your list for good.", body))

story.append(Paragraph("2 · Where you fished", h2))
B("Click the map to drop your starting pin. Click again to add each spot along your troll.")
B("The map opens centered on the water you fished <b>last trip</b> — handy if you pound the same spots.")
B("Under the map, enter how many fish you caught at each spot (0 = none). Spots with fish "
  "show a fish icon on the map, with an \u00d7N badge when you caught several there.")
B("Use the <b>Last</b> button to undo the most recent pin or <b>Clear</b> to start over.")
B("Skipping the map is fine — the trip just won't get a pin.")
story.append(Paragraph("Tracking your trolling route", h2))
story.append(Paragraph(
    "This is one of the coolest features. Don't stop at one pin — click the map again at "
    "each point along your troll. Later, when you open that trip in Browse &amp; Search, "
    "you'll see your whole route drawn out: the pins are numbered in the order you dropped "
    "them, a line with arrows shows the direction you trolled, and a fish icon marks every "
    "spot where you entered a fish count.", body))
story.append(Paragraph(
    "Not trolling? Multiple pins still work great — drop one on each hole you fished that day.", body))
story.append(Paragraph(
    "<b>Good to know:</b> the big Map page shows ONE pin per trip, and it uses your FIRST pin. "
    "So make your first click the spot that best represents the trip — usually where you "
    "started — then add the rest of the route after it.", tip))

story.append(Paragraph("3 · What you caught", h2))
story.append(Paragraph(
    "There are two tables here, and you can use either or both on the same trip. Both start "
    "with a row already set to <b>Striper</b>, since that's what most of us are after.", body))
story.append(Paragraph("Fish you measured — one row each", h2))
story.append(Paragraph(
    "Pick a species, then enter length, depth and weight. Caught another? Click the blank row "
    "at the bottom and it becomes a new fish. Check <b>Kept?</b> for harvested fish; leave it "
    "unchecked for released.", body))
story.append(Paragraph(
    "<b>Only the species is required</b> — a fish with just a species still counts in every "
    "catch stat (totals, success rate, fish per hour). Length, depth and weight are optional. "
    "The trade-off is simple: whatever you enter feeds your Analytics, and whatever you skip "
    "just sits out those charts. Measure your fish and the Sizes and Personal Bests pages "
    "come alive.", body))
story.append(Paragraph(
    "Each row also has <b>Bait</b> and <b>Style</b>, already set to your primary method. Change "
    "them on any fish you caught a different way — and the next row you add keeps whatever you "
    "picked last, so a run of them is one click, not one per fish.", body))
story.append(Paragraph(
    "The small checkbox on the far LEFT of each row is only for deleting rows: check it and a "
    "trash can appears at the top of the table. You don't need it for normal entry.", tip))

story.append(Paragraph("Fish you counted but didn't measure", h2))
story.append(Paragraph(
    "For the tail end of a good day. Twenty fish in the boat and you measured three of them? "
    "Enter the three above, then use this for the other seventeen: how many, and the range of "
    "sizes you saw. Set the bait and style for the group, and tick Kept if they were harvested.", body))
story.append(Paragraph(
    "It's recorded honestly as a range — the app never pretends those were seventeen individual "
    "measurements. The biggest end of your range still counts for your personal best, because "
    "\"my biggest was 32 inches\" is something you saw, not a guess.", body))
story.append(Paragraph(
    "Fished two ways? Use <b>Add another group</b> — one group for the spoon fish, another for "
    "the downline fish. Each group carries its own bait and style.", body))
story.append(Paragraph(
    "Leave <b>How many</b> at blank or zero and the group is simply ignored.", tip))

story.append(Paragraph("Got skunked?", h2))
story.append(Paragraph(
    "Tick <b>No fish caught (skunked trip)</b> at the top of section 3 and press Save. The "
    "tables are ignored entirely. Skunked trips are real data — they're what makes your "
    "success rate mean anything.", body))

story.append(Paragraph("Saving", h2))
story.append(Paragraph(
    "As you enter fish, a running total appears — <i>\"23 fish this trip \u2014 1 measured "
    "individually, 22 in groups\"</i>. Check it matches what's in the boat, then press "
    "<b>Save this trip</b> at the bottom. It saves everything: the trip, the map and every "
    "fish, in one go.", body))
story.append(Paragraph(
    "Saving takes a few seconds — you'll see <i>Saving your trip\u2026</i> while it works. Then "
    "the page changes to show <b>Trip saved</b>, exactly what was recorded, and your DWR "
    "report card if you logged stripers. Press <b>Log another trip</b> to start the next one.", body))
story.append(Paragraph(
    "Once a trip is saved the form is gone on purpose, so nobody accidentally saves the same "
    "trip twice. To change it, open it under Browse &amp; Search and edit it there.", tip))

# ---- DWR ----
story.append(Paragraph("3. Filing your DWR striper report", h1))
story.append(Paragraph(
    "Virginia DWR asks striper anglers to report each outing. The app does the paperwork for you: "
    "after you save a trip, a report card appears with your numbers already totaled.", body))
B("<b>Step 1 — Open pre-filled DWR report:</b> opens the official Google Form with your date, "
  "hours, anglers, and harvested/released counts and sizes already filled in. Review it and hit Submit.")
B("<b>Step 2 — Mark as filed to DWR:</b> check this box after you submit so the app knows it's done.")
story.append(Paragraph(
    "Once you check Step 2, that report is a done deal — the card switches to \"Filed on "
    "(date)\" and the buttons go away so nobody can accidentally double-file. If you later edit "
    "a filed trip, the app reminds you that the state already has its copy. Checked the box by "
    "mistake? There's an <b>Unmark</b> button inside the trip's edit form.", body))
story.append(Paragraph(
    "The Dashboard shows a reminder listing any trips you haven't filed yet.", tip))

# ---- Browse ----
story.append(Paragraph("4. Reviewing trips (Browse &amp; Search)", h1))
B("Filter by date range, location, or species at the top of the page.")
B("Each trip shows as a card — click <b>Open trip</b> and it opens on its own page.")
B("The trip page shows everything: conditions, the fish, your trolling route on a map, "
  "and the DWR report status.")
B("<b>Back to all trips</b> at the top and bottom returns you to the list.")
B("<b>Edit this trip</b> opens the same three sections you used to log it, with one "
  "<b>Save changes</b> at the bottom. <b>Cancel editing</b> backs out without saving.")
B("<b>Filter trips</b> at the top is collapsed until you need it — trips are newest first.")
B("<b>Delete this session</b> is at the very bottom, on purpose — it can't be undone.")

# ---- Calendar ----
story.append(Paragraph("5. Calendar", h1))
B("A month grid of your season: <b>green</b> days = caught fish, <b>gray</b> days = skunked, "
  "white = no trip.")
B("Each trip day shows the fish count and location; the moon phase icon appears in the corner.")
B("Navigate with Prev / Next, jump to <b>Today</b>, or hit <b>Year ago</b> to compare "
  "against last season.")
B("Below the grid, every trip that month is listed — click <b>View →</b> to read the full detail "
  "without leaving the page.")

# ---- Analytics ----
story.append(Paragraph("6. Analytics", h1))
story.append(Paragraph(
    "This is where the log pays off. Pick a year and browse the tabs:", body))
story.append(Paragraph(
    "Analytics runs on whatever you've entered — a fish logged without a weight still counts "
    "as a fish everywhere; it just won't appear in the size and weight charts. The more "
    "detail you log, the more these pages can tell you.", tip))
B("<b>Monthly:</b> trips, fish, and success rate by month.")
B("<b>Sizes:</b> how your fish measure up over the season.")
B("<b>Personal Bests:</b> your longest and heaviest fish, by species, with dates.")
B("<b>What's Working:</b> your most productive water temps, weather, baits, styles, and times — "
  "ranked by fish per hour.")

# ---- Map ----
story.append(Paragraph("Backing up from a phone", h2))
story.append(Paragraph(
    "The download works fine on a phone, but where it lands matters. On an iPhone it goes to "
    "<b>Files \u2192 Downloads</b>; on Android, your <b>Downloads</b> folder.", body))
story.append(Paragraph(
    "<b>Then move it off the phone.</b> A backup that only exists on your phone does not "
    "survive losing your phone, and there is no copy on our side to fall back on. On an "
    "iPhone: Files \u2192 Downloads \u2192 press and hold the file \u2192 Move \u2192 iCloud Drive. On "
    "Android: Files \u2192 Downloads \u2192 Share \u2192 Save to Drive. Emailing it to yourself works "
    "on either and is the easiest to find again later.", body))
story.append(Paragraph(
    "<b>If the download button seems to do nothing</b>, you are probably in an in-app browser \u2014 "
    "the one that opens when you tap a link inside Facebook or Messenger. Those block "
    "downloads. Open the app in Safari or Chrome instead and it will work.", tip))

story.append(Paragraph("7. Map", h1))
B("Every trip's spot on one map, color-coded by how the day went: Skunked (0), Good (1–3), "
  "Great (4–6), Blowout (7+).")
B("Click a pin for the trip's date, conditions, bait, and catch.")
B("Turn on the <b>catch hotspots</b> checkbox for a heat map of everywhere you've actually caught fish.")
B("Each trip appears as one pin — specifically the FIRST pin you dropped when logging it "
  "(your full trolling route lives in the trip's detail under Browse &amp; Search).")
B("The same date/location/species filters apply, and there's a full-screen toggle.")

# ---- Backup & Export ----
story.append(Paragraph("8. Backup &amp; Export", h1))
story.append(Paragraph(
    "The <b>Backup &amp; Export</b> page downloads a single ZIP with EVERYTHING: your trips, "
    "every fish (with kept/released), and your map spots and routes — plus a backup.json file "
    "the app can restore from. Grab one every month or so and stash it somewhere safe.", body))
B("<b>Download full backup (ZIP)</b> — the one button that backs up everything.")
B("<b>Restore from backup</b> — upload a backup ZIP and the app loads those trips back into "
  "your account. Trips you already have are skipped automatically.")
B("Prefer spreadsheets? The individual Sessions and Fish CSVs are still there under "
  "\"Individual CSVs\" — handy for Excel, but the ZIP is the real backup.")

# ---- Phone ----
story.append(Paragraph("9. Using it on your phone", h1))
story.append(Paragraph(
    "The app works in your phone's browser and is tuned for smaller screens — bigger buttons, "
    "a compact calendar, and a simpler layout.", body))
B("Tap the teal <b>Menu</b> button (top-left) to open the page list; it closes itself after you pick "
  "a page. When the menu is open, <b>Hide menu</b> tucks it away.")
B("<b>Make it feel like a real app:</b> in Safari or Chrome, tap Share → <b>Add to Home Screen</b>. "
  "You get a Fishing Log icon that opens full-screen, no address bar.")
B("The computer is still the best place for map-heavy work like setting trolling routes; the phone "
  "is great for logging a trip at the dock and checking your log anywhere.")

# ---- FAQ ----
story.append(Paragraph("10. Quick answers", h1))
faq = [
    ("Is my data private?", "Trips are tied to your email, and the app only ever shows you your "
     "own log — no other member can see it. (As with any shared cloud database, John, as the "
     "administrator, can access the database when maintaining the app.)"),
    ("I got skunked. Do I still log it?", "Absolutely — skunked trips are data too, and the DWR wants "
     "those reports just as much. Tick No fish caught (skunked trip) in section 3 and save."),
    ("I made a mistake on a trip.", "Browse &amp; Search → Open trip → Edit this trip. Fix it and "
     "press Save changes. Cancel editing backs out without changing anything."),
    ("Can I lose my data?", "It lives in a cloud database, not on your phone. There is no second "
     "copy on our side, though, so download a full backup ZIP every month or so — the Restore "
     "button puts everything back from it. See section 6 for doing this on a phone."),
    ("Something looks broken.", "Note what page you were on and what you clicked, then tell John "
     "Parrent. The 'build' number at the bottom of the menu helps troubleshooting."),
    ("Have an idea to make it better?", "Tell John Parrent! The app is homegrown and always "
     "improving — member suggestions are where the best features come from."),
]
rows = [[Paragraph(f"<b>{q}</b>", body), Paragraph(a, body)] for q, a in faq]
t = Table(rows, colWidths=[2.1 * inch, 4.7 * inch])
t.setStyle(TableStyle([
    ("VALIGN", (0, 0), (-1, -1), "TOP"),
    ("ROWBACKGROUNDS", (0, 0), (-1, -1), [white, LIGHT]),
    ("TOPPADDING", (0, 0), (-1, -1), 6),
    ("BOTTOMPADDING", (0, 0), (-1, -1), 6),
    ("LINEBELOW", (0, 0), (-1, -2), 0.5, HexColor("#d7e2ec")),
]))
story.append(t)
story.append(Spacer(1, 18))
story.append(Paragraph("Tight lines!", ParagraphStyle(
    "Sign", parent=body, textColor=GRAY, fontSize=11, alignment=1)))

doc.build(story)
print("Wrote Fishing_Log_User_Guide.pdf")

