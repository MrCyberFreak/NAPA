"""Standings parsers (poolshooters standings_* pages).

- parse_team_record  <- standings_teams_record.php : a TEAM's full-season
  weekly match results (both teams' match points each week). One page per team;
  summing match points across loaded pages gives the standings table.
- parse_team_players <- standings_teams.php : a team's per-player season stats
  (POINTS / SL / SM / REC / WIN%) for the player-enrichment layer.

Teams use SHORT names ("Ed's Balls (Felt Billiards)"); the loader resolves them
to canonical roster teams by prefix. Canonical player key stays the 8-digit id
(joined by name; these pages don't carry the 8-digit id directly).
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field

from bs4 import BeautifulSoup

from .roster import read_source

_MONTHS = {
    "Jan": 1, "Feb": 2, "Mar": 3, "Apr": 4, "May": 5, "Jun": 6,
    "Jul": 7, "Aug": 8, "Sep": 9, "Oct": 10, "Nov": 11, "Dec": 12,
}
_WEEK_RE = re.compile(r"Week\s+(\d+):")
_DATE_RE = re.compile(r"([A-Z][a-z]{2})\.?\s+(\d{1,2}),\s*(\d{4})")


def _short_team(text: str) -> str:
    return re.sub(r"\s*\(.*\)\s*$", "", text).strip()


def _date(text: str) -> str | None:
    m = _DATE_RE.search(text)
    if not m or m.group(1) not in _MONTHS:
        return None
    return f"{m.group(3)}-{_MONTHS[m.group(1)]:02d}-{int(m.group(2)):02d}"


def _int(text: str) -> int | None:
    m = re.search(r"\d+", text or "")
    return int(m.group()) if m else None


@dataclass(frozen=True)
class MatchResult:
    week: int
    date: str | None
    home: str
    home_points: int | None
    away: str
    away_points: int | None


@dataclass
class TeamRecord:
    team: str                       # the page's team (short name)
    results: list[MatchResult] = field(default_factory=list)


def parse_team_record(html: str) -> TeamRecord:
    soup = BeautifulSoup(html, "lxml")
    results: list[MatchResult] = []
    for table in soup.find_all("table"):
        rows = [[c.get_text(" ", strip=True) for c in tr.find_all(["td", "th"])]
                for tr in table.find_all("tr")]
        if not rows:
            continue
        wm = _WEEK_RE.search(rows[0][0] if rows[0] else "")
        if not wm:
            continue
        week, date = int(wm.group(1)), _date(rows[0][0])
        side = {}
        for r in rows[1:]:
            if len(r) >= 3 and r[0].upper() in ("HOME", "AWAY"):
                side[r[0].upper()] = (_short_team(r[1]), _int(r[2]))
        if "HOME" in side and "AWAY" in side:
            (ht, hp), (at, ap) = side["HOME"], side["AWAY"]
            results.append(MatchResult(week, date, ht, hp, at, ap))

    # The page's team is the one present in every result.
    teams = [{r.home, r.away} for r in results]
    common = set.intersection(*teams) if teams else set()
    team = next(iter(common)) if common else ""
    return TeamRecord(team=team, results=results)


def parse_team_record_file(path) -> TeamRecord:
    return parse_team_record(read_source(path))
