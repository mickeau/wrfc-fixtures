# Withycombe RFC fixtures → calendar feed

Turns the club's fixture list on Pitchero into a **live calendar feed** (`.ics`) that
you can subscribe to on a phone, and that keeps itself up to date as the club
changes fixtures. Made to be tapped from an NFC tag, but the links work anywhere.

Feeds produced:

| File | What's in it |
|------|--------------|
| `calendar.ics` | 1st XV and 2nd XV, in one calendar |
| `index.html` | A page with a Subscribe button, so a tag can point at one address |

Unofficial — this is not run by the club.

## How it works, in one paragraph

The club's website is hosted by Pitchero. Behind the visible page, Pitchero serves
its own fixture data as JSON (a plain, machine-readable format) from
`https://www.pitchero.com/data/club/27760/matches?teamId=...&seasonId=...`.
`build_calendar.py` reads the club homepage once to find the current season and the
team ID numbers, pulls each team's fixtures from that JSON, and writes them out as
calendar files. A GitHub Action re-runs it twice a day and republishes the result to
GitHub Pages, so the address you subscribe to always serves current fixtures.

Because it reads Pitchero's own data rather than picking apart the visual page, it
doesn't break every time they restyle the site.

What it does with awkward fixtures:

- **Cancelled or postponed** matches are left out. If a match you already have in
  your calendar gets cancelled, it disappears at the next refresh.
- **Kick-off not yet confirmed** (Pitchero stores these as midnight) becomes an
  all-day entry marked `(KO TBC)`, rather than a bogus match at 00:00.
- **Home** matches are located at Raleigh Park, with map coordinates attached.
- **Duplicates** — Pitchero sometimes lists the same match twice under two IDs —
  are collapsed into one entry.

## Setting it up

You need a free GitHub account. Everything below is done once.

### 1. Put the code on GitHub

Create a new **empty** repository on GitHub (no README, no .gitignore) called
`wrfc-fixtures`. Then, in this folder:

```bash
git init
git add .
git commit -m "Withycombe RFC fixtures calendar"
git branch -M main
git remote add origin https://github.com/YOUR-USERNAME/wrfc-fixtures.git
git push -u origin main
```

Replace `YOUR-USERNAME` with your GitHub username.

### 2. Turn on GitHub Pages

On the repository page: **Settings → Pages**, and under **Source** choose
**GitHub Actions**. Nothing else to change there.

### 3. Run it once by hand

**Actions** tab → **Update fixtures calendar** → **Run workflow**. It takes about a
minute. When it goes green, your files are live at:

```
https://YOUR-USERNAME.github.io/wrfc-fixtures/
https://YOUR-USERNAME.github.io/wrfc-fixtures/calendar.ics
```

Open the first one in a browser to check it looks right.

From then on it runs itself at about 06:20 and 18:20 UTC each day.

## Subscribing (and the NFC tag)

There are two ways to hand someone the calendar, and the difference matters:

- `https://.../calendar.ics` — most phones **download a copy**. A snapshot, frozen
  at the moment they tapped.
- `webcal://.../calendar.ics` — phones treat this as a **subscription**. The
  calendar app re-checks the address and keeps it current. Same file, different
  first word.

So for the tag, write:

```
webcal://YOUR-USERNAME.github.io/wrfc-fixtures/calendar.ics
```

### Writing the tag

1. Install **NFC Tools** (Android or iPhone) or **NXP TagWriter** (Android).
2. *Write* → *Add a record* → **URL/URI**.
3. Paste the `webcal://` address. If the app insists on a prefix from a dropdown,
   choose `http://` and then edit the field so it reads `webcal://...` — some apps
   let you, some don't; if yours won't, use the plain `https://` page address
   instead (see below).
4. *Write* and hold the tag to the back of the phone.

An NTAG213 tag holds about 144 bytes, so this address fits easily.

### Which address to put on the tag

- **iPhone** handles `webcal://` properly: one tap, "Subscribe to calendar?", done.
- **Android** is patchier. The Google Calendar app has no way to add a subscription
  on the phone at all — it has to be done on a computer at calendar.google.com
  (**Other calendars → + → From URL**), or with a helper app such as the free
  [ICSx⁵](https://play.google.com/store/apps/details?id=at.bitfire.icsdroid), which
  does handle `webcal://` links on the phone.

If the tag will be tapped by a mix of phones, point it at the landing page instead:

```
https://YOUR-USERNAME.github.io/wrfc-fixtures/
```

That page has a Subscribe button that builds the `webcal://` address itself, and
spells out the Android options, so it works reasonably on anything.

## Changing what's in the calendar

Open `build_calendar.py` — the settings are at the top, under
"Settings you might want to change".

- **Add a team**: add its name to `TEAMS_WANTED`, spelled exactly as it appears on
  the club site, e.g. `["1st XV", "2nd XV", "Colts"]`. The available names are
  1st XV, 2nd XV, Walking Rugby, Ladies, Colts, and the junior age groups. Every
  team listed goes into the single `calendar.ics`.
- **Match length** (default 2 hours): `MATCH_LENGTH`.
- **Ground details**: `HOME_GROUND` and `HOME_GEO`.

Commit and push the change; the workflow rebuilds on push.

You do **not** need to update anything at the start of a new season — the script
reads the current season from the club site each time it runs.

## Running it on your own machine

```bash
pip install -r requirements.txt
python3 build_calendar.py
```

The files appear in `public/`. That folder is deliberately not committed to git;
GitHub builds it fresh on every run.

## If it stops working

The most likely cause is Pitchero changing their site. The script fails loudly
rather than publishing an empty calendar, and the workflow checks the file has
events in it before deploying, so a broken run leaves the last good version live.

To see what happened: **Actions** tab → the failed run → open the log.

- *"Could not find the __NEXT_DATA__ block"* — Pitchero has rebuilt their site;
  the way we find the club's ID numbers needs revisiting.
- *"no team called '1st XV'"* — the club renamed a team. The error message lists
  the names it did find; copy the right one into `TEAMS_WANTED`.
- An HTTP error — usually temporary. Re-run the workflow.
