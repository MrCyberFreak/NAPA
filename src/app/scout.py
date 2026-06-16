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
from ..model import Estimate, Matchup, Model
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
class GameForecast:
    """Phase 6 — one game type of an A-vs-B pairing, with the win-probability
    model layered on top of the raw CSR edge. `matchup.match_prob_a` is P(MY
    player wins the handicapped race)."""
    game: int
    my: Estimate          # my player's base+adj estimate (the §2 display pieces)
    opp: Estimate
    matchup: Matchup      # rack/match prob + edge, from my perspective


@dataclass(frozen=True)
class CellForecast:
    """The §3/§4 forecast for one pairing: per-game win-prob + Lagger's-Choice
    picks resolved by win probability (not raw CSR edge)."""
    games: tuple[GameForecast, ...]

    @property
    def my_pick(self) -> GameForecast | None:
        """If I win the lag, the game that maximises my match win probability."""
        return max(self.games, key=lambda g: g.matchup.match_prob_a) if self.games else None

    @property
    def opp_pick(self) -> GameForecast | None:
        """If the opponent wins the lag, the game they'd pick — the one that
        minimises my match win probability."""
        return min(self.games, key=lambda g: g.matchup.match_prob_a) if self.games else None

    @property
    def neutral_edge(self) -> float | None:
        """Lag-neutral edge in win-probability points — a scannable scouting
        number (positive = the handicap leaves value on my side)."""
        if not self.games:
            return None
        return (self.my_pick.matchup.edge_a + self.opp_pick.matchup.edge_a) / 2

    @property
    def prob_swing(self) -> float | None:
        """How much my match win prob swings between best and worst game = how
        much the lag matters here (the §4 volatility, in probability space)."""
        if not self.games:
            return None
        return self.my_pick.matchup.match_prob_a - self.opp_pick.matchup.match_prob_a


@dataclass(frozen=True)
class Cell:
    my_player: str
    my_id: str
    opp_player: str
    opp_id: str
    edges: tuple[GameEdge, ...]  # one per game BOTH players carry a CSR for
    forecast: CellForecast | None = None  # Phase 6 win-prob layer (None = CSR-only)

    @property
    def my_pick(self) -> GameEdge | None:
        """The game I'd choose if I win the lag (largest edge for me)."""
        return max(self.edges, key=lambda e: e.edge) if self.edges else None

    @property
    def opp_pick(self) -> GameEdge | None:
        """The game my opponent would choose if they win the lag (smallest edge for me)."""
        return min(self.edges, key=lambda e: e.edge) if self.edges else None

    @property
    def volatility(self) -> int | None:
        """How much my edge swings across the games = how much the lag matters."""
        return self.my_pick.edge - self.opp_pick.edge if self.edges else None

    @property
    def neutral_edge(self) -> float | None:
        """Lag-neutral midpoint of best/worst case — a scannable single number."""
        return (self.my_pick.edge + self.opp_pick.edge) / 2 if self.edges else None


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


def _build_forecast(model: Model, my_id: str, opp_id: str) -> CellForecast | None:
    """The Phase-6 win-prob layer for one pairing, over the games BOTH players
    carry a CSR for. None when the model can't price any game (a sub with no
    rating)."""
    games = []
    for g in GAMES:
        mu = model.matchup(my_id, opp_id, g)
        if mu is None:
            continue
        my_e = model.estimate(my_id, g)
        opp_e = model.estimate(opp_id, g)
        games.append(GameForecast(game=g, my=my_e, opp=opp_e, matchup=mu))
    return CellForecast(games=tuple(games)) if games else None


def _build_cell(me: sqlite3.Row, opp: sqlite3.Row, model: Model | None = None) -> Cell:
    # A game only makes a scouting edge when BOTH players carry a CSR for it —
    # snapshots sourced from a 1- or 2-game division's grid leave the others NULL.
    edges = tuple(
        GameEdge(game=g, my_csr=me[f"csr_{g}"], opp_csr=opp[f"csr_{g}"])
        for g in GAMES
        if me[f"csr_{g}"] is not None and opp[f"csr_{g}"] is not None
    )
    forecast = _build_forecast(model, me["player_id"], opp["player_id"]) if model else None
    return Cell(
        my_player=me["name"], my_id=me["player_id"],
        opp_player=opp["name"], opp_id=opp["player_id"],
        edges=edges, forecast=forecast,
    )


def build_grid(
    conn: sqlite3.Connection,
    my_team: str,
    opp_team: str,
    season: str = config.SEASON,
    division_id: int = config.DID,
    model: Model | None = None,
) -> Grid:
    """Build the scout grid. Pass a fitted `model` to layer the Phase-6 win-prob
    forecast onto every cell; omit it for the Phase-5 CSR-edge-only grid."""
    my_roster = team_roster_latest(conn, my_team, season, division_id)
    opp_roster = team_roster_latest(conn, opp_team, season, division_id)
    if not my_roster:
        raise ValueError(f"no roster found for {my_team!r} in season {season!r}")
    if not opp_roster:
        raise ValueError(f"no roster found for {opp_team!r} in season {season!r}")

    cells = tuple(
        tuple(_build_cell(me, opp, model) for opp in opp_roster) for me in my_roster
    )
    depth = {r["team"]: r["roster_size"] for r in team_depth(conn, season, division_id)}
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


