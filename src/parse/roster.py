"""Roster-grid parser — the single best source in the system.

One fetch of `roster_grid.php` yields the entire division's current per-game
CSR ratings + player IDs. The grid is organized as team blocks delimited by
`#`-prefixed header rows:

    # <team name> ... CSR  8 - 9 - 10  SM

followed by one row per player:

    rownum, name, (C) captain flag, 8-digit playerID, CSR "8 / 9 / 10", SM count

The CSR header column is AUTHORITATIVE for the division's game set (B1 recon
+ 14022 onboarding): "CSR 8 - 9 - 10" (3-game LC), bare "CSR" (8-ball-only),
"CSR 9 - 10" (2-game DP), "CSR 8 - 9 - 10 - 10BP" (4-game LC with the 10BP
variant, 14022). A row's dash-separated values map positionally onto the
declared games; undeclared games are None. A value-count/header mismatch or an
unknown game token RAISES — never guess (positional guessing is how a 2-game
row's SM gets swallowed as a rating).

CRITICAL parsing rules (from the build plan):
- Segment teams on the `#` header rows; take EVERY player row until the next
  header. Real team sizes are 7–11 — NEVER assume 8 per team.
- The 8-digit player ID is the reliable anchor for a player row.
- Players seen here are a subset of all players (subs appear only in results),
  so the loader must not constrain other tables to roster membership.
"""

from __future__ import annotations

import email
import re
from dataclasses import dataclass, asdict
from email import policy
from pathlib import Path

from bs4 import BeautifulSoup

# A team header looks like "# <name> ... CSR <games> SM". Team names can
# themselves contain '#' (e.g. "Cheat Code Felt Billiards #6"), so we anchor on
# the leading '#' AND require the "CSR" column marker to avoid false positives.
# What follows "CSR" declares the division's game set — the shapes seen in B1
# recon + onboarding (the header row repeats per team block, so it travels
# with the team segmentation for free). Game tokens may carry a letter suffix
# ("10BP"); tokens are validated against the known set, unknown ones RAISE:
#     "CSR 8 - 9 - 10"        -> games ("8", "9", "10")          3-game LC (13077, 13985)
#     "CSR"                   -> games ("8",)                    8-ball-only (13298)
#     "CSR 9 - 10"            -> games ("9", "10")               2-game DP (13744)
#     "CSR 8 - 9 - 10 - 10BP" -> games ("8", "9", "10", "10BP")  4-game LC (14022)
#     "CSR 8 - 9 - 10 - F8"    -> games ("8", "9", "10", "F8")    4-game LC+F8 (10874)
#     "CSR 9 - 10 - F8"        -> games ("9", "10", "F8")         3-game DP+F8 (10993)
#     "CSR 9 - 10 - 7B"        -> games ("9", "10", "7B")         3-game +7-ball (11297)
# An OLD (pre-2024) grid DASH-joins the SM column into the CSR header
# ("CSR 8 - 9 - 10 - SM") and into each player's CSR run ("50 - 53 - 56 - 18");
# the optional `smjoin` group flags that so the row parser splits SM off the run
# instead of mistaking it for an extra game (historical-session backfill, 10102).
# Modern grids SPACE-separate SM ("CSR 8 - 9 - 10  SM"), which `smjoin` ignores.
# A game token is digit-first ("8", "10", "10BP") OR letter-first ("F8", the
# Felt-8-ball rating carried by the Zoosters/Piazza "LC+F8" divisions).
_GAME_TOK = r"(?:\d{1,2}[A-Za-z]{0,3}|[A-Za-z]{1,3}\d{1,2})"
_TEAM_HEADER_RE = re.compile(
    r"^#\s*(?P<team>.+?)\s+CSR(?![A-Za-z])\s*"
    rf"(?P<games>{_GAME_TOK}(?:\s*[-/]\s*{_GAME_TOK})*)?"
    r"(?P<smjoin>\s*[-/]\s*SM\b)?",
    re.IGNORECASE,
)

# Canonical game labels the system knows how to store (RosterPlayer fields,
# skill_snapshots columns). A header token outside this set is a NEW division
# format: capture -> fixture -> deliberate extension, never a silent skip.
_GAME_TOKEN_RE = re.compile(_GAME_TOK)
_KNOWN_GAMES = ("8", "9", "10", "10BP", "F8", "7B")

