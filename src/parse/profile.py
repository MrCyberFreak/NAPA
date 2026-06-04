"""Player-profile parser — SUMMARY VIEW ONLY.

A plain GET of `stats.php?playerID=` yields only the summary: the header
(name, Shooter's ID, gender, home base, member-since, match counts) plus the
dated current CSRs and the highest-ever CSRs per game. The deep data (match
history, H2H, rivals) is JS-tab-loaded and needs a real browser — that is
Phase 6, NOT here.

Value of this parser: enrich the `players` table with demographics the roster
grid doesn't carry (gender / home_base / member_since), plus highest-ever CSR
per game for the scout-grid "form vs lifetime" drill-down.

NOTE: poolshooters.com's exact markup isn't captured yet (and the host is
bot-blocked — see Phase 4). This parser is label-tolerant and pinned to a
synthetic fixture; tune against a real capture when one lands.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field

from bs4 import BeautifulSoup

_PLAYER_ID_RE = re.compile(r"(?<!\d)(\d{8})(?!\d)")
_GAME_TOKEN_RE = re.compile(r"\b(8|9|10)\s*-?\s*ball\b", re.IGNORECASE)
_DATE_RE = re.compile(r"\d{4}-\d{2}-\d{2}")
_INT_RE = re.compile(r"\d+")


@dataclass
class Profile:
    player_id: str | None
    name: str | None
    gender: str | None = None
    home_base: str | None = None
    member_since: str | None = None
    matches_played: int | None = None
    as_of: str | None = None
    current_csr: dict[int, int] = field(default_factory=dict)   # {8:.,9:.,10:.}
    highest_csr: dict[int, int] = field(default_factory=dict)


def _labeled(lines: list[str], *labels: str) -> str | None:
    """Return the value following any of the given labels (e.g. 'Gender: Male')."""
    pat = re.compile(
        r"^\s*(?:" + "|".join(re.escape(l) for l in labels) + r")\s*[:\-]\s*(.+?)\s*$",
        re.IGNORECASE,
    )
    for line in lines:
        m = pat.match(line)
        if m:
            return m.group(1).strip()
    return None


def _parse_csr_rows(soup: BeautifulSoup) -> tuple[dict[int, int], dict[int, int], str | None]:
    """Per-game current/highest CSR + the 'as of' date.

    Looks for table rows whose first content is a game token (N-Ball); the two
    integers in the row are read as (current, highest), and any ISO date as the
    'as of'. Falls back to scanning text lines if there is no table.
    """
    current: dict[int, int] = {}
    highest: dict[int, int] = {}
    as_of: str | None = None

    def consume(game: int, text: str) -> None:
        nonlocal as_of
        nums = [int(n) for n in _INT_RE.findall(re.sub(r"\d+\s*-?\s*ball", "", text, flags=re.IGNORECASE))]
        if nums:
            current[game] = nums[0]
        if len(nums) > 1:
            highest[game] = nums[1]
        d = _DATE_RE.search(text)
        if d and as_of is None:
            as_of = d.group(0)

    rows = soup.find_all("tr")
    handled = False
    for tr in rows:
        text = tr.get_text(" ", strip=True)
        m = _GAME_TOKEN_RE.search(text)
        if m:
            consume(int(m.group(1)), text)
            handled = True
    if not handled:
        for line in soup.get_text("\n").splitlines():
            m = _GAME_TOKEN_RE.search(line)
            if m:
                consume(int(m.group(1)), line)
    return current, highest, as_of


def parse_profile(html: str) -> Profile:
    soup = BeautifulSoup(html, "lxml")
    lines = [re.sub(r"\s+", " ", l.strip()) for l in soup.get_text("\n").splitlines() if l.strip()]

    full_text = " ".join(lines)
    id_label = _labeled(lines, "Shooter's ID", "Shooters ID", "ID")
    id_m = _PLAYER_ID_RE.search(id_label or "") or _PLAYER_ID_RE.search(full_text)
    player_id = id_m.group(1) if id_m else None

    name = None
    h = soup.find(["h1", "h2"])
    if h and h.get_text(strip=True):
        name = h.get_text(strip=True)
    name = _labeled(lines, "Name") or name

    matches = _labeled(lines, "Matches Played", "Match Count", "Matches")
    matches_played = int(_INT_RE.search(matches).group()) if matches and _INT_RE.search(matches) else None

    current, highest, as_of = _parse_csr_rows(soup)

    return Profile(
        player_id=player_id,
        name=name,
        gender=_labeled(lines, "Gender", "Sex"),
        home_base=_labeled(lines, "Home Base", "Home"),
        member_since=_labeled(lines, "Member Since", "Member"),
        matches_played=matches_played,
        as_of=as_of,
        current_csr=current,
        highest_csr=highest,
    )


def parse_profile_file(path) -> Profile:
    from .roster import read_source  # reuse the .mht/.html loader
    return parse_profile(read_source(path))
