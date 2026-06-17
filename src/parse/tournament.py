"""Per-player career TOURNAMENT-MATCHES parser (napaleagues.com stats.php tab 24).

SOURCE: a rendered profile page for the Tournaments > "View All" tab —
    stats.php?playerSelected=Y&playerID=<8-digit>&xTab=24&start=<N>
The page is JS/AJAX rendered (so the input is a browser capture, never a plain
GET — see CLAUDE.md hard rules); the harvester archives each paginated page to
data/raw/profiles/<id>/match_24_<start>.html (the SAME naming + NEXT>>> &start
pagination the league tabs use — so capture is decoupled and this build is
PARSE + LOAD only, no fetch/harvest changes).

GRAIN: one row per career tournament-bracket match for the subject (the profile
owner). A DIFFERENT structure from the league match_history tabs (2/3/4) and
from `games` (this-season score-sheet grain): tournament matches are league-wide,
span a player's whole career across NAPA national/regional events (many off-NoCo,
never seen by the division scrape), carry hometowns + tournament_name/event, and
LACK division_id / venue / CSR-at-time. Its OWN table, like match_history.

This is NOT parsed by parse_match_history(): that league parser EXPLICITLY
excludes tab 24 (its _is_match_table discriminator is style="width:950px" + 3
<th>, which tournament tables do NOT have). Only next_start_from_html() is shared
(it is already tab-agnostic). A naive "all .table-bordered" walk would
double-count every match — each match also has a hidden modal table with the same
players/RACE/SCORE rows; the bgcolor=002664 tournament-name banner row is the
discriminator that keeps the visible match table and excludes the player-info
header, the aggregate-summary table, AND the nested modal.

Each match renders as its OWN <table class="table table-bordered"> with rows:
  row0 (bgcolor 002664, colspan 3): TOURNAMENT NAME (a <strong>)
  row1 (bgcolor 002664, colspan 3): EVENT + "Played: <weekday>, <Mon DD, YYYY>" (<small>)
  row2 (bgcolor EEEEEE): subject "Name<br><small>City, State</small>" | "vs." | opponent
  row3: <left race> | RACE | <right race>
  row4: SCORE row, each side <font color="red">(LOST)</font> / <font color="green">(WON)</font>
  row5: "[more match details]" modal link (IGNORED)

The SUBJECT is the profile owner (the playerID anchor / <h2> name); it may be the
LEFT or the RIGHT side of row2 — match the owner name to a side like
match_history does, never assume left=subject. result/scores are stored from the
SUBJECT's perspective.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field

from bs4 import BeautifulSoup

from .match_history import (_clean, _subject_id_from_page,
                            _subject_name_from_page, _to_int,
                            next_start_from_html)

# EVENT TOKEN -> game_type, mirroring the games/skill_snapshots convention (ints
# for plain ball games, text tokens for variants). The page has no per-game stat
# row, so game_type is derived from the event text. An UNKNOWN token after
# normalization RAISES (mirrors the CLAUDE.md grid-header rule — catch a new event
# type, never silently NULL it).
_EVENT_GAME_TYPE: dict[str, int | str] = {
    "8-BALL": 8, "9-BALL": 9, "10-BALL": 10, "7-BALL": 7,
    "FAST 8": "Fast8", "LAGGER'S CHOICE": "LC",
    # Pro variants — keep the same text tokens as match_history's TAB_GAME_TYPE
    # ("9BP" = 9-Ball Pro, "10BP" = 10-Ball Pro) so the schema stays consistent.
    "9-BALL PRO": "9BP", "10-BALL PRO": "10BP",
}

# Long tournament date: "Played: Saturday, Aug 09, 2025" -> month abbrev, day,
# 4-digit year. DISTINCT from match_history's "Apr. 30 '26" short form. The
# weekday word is consumed but ignored.
_PLAYED_RE = re.compile(
    r"Played:\s*[A-Za-z]+,\s*([A-Za-z]{3})\s+(\d{1,2}),\s*(\d{4})")
_MONTHS = {"Jan": 1, "Feb": 2, "Mar": 3, "Apr": 4, "May": 5, "Jun": 6,
           "Jul": 7, "Aug": 8, "Sep": 9, "Oct": 10, "Nov": 11, "Dec": 12}

# Aggregate-summary regexes (first page only — absent on start>0 pages).
_SUM_TOTAL = re.compile(r"TOURNAMENT MATCHES:\s*(\d+)")
_SUM_WINS = re.compile(r"TOURNAMENT MATCH WINS:\s*(\d+)")
_SUM_LOSSES = re.compile(r"TOURNAMENT MATCH LOSSES:\s*(\d+)")
_SUM_PCT = re.compile(r"TOURNAMENT WIN %:\s*([\d.]+)")

_SOURCE_TAB = 24


@dataclass(frozen=True)
class TournamentMatch:
    """One career tournament match from the subject's perspective. Mirrors the
    tournament_matches schema columns. Player ids are NOT resolved here — the
    subject id is passed in (the profile owner) and the opponent is a raw name
    (an out-of-scope tournament player with no `players` row). Only the
    natural-key columns (played_date, tournament_name, opponent_name, event_name)
    are required; every other column is None-able so a name-variant row is KEPT,
    not dropped."""
    subject_player_id: str | None
    played_date: str | None        # ISO yyyy-mm-dd
    tournament_name: str | None     # row0, e.g. "2025 NAPA CUESPEED MILE HIGH TRIFECTA"
    opponent_name: str | None       # the non-subject side's name (key column)
    event_name: str | None          # row1 lead text, e.g. "OPEN 8-BALL CHAMPIONSHIP"
    game_type: int | str | None     # 8/9/10/7 or "Fast8"/"LC" from the event text
    subject_name: str | None        # subject side display name (row2)
    subject_location: str | None    # subject side "City, State" (<small>)
    opponent_location: str | None   # opponent side "City, State" (<small>)
    subject_side: str | None        # 'home' (left) / 'away' (right); None when neither
    result: str | None              # 'W' / 'L' from the SUBJECT's perspective
    subject_race: int | None        # RACE row, subject side
    opp_race: int | None            # RACE row, opponent side
    subject_score: int | None       # SCORE row, subject side
    opp_score: int | None           # SCORE row, opponent side
    source_tab: int                 # provenance: xTab (24)
    source_start: int               # provenance: pagination &start of the page
    page_index: int                 # provenance: 0-based position WITHIN the page


@dataclass
class TournamentPage:
    """One harvested page: the subject id, the matches on it (document order =
    reverse-chronological), the next page's &start (None on the last page), and
    the once-per-profile aggregate summary (only present on start=0)."""
    subject_player_id: str | None
    source_tab: int
    source_start: int
    matches: list[TournamentMatch] = field(default_factory=list)
    next_start: int | None = None
    summary: dict | None = None


def _parse_played_date(text: str) -> str | None:
    """\"Played: Saturday, Aug 09, 2025\" -> '2025-08-09'."""
    m = _PLAYED_RE.search(text or "")
    if not m:
        return None
    mon = m.group(1).title()
    if mon not in _MONTHS:
        return None
    return f"{m.group(3)}-{_MONTHS[mon]:02d}-{int(m.group(2)):02d}"


