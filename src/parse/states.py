"""states.php parser — the league-discovery page.

`poolshooters.com/states.php?location=Colorado` lists every active division,
grouped by NAPA franchise under `<h4 class="text-white">GROUP</h4>` header rows.
Each division is a pair of `<tr>`s:

    <tr><td><strong>Division Standings: 14050</strong></td></tr>
    <tr><td><a href="division.php?did=14050">Thursday "Big Table Felt" No Limit LC </a></td></tr>

NAPA mints a NEW division-id every season, so this page is how we notice a
rollover (13077 -> 14050) or a brand-new league. We track ONLY the
`NAPA of Northern Colorado` group; El Paso (`NAPA of the Rockies 2.0`) and
`Mesa NAPA` are out of scope and excluded here.

The `slug` is the STABLE logical-league key (`weekday-venue-gameset`) that
survives a did rollover — both 13077 and its successor 14050 normalize to
`thursday-big-table-felt-lc`. The gameset token (`lc`/`8ball`/...) is
load-bearing: three NoCo venues host an LC and an 8-ball division on the same
night, and the token is the only thing that keeps their slugs distinct.

Best-effort: a malformed row is skipped, never raised on — the caller guards on
the row COUNT (0 NoCo rows on a non-challenge page => the group header changed).
"""

from __future__ import annotations

import re
from dataclasses import dataclass, asdict

from bs4 import BeautifulSoup

from .roster import read_source  # reuse the .mht/.html loader

# The only league group we track. Pinned verbatim to the states.php h4 header;
# if NAPA renames it, parse_states returns 0 rows and the caller alerts.
NOCO_GROUP = "NAPA of Northern Colorado"

_STANDINGS_RE = re.compile(r"Division Standings:\s*(\d+)")
_DIVISION_HREF_RE = re.compile(r"division\.php\?did=(\d+)")
# "Weekday "Venue" Fmt words" — the trailing fmt may carry a trailing space.
_NAME_RE = re.compile(r'^(?P<weekday>\w+)\s+"(?P<venue>[^"]*)"\s+(?P<fmt>.*)$')


@dataclass(frozen=True)
class StatesRow:
    did: int
    name: str               # raw division label, e.g. 'Thursday "Big Table Felt" No Limit LC'
    slug: str               # stable logical-league key (weekday-venue-gameset)
    weekday: str | None     # "Thursday" (None if the label didn't parse)
    venue: str | None       # "Big Table Felt"
    gameset: str            # "lc" | "8ball" | "9ball" | "10ball"
    group: str              # league group header (always NOCO_GROUP for emitted rows)

    def to_dict(self) -> dict:
        return asdict(self)


def _slugify(text: str) -> str:
    """Lowercase, drop apostrophes (Pharaoh's -> pharaohs), collapse any run of
    non-alphanumerics to a single '-', trim leading/trailing '-'."""
    text = text.lower().replace("'", "").replace("’", "")
    return re.sub(r"[^a-z0-9]+", "-", text).strip("-")


def _gameset(fmt: str) -> str:
    """The game-set token from the division's format words. Play-type words
    ("No Limit", "Standard Limit", "Singles", "Scotch Doubles") carry no ball
    token, so they fall through to the LC default — no explicit strip needed."""
    f = fmt.lower()
    if "10-ball" in f or "10ball" in f:
        return "10ball"
    if "9-ball" in f or "9ball" in f:
        return "9ball"
    if "8-ball" in f or "8ball" in f:
        return "8ball"
    return "lc"


def slug_from_states_name(name: str) -> str:
    """Normalize a states.php division label to its stable slug. Best-effort —
    an unrecognized shape slugifies the whole label rather than raising, so a
    one-off malformed row can't crash discovery."""
    name = re.sub(r"\s+", " ", name).strip()
    m = _NAME_RE.match(name)
    if not m:
        return _slugify(name)
    return f"{m.group('weekday').lower()}-{_slugify(m.group('venue'))}-{_gameset(m.group('fmt'))}"


def _row(did: int, name: str, group: str) -> StatesRow:
    name = re.sub(r"\s+", " ", name).strip()
    m = _NAME_RE.match(name)
    if m:
        weekday, venue = m.group("weekday"), m.group("venue")
        gameset = _gameset(m.group("fmt"))
        slug = f"{weekday.lower()}-{_slugify(venue)}-{gameset}"
    else:
        weekday = venue = None
        gameset = "lc"
        slug = _slugify(name)
    return StatesRow(did=did, name=name, slug=slug, weekday=weekday,
                     venue=venue, gameset=gameset, group=group)


def parse_states(html: str) -> list[StatesRow]:
    """Every NAPA of Northern Colorado division on the page, in listed order.

    Walks the table rows tracking the active `<h4>` group; a division emits only
    while the active group is NOCO_GROUP. Each division's did is read from BOTH
    the "Division Standings: <did>" header and the division.php link — they must
    agree (a drift guard against a structural change); a row whose dids disagree,
    or that can't be paired, is skipped rather than guessed.
    """
    soup = BeautifulSoup(html, "lxml")
    rows: list[StatesRow] = []
    active_group: str | None = None
    pending_did: int | None = None

    for tr in soup.find_all("tr"):
        h4 = tr.find("h4")
        if h4 is not None:                       # group header row
            active_group = h4.get_text(strip=True)
            pending_did = None
            continue
        sm = _STANDINGS_RE.search(tr.get_text(" ", strip=True))
        if sm:                                   # "Division Standings: <did>"
            pending_did = int(sm.group(1))
            continue
        a = tr.find("a", href=_DIVISION_HREF_RE)
        if a is None:
            continue
        href_did = int(_DIVISION_HREF_RE.search(a["href"]).group(1))
        if pending_did is not None and pending_did != href_did:
            pending_did = None                   # drift — header/link disagree, skip
            continue
        pending_did = None
        if active_group == NOCO_GROUP:
            rows.append(_row(href_did, a.get_text(" ", strip=True), active_group))
    return rows


def parse_states_file(path) -> list[StatesRow]:
    return parse_states(read_source(path))
