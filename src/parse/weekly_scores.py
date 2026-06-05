"""Live-scores parser -> per-game (race) results (the `games` grain).

Source: scores.playpool.io/livescores.php (fixture: live_scores.mht). The page
has two parts:
- Matchup header tables (HOME/AWAY team) for the CURRENT week (often no games yet).
- Per-game DETAIL tables for the most recent played games, one per table:
    PLAYERS | SL | GM | TM | RC | G1..G11 | TRUN | SNAP
  with two player rows (home, away), a 'W' in each rack column the player won,
  RC='W' marking the race winner, and a trailing date row.

Each detail table is ONE game (a race of racks) between a home and away player.
The two rounds can differ (headers = upcoming, details = last played), so we do
NOT pair header<->detail; team/round come from the players + the game date.

Players here are a SUPERSET of the roster (subs play) — the canonical key is the
8-digit playerID, resolved by NAME downstream; rows are kept regardless.
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
_DATE_RE = re.compile(r"([A-Z][a-z]{2})\.?\s+(\d{1,2}),\s*(\d{4})")


@dataclass(frozen=True)
class PlayerLine:
    player: str
    sl: int | None          # per-game CueSpeed for the game played
    racks_won: int
    is_race_winner: bool


@dataclass(frozen=True)
class Game:
    date: str | None        # ISO yyyy-mm-dd
    home: PlayerLine
    away: PlayerLine

    @property
    def home_won(self) -> bool:
        # RC='W' marks the race winner; fall back to the rack count.
        if self.home.is_race_winner != self.away.is_race_winner:
            return self.home.is_race_winner
        return self.home.racks_won >= self.away.racks_won


def _parse_date(text: str) -> str | None:
    m = _DATE_RE.search(text)
    if not m or m.group(1) not in _MONTHS:
        return None
    return f"{m.group(3)}-{_MONTHS[m.group(1)]:02d}-{int(m.group(2)):02d}"


def _int(text: str) -> int | None:
    m = re.search(r"-?\d+", text or "")
    return int(m.group()) if m else None


def _is_detail_header(cells: list[str]) -> bool:
    up = [c.upper() for c in cells]
    return "PLAYERS" in up and "G1" in up


def _col_index(cells: list[str], label: str) -> int | None:
    up = [c.upper() for c in cells]
    return up.index(label) if label in up else None


def parse_live_scores(html: str) -> list[Game]:
    soup = BeautifulSoup(html, "lxml")
    games: list[Game] = []
    for table in soup.find_all("table"):
        rows = [
            [re.sub(r"\s+", " ", c.get_text(" ", strip=True)) for c in tr.find_all(["td", "th"])]
            for tr in table.find_all("tr")
        ]
        if not rows or not _is_detail_header(rows[0]):
            continue

        header = rows[0]
        name_i = _col_index(header, "PLAYERS")
        sl_i = _col_index(header, "SL")
        rc_i = _col_index(header, "RC")
        g_cols = [i for i in (_col_index(header, f"G{k}") for k in range(1, 12)) if i is not None]

        date = None
        players: list[PlayerLine] = []
        for r in rows[1:]:
            joined = " ".join(r).strip()
            if not joined:
                continue
            # the trailing date row is a single dated cell with no player name
            if (len(r) <= 2 or not (r[name_i] if name_i is not None and name_i < len(r) else "")) \
                    and _parse_date(joined):
                date = _parse_date(joined)
                continue
            name = r[name_i] if name_i is not None and name_i < len(r) else ""
            if not name or not re.search(r"[A-Za-z]", name):
                continue
            rack_wins = [
                (r[i].strip().upper() == "W") if i < len(r) else False for i in g_cols
            ]
            players.append(PlayerLine(
                player=name,
                sl=_int(r[sl_i]) if sl_i is not None and sl_i < len(r) else None,
                racks_won=sum(rack_wins),
                is_race_winner=(rc_i is not None and rc_i < len(r) and r[rc_i].strip().upper() == "W"),
            ))

        if len(players) < 2:
            continue
        games.append(Game(date=date, home=players[0], away=players[1]))
    return games


def parse_live_scores_file(path) -> list[Game]:
    return parse_live_scores(read_source(path))
