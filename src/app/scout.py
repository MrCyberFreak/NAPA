"""Scout grid (Phase 5 payoff) — your roster x an opponent roster.

This is the view the official site structurally can't produce. It reads ONLY
from the DB and is derived entirely from roster-grid CSRs (no blocked host, no
weekly-scores data needed).

Lagger's Choice framing: the lag winner picks the game (8/9/10), and skill is
tracked separately per game. So for any pairing the outcome hinges on WHICH game
gets played:
  - If I win the lag, I pick the game where my per-game CSR edge is largest.
  - If my opponent wins the lag, they pick the game where my edge is smallest.
The swing between those two is the cell's *volatility* — a high-volatility cell
means the lag matters enormously for that pairing (an exploitable signal). A
player's spread across the three games is the key scouting tell.

The grid is NON-SQUARE and variable: rosters run 7-11, so it may be 7x11.
Never assume equal or fixed dimensions on either axis.

Race lengths come from the official NAPA matrix (src/race.py, transcribed from
the calculator's races.js) — per game (8/9/10), each player's actual handicapped
race. The CSR edge + volatility remain the scannable scouting signals; a
win-probability model on top is Phase 6.
"""

from __future__ import annotations

import sqlite3
from dataclasses import dataclass

from .. import config
from ..db import team_depth, team_roster_latest
from ..race import race as race_lookup

GAMES = (8, 9, 10)


@dataclass(frozen=True)
class GameEdge:
    game: int          # 8, 9, or 10
    my_csr: int
    opp_csr: int

    @property
    def edge(self) -> int:
        """My per-game CSR advantage (positive = I'm favored)."""
        return self.my_csr - self.opp_csr

    @property
    def race(self) -> tuple[int, int]:
        """Actual handicapped race (my_race, opp_race) from the NAPA matrix."""
        return race_lookup(self.my_csr, self.opp_csr)


@dataclass(frozen=True)
class Cell:
    my_player: str
    my_id: str
    opp_player: str
    opp_id: str
    edges: tuple[GameEdge, ...]  # one per game in GAMES order

    @property
    def my_pick(self) -> GameEdge:
        """The game I'd choose if I win the lag (largest edge for me)."""
        return max(self.edges, key=lambda e: e.edge)

    @property
    def opp_pick(self) -> GameEdge:
        """The game my opponent would choose if they win the lag (smallest edge for me)."""
        return min(self.edges, key=lambda e: e.edge)

    @property
    def volatility(self) -> int:
        """How much my edge swings across the three games = how much the lag matters."""
        return self.my_pick.edge - self.opp_pick.edge

    @property
    def neutral_edge(self) -> float:
        """Lag-neutral midpoint of best/worst case — a scannable single number."""
        return (self.my_pick.edge + self.opp_pick.edge) / 2


@dataclass(frozen=True)
class Grid:
    my_team: str
    opp_team: str
    season: str
    my_players: tuple[str, ...]      # row labels (player names)
    opp_players: tuple[str, ...]     # column labels
    cells: tuple[tuple[Cell, ...], ...]
    my_depth: int
    opp_depth: int

    @property
    def shape(self) -> tuple[int, int]:
        return (len(self.my_players), len(self.opp_players))

    @property
    def depth_advantage(self) -> int:
        """Bench-depth differential — only 5 play league night, so a deeper team
        has more lineup flexibility to hold back a counter (an exploitable tell)."""
        return self.my_depth - self.opp_depth


def _build_cell(me: sqlite3.Row, opp: sqlite3.Row) -> Cell:
    edges = tuple(
        GameEdge(game=g, my_csr=me[f"csr_{g}"], opp_csr=opp[f"csr_{g}"]) for g in GAMES
    )
    return Cell(
        my_player=me["name"], my_id=me["player_id"],
        opp_player=opp["name"], opp_id=opp["player_id"],
        edges=edges,
    )


def build_grid(
    conn: sqlite3.Connection,
    my_team: str,
    opp_team: str,
    season: str = config.SEASON,
) -> Grid:
    my_roster = team_roster_latest(conn, my_team, season)
    opp_roster = team_roster_latest(conn, opp_team, season)
    if not my_roster:
        raise ValueError(f"no roster found for {my_team!r} in season {season!r}")
    if not opp_roster:
        raise ValueError(f"no roster found for {opp_team!r} in season {season!r}")

    cells = tuple(
        tuple(_build_cell(me, opp) for opp in opp_roster) for me in my_roster
    )
    depth = {r["team"]: r["roster_size"] for r in team_depth(conn, season)}
    return Grid(
        my_team=my_team,
        opp_team=opp_team,
        season=season,
        my_players=tuple(r["name"] for r in my_roster),
        opp_players=tuple(r["name"] for r in opp_roster),
        cells=cells,
        my_depth=depth.get(my_team, len(my_roster)),
        opp_depth=depth.get(opp_team, len(opp_roster)),
    )


# --------------------------------------------------------------------------- #
# Rendering (terminal-friendly)
# --------------------------------------------------------------------------- #

def _vol_marker(volatility: int) -> str:
    """Scannable volatility cue: more bars = the lag matters more for this cell."""
    if volatility >= 40:
        return "###"
    if volatility >= 20:
        return "## "
    if volatility >= 10:
        return "#  "
    return "   "


def render_cell(cell: Cell) -> str:
    """Drill-down: the three per-game edges, the actual handicapped race, and the
    LC picks for one pairing."""
    lines = [
        f"{cell.my_player} ({cell.my_id})  vs  {cell.opp_player} ({cell.opp_id})",
        f"  {'game':>5} {'mine':>5} {'opp':>5} {'edge':>6} {'race':>7}",
    ]
    for e in cell.edges:
        flag = "  <- I'd pick" if e is cell.my_pick else (
            "  <- they'd pick" if e is cell.opp_pick else "")
        my_race, opp_race = e.race
        lines.append(f"  {e.game:>5} {e.my_csr:>5} {e.opp_csr:>5} {e.edge:>+6} "
                     f"{my_race:>3}-{opp_race:<3}{flag}")
    lines.append(
        f"  volatility {cell.volatility:>3}  (I win lag: {cell.my_pick.edge:+d} on "
        f"{cell.my_pick.game}-ball | they win lag: {cell.opp_pick.edge:+d} on "
        f"{cell.opp_pick.game}-ball)"
    )
    return "\n".join(lines)


def render_grid(grid: Grid) -> str:
    """Compact matrix. Each cell shows the lag-neutral edge and a volatility cue."""
    rows, cols = grid.shape
    out = [
        f"Scout grid  {grid.my_team}  (you)  x  {grid.opp_team}",
        f"  shape {rows}x{cols}   bench depth {grid.my_depth} vs {grid.opp_depth} "
        f"({grid.depth_advantage:+d})",
        "  cell = lag-neutral edge (+ = you favored); bars = volatility (lag leverage)",
        "",
    ]
    name_w = max((len(n) for n in grid.my_players), default=8)
    header = " " * (name_w + 2) + "".join(f"{c[:8]:>10}" for c in grid.opp_players)
    out.append(header)
    for r, me in enumerate(grid.my_players):
        fields = []
        for cell in grid.cells[r]:
            marker = _vol_marker(cell.volatility).strip()
            fields.append(f"{cell.neutral_edge:+.0f}{marker}")
        out.append(f"{me[:name_w]:<{name_w}}  " + "".join(f"{f:>10}" for f in fields))
    return "\n".join(out)
