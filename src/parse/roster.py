"""Roster-grid parser — the single best source in the system.

One fetch of `roster_grid.php` yields the entire division's current per-game
CSR ratings + player IDs. The grid is organized as team blocks delimited by
`#`-prefixed header rows:

    # <team name> ... CSR  8 - 9 - 10  SM

followed by one row per player:

    rownum, name, (C) captain flag, 8-digit playerID, CSR "8 / 9 / 10", SM count

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

# A team header looks like "# <name> ... CSR 8 - 9 - 10 SM". Team names can
# themselves contain '#' (e.g. "Cheat Code Felt Billiards #6"), so we anchor on
# the leading '#' AND require the "CSR" column marker to avoid false positives.
_TEAM_HEADER_RE = re.compile(r"^#\s*(?P<team>.+?)\s+CSR\b", re.IGNORECASE)

# An 8-digit player ID, not part of a longer run of digits.
_PLAYER_ID_RE = re.compile(r"(?<!\d)(\d{8})(?!\d)")

# Captain marker "(C)" (tolerant of spacing/case).
_CAPTAIN_RE = re.compile(r"\(\s*[Cc]\s*\)")

# CSR triple rendered as "8 / 9 / 10".
_CSR_TRIPLE_RE = re.compile(r"(\d{1,4})\s*/\s*(\d{1,4})\s*/\s*(\d{1,4})")

_ANY_INT_RE = re.compile(r"\d+")


@dataclass(frozen=True)
class RosterPlayer:
    team: str
    player: str
    player_id: str
    csr_8: int
    csr_9: int
    csr_10: int
    session_matches: int | None
    is_captain: bool

    def to_dict(self) -> dict:
        return asdict(self)

    @property
    def spread(self) -> int:
        """Max-minus-min across the three games — the key scouting signal."""
        vals = (self.csr_8, self.csr_9, self.csr_10)
        return max(vals) - min(vals)


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


def _match_team_header(text: str) -> str | None:
    m = _TEAM_HEADER_RE.match(text)
    return m.group("team").strip() if m else None


def _match_player_row(cells: list[str], current_team: str | None) -> RosterPlayer | None:
    if current_team is None:
        return None
    joined = " ".join(cells).strip()
    id_m = _PLAYER_ID_RE.search(joined)
    if not id_m:
        return None
    player_id = id_m.group(1)

    after_id = joined.split(player_id, 1)[1]
    nums_after = [int(n) for n in _ANY_INT_RE.findall(after_id)]

    triple = _CSR_TRIPLE_RE.search(after_id)
    if triple:
        csr_8, csr_9, csr_10 = (int(g) for g in triple.groups())
    elif len(nums_after) >= 3:
        csr_8, csr_9, csr_10 = nums_after[0:3]
    else:
        # An 8-digit number with no three trailing ratings is not a player row.
        return None

    session_matches = nums_after[3] if len(nums_after) >= 4 else None
    is_captain = bool(_CAPTAIN_RE.search(joined))

    # Name = the text before the player ID, minus the row number and captain mark.
    before_id = joined.split(player_id, 1)[0]
    before_id = _CAPTAIN_RE.sub(" ", before_id)
    before_id = re.sub(r"^\s*\d+\s+", "", before_id)  # drop leading row number
    name = re.sub(r"\s+", " ", before_id).strip(" .,-")

    if not name:
        return None

    return RosterPlayer(
        team=current_team,
        player=name,
        player_id=player_id,
        csr_8=csr_8,
        csr_9=csr_9,
        csr_10=csr_10,
        session_matches=session_matches,
        is_captain=is_captain,
    )


def parse_roster(html: str) -> list[RosterPlayer]:
    """Parse roster-grid HTML into a flat list of players (team carried down)."""
    soup = BeautifulSoup(html, "lxml")
    players: list[RosterPlayer] = []
    current_team: str | None = None
    for cells in _logical_rows(soup):
        text = " ".join(cells).strip()
        if not text:
            continue
        team = _match_team_header(text)
        if team is not None:
            current_team = team
            continue
        player = _match_player_row(cells, current_team)
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
