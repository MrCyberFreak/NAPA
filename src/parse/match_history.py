"""Per-player career MATCH-HISTORY parser (poolshooters.com stats.php deep tab).

SOURCE: a rendered profile page for one of the per-game MATCH-HISTORY tabs —
    stats.php?playerSelected=Y&playerID=<8-digit>&xTab=<TAB>&start=<N>
    TAB 2 = league 8-ball, 3 = league 9-ball, 4 = league 10-ball.
The page is JS/AJAX rendered (so the input is a browser capture, never a plain
GET — see CLAUDE.md hard rules); browser_fetch.harvest_match_history archives
each paginated page to data/raw/profiles/<id>/match_<tab>_<start>.html.

GRAIN: one row per career match for the subject (the profile owner). RICHER than
the this-season `games` table — it carries the subject's CSR-at-match-time, the
makeup flag, the venue, and spans the player's WHOLE career across divisions
(including prior-season / non-NoCo dids the scrape set never sees).

Each match renders as its OWN <table>. A table IS a match record iff its first
<tr> carries the inline marker style="width:950px" AND has three <th> cells
(result, date, CSR). That discriminator cleanly excludes every other table on
the page (player-info header, the "LEAGUE 8-BALL MATCHES" banner, the season-
summary stats, the tournament-performance interstitial that sits BETWEEN match
tables, and the footer NEXT>>> link).

Parsing is LABEL-TOLERANT (dispatch on the first cell's normalized text, never a
fixed row index) — VENUE/DIVISION rows use a colspan=2 value cell while the stat
rows have three cells. Missing optional data yields None; only a truly
unparseable required token would raise. game_type comes from the TAB, not the
per-row stat label ('8-B'/'9-B'/'10-B').
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field

from bs4 import BeautifulSoup

# game_type per source tab — authoritative, NOT inferred from the page body.
TAB_GAME_TYPE = {2: 8, 3: 9, 4: 10}

_PLAYER_ID_RE = re.compile(r"playerID=(\d{8})")
_DIVISION_DID_RE = re.compile(r"division\.php\?did=(\d+)")
_CSR_RE = re.compile(r"CSR:\s*(\d+)")
_NEXT_START_RE = re.compile(r"[?&]start=(\d+)")
_INT_RE = re.compile(r"-?\d+")
# "Apr. 30 '26" -> month abbrev (with the dot in the token), day, 2-digit year.
_DATE_RE = re.compile(r"([A-Za-z]{3})\.?\s+(\d{1,2})\s*['’]\s*(\d{2})")

_MONTHS = {"Jan": 1, "Feb": 2, "Mar": 3, "Apr": 4, "May": 5, "Jun": 6,
           "Jul": 7, "Aug": 8, "Sep": 9, "Oct": 10, "Nov": 11, "Dec": 12}


@dataclass(frozen=True)
class MatchRow:
    """One career match from the subject's perspective. Mirrors the match_history
    schema columns. Player ids are NOT resolved here — the subject id is passed in
    (the profile owner) and the opponent is a raw name (may be a sub / out-of-scope
    player with no `players` row). All numeric fields are int|None."""
    subject_player_id: str | None
    game_type: int                 # 8 / 9 / 10 (from the tab)
    played_date: str | None        # ISO yyyy-mm-dd
    division_id: int | None        # leading int of the DIVISION row (may be off-scrape)
    division_name: str | None
    result: str | None             # 'W' / 'L' from the SUBJECT's perspective
    subject_csr: int | None        # subject's CSR at match time
    venue: str | None
    subject_side: str | None       # 'home' / 'away' / None (sub / name-variant)
    home_player_name: str | None
    away_player_name: str | None
    home_race: int | None
    away_race: int | None
    home_rl: str | None
    away_rl: str | None
    home_trun: int | None
    away_trun: int | None
    game_stat_home: int | None     # the '8-B'/'9-B'/'10-B' per-game stat
    game_stat_away: int | None
    home_wins: int | None          # "# WINS" = racks won
    away_wins: int | None
    home_score: int | None         # "SCORE" = match points
    away_score: int | None
    is_makeup: bool
    source_tab: int                # xTab (2/3/4)
    source_start: int              # pagination &start of the harvested page
    page_index: int                # 0-based position of this match table WITHIN the page

    @property
    def opponent_name(self) -> str | None:
        """The non-subject side's name (None when subject_side is unknown)."""
        if self.subject_side == "home":
            return self.away_player_name
        if self.subject_side == "away":
            return self.home_player_name
        return None


@dataclass
class MatchHistoryPage:
    """One harvested page: the subject id, the matches on it (document order =
    reverse-chronological), and the next page's &start (None on the last page)."""
    subject_player_id: str | None
    game_type: int
    source_tab: int
    source_start: int
    matches: list[MatchRow] = field(default_factory=list)
    next_start: int | None = None


