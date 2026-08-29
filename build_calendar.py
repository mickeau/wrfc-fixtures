#!/usr/bin/env python3
"""Build an iCalendar (.ics) feed of Withycombe RFC fixtures.

Data comes from the JSON feed that powers the club's own Pitchero website
(https://www.pitchero.com/clubs/withycomberfc), so the output tracks whatever
the club publishes. Nothing here is scraped out of HTML except the one blob of
JSON that Pitchero embeds in its club homepage, which tells us the club id, the
team ids and the current season id.

Run it with:   python3 build_calendar.py
Output lands in the ./public folder, ready to publish to GitHub Pages.
"""

from __future__ import annotations

import html
import json
import re
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path

import requests

# ---------------------------------------------------------------------------
# Settings you might want to change
# ---------------------------------------------------------------------------

CLUB_URL = "https://www.pitchero.com/clubs/withycomberfc"

# Teams to include, written exactly as Pitchero names them on the club site.
# Add e.g. "Colts" or "Ladies" here if you want them in the calendar too.
TEAMS_WANTED = ["1st XV", "2nd XV"]

# Where home games are played. Used as the event location for home fixtures.
HOME_GROUND = "Raleigh Park, Hulham Road, Exmouth, Devon EX8 3HS"
HOME_GEO = "50.6300812;-3.40608"

CALENDAR_NAME = "Withycombe RFC — 1st & 2nd XV"
CALENDAR_DESC = "Fixtures for Withycombe RFC 1st XV and 2nd XV, updated twice a day."

# How long to block out for a match, when we know the kick-off time.
MATCH_LENGTH = timedelta(hours=2)

OUTPUT_DIR = Path(__file__).parent / "public"

USER_AGENT = (
    "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/126.0 Safari/537.36"
)
TIMEOUT = 30


# ---------------------------------------------------------------------------
# Talking to Pitchero
# ---------------------------------------------------------------------------


def get_session() -> requests.Session:
    session = requests.Session()
    session.headers.update({"User-Agent": USER_AGENT, "Accept-Language": "en-GB,en;q=0.9"})
    return session


def fetch_club_info(session: requests.Session) -> dict:
    """Read the club id, its teams and its seasons off the club homepage.

    Pitchero is a Next.js site: every page carries a <script id="__NEXT_DATA__">
    tag holding the page's data as JSON. That is far more stable to read than
    the rendered HTML.
    """
    response = session.get(CLUB_URL, timeout=TIMEOUT)
    response.raise_for_status()

    match = re.search(
        r'<script id="__NEXT_DATA__" type="application/json">(.*?)</script>',
        response.text,
        re.S,
    )
    if not match:
        raise SystemExit(
            "Could not find the __NEXT_DATA__ block on the club page. "
            "Pitchero has probably changed how the site is built."
        )
    return json.loads(match.group(1))["props"]["pageProps"]["club"]


def pick_season(club: dict) -> dict:
    """Choose the season that is running today, else the most recent one."""
    seasons = club.get("seasons") or []
    if not seasons:
        raise SystemExit("The club page listed no seasons.")

    today = datetime.now(timezone.utc).date().isoformat()
    for season in seasons:
        if season["start"] <= today <= season["end"]:
            return season
    return max(seasons, key=lambda s: s["start"])


def find_teams(club: dict) -> list[dict]:
    """Match the team names in TEAMS_WANTED to their Pitchero team ids."""
    by_name = {
        team["name"].strip(): team
        for section in club.get("sections", [])
        for team in section.get("teams", [])
    }

    teams = []
    for wanted in TEAMS_WANTED:
        team = by_name.get(wanted)
        if team is None:
            print(
                f"WARNING: no team called {wanted!r} on the club site. "
                f"Teams found: {', '.join(sorted(by_name))}",
                file=sys.stderr,
            )
            continue
        teams.append(team)

    if not teams:
        raise SystemExit("None of the wanted teams were found — nothing to build.")
    return teams


def fetch_fixtures(session: requests.Session, club_id: int, team: dict, season_id: int) -> list[dict]:
    """Fetch one team's fixture list from Pitchero's page-data JSON endpoint."""
    url = f"https://www.pitchero.com/data/club/{club_id}/matches"
    params = {"teamId": team["id"], "seasonId": season_id}
    response = session.get(url, params=params, timeout=TIMEOUT)
    response.raise_for_status()

    fixtures = response.json().get("data", {}).get("matchFixtures", [])
    for fixture in fixtures:
        fixture["_team_name"] = team["name"]
        fixture["_club_id"] = club_id
    return fixtures


