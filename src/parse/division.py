"""division.php parser — the League Portal overview page.

`poolshooters.com/division.php?did=N` renders one division's portal. The
overview table carries label/value `<tr>` pairs (all on one physical line):

    <tr><td ...><strong>Division ID:</strong></td>  <td ...>14050</td></tr>
    <tr><td ...><strong>Division Name:</strong></td><td ...>Thursday "Big Table Felt" No Limit LC League</td></tr>
    <tr><td ...><strong>Location:</strong></td>     <td ...>Englewood</td></tr>

This is the DISCOVERY probe. NAPA mints a new did every season and exposes NO
season/year URL param, so the only lever to find a league's PAST sessions is the
did integer itself: sweep the id space, read each division's NAME, and group by
the stable `slug` (weekday-venue-gameset, shared across a league's session-ids).

MISS detection: an invalid/empty did is NOT a 404 and NOT a bot-challenge — the
page renders the SAME template with the VALUE cells EMPTY. So a probe "resolved"
iff the Division Name value is non-empty (verified live: did 99999990 / did 1
render an empty name cell at ~19.7K bytes, indistinguishable from a real hit by
size alone — key on the empty field, never on length).

NoCo membership is decided by SLUG (slug in the curated NoCo slug set), NEVER by
Location: Location is a free-text city ("Englewood", "Whipple, Ohio"), useless
as a region filter.

Best-effort like states.py: a malformed/garbage page yields resolved=False (same
as a MISS — the sweep skips it), never raises.
"""

from __future__ import annotations

import re
from dataclasses import asdict, dataclass

from bs4 import BeautifulSoup

from .roster import read_source  # reuse the .mht/.html loader
from .states import slug_from_states_name  # the slug works on division.php names too


@dataclass(frozen=True)
class DivisionPage:
    did: int | None      # the echoed "Division ID:" value (cross-check vs the probed did)
    name: str            # "Division Name:" value; "" on a MISS / malformed page
    slug: str            # slug_from_states_name(name); "" when name == ""
    location: str        # "Location:" free-text city (audit field, NOT a region filter)
    resolved: bool       # bool(name) — THE miss detector

    def to_dict(self) -> dict:
        return asdict(self)


def _labeled_value(soup: BeautifulSoup, label: str) -> str:
    """Text of the `<td>` immediately after the `<td><strong>LABEL:</strong></td>`
    whose strong reads `label` (case-insensitive, trailing ':' ignored). '' when
    the label is absent or its value cell is empty (the MISS signal)."""
    for strong in soup.find_all("strong"):
        if strong.get_text(" ", strip=True).rstrip(":").strip().lower() != label:
            continue
        cell = strong.find_parent("td")
        if cell is None:
            continue
        val = cell.find_next_sibling("td")
        if val is None:
            continue
        return re.sub(r"\s+", " ", val.get_text(" ", strip=True)).strip()
    return ""


def parse_division(html: str) -> DivisionPage:
    soup = BeautifulSoup(html, "lxml")
    name = _labeled_value(soup, "division name")
    location = _labeled_value(soup, "location")
    m = re.search(r"\d+", _labeled_value(soup, "division id"))
    return DivisionPage(
        did=int(m.group()) if m else None,
        name=name,
        slug=slug_from_states_name(name) if name else "",
        location=location,
        resolved=bool(name),
    )


def parse_division_file(path) -> DivisionPage:
    return parse_division(read_source(path))