def _clean(node) -> str:
    """Text of a node with <br> flattened to a space and whitespace collapsed."""
    return re.sub(r"\s+", " ", node.get_text(" ", strip=True)).strip()


def _to_int(text: str | None) -> int | None:
    if not text:
        return None
    m = _INT_RE.search(text)
    return int(m.group()) if m else None


def _parse_date(text: str) -> str | None:
    """\"Apr. 30 '26\" -> '2026-04-30'. Year is always 20YY in this data."""
    m = _DATE_RE.search(text or "")
    if not m:
        return None
    mon = m.group(1).title()
    if mon not in _MONTHS:
        return None
    return f"20{m.group(3)}-{_MONTHS[mon]:02d}-{int(m.group(2)):02d}"


def _is_match_table(table) -> bool:
    """A table is a match record iff its first <tr> carries the width:950px marker
    and has exactly three <th> cells (result / date / CSR header)."""
    first_tr = table.find("tr")
    if first_tr is None:
        return False
    style = (first_tr.get("style") or "").replace(" ", "")
    if "width:950px" not in style:
        return False
    return len(first_tr.find_all("th", recursive=False)) == 3


def _subject_id_from_page(soup: BeautifulSoup) -> str | None:
    """The profile owner's 8-digit id — first playerID= anchor on the page."""
    for a in soup.find_all("a", href=True):
        m = _PLAYER_ID_RE.search(a["href"])
        if m:
            return m.group(1)
    return None


def _subject_name_from_page(soup: BeautifulSoup) -> str | None:
    """The page-owner display name (player-info <h2>), e.g. 'Sam Trojanovich'."""
    h = soup.find(["h1", "h2"])
    return _clean(h) if h else None


def _next_start(soup: BeautifulSoup) -> int | None:
    """The NEXT>>> link's &start value (None when absent = last page)."""
    for a in soup.find_all("a", href=True):
        if a.get_text(strip=True).replace(" ", "").upper().startswith("NEXT"):
            m = _NEXT_START_RE.search(a["href"])
            if m:
                return int(m.group(1))
    return None


def _parse_match_table(table, subject_id: str | None, subject_name: str | None,
                       game_type: int, source_tab: int, source_start: int,
                       page_index: int) -> MatchRow:
    rows = table.find_all("tr")
    header = rows[0]
    ths = header.find_all("th", recursive=False)

    # th[0]: result letter (span text), bgcolor green/red as fallback.
    result = _clean(ths[0]) or None
    if result not in ("W", "L"):
        bg = (ths[0].get("bgcolor") or "").lower()
        result = "W" if bg == "green" else ("L" if bg == "red" else None)

    played_date = _parse_date(_clean(ths[1])) if len(ths) > 1 else None

    subject_csr = None
    if len(ths) > 2:
        m = _CSR_RE.search(_clean(ths[2]))
        if m:
            subject_csr = int(m.group(1))

    # Defaults for the by-label rows.
    venue = division_name = None
    division_id: int | None = None
    home_name = away_name = None
    is_makeup = False
    home_race = away_race = home_trun = away_trun = None
    home_rl = away_rl = None
    game_stat_home = game_stat_away = None
    home_wins = away_wins = home_score = away_score = None

    for tr in rows[1:]:
        cells = tr.find_all("td", recursive=False)
        if not cells:
            continue
        label = re.sub(r"[^A-Z0-9 ]", "", _clean(cells[0]).upper()).strip()
        # home = 2nd cell, away = 3rd cell (when present).
        c1 = cells[1] if len(cells) > 1 else None
        c2 = cells[2] if len(cells) > 2 else None

        if label == "VENUE":
            venue = _clean(c1) if c1 is not None else None
        elif label == "DIVISION":
            link = cells[1].find("a") if len(cells) > 1 else None
            strong = (link or cells[1] if len(cells) > 1 else None)
            text = _clean(strong) if strong is not None else ""
            lead = text.split(" ", 1)
            lead_did = int(lead[0]) if lead and lead[0].lstrip("-").isdigit() else None
            href_did = None
            if link is not None and link.get("href"):
                hm = _DIVISION_DID_RE.search(link["href"])
                if hm:
                    href_did = int(hm.group(1))
            # Prefer the href did; cross-check the leading integer.
            division_id = href_did if href_did is not None else lead_did
            division_name = lead[1].strip() if len(lead) > 1 else (text or None)
        elif label.startswith("MATCH"):
            is_makeup = cells[0].find("small") is not None and "(mm)" in _clean(cells[0])
            home_name = _clean(c1) if c1 is not None else None
            away_name = _clean(c2) if c2 is not None else None
        elif label == "RACE":
            home_race, away_race = _to_int(_clean(c1)) if c1 else None, _to_int(_clean(c2)) if c2 else None
        elif label == "RL":
            home_rl = _clean(c1) or None if c1 is not None else None
            away_rl = _clean(c2) or None if c2 is not None else None
        elif label == "TRUN":
            home_trun, away_trun = _to_int(_clean(c1)) if c1 else None, _to_int(_clean(c2)) if c2 else None
        elif re.fullmatch(r"\d+-?B", label):  # '8-B' / '9-B' / '10-B' (game-type stat)
            game_stat_home = _to_int(_clean(c1)) if c1 else None
            game_stat_away = _to_int(_clean(c2)) if c2 else None
        elif label == "WINS":  # "# WINS" after stripping the '#'
            home_wins, away_wins = _to_int(_clean(c1)) if c1 else None, _to_int(_clean(c2)) if c2 else None
        elif label == "SCORE":
            home_score, away_score = _to_int(_clean(c1)) if c1 else None, _to_int(_clean(c2)) if c2 else None

    # Which column is the subject? Match the profile-owner display name.
    subject_side: str | None = None
    if subject_name:
        if home_name == subject_name:
            subject_side = "home"
        elif away_name == subject_name:
            subject_side = "away"

    return MatchRow(
        subject_player_id=subject_id, game_type=game_type, played_date=played_date,
        division_id=division_id, division_name=division_name, result=result,
        subject_csr=subject_csr, venue=venue, subject_side=subject_side,
        home_player_name=home_name, away_player_name=away_name,
        home_race=home_race, away_race=away_race, home_rl=home_rl, away_rl=away_rl,
        home_trun=home_trun, away_trun=away_trun,
        game_stat_home=game_stat_home, game_stat_away=game_stat_away,
        home_wins=home_wins, away_wins=away_wins,
        home_score=home_score, away_score=away_score, is_makeup=is_makeup,
        source_tab=source_tab, source_start=source_start, page_index=page_index,
    )