# An 8-digit player ID, not part of a longer run of digits.
_PLAYER_ID_RE = re.compile(r"(?<!\d)(\d{8})(?!\d)")

# Captain marker "(C)" (tolerant of spacing/case).
_CAPTAIN_RE = re.compile(r"\(\s*[Cc]\s*\)")

# A row's CSR run: dash-separated values on the live grid ("95 - 79 - 81"),
# slash-separated in some views ("95 / 79 / 81"), a bare "90" on single-game
# grids. The run's length is validated against the header's declared games;
# the standalone number AFTER the run is the SM column.
_CSR_RUN_RE = re.compile(r"\d{1,4}(?:\s*[-/]\s*\d{1,4})*")

_ANY_INT_RE = re.compile(r"\d+")


@dataclass(frozen=True)
class RosterPlayer:
    team: str
    player: str
    player_id: str
    csr_8: int | None  # None when the division's grid doesn't declare the game
    csr_9: int | None
    csr_10: int | None
    session_matches: int | None
    is_captain: bool
    # Defaulted (last): only some grids declare these extra games (10BP on 14022;
    # F8 on the Zoosters/Piazza LC+F8 divisions; 7B on Piazza Tuesday 11297).
    # Keyword-built RosterPlayers elsewhere keep working without them.
    csr_10bp: int | None = None
    csr_f8: int | None = None
    csr_7b: int | None = None

    def to_dict(self) -> dict:
        return asdict(self)

    @property
    def spread(self) -> int | None:
        """Max-minus-min across the rated games — the key scouting signal.

        None when fewer than two games carry a rating (8-ball-only grids):
        a single-game player has no cross-game spread.
        """
        vals = [v for v in (self.csr_8, self.csr_9, self.csr_10,
                            self.csr_10bp, self.csr_f8, self.csr_7b)
                if v is not None]
        if len(vals) < 2:
            return None
        return max(vals) - min(vals)


@dataclass(frozen=True)
class _TeamHeader:
    """A parsed `#` header row: team name + the declared CSR game set
    (canonical uppercase labels, e.g. ("8", "9", "10", "10BP"))."""
    team: str
    games: tuple[str, ...]
    text: str  # raw row text, kept for mismatch error messages
    sm_in_run: bool = False  # old grids dash-join SM into the CSR run/header


# --------------------------------------------------------------------------- #
# Source loading (handles both saved .mht/.mhtml and plain .html fixtures)
# --------------------------------------------------------------------------- #

def _decode_mhtml(raw: bytes) -> str:
    """Extract the (largest) text/html part from a saved MHTML page."""
    msg = email.message_from_bytes(raw, policy=policy.default)
    htmls = [
        part.get_content()
        for part in msg.walk()
        if part.get_content_type() == "text/html"
    ]
    if htmls:
        return max(htmls, key=len)
    return raw.decode("utf-8", errors="replace")


def read_source(path: str | Path) -> str:
    """Read a fixture/archive file to HTML text, decoding MHTML when needed."""
    p = Path(path)
    raw = p.read_bytes()
    is_mhtml = p.suffix.lower() in {".mht", ".mhtml"} or (
        b"MIME-Version" in raw[:1024] and b"multipart/related" in raw[:1024]
    )
    if is_mhtml:
        return _decode_mhtml(raw)
    return raw.decode("utf-8", errors="replace")


# --------------------------------------------------------------------------- #
# Parsing
# --------------------------------------------------------------------------- #

def _logical_rows(soup: BeautifulSoup) -> list[list[str]]:
    """Reduce the page to a list of rows, each a list of cell texts.

    Prefers real table rows; falls back to text lines for non-tabular layouts.
    """
    trs = soup.find_all("tr")
    if trs:
        rows = []
        for tr in trs:
            cells = [
                re.sub(r"\s+", " ", c.get_text(" ", strip=True))
                for c in tr.find_all(["td", "th"])
            ]
            rows.append(cells)
        return rows
    text = soup.get_text("\n")
    return [[re.sub(r"\s+", " ", line.strip())] for line in text.splitlines() if line.strip()]


