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
from .standings import MatchResult  # the official per-match result shape (reused)

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


# --------------------------------------------------------------------------- #
# Score sheet (scores.php) — the authoritative per-game grain for backfill.
# One table per game: game_type | home_player (team) | away_player (team), then
# RACE / # WINS / SCORE rows. Unlike the live board, it carries the GAME TYPE
# (8/9/10 ints, "10BP" for the BP variant) and each player's race target
# (needed for censored-count handling).
# --------------------------------------------------------------------------- #

_GAME_TYPE_RE = re.compile(r"(\d+)\s*-?\s*ball", re.IGNORECASE)
# A BP-variant game label ("10BP" / "10 BP" / "10-Ball BP") -> canonical
# "<n>BP" game_type (first real capture: 13986 week_02, 2026-06-11). Must be
# checked BEFORE the plain ball regex — "10-Ball BP" would otherwise be
# silently conflated with plain 10-ball.
_BP_GAME_RE = re.compile(r"\s*(\d{1,2})\s*(?:-?\s*ball\s*)?BP\b", re.IGNORECASE)
# The Felt-8-ball game label ("F8") -> canonical "F8" game_type, the played
# counterpart of the roster's csr_f8 rating (LC+F8 divisions, e.g. 10874). The
# bare "F8" cell misses the ball regex entirely, so it needs its own matcher.
_F8_GAME_RE = re.compile(r"^\s*F8\b", re.IGNORECASE)
_NAME_TEAM_RE = re.compile(r"^(.*?)\s*\((.+)\)\s*$")
_SHEET_DATE_RE = re.compile(r"([A-Z][a-z]{2})\.?\s+(\d{1,2}),\s*(\d{4})")


@dataclass(frozen=True)
class ScoreGame:
    game_type: int | str            # 8 / 9 / 10 as ints; "10BP"/"F8" text variants
    home_player: str
    home_team: str
    away_player: str
    away_team: str
    home_race: int | None
    away_race: int | None
    home_wins: int | None
    away_wins: int | None

    @property
    def home_won(self) -> bool | None:
        if self.home_wins is None or self.home_race is None or self.away_race is None:
            return None
        if self.home_wins >= self.home_race:
            return True
        if self.away_wins is not None and self.away_wins >= self.away_race:
            return False
        return None  # incomplete


@dataclass
class ScoreSheet:
    home_team: str
    away_team: str
    date: str | None
    games: list[ScoreGame] = field(default_factory=list)


def _name_team(text: str) -> tuple[str, str]:
    m = _NAME_TEAM_RE.match(text)
    return (m.group(1).strip(), m.group(2).strip()) if m else (text.strip(), "")


def parse_score_sheet(html: str) -> ScoreSheet:
    soup = BeautifulSoup(html, "lxml")
    tables = soup.find_all("table")

    matchup_home = matchup_away = ""
    date = None
    games: list[ScoreGame] = []

    for table in tables:
        rows = [[c.get_text(" ", strip=True) for c in tr.find_all(["td", "th"])]
                for tr in table.find_all("tr")]
        if not rows:
            continue
        first = rows[0]
        # matchup header "TeamA vs. TeamB". Collapse internal whitespace runs:
        # the raw header can carry a double space ("Alex  I mean Robert") that the
        # roster grid normalizes away, which otherwise breaks the team-name match
        # in load_score_sheets and leaves every game of that match unlinked.
        if len(first) == 1 and " vs" in first[0].lower() and not games and not matchup_home:
            parts = re.split(r"\s+vs\.?\s+", first[0], maxsplit=1, flags=re.IGNORECASE)
            if len(parts) == 2:
                matchup_home = re.sub(r"\s+", " ", parts[0]).strip()
                matchup_away = re.sub(r"\s+", " ", parts[1]).strip()
            continue
        if len(first) == 1 and _SHEET_DATE_RE.search(first[0]) and date is None:
            date = _sheet_date(first[0])
            continue
        # game table: first row is [game_type, home_player(team), away_player(team)].
        # BP and F8 variants FIRST — their labels miss the plain ball regex
        # ("10-Ball BP" would otherwise read as plain 10-ball; "F8" not at all).
        bp = _BP_GAME_RE.match(first[0]) if first and first[0] else None
        f8 = None if bp else (_F8_GAME_RE.match(first[0]) if first and first[0] else None)
        gt = None if (bp or f8) else (_GAME_TYPE_RE.match(first[0]) if first else None)
        if (bp or f8 or gt) and len(first) >= 3:
            by_label = {r[0].upper(): r[1:] for r in rows if r and r[0]}
            hp, ht = _name_team(first[1])
            ap, at = _name_team(first[2])
            race = by_label.get("RACE", [])
            wins = by_label.get("# WINS", by_label.get("WINS", []))
            games.append(ScoreGame(
                game_type=(f"{bp.group(1)}BP" if bp else
                           "F8" if f8 else int(gt.group(1))),
                home_player=hp, home_team=ht, away_player=ap, away_team=at,
                home_race=_int(race[0]) if len(race) > 0 else None,
                away_race=_int(race[1]) if len(race) > 1 else None,
                home_wins=_int(wins[0]) if len(wins) > 0 else None,
                away_wins=_int(wins[1]) if len(wins) > 1 else None,
            ))
    return ScoreSheet(home_team=matchup_home, away_team=matchup_away, date=date, games=games)