def _game_type_from_event(event: str | None) -> int | str | None:
    """Derive game_type from the event string. Strip a leading division qualifier
    (OPEN/LADIES/SENIORS), an optional table qualifier (BAR BOX / BIG TABLE), and a
    trailing CHAMPIONSHIP, then map the remaining token. An unmapped token RAISES
    (a new event type must be caught, not silently NULLed)."""
    if not event:
        return None
    token = event.upper().strip()
    token = re.sub(r"^(OPEN|LADIES|SENIORS)\s+", "", token)
    token = re.sub(r"^(BAR BOX|BIG TABLE)\s+", "", token)
    token = re.sub(r"\s+CHAMPIONSHIP$", "", token).strip()
    if token not in _EVENT_GAME_TYPE:
        raise ValueError(f"unknown tournament event game-type token {token!r} "
                         f"(from event {event!r})")
    return _EVENT_GAME_TYPE[token]


def _is_match_table(table) -> bool:
    """A table is a tournament-match record iff it contains a <tr bgcolor=002664>
    (the tournament-name banner). This cleanly excludes the player-info header
    (no 002664), the aggregate-summary table (BB133E/b4f596 rows), and the hidden
    per-match MODAL table (EEEEEE/DDDDDD/red/green rows, NEVER 002664)."""
    return table.find("tr", bgcolor=re.compile("002664", re.I)) is not None


def _cell_name_location(cell) -> tuple[str | None, str | None]:
    """A player cell is \"Name<br><small>City, State</small>\". Split the <small>
    (hometown) off the name. Caller passes a CLONE, so extracting the <small> here
    is safe. Either field may be None/absent."""
    small = cell.find("small")
    location = (_clean(small) or None) if small is not None else None
    if small is not None:
        small.extract()  # mutate the clone so the name read excludes the hometown
    name = _clean(cell) or None
    return name, location


def _parse_summary(soup: BeautifulSoup) -> dict | None:
    """The aggregate block (TOURNAMENT MATCHES/WINS/LOSSES/WIN %) — only on the
    first page (start=0); absent on later pages. Scans the b4f596 rows."""
    text = " ".join(_clean(tr) for tr in soup.find_all("tr", bgcolor="b4f596"))
    if not text:
        return None
    total = _SUM_TOTAL.search(text)
    wins = _SUM_WINS.search(text)
    losses = _SUM_LOSSES.search(text)
    pct = _SUM_PCT.search(text)
    if not (total or wins or losses or pct):
        return None
    return {
        "total": int(total.group(1)) if total else None,
        "wins": int(wins.group(1)) if wins else None,
        "losses": int(losses.group(1)) if losses else None,
        "win_pct": float(pct.group(1)) if pct else None,
    }