def _match_team_header(text: str) -> _TeamHeader | None:
    m = _TEAM_HEADER_RE.match(text)
    if m is None:
        return None
    raw = m.group("games")
    # Bare "CSR" (no game list) is the 8-ball-only shape: one 8-ball rating.
    games = tuple(t.upper() for t in _GAME_TOKEN_RE.findall(raw)) if raw else ("8",)
    if len(set(games)) != len(games) or any(g not in _KNOWN_GAMES for g in games):
        raise ValueError(f"unrecognized CSR game set in roster team header: {text!r}")
    return _TeamHeader(team=m.group("team").strip(), games=games, text=text,
                       sm_in_run=bool(m.group("smjoin")))


def _match_player_row(cells: list[str], header: _TeamHeader | None) -> RosterPlayer | None:
    if header is None:
        return None
    joined = " ".join(cells).strip()
    id_m = _PLAYER_ID_RE.search(joined)
    if not id_m:
        return None
    player_id = id_m.group(1)

    after_id = joined.split(player_id, 1)[1]
    run = _CSR_RUN_RE.search(after_id)
    if run is None:
        # An 8-digit number with no trailing ratings is not a player row.
        return None
    values = [int(n) for n in _ANY_INT_RE.findall(run.group(0))]

    # Old grids (pre-2024) dash-join the SM column into the CSR run
    # ("50 - 53 - 56 - 18" under a "CSR 8 - 9 - 10 - SM" header): the trailing
    # value is SM, not a fourth game. Split it off ONLY when the header declared
    # the dash-joined SM and the count is exactly one long — anything else still
    # RAISES (a real mismatch is corruption, never silently mapped).
    sm_from_run: int | None = None
    if header.sm_in_run and len(values) == len(header.games) + 1:
        sm_from_run = values[-1]
        values = values[:-1]

    if len(values) != len(header.games):
        # NEVER map positionally on a mismatch — that's exactly how a 2-game
        # row under a triple-shaped parser swallows the SM column as a rating.
        raise ValueError(
            f"roster row has {len(values)} CSR value(s) but the team header "
            f"declares {len(header.games)}: header {header.text!r}, row {joined!r}"
        )
    by_game = dict(zip(header.games, values))

    # SM stays its own column: the dash-joined trailing value (old grids) or the
    # first standalone number AFTER the CSR run (modern grids).
    if sm_from_run is not None:
        session_matches: int | None = sm_from_run
    else:
        sm_m = _ANY_INT_RE.search(after_id, run.end())
        session_matches = int(sm_m.group(0)) if sm_m else None
    is_captain = bool(_CAPTAIN_RE.search(joined))

    # Name = the text before the player ID, minus the row number and captain mark.
    before_id = joined.split(player_id, 1)[0]
    before_id = _CAPTAIN_RE.sub(" ", before_id)
    before_id = re.sub(r"^\s*\d+\s+", "", before_id)  # drop leading row number
    name = re.sub(r"\s+", " ", before_id).strip(" .,-")

    if not name:
        return None

    return RosterPlayer(
        team=header.team,
        player=name,
        player_id=player_id,
        csr_8=by_game.get("8"),
        csr_9=by_game.get("9"),
        csr_10=by_game.get("10"),
        csr_10bp=by_game.get("10BP"),
        csr_f8=by_game.get("F8"),
        csr_7b=by_game.get("7B"),
        session_matches=session_matches,
        is_captain=is_captain,
    )


def parse_roster(html: str) -> list[RosterPlayer]:
    """Parse roster-grid HTML into a flat list of players (team carried down)."""
    soup = BeautifulSoup(html, "lxml")
    players: list[RosterPlayer] = []
    current_header: _TeamHeader | None = None
    for cells in _logical_rows(soup):
        text = " ".join(cells).strip()
        if not text:
            continue
        header = _match_team_header(text)
        if header is not None:
            current_header = header
            continue
        player = _match_player_row(cells, current_header)
        if player is not None:
            players.append(player)
    return players


def parse_roster_file(path: str | Path) -> list[RosterPlayer]:
    return parse_roster(read_source(path))


def roster_summary(players: list[RosterPlayer]) -> dict:
    """Aggregate counts used for the regression guard (10 teams / 82 / sizes)."""
    team_sizes: dict[str, int] = {}
    captains: dict[str, int] = {}
    for p in players:
        team_sizes[p.team] = team_sizes.get(p.team, 0) + 1
        if p.is_captain:
            captains[p.team] = captains.get(p.team, 0) + 1
    return {
        "n_players": len(players),
        "n_teams": len(team_sizes),
        "team_sizes": team_sizes,
        "n_captains": sum(captains.values()),
        "captains_per_team": captains,
    }