def _sheet_date(text: str) -> str | None:
    m = _SHEET_DATE_RE.search(text)
    if not m or m.group(1) not in _MONTHS:
        return None
    return f"{m.group(3)}-{_MONTHS[m.group(1)]:02d}-{int(m.group(2)):02d}"


def parse_score_sheet_file(path) -> ScoreSheet:
    return parse_score_sheet(read_source(path))


def parse_week_index(html: str) -> list[str]:
    """From a standings_weekly_scores.php?week=N page, the 'view score sheet'
    links -> score-sheet (scores.php) URLs (one per team; dedup at load)."""
    soup = BeautifulSoup(html, "lxml")
    seen, urls = set(), []
    for a in soup.find_all("a", href=True):
        href = a["href"]
        if "scores.php" in href and href not in seen:
            seen.add(href)
            urls.append(href)
    return urls


_ROUND_RE = re.compile(r"Round\s+(\d+)\s+Scores", re.IGNORECASE)
_MATCH_PTS_RE = re.compile(r"(\d+)\s*\(\s*match\s*points\s*\)", re.IGNORECASE)


def parse_week_results(html: str) -> list[MatchResult]:
    """The official match-POINT results printed on a standings_weekly_scores.php
    page (the totals shown next to each team, e.g. "48 (match points)") — the
    outcome layer that lives on the SAME page we already fetch for sheet URLs.

    Each match is two consecutive team rows; we pair them in listed order and
    leave home/away orientation to be resolved against the schedule at load
    time. The page can carry more than one round (makeups land under their own
    "Round N Scores" header on an off-schedule date), so the round/date are
    tracked from the section headers as we walk, not assumed from the week.
    A genuinely-unplayed match shows 0/0 here; that is faithfully parsed (the
    load step decides 0-0 means "not played", not the parser)."""
    soup = BeautifulSoup(html, "lxml")
    results: list[MatchResult] = []
    cur_round: int | None = None
    cur_date: str | None = None
    pair: list[tuple[str, int]] = []

    def flush() -> None:
        nonlocal pair
        if len(pair) == 2 and cur_round is not None:
            (t1, p1), (t2, p2) = pair
            results.append(MatchResult(cur_round, cur_date, t1, p1, t2, p2))
        pair = []

    for tr in soup.find_all("tr"):
        cells = tr.find_all(["td", "th"])
        text = tr.get_text(" ", strip=True)
        rm = _ROUND_RE.search(text)
        if rm:                                   # "Round N Scores" section header
            flush()
            cur_round, cur_date = int(rm.group(1)), None
            continue
        if len(cells) == 1 and "match points" not in text.lower():
            dm = _sheet_date(text)               # the section's play-date header
            if dm:
                cur_date = dm
            continue
        pm = _MATCH_PTS_RE.search(text)
        if pm and tr.find("a", href=re.compile("scores.php")):
            name = cells[0].get_text("|", strip=True).split("|")[0].strip()
            pair.append((name, int(pm.group(1))))
            if len(pair) == 2:
                flush()
            continue
        flush()                                  # spacer / unrelated row = boundary
    flush()
    return results


def parse_week_results_file(path) -> list[MatchResult]:
    return parse_week_results(read_source(path))
