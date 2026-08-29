# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## What this is

A single Python script that turns Withycombe RFC's fixture list into an iCalendar
feed, plus a GitHub Actions workflow that republishes it twice daily to GitHub
Pages. People subscribe to the feed from a link or an NFC tag.

Live at https://mickeau.github.io/wrfc-fixtures/ — repo `mickeau/wrfc-fixtures`.

## Commands

```bash
pip install -r requirements.txt
python3 build_calendar.py          # writes public/calendar.ics and public/index.html
```

`public/` is gitignored — CI builds it fresh on every run. Pushing to `main`
triggers a rebuild and deploy; `gh run list` / `gh run view <id> --log` to check.
`gh workflow run update-calendar.yml` runs it on demand.

There are no tests. Verification is running the script and looking at the output;
the workflow additionally refuses to deploy a `calendar.ics` with no `BEGIN:VEVENT`
in it, so a broken build leaves the last good version live. To check the output
really parses, run it through a strict parser rather than trusting the eye:

```bash
python3 -m venv /tmp/v && /tmp/v/bin/pip install icalendar
/tmp/v/bin/python -c "from icalendar import Calendar; from pathlib import Path; \
  print(len(list(Calendar.from_ical(Path('public/calendar.ics').read_bytes()).walk('VEVENT'))))"
```

## Where the data comes from

Pitchero hosts the club's site as a Next.js app. **Nothing here parses rendered
HTML.** Two hops:

1. `GET /clubs/withycomberfc` — pull the `__NEXT_DATA__` JSON blob out of the page.
   It carries the club id (27760), every team with its id, and every season with
   start/end dates. Team ids and the season id are looked up here on each run, so
   the script needs no attention at the turn of a season.
2. `GET /data/club/{clubId}/matches?teamId={id}&seasonId={id}` — Pitchero's own
   page-data endpoint, returning fixtures as JSON. Public, no auth.

That second endpoint is undocumented and was found by reading Pitchero's JS
bundle. If it disappears, the fallback is the `v2/club-website/{clubId}/page?key=`
API the same bundle calls server-side. Fixture pages live at
`/clubs/withycomberfc/teams/{teamId}/fixtures-results` — note `fixtures-results`,
not `fixtures`, which 404s.

## Fixture handling worth knowing

- `kickoff: "TBC"` means the time isn't confirmed, and `dateTime` is then midnight.
  These become **all-day events** marked `(KO TBC)` — never a match at 00:00.
- Cancelled and postponed fixtures are dropped, so they vanish from subscribers'
  calendars at the next refresh.
- Pitchero sometimes lists one match twice under two ids. `dedupe()` collapses on
  (team, date, opponent, home/away).
- Home fixtures get Raleigh Park as the location plus `GEO`.

## The .ics is hand-built

No calendar library — `build_calendar()` and `build_event()` emit RFC 5545 text
directly. Consequences if you edit them: lines end `\r\n`, long lines fold at 75
octets with a leading space on continuations (`fold()`, which is UTF-8 aware),
and text values need `escape()` for `\ ; ,` and newlines. Times are emitted as
UTC `Z`, which is why no `VTIMEZONE` block is needed.

## Platform behaviour (learned the hard way — don't re-derive)

- `webcal://` makes a calendar app **subscribe**; `https://` makes it **download a
  frozen copy**. Same file.
- iPhone handles `webcal://` in one tap. Android has no handler for it at all.
- **Google's `calendar.google.com/calendar/render?cid=…` deep link does not work
  here.** Given an `https://` address it reads the value as a calendar *ID*,
  reports "calendar was successfully added" and subscribes to nothing. It was
  tried, shipped, and removed. Don't reintroduce it.
- Google's **Other calendars → + → From URL** box does work, and wants the plain
  `https://` address. It is desktop-site only — hence the Chrome → ⋮ → Desktop
  site instructions on the landing page.
- A newly subscribed calendar arrives **switched off** in the Google Calendar
  Android app; nothing shows until Settings → the calendar → Sync is turned on.
- Downloading the `.ics` on Android does import all fixtures cleanly (confirmed on
  a real phone), but it is a snapshot that never updates. The landing page says so
  in as many words.

The landing page's job is to state which route subscribes and which doesn't. Keep
that honest — a route that silently fails is worse than one that isn't offered.

## Settings

Top of `build_calendar.py`: `TEAMS_WANTED` (team names exactly as Pitchero spells
them, all going into the one `calendar.ics`), `HOME_GROUND`, `HOME_GEO`,
`MATCH_LENGTH`, `CALENDAR_NAME`.
