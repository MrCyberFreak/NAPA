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
_DIVISION_LINK_RE = re.compile(r"division\.php\?did=(\d+)")


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
    divisions: list[int] = field(default_factory=list)  # Active Divisions: dids


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


def _parse_divisions(soup: BeautifulSoup) -> list[int]:
    """'Active Divisions:' anchors — one division.php?did=N link per current
    division. De-duplicated, document order preserved."""
    seen: set[int] = set()
    divisions: list[int] = []
    for a in soup.find_all("a", href=True):
        m = _DIVISION_LINK_RE.search(a["href"])
        if not m:
            continue
        did = int(m.group(1))
        if did not in seen:
            seen.add(did)
            divisions.append(did)
    return divisions


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
        divisions=_parse_divisions(soup),
    )


def parse_profile_file(path) -> Profile:
    from .roster import read_source  # reuse the .mht/.html loader
    return parse_profile(read_source(path))


# --------------------------------------------------------------------------- #
# MAIN tab: dated CueSpeed ratings (current + peak per game).
# --------------------------------------------------------------------------- #

_RATING_RE = re.compile(r"(\d+)\s*\(([A-Z][a-z]{2})\s+(\d{1,2}),\s*(\d{4})\)")
_GAME_LABEL_RE = re.compile(r"^(8|9|10)-Ball:", re.IGNORECASE)
_MONTHS = {"Jan": 1, "Feb": 2, "Mar": 3, "Apr": 4, "May": 5, "Jun": 6,
           "Jul": 7, "Aug": 8, "Sep": 9, "Oct": 10, "Nov": 11, "Dec": 12}


def _mon_date(mon: str, day: str, year: str) -> str | None:
    return f"{year}-{_MONTHS[mon]:02d}-{int(day):02d}" if mon in _MONTHS else None


@dataclass
class CueSpeed:
    # game -> (rating, as_of ISO date)
    current: dict[int, tuple[int, str | None]] = field(default_factory=dict)
    peak: dict[int, tuple[int, str | None]] = field(default_factory=dict)


def parse_cuespeed(html: str) -> CueSpeed:
    """MAIN tab -> current + HIGHEST (peak) CueSpeed per game, each dated."""
    soup = BeautifulSoup(html, "lxml")
    cs = CueSpeed()
    target: dict | None = None
    for tr in soup.find_all("tr"):
        cells = [c.get_text(" ", strip=True) for c in tr.find_all(["td", "th"])]
        cells = [c for c in cells if c]
        if not cells:
            continue
        head = cells[0].upper()
        if "HIGHEST CUESPEED RATINGS" in head:
            target = cs.peak
            continue
        if "CUESPEED RATINGS" in head:
            target = cs.current
            continue
        if target is None or len(cells) < 2:
            continue
        gm = _GAME_LABEL_RE.match(cells[0])
        vm = _RATING_RE.search(cells[1])
        if gm and vm:
            target[int(gm.group(1))] = (int(vm.group(1)),
                                        _mon_date(vm.group(2), vm.group(3), vm.group(4)))
    return cs


# --------------------------------------------------------------------------- #
# TRENDS tab: lifetime + last-10 + 30/60/90-day form (the form term).
# --------------------------------------------------------------------------- #

@dataclass
class TrendForm:
    lifetime_played: int | None = None
    lifetime_w: int | None = None
    lifetime_l: int | None = None
    lifetime_win_pct: int | None = None
    avg_ppm: float | None = None
    last10_w: int | None = None
    last10_l: int | None = None
    last10_win_pct: int | None = None
    last10_assessment: str | None = None
    d30: tuple[int, int, int] | None = None   # (played, w, l)
    d60: tuple[int, int, int] | None = None
    d90: tuple[int, int, int] | None = None


def _section(text: str, start: str, *ends: str) -> str:
    i = text.find(start)
    if i < 0:
        return ""
    j = len(text)
    for e in ends:
        k = text.find(e, i + len(start))
        if k >= 0:
            j = min(j, k)
    return text[i:j]


