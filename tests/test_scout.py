"""Phase 5 scout-grid tests (derived purely from roster data)."""

from __future__ import annotations

from pathlib import Path

import pytest

from src.app.scout import Cell, GameEdge, build_grid, render_cell, render_grid, render_schedule
from src.db import connect, init_db, load_roster, upcoming_fixtures
from src.parse.roster import parse_roster_file
from src import config

REPO = Path(__file__).resolve().parents[1]
SYNTHETIC = REPO / "tests" / "data" / "synthetic_roster_grid.html"
SEASON = "test-season"


@pytest.fixture
def conn():
    c = connect(":memory:")
    load_roster(c, parse_roster_file(SYNTHETIC), captured_date="2026-06-04", season=SEASON)
    return c


def test_grid_is_non_square_with_correct_dimensions(conn):
    # Pocket Pals #1 = 7, Cheat Code #6 = 11  -> a 7x11 grid.
    grid = build_grid(conn, "Pocket Pals #1", "Cheat Code Felt Billiards #6", season=SEASON)
    assert grid.shape == (7, 11)
    assert len(grid.cells) == 7
    assert all(len(row) == 11 for row in grid.cells)
    assert grid.depth_advantage == 7 - 11  # bench-depth differential


def test_cell_edge_and_lc_pick_logic():
    # I'm a big-game specialist: strong on 8, weak on 10.
    cell = Cell(
        my_player="Me", my_id="00000001", opp_player="Opp", opp_id="00000002",
        edges=(
            GameEdge(8, my_csr=100, opp_csr=60),   # +40
            GameEdge(9, my_csr=70, opp_csr=70),    #   0
            GameEdge(10, my_csr=60, opp_csr=95),   # -35
        ),
    )
    assert cell.my_pick.game == 8 and cell.my_pick.edge == 40    # I win lag -> 8-ball
    assert cell.opp_pick.game == 10 and cell.opp_pick.edge == -35  # they win lag -> 10-ball
    assert cell.volatility == 75                                  # huge lag leverage
    assert cell.neutral_edge == (40 + -35) / 2


def test_grid_cell_values_match_roster_csrs(conn):
    grid = build_grid(conn, "Pocket Pals #1", "The Furies #2", season=SEASON)
    rows = conn.execute(
        "SELECT p.name AS name, csr_8, csr_9, csr_10 FROM players p "
        "JOIN skill_snapshots s USING(player_id) "
        "JOIN team_members tm USING(player_id) JOIN teams t USING(team_id) "
        "WHERE t.name=? ORDER BY p.name", ("Pocket Pals #1",)
    ).fetchall()
    my_by_name = {r["name"]: r for r in rows}
    cell = grid.cells[0][0]
    src = my_by_name[cell.my_player]
    e8 = next(e for e in cell.edges if e.game == 8)
    assert e8.my_csr == src["csr_8"]


def test_renderers_produce_output(conn):
    grid = build_grid(conn, "Pocket Pals #1", "Cheat Code Felt Billiards #6", season=SEASON)
    text = render_grid(grid)
    assert "Scout grid" in text
    assert "7x11" in text
    cell = grid.cells[0][0]
    drill = render_cell(cell)
    assert cell.my_player in drill and "volatility" in drill


def test_unknown_team_raises(conn):
    with pytest.raises(ValueError):
        build_grid(conn, "Nope FC", "The Furies #2", season=SEASON)


def test_cell_carries_real_race_lengths(conn):
    from src.race import race as race_lookup
    grid = build_grid(conn, "Pocket Pals #1", "Cheat Code Felt Billiards #6", season=SEASON)
    cell = grid.cells[0][0]
    for e in cell.edges:
        assert e.race == race_lookup(e.my_csr, e.opp_csr)
        my_race, opp_race = e.race
        assert my_race >= 2 and opp_race >= 2          # NAPA minimum race is 2
        # stronger player races to the higher (or equal) number
        if e.my_csr > e.opp_csr:
            assert my_race >= opp_race
    # drill-down shows the race column
    assert "race" in render_cell(cell)


# --------------------------------------------------------------------------- #
# Phase 6 §5 — upcoming-fixture schedule (auto-expanded into scout grids)
# --------------------------------------------------------------------------- #

def _schedule_db():
    """A bare division schedule: team ME plays others on staggered dates, plus a
    BYE round and one already-played (past) fixture."""
    c = connect(":memory:")
    init_db(c)
    did = config.DID
    teams = {"ME": 1, "Opp A": 2, "Opp B": 3, "Bye Felt Billiards Team #9": 4}
    for name, tid in teams.items():
        c.execute("INSERT INTO teams (team_id, division_id, name, season) VALUES (?,?,?,?)",
                  (tid, did, name, "test"))
    # (round, date, home, away)
    rows = [
        (1, "2026-06-01", 1, 2),   # past — ME (home) vs Opp A
        (2, "2026-06-20", 3, 1),   # future — ME is AWAY vs Opp B
        (3, "2026-06-27", 1, 4),   # future — ME vs a BYE (must be excluded)
        (4, "2026-07-04", 2, 1),   # future — ME is AWAY vs Opp A
    ]
    for i, (rnd, dt, h, a) in enumerate(rows, start=1):
        c.execute("INSERT INTO matches (match_id, division_id, season, round, date, "
                  "home_team_id, away_team_id) VALUES (?,?,?,?,?,?,?)",
                  (i, did, "test", rnd, dt, h, a))
    c.commit()
    return c


def test_upcoming_fixtures_filters_dates_resolves_opponent_and_excludes_bye():
    c = _schedule_db()
    fx = upcoming_fixtures(c, "ME", as_of="2026-06-16", season="test", division_id=config.DID)
    # past fixture (06-01) dropped; bye fixture dropped -> 2 remain, chronological
    assert [r["round"] for r in fx] == [2, 4]
    assert fx[0]["opponent"] == "Opp B" and fx[0]["venue"] == "away"   # ME was away
    assert fx[1]["opponent"] == "Opp A" and fx[1]["venue"] == "away"
    # none of the returned opponents is the bye
    assert all("Bye" not in r["opponent"] for r in fx)


def test_upcoming_fixtures_empty_for_finished_season():
    c = _schedule_db()
    fx = upcoming_fixtures(c, "ME", as_of="2027-01-01", season="test", division_id=config.DID)
    assert fx == []


def test_render_schedule_lists_each_remaining_fixture():
    c = _schedule_db()
    fx = upcoming_fixtures(c, "ME", as_of="2026-06-16", season="test", division_id=config.DID)
    text = render_schedule("ME", fx)
    assert "2 remaining" in text
    assert "Opp B" in text and "Opp A" in text
    assert "Bye" not in text
