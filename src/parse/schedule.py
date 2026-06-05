"""Schedule parser — print_schedule_v1.php -> per-round fixtures.

Real structure (verified against the browser-captured page):
- Round header rows: "Round: N  <Weekday>, <Mon>. DD, YYYY" (+ optional status note
  like "LAST CHANCE FOR ROSTER CHANGES").
- A column-header row: HOME | - | AWAY | PLAYING LOCATION | COMP SHEETS.
- Match rows (5 cells): [home_short, "Table N" | "vs.", away_short, "Felt
  Billiards", comp]. Teams use SHORT names ("The Furies", '"And then?"') — a
  prefix of the roster's full team name, so the loader resolves them by prefix.

10 teams -> 5 matches/round; 27 rounds.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, asdict

from bs4 import BeautifulSoup

from .roster import read_source  # reuse the .mht/.html loader

_MONTHS = {
    "Jan": 1, "Feb": 2, "Mar": 3, "Apr": 4, "May": 5, "Jun": 6,
    "Jul": 7, "Aug": 8, "Sep": 9, "Oct": 10, "Nov": 11, "Dec": 12,
}
_ROUND_RE = re.compile(r"Round:\s*(\d+)")
_DATE_RE = re.compile(r"\w+day,\s*([A-Z][a-z]{2})\.?\s+(\d{1,2}),\s*(\d{4})")


@dataclass(frozen=True)
class Fixture:
    round: int
    date: str | None        # ISO yyyy-mm-dd
    home: str               # short team name (prefix of the roster full name)
    away: str
    location: str | None    # e.g. "Table 2" (None when not yet assigned)
    comp_sheet: bool        # a comp sheet is available/printable

    def to_dict(self) -> dict:
        return asdict(self)


def _parse_date(text: str) -> str | None:
    m = _DATE_RE.search(text)
    if not m:
        return None
    mon, day, year = m.group(1), int(m.group(2)), m.group(3)
    if mon not in _MONTHS:
        return None
    return f"{year}-{_MONTHS[mon]:02d}-{day:02d}"


def _is_match_row(cells: list[str]) -> bool:
    # 5-cell row whose 2nd cell is the table/"vs." marker and whose 1st cell is a
    # real team (not the HOME header).
    return (
        len(cells) >= 3
        and cells[0]
        and cells[0].upper() != "HOME"
        and (cells[1] == "vs." or cells[1].lower().startswith("table"))
    )


def parse_schedule(html: str) -> list[Fixture]:
    soup = BeautifulSoup(html, "lxml")
    fixtures: list[Fixture] = []
    current_round: int | None = None
    current_date: str | None = None

    for tr in soup.find_all("tr"):
        cells = [
            re.sub(r"\s+", " ", c.get_text(" ", strip=True))
            for c in tr.find_all(["td", "th"], recursive=False)
        ]
        if not cells:
            continue
        head = cells[0]
        rm = _ROUND_RE.match(head)
        if rm:
            current_round = int(rm.group(1))
            current_date = _parse_date(head)
            continue
        if current_round is not None and _is_match_row(cells):
            location = cells[1] if cells[1].lower().startswith("table") else None
            comp = len(cells) >= 5 and "print here" in cells[-1].lower()
            fixtures.append(Fixture(
                round=current_round,
                date=current_date,
                home=cells[0],
                away=cells[2],
                location=location,
                comp_sheet=comp,
            ))
    return fixtures


def parse_schedule_file(path) -> list[Fixture]:
    return parse_schedule(read_source(path))