def _fmt_est(e: Estimate) -> str:
    """The §2 three-piece display: CSR prior, data-driven adj (+ its games-count
    backing), and the resulting estimate — never a bare number."""
    return f"CSR {e.base:>3} adj {e.adj:+4.1f}({e.n_races}g) ->{e.skill:>5.1f}"


def _render_forecast(fc: CellForecast) -> list[str]:
    """The Phase-6 §2/§3/§4 block: per-game estimates + win-prob + edge, then the
    Lagger's-Choice picks resolved by win probability."""
    lines = [
        "  forecast - skill = NAPA CSR + data-driven adj (games backing it); "
        "edge = data win-prob minus the race's ~50/50 design:",
        f"  {'game':>5}  {'you (base+adj->est)':<28} {'opp (base+adj->est)':<28} "
        f"{'race':>5} {'rackP':>6} {'matchP':>7} {'edge':>6}",
    ]
    for g in fc.games:
        mu = g.matchup
        flag = "  <- you'd pick" if g is fc.my_pick else (
            "  <- they'd pick" if g is fc.opp_pick else "")
        lines.append(
            f"  {g.game:>5}  {_fmt_est(g.my):<28} {_fmt_est(g.opp):<28} "
            f"{mu.race_a:>2}-{mu.race_b:<2} {mu.rack_prob_a:>6.2f} "
            f"{mu.match_prob_a:>7.2f} {mu.edge_a*100:>+5.0f}{flag}"
        )
    mp, op = fc.my_pick, fc.opp_pick
    lines.append(
        f"  Lagger's Choice: you win lag -> {mp.game}-ball "
        f"(match {mp.matchup.match_prob_a:.0%}, edge {mp.matchup.edge_a*100:+.0f}pp)  |  "
        f"opp wins lag -> {op.game}-ball "
        f"(your match {op.matchup.match_prob_a:.0%}, edge {op.matchup.edge_a*100:+.0f}pp)"
    )
    lines.append(f"  lag swing {fc.prob_swing*100:.0f}pp  "
                 f"(how much winning the lag is worth in this pairing)")
    return lines


def render_cell(cell: Cell) -> str:
    """Drill-down: the per-game edges, the actual handicapped race, and the
    LC picks for one pairing. With a forecast attached, also the §2/§3/§4
    win-probability layer."""
    if not cell.edges:
        return (f"{cell.my_player} ({cell.my_id})  vs  {cell.opp_player} ({cell.opp_id})\n"
                "  no game both players carry a CSR for")
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
    if cell.forecast is not None:
        lines.append("")
        lines.extend(_render_forecast(cell.forecast))
    return "\n".join(lines)


def _swing_marker(swing_pp: float) -> str:
    """Win-prob analogue of _vol_marker: more bars = the lag is worth more here."""
    if swing_pp >= 20:
        return "###"
    if swing_pp >= 12:
        return "## "
    if swing_pp >= 6:
        return "#  "
    return "   "


def render_grid(grid: Grid) -> str:
    """Compact matrix. Without a forecast, each cell shows the lag-neutral CSR
    edge + volatility cue (Phase 5). With one, the lag-neutral win-prob edge in
    points (+ = the handicap leaves value on your side) + a lag-swing cue."""
    rows, cols = grid.shape
    has_forecast = any(c.forecast is not None for row in grid.cells for c in row)
    legend = ("  cell = lag-neutral win-prob edge in pts (+ = you favored vs the "
              "handicap); bars = lag swing" if has_forecast else
              "  cell = lag-neutral edge (+ = you favored); bars = volatility (lag leverage)")
    out = [
        f"Scout grid  {grid.my_team}  (you)  x  {grid.opp_team}",
        f"  shape {rows}x{cols}   bench depth {grid.my_depth} vs {grid.opp_depth} "
        f"({grid.depth_advantage:+d})",
        legend,
        "",
    ]
    name_w = max((len(n) for n in grid.my_players), default=8)
    header = " " * (name_w + 2) + "".join(f"{c[:8]:>10}" for c in grid.opp_players)
    out.append(header)
    for r, me in enumerate(grid.my_players):
        fields = []
        for cell in grid.cells[r]:
            fc = cell.forecast
            if has_forecast:
                if fc is None:
                    fields.append("--")
                    continue
                marker = _swing_marker(fc.prob_swing * 100).strip()
                fields.append(f"{fc.neutral_edge*100:+.0f}{marker}")
            else:
                if cell.neutral_edge is None:
                    fields.append("--")
                    continue
                marker = _vol_marker(cell.volatility).strip()
                fields.append(f"{cell.neutral_edge:+.0f}{marker}")
        out.append(f"{me[:name_w]:<{name_w}}  " + "".join(f"{f:>10}" for f in fields))
    return "\n".join(out)