def _parse_match_table(table, subject_id: str | None, subject_name: str | None,
                       source_start: int, page_index: int) -> TournamentMatch:
    # Dispatch on bgcolor / label, NOT a fixed row index (parse defensively).
    tournament_name: str | None = None
    event_name: str | None = None
    played_date: str | None = None
    left_name = right_name = None
    left_location = right_location = None
    left_race = right_race = None
    left_score = right_score = None
    left_color = right_color = None

    for tr in table.find_all("tr", recursive=False) or table.find_all("tr"):
        bg = (tr.get("bgcolor") or "").upper()
        cells = tr.find_all("td", recursive=False)
        if not cells:
            continue

        if bg == "002664":
            # row0 has a <strong> (tournament name); row1 has NO <strong> (event).
            if cells[0].find("strong") is not None:
                tournament_name = _clean(cells[0]) or None
            else:
                small = cells[0].find("small")
                if small is not None:
                    played_date = _parse_played_date(_clean(small))
                    # event = the td text BEFORE the <small>; strip the small off
                    # a clone so the original (and any sibling parse) is untouched.
                    clone = BeautifulSoup(str(cells[0]), "lxml")
                    for s in clone.find_all("small"):
                        s.extract()
                    event_name = _clean(clone) or None
                else:
                    event_name = _clean(cells[0]) or None
            continue

        if len(cells) < 3:
            continue
        center = _clean(cells[1]).upper()

        if center == "VS.":
            # row2: players. Operate on clones so the <small> extract is local.
            lc = BeautifulSoup(str(cells[0]), "lxml")
            rc = BeautifulSoup(str(cells[2]), "lxml")
            left_name, left_location = _cell_name_location(lc)
            right_name, right_location = _cell_name_location(rc)
        elif center == "RACE":
            left_race = _to_int(_clean(cells[0]))
            right_race = _to_int(_clean(cells[2]))
        elif center == "SCORE":
            left_score = _to_int(_clean(cells[0]))
            right_score = _to_int(_clean(cells[2]))
            lf = cells[0].find("font")
            rf = cells[2].find("font")
            left_color = (lf.get("color") or "").lower() if lf is not None else None
            right_color = (rf.get("color") or "").lower() if rf is not None else None

    game_type = _game_type_from_event(event_name)

    # Which side is the subject? Match the profile-owner display name.
    subject_side: str | None = None
    if subject_name:
        if left_name == subject_name:
            subject_side = "home"
        elif right_name == subject_name:
            subject_side = "away"

    # Order by subject when known; default to left so the row is still keyed/kept.
    if subject_side == "away":
        subj_name, subj_loc = right_name, right_location
        opp_name, opp_loc = left_name, left_location
        subj_race, opp_race_v = right_race, left_race
        subj_score, opp_score_v = right_score, left_score
        subj_color = right_color
    else:
        subj_name, subj_loc = left_name, left_location
        opp_name, opp_loc = right_name, right_location
        subj_race, opp_race_v = left_race, right_race
        subj_score, opp_score_v = left_score, right_score
        subj_color = left_color

    # Result from the SUBJECT's perspective: green=won, red=lost. Fall back to
    # subject_score vs subject_race when a color is missing. None when side unknown.
    result: str | None = None
    if subject_side is not None:
        if subj_color == "green":
            result = "W"
        elif subj_color == "red":
            result = "L"
        elif subj_score is not None and subj_race is not None:
            result = "W" if subj_score >= subj_race else "L"

    return TournamentMatch(
        subject_player_id=subject_id, played_date=played_date,
        tournament_name=tournament_name, opponent_name=opp_name,
        event_name=event_name, game_type=game_type,
        subject_name=subj_name, subject_location=subj_loc,
        opponent_location=opp_loc, subject_side=subject_side, result=result,
        subject_race=subj_race, opp_race=opp_race_v,
        subject_score=subj_score, opp_score=opp_score_v,
        source_tab=_SOURCE_TAB, source_start=source_start, page_index=page_index,
    )


def parse_tournament(html: str, *, source_start: int = 0
                     ) -> tuple[str | None, TournamentPage]:
    """Parse ONE harvested tournaments (xTab=24) page.

    Returns (subject_player_id, TournamentPage). The page carries the matches
    (document order = newest first), next_start (the NEXT>>> &start, or None on
    the last page), and the once-per-profile aggregate summary (only on start=0).
    """
    soup = BeautifulSoup(html, "lxml")
    subject_id = _subject_id_from_page(soup)
    subject_name = _subject_name_from_page(soup)

    matches = [
        _parse_match_table(t, subject_id, subject_name, source_start, page_index)
        for page_index, t in
        enumerate(t for t in soup.find_all("table") if _is_match_table(t))
    ]
    page = TournamentPage(
        subject_player_id=subject_id, source_tab=_SOURCE_TAB,
        source_start=source_start, matches=matches,
        next_start=next_start_from_html(html), summary=_parse_summary(soup),
    )
    return subject_id, page


def parse_tournament_file(path) -> tuple[str | None, TournamentPage]:
    """File entrypoint. The &start is recovered from the filename
    `match_24_<start>.html` (the harvest naming); falls back to 0."""
    from pathlib import Path

    from .roster import read_source

    p = Path(path)
    source_start = 0
    m = re.match(r"match_24_(\d+)$", p.stem)
    if m:
        source_start = int(m.group(1))
    return parse_tournament(read_source(p), source_start=source_start)