def parse_trends(html: str) -> TrendForm:
    text = re.sub(r"\s+", " ", BeautifulSoup(html, "lxml").get_text(" ", strip=True))
    f = TrendForm()

    life = _section(text, "LIFETIME STATS", "LAST 10")
    if life:
        m = re.search(r"Matches Played:\s*(\d+)", life);  f.lifetime_played = int(m.group(1)) if m else None
        m = re.search(r"Match Record:\s*(\d+)\s*wins?\s*-?\s*(\d+)\s*loss", life)
        if m: f.lifetime_w, f.lifetime_l = int(m.group(1)), int(m.group(2))
        m = re.search(r"Win %:\s*(\d+)%", life);  f.lifetime_win_pct = int(m.group(1)) if m else None
        m = re.search(r"AvgPPM:\s*([\d.]+)", life);  f.avg_ppm = float(m.group(1)) if m else None

    l10 = _section(text, "LAST 10 MATCHES", "LAST 30")
    if l10:
        m = re.search(r"Match Record:\s*(\d+)\s*wins?\s*-?\s*(\d+)\s*loss", l10)
        if m: f.last10_w, f.last10_l = int(m.group(1)), int(m.group(2))
        m = re.search(r"Win %:\s*(\d+)%", l10);  f.last10_win_pct = int(m.group(1)) if m else None
        m = re.search(r"Assessment:\s*(.+?)(?:\s*LAST|\s*©|$)", l10)
        if m: f.last10_assessment = m.group(1).strip()

    for tag, attr, nxt in (("LAST 30 DAYS", "d30", "LAST 60"),
                           ("LAST 60 DAYS", "d60", "LAST 90"),
                           ("LAST 90 DAYS", "d90", "©")):
        sec = _section(text, tag, nxt)
        if sec:
            played = re.search(r"Matches Played:\s*(\d+)", sec)
            rec = re.search(r"Match Record:\s*(\d+)\s*wins?\s*-?\s*(\d+)\s*loss", sec)
            if played and rec:
                setattr(f, attr, (int(played.group(1)), int(rec.group(1)), int(rec.group(2))))
    return f


# --------------------------------------------------------------------------- #
# Deep tabs (JS/AJAX-loaded via stats.php?...&xTab=N). The harvest captures
# RIVALS (xTab=5; drill per rival via &rival=<id>), H2H (12), TRENDS (33).
# --------------------------------------------------------------------------- #

_RIVAL_LINK_RE = re.compile(r"playerID=(\d{8})[^\"']*?rival=(\d{8})")
_WL_RE = re.compile(r"(\d+)\s*-\s*(\d+)")


@dataclass(frozen=True)
class Rival:
    rival_id: str
    name: str


def parse_profile_rivals(html: str) -> tuple[str | None, list[Rival]]:
    """RIVALS tab -> (subject player_id, lifetime opponents). Each rival row is a
    drill-down link stats.php?...&playerID=<subject>&rival=<rival_id>. This is the
    pairing-graph densifier; rival_id is the canonical 8-digit key."""
    soup = BeautifulSoup(html, "lxml")
    subject: str | None = None
    seen: set[str] = set()
    rivals: list[Rival] = []
    for a in soup.find_all("a", href=True):
        m = _RIVAL_LINK_RE.search(a["href"])
        if not m:
            continue
        subject = m.group(1)
        rid = m.group(2)
        if rid in seen:
            continue
        seen.add(rid)
        rivals.append(Rival(rival_id=rid, name=a.get_text(" ", strip=True)))
    return subject, rivals


_RIVAL_GAME_RE = re.compile(
    r"(8|9|10)-BALL MATCHES\s+Played\s+(\d+)\s+matches?\s+"
    r"Won the lag:\s+(\d+)\s+times?\s+Record\s+(\d+)\s+wins?\s*-\s*(\d+)\s+loss",
    re.IGNORECASE)


def parse_rival_h2h(html: str) -> dict[int, tuple[int, int, int, int]]:
    """Rival drill-down (xTab=5&rival=<id>) -> per-game lifetime H2H:
    {game: (matches_played, lags_won, wins, losses)} for 8/9/10-ball."""
    text = re.sub(r"\s+", " ", BeautifulSoup(html, "lxml").get_text(" ", strip=True))
    out: dict[int, tuple[int, int, int, int]] = {}
    for m in _RIVAL_GAME_RE.finditer(text):
        g = int(m.group(1))
        if g not in out:  # first (canonical) block per game
            out[g] = (int(m.group(2)), int(m.group(3)), int(m.group(4)), int(m.group(5)))
    return out


@dataclass
class H2HSummary:
    total_matches: int | None = None
    wins: int | None = None
    losses: int | None = None
    win_pct: int | None = None
    per_game: dict[int, tuple[int, int]] = field(default_factory=dict)  # game -> (w, l)


def parse_h2h_summary(html: str) -> H2HSummary:
    """H2H tab -> overall meetings, record, win%, and per-game W-L."""
    soup = BeautifulSoup(html, "lxml")
    text_rows = [r.get_text(" | ", strip=True) for t in soup.find_all("table")
                 for r in t.find_all("tr")]
    blob = "\n".join(text_rows)
    s = H2HSummary()
    m = re.search(r"Total H2H Matches.*?\b(\d+)\b", blob, re.DOTALL)
    if m:
        s.total_matches = int(m.group(1))
    m = re.search(r"H2H W-L Record\D+(\d+)\s*-\s*(\d+)", blob, re.DOTALL)
    if m:
        s.wins, s.losses = int(m.group(1)), int(m.group(2))
    m = re.search(r"H2H Win %\D+(\d+)%", blob, re.DOTALL)
    if m:
        s.win_pct = int(m.group(1))
    for g in (8, 9, 10):
        m = re.search(rf"{g}-ball H2H W-L\D+(\d+)\s*-\s*(\d+)", blob, re.DOTALL)
        if m:
            s.per_game[g] = (int(m.group(1)), int(m.group(2)))
    return s