def parse_match_history(html: str, *, game_type: int | None = None,
                        source_tab: int | None = None,
                        source_start: int = 0) -> tuple[str | None, MatchHistoryPage]:
    """Parse ONE harvested match-history page.

    game_type/source_tab come from the URL tab (NOT the page). Pass either:
    `source_tab` (2/3/4) and game_type is derived, or `game_type` (8/9/10) and
    source_tab is derived. Returns (subject_player_id, MatchHistoryPage). The page
    carries the matches (document order = newest first) and next_start (the NEXT>>>
    &start, or None on the last page).
    """
    if source_tab is None and game_type is None:
        raise ValueError("pass game_type (8/9/10) or source_tab (2/3/4)")
    if source_tab is None:
        # invert TAB_GAME_TYPE
        inv = {v: k for k, v in TAB_GAME_TYPE.items()}
        if game_type not in inv:
            raise ValueError(f"unsupported game_type {game_type!r}; scope is 8/9/10")
        source_tab = inv[game_type]
    if game_type is None:
        if source_tab not in TAB_GAME_TYPE:
            raise ValueError(f"unsupported source_tab {source_tab!r}; scope is 2/3/4")
        game_type = TAB_GAME_TYPE[source_tab]

    soup = BeautifulSoup(html, "lxml")
    subject_id = _subject_id_from_page(soup)
    subject_name = _subject_name_from_page(soup)

    rows = [
        _parse_match_table(t, subject_id, subject_name, game_type, source_tab,
                           source_start, page_index)
        for page_index, t in
        enumerate(t for t in soup.find_all("table") if _is_match_table(t))
    ]
    page = MatchHistoryPage(
        subject_player_id=subject_id, game_type=game_type, source_tab=source_tab,
        source_start=source_start, matches=rows, next_start=_next_start(soup),
    )
    return subject_id, page


def parse_match_history_file(path, *, game_type: int | None = None,
                             source_tab: int | None = None,
                             source_start: int | None = None) -> tuple[str | None, MatchHistoryPage]:
    """File entrypoint. When tab/start aren't given they are recovered from the
    filename `match_<tab>_<start>.html` (the harvest naming)."""
    from pathlib import Path

    from .roster import read_source

    p = Path(path)
    if source_tab is None or source_start is None:
        m = re.match(r"match_(\d+)_(\d+)", p.stem)
        if m:
            source_tab = source_tab if source_tab is not None else int(m.group(1))
            source_start = source_start if source_start is not None else int(m.group(2))
    if source_start is None:
        source_start = 0
    return parse_match_history(read_source(p), game_type=game_type,
                               source_tab=source_tab, source_start=source_start)
