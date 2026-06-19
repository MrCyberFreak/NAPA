"""Flex / individual-point-standings parser (poolshooters division.php?view=flex).

The "FLEX POINT" view is the division's INDIVIDUAL race: one row per player,
ranked by average points per match. It updates weekly and the host OVERWRITES
it (no historical-flex URL), so each capture is a dated drift snapshot.

Table shape (header-driven — we locate the row carrying "AVG PPM" and map every
labelled column, so a reorder or an added column degrades gracefully):

    #   PLAYER (RATINGS)        AP  MP  FF 20  FF 14  ADJ. AP  ADJ. MP  AVG PPM
    1.  Ed Kiefer (77, 54, 49)  20  1   0      0      20       [ 1 ]    20.00

- AP  = actual points,  MP = matches played.
- FF 20 / FF 14   = forfeit credits at the two race lengths.
- ADJ. AP / ADJ. MP = points / matches after the forfeit adjustment
  (ADJ. MP is printed bracketed, e.g. "[ 1 ]").
- AVG PPM = ADJ. AP / ADJ. MP — the ranking key.
- The PLAYER cell embeds the per-game ratings triple in parens; we keep the raw
  text AND the parsed ints, but do NOT map them onto 8/9/10 columns here — the
  game set is division-specific (see roster.py) and flex never declares it.

No 8-digit player id is present (name only) — the loader resolves names to ids
division-first (db._resolve_player_id, A1). A missing standings table RAISES
(a layout change must be loud, like the roster parser); a single malformed data
row is skipped.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field

from bs4 import BeautifulSoup

from .roster import read_source

_MIN_MATCHES_RE = re.compile(r"MINIMUM\s+MATCHES\s+REQUIRED:\s*(\d+)", re.I)
_RATINGS_RE = re.compile(r"^(.*?)\s*\(([\d,\s]+)\)\s*$")

# Header label (normalized: upper-cased, whitespace-collapsed) -> field name.
_COLUMNS = {
    "#": "rank",
    "AP": "ap",
    "MP": "mp",
    "FF 20": "ff_20",
    "FF 14": "ff_14",
    "ADJ. AP": "adj_ap",
    "ADJ. MP": "adj_mp",
    "AVG PPM": "avg_ppm",
    # PLAYER (RATINGS) handled by prefix match below — the parenthetical varies.
}


@dataclass(frozen=True)
class FlexRow:
    rank: int | None
    player: str
    ratings: tuple[int, ...]        # parsed from "(77, 54, 49)"; () if absent
    ratings_raw: str | None         # the literal "(77, 54, 49)" text, faithful
    ap: int | None
    mp: int | None
    ff_20: int | None
    ff_14: int | None
    adj_ap: int | None
    adj_mp: int | None
    avg_ppm: float | None


@dataclass
class FlexStandings:
    did: int | None
    min_matches: int | None
    rows: list[FlexRow] = field(default_factory=list)


def _norm(text: str) -> str:
    return re.sub(r"\s+", " ", (text or "")).strip().upper()


def _int(text: str | None) -> int | None:
    m = re.search(r"-?\d+", text or "")
    return int(m.group()) if m else None


def _float(text: str | None) -> float | None:
    m = re.search(r"-?\d+(?:\.\d+)?", text or "")
    return float(m.group()) if m else None


def _split_player(cell: str) -> tuple[str, tuple[int, ...], str | None]:
    """"Ed Kiefer (77, 54, 49)" -> ("Ed Kiefer", (77,54,49), "(77, 54, 49)")."""
    cell = (cell or "").strip()
    m = _RATINGS_RE.match(cell)
    if not m:
        return cell, (), None
    name = m.group(1).strip()
    ratings = tuple(int(n) for n in re.findall(r"\d+", m.group(2)))
    return name, ratings, f"({m.group(2).strip()})"


def _header_map(rows: list[list[str]]) -> tuple[int, dict[str, int]] | None:
    """Find the standings header row (the one carrying AVG PPM) and map each
    known column label to its index. Returns (header_row_index, {field: col})."""
    for ri, cells in enumerate(rows):
        norm = [_norm(c) for c in cells]
        if "AVG PPM" not in norm:
            continue
        colmap: dict[str, int] = {}
        for ci, label in enumerate(norm):
            if label in _COLUMNS:
                colmap[_COLUMNS[label]] = ci
            elif label.startswith("PLAYER"):
                colmap["player"] = ci
        if "player" in colmap and "avg_ppm" in colmap:
            return ri, colmap
    return None


def _cell(cells: list[str], colmap: dict[str, int], field_name: str) -> str | None:
    ci = colmap.get(field_name)
    if ci is None or ci >= len(cells):
        return None
    return cells[ci]


def parse_flex(html: str) -> FlexStandings:
    soup = BeautifulSoup(html, "lxml")
    page_text = soup.get_text(" ", strip=True)

    did = None
    for tr in soup.find_all("tr"):
        cells = [c.get_text(" ", strip=True) for c in tr.find_all(["td", "th"])]
        if len(cells) == 2 and cells[0].rstrip(":").strip().upper() == "DIVISION ID":
            did = _int(cells[1])
            break

    mm = _MIN_MATCHES_RE.search(page_text)
    min_matches = int(mm.group(1)) if mm else None

    standings = FlexStandings(did=did, min_matches=min_matches)

    # Locate the standings table by its header signature among all tables.
    for table in soup.find_all("table"):
        rows = [[c.get_text(" ", strip=True) for c in tr.find_all(["td", "th"])]
                for tr in table.find_all("tr")]
        hdr = _header_map(rows)
        if hdr is None:
            continue
        hi, colmap = hdr
        for cells in rows[hi + 1:]:
            if not any(cells) or len(cells) < 3:
                continue
            player_cell = _cell(cells, colmap, "player")
            if not player_cell:
                continue  # spacer / spanning row
            name, ratings, ratings_raw = _split_player(player_cell)
            if not name:
                continue
            standings.rows.append(FlexRow(
                rank=_int(_cell(cells, colmap, "rank")),
                player=name,
                ratings=ratings,
                ratings_raw=ratings_raw,
                ap=_int(_cell(cells, colmap, "ap")),
                mp=_int(_cell(cells, colmap, "mp")),
                ff_20=_int(_cell(cells, colmap, "ff_20")),
                ff_14=_int(_cell(cells, colmap, "ff_14")),
                adj_ap=_int(_cell(cells, colmap, "adj_ap")),
                adj_mp=_int(_cell(cells, colmap, "adj_mp")),
                avg_ppm=_float(_cell(cells, colmap, "avg_ppm")),
            ))
        return standings

    raise ValueError("flex: individual-point-standings table not found "
                     "(no header row carrying 'AVG PPM') — layout changed?")


def parse_flex_file(path) -> FlexStandings:
    return parse_flex(read_source(path))