def dedupe(fixtures: list[dict]) -> list[dict]:
    """Drop repeats.

    Pitchero occasionally lists the same match twice under two different ids
    (a league re-import, usually). Same team, same day, same opponent, same
    home/away is treated as the same match.
    """
    seen: set[tuple] = set()
    unique = []
    for fixture in fixtures:
        key = (
            fixture["_team_name"],
            fixture["dateTime"][:10],
            fixture["opponent"],
            fixture["ha"],
        )
        if key in seen:
            continue
        seen.add(key)
        unique.append(fixture)
    return unique


# ---------------------------------------------------------------------------
# Turning fixtures into calendar events
# ---------------------------------------------------------------------------


def escape(text: str) -> str:
    """Escape a value for an iCalendar text field (RFC 5545 section 3.3.11)."""
    return (
        str(text)
        .replace("\\", "\\\\")
        .replace(";", "\\;")
        .replace(",", "\\,")
        .replace("\r\n", "\\n")
        .replace("\n", "\\n")
    )


def fold(line: str) -> str:
    """Wrap a long line to 75 octets, continuation lines starting with a space."""
    raw = line.encode("utf-8")
    if len(raw) <= 75:
        return line

    chunks, current = [], b""
    for char in line:
        encoded = char.encode("utf-8")
        limit = 75 if not chunks else 74  # continuation lines lose one to the space
        if len(current) + len(encoded) > limit:
            chunks.append(current)
            current = b""
        current += encoded
    chunks.append(current)
    return "\r\n ".join(chunk.decode("utf-8") for chunk in chunks)


def utc_stamp(moment: datetime) -> str:
    return moment.astimezone(timezone.utc).strftime("%Y%m%dT%H%M%SZ")


def match_centre_url(fixture: dict) -> str:
    return (
        f"https://www.pitchero.com/clubs/withycomberfc/teams/"
        f"{fixture['teamId']}/match-centre/{fixture['id']}"
    )


def build_event(fixture: dict, now: datetime) -> list[str]:
    """Build one VEVENT as a list of unfolded content lines."""
    kickoff_known = (fixture.get("kickoff") or "TBC").upper() != "TBC"
    start = datetime.fromisoformat(fixture["dateTime"])
    is_home = fixture["ha"] == "h"

    where = "H" if is_home else "A"
    title = f"{fixture['_team_name']} v {fixture['opponent']} ({where})"
    if not kickoff_known:
        # Pitchero stores an unconfirmed kick-off as midnight. Showing a match
        # at 00:00 would be worse than useless, so it becomes an all-day entry.
        title += " (KO TBC)"

    if is_home:
        location = HOME_GROUND
    elif fixture.get("location"):
        location = fixture["location"]
    else:
        location = f"Away at {fixture['opponent']}"

    description_bits = [fixture.get("type") or fixture.get("division") or "Fixture"]
    description_bits.append(
        f"Kick-off {fixture['kickoff']}" if kickoff_known else "Kick-off to be confirmed"
    )
    description_bits.append(match_centre_url(fixture))

    lines = [
        "BEGIN:VEVENT",
        f"UID:pitchero-{fixture['id']}-{fixture['teamId']}@withycomberfc",
        f"DTSTAMP:{utc_stamp(now)}",
    ]

    if kickoff_known:
        lines.append(f"DTSTART:{utc_stamp(start)}")
        lines.append(f"DTEND:{utc_stamp(start + MATCH_LENGTH)}")
    else:
        day = start.date()
        lines.append(f"DTSTART;VALUE=DATE:{day.strftime('%Y%m%d')}")
        lines.append(f"DTEND;VALUE=DATE:{(day + timedelta(days=1)).strftime('%Y%m%d')}")

    lines += [
        f"SUMMARY:{escape(title)}",
        f"LOCATION:{escape(location)}",
        f"DESCRIPTION:{escape(chr(10).join(description_bits))}",
        f"URL:{match_centre_url(fixture)}",
        "TRANSP:OPAQUE",
        "SEQUENCE:0",
        f"LAST-MODIFIED:{utc_stamp(now)}",
    ]
    if is_home:
        lines.append(f"GEO:{HOME_GEO}")
    lines.append("END:VEVENT")
    return lines


def build_calendar(fixtures: list[dict], name: str, description: str) -> str:
    now = datetime.now(timezone.utc)
    lines = [
        "BEGIN:VCALENDAR",
        "VERSION:2.0",
        "PRODID:-//withycombe-fixtures//Pitchero to iCalendar//EN",
        "CALSCALE:GREGORIAN",
        "METHOD:PUBLISH",
        f"X-WR-CALNAME:{escape(name)}",
        f"X-WR-CALDESC:{escape(description)}",
        "X-WR-TIMEZONE:Europe/London",
        # Hints to calendar apps about how often to re-check the feed.
        "REFRESH-INTERVAL;VALUE=DURATION:PT12H",
        "X-PUBLISHED-TTL:PT12H",
    ]
    for fixture in sorted(fixtures, key=lambda f: f["dateTime"]):
        lines += build_event(fixture, now)
    lines.append("END:VCALENDAR")

    return "\r\n".join(fold(line) for line in lines) + "\r\n"


# ---------------------------------------------------------------------------
# The landing page that sits next to the .ics files
# ---------------------------------------------------------------------------


def build_index(count: int, season_name: str, built: datetime) -> str:
    """Write the page people land on when they tap the tag or the link.

    Two routes, stated plainly, because they behave differently: a one-tap
    download that never changes again, and a proper subscription that does.
    The addresses are filled in by a few lines of JavaScript, since the page has
    no way of knowing where it is published until someone opens it.
    """
    teams = " and ".join(TEAMS_WANTED) if len(TEAMS_WANTED) < 3 else ", ".join(TEAMS_WANTED)
    return f"""<!doctype html>
<html lang="en">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>Withycombe RFC fixtures calendar</title>
<style>
  body {{ font-family: system-ui, -apple-system, "Segoe UI", sans-serif; margin: 0 auto;
         max-width: 34rem; padding: 2rem 1.25rem 3rem; line-height: 1.55; color: #14200f;
         background: #fbfbf8; }}
  h1 {{ color: #0d8e38; margin-bottom: .25rem; font-size: 1.6rem; }}
  h2 {{ font-size: 1.05rem; margin: 0 0 .2rem; }}
  .card {{ border: 1px solid #dcdcd2; border-radius: .6rem; padding: 1.1rem 1.2rem;
           margin: 1.1rem 0; background: #fff; }}
  .card.best {{ border-color: #0d8e38; border-width: 2px; }}
  .verdict {{ font-size: .85rem; font-weight: 600; margin: 0 0 .8rem; }}
  .yes {{ color: #0d6d2e; }}
  .no {{ color: #a3401a; }}
  .button {{ display: inline-block; background: #0d8e38; color: #fff; text-decoration: none;
             padding: .65rem 1.4rem; border-radius: .4rem; font-weight: 600; }}
  .button.grey {{ background: #55605a; }}
  ol {{ padding-left: 1.3rem; margin: .6rem 0 0; }}
  li {{ margin-bottom: .55rem; }}
  .address {{ display: flex; gap: .5rem; align-items: center; margin: .5rem 0 0; }}
  code {{ background: #f0f0e8; padding: .35rem .5rem; border-radius: .3rem; font-size: .8rem;
          word-break: break-all; flex: 1; }}
  button.copy {{ font: inherit; font-size: .8rem; padding: .35rem .7rem; border: 1px solid #b9bdb2;
                 background: #fff; border-radius: .3rem; cursor: pointer; white-space: nowrap; }}
  footer {{ color: #5b6157; font-size: .85rem; margin-top: 2rem; }}
</style>
</head>
<body>
  <h1>Withycombe RFC fixtures</h1>
  <p>{html.escape(teams)} fixtures for the {html.escape(season_name.strip())} &mdash;
     {count} matches, in one calendar.</p>

  <div class="card best">
    <h2>iPhone or iPad</h2>
    <p class="verdict yes">&#10003; Subscribes &mdash; updates itself when fixtures change</p>
    <p><a class="button" href="calendar.ics" data-subscribe="calendar.ics">Add to my calendar</a></p>
  </div>

  <div class="card best">
    <h2>Android &mdash; the proper way</h2>
    <p class="verdict yes">&#10003; Subscribes &mdash; updates itself when fixtures change</p>
    <p>Google Calendar can only take a subscription through its full desktop site. You
       can reach that on the phone &mdash; it just needs one setting turned on first.</p>
    <ol>
      <li>In <strong>Chrome</strong>, tap the <strong>&#8942;</strong> menu (top right) and
          tick <strong>Desktop site</strong>.</li>
      <li>Go to <strong>calendar.google.com</strong>. It will load small &mdash; pinch to
          zoom into the left-hand column.</li>
      <li>Scroll down that column to <strong>Other calendars</strong> and tap the
          <strong>+</strong> beside it.</li>
      <li>Choose <strong>From URL</strong>.</li>
      <li>Paste the address below, then tap <strong>Add calendar</strong>.
        <div class="address"><code id="feed">calendar.ics</code>
          <button class="copy" type="button" id="copy">Copy</button></div>
      </li>
      <li>Open the <strong>Google Calendar app</strong> &rarr; <strong>&#9776;</strong> &rarr;
          <strong>Settings</strong>, find <em>Withycombe RFC</em> in the list, and turn on
          <strong>Sync</strong>. New calendars arrive switched off, so this step is easy to
          miss and nothing shows without it.</li>
    </ol>
  </div>

  <div class="card">
    <h2>Android &mdash; the quick way</h2>
    <p class="verdict no">&#10007; Does <strong>not</strong> subscribe &mdash; a snapshot of
       today's fixtures that will never update</p>
    <p>Your phone will offer to add these fixtures to your calendar in one go. Fine if you
       just want the dates in front of you, but any later change at the club &mdash; a
       postponement, a kick-off time confirmed &mdash; will never reach you.</p>
    <p><a class="button grey" href="calendar.ics">Download the fixtures</a></p>
  </div>

  <footer>
    Built {built.strftime('%d %b %Y %H:%M')} UTC from the club's
    <a href="{CLUB_URL}">Pitchero site</a>. Unofficial &mdash; not run by the club.
  </footer>
<script>
  var base = location.href.replace(/[^/]*$/, "");
  // iPhone: webcal:// is what makes a calendar app subscribe rather than download.
  document.querySelectorAll("[data-subscribe]").forEach(function (link) {{
    link.href = (base + link.dataset.subscribe).replace(/^https?:/, "webcal:");
  }});
  // Google's "From URL" box wants the plain https:// address.
  var feed = document.getElementById("feed");
  feed.textContent = base + "calendar.ics";
  document.getElementById("copy").addEventListener("click", function () {{
    var self = this;
    navigator.clipboard.writeText(feed.textContent).then(function () {{
      self.textContent = "Copied";
      setTimeout(function () {{ self.textContent = "Copy"; }}, 2000);
    }}).catch(function () {{
      self.textContent = "Select it and copy";
    }});
  }});
</script>
</body>
</html>
"""


# ---------------------------------------------------------------------------


def main() -> int:
    session = get_session()

    club = fetch_club_info(session)
    season = pick_season(club)
    teams = find_teams(club)
    print(f"Club {club['name']} (id {club['id']}), season {season['name'].strip()} (id {season['id']})")

    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
    everything: list[dict] = []

    for team in teams:
        fixtures = dedupe(fetch_fixtures(session, club["id"], team, season["id"]))
        playable = [f for f in fixtures if not f.get("isCancelledOrPostponed")]
        dropped = len(fixtures) - len(playable)
        print(
            f"  {team['name']}: {len(playable)} fixtures"
            + (f" ({dropped} cancelled or postponed, left out)" if dropped else "")
        )
        everything += playable

    # One feed, holding every team listed in TEAMS_WANTED.
    (OUTPUT_DIR / "calendar.ics").write_text(
        build_calendar(everything, CALENDAR_NAME, CALENDAR_DESC), encoding="utf-8"
    )
    (OUTPUT_DIR / "index.html").write_text(
        build_index(len(everything), season["name"], datetime.now(timezone.utc)),
        encoding="utf-8",
    )

    print(f"Wrote calendar.ics ({len(everything)} fixtures) and index.html to {OUTPUT_DIR}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
