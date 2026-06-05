"""Schedule parser + loader tests, pinned to the real captured schedule."""

from __future__ import annotations

from collections import Counter
from pathlib import Path

import pytest

from src.db import connect, load_roster, load_schedule, matches_for_round
from src.parse.roster import parse_roster_file
from src.parse.schedule import parse_schedule_file

REPO = Path(__file__).resolve().parents[1]
SCHEDULE = REPO / "fixtures" / "schedule.html"
ROSTER = REPO / "fixtures" / "roster_grid.html"
SEASON = "test-season"

pytestmark = pytest.mark.skipif(
    not SCHEDULE.exists(), reason="no real schedule fixture committed yet"
)


def test_schedule_shape():
    fx = parse_schedule_file(SCHEDULE)
    rounds = Counter(f.round for f in fx)
    assert len(fx) == 135                       # 27 rounds x 5 matches
    assert sorted(rounds) == list(range(1, 28))
    assert set(rounds.values()) == {5}          # 10 teams -> 5 matches/round


def test_schedule_dates_and_teams():
    fx = parse_schedule_file(SCHEDULE)
    by_round = {f.round: f for f in fx}
    assert by_round[1].date == "2025-10-02"
    assert by_round[27].date == "2026-06-04"
    teams = set(f.home for f in fx) | set(f.away for f in fx)
    assert len(teams) == 10
    # Each team plays exactly once per round (no team twice in a round).
    r1 = [f for f in fx if f.round == 1]
    names = [f.home for f in r1] + [f.away for f in r1]
    assert len(names) == len(set(names)) == 10


def test_load_schedule_resolves_short_names_to_teams():
    conn = connect(":memory:")
    load_roster(conn, parse_roster_file(ROSTER), captured_date="2026-06-04", season=SEASON)
    result = load_schedule(conn, parse_schedule_file(SCHEDULE), season=SEASON)
    assert result["fixtures"] == 135
    assert result["unresolved"] == 0            # every short name resolved
    assert result["loaded"] == 135
    # Idempotent reload — no duplicate matches.
    load_schedule(conn, parse_schedule_file(SCHEDULE), season=SEASON)
    assert conn.execute("SELECT COUNT(*) FROM matches").fetchone()[0] == 135


def test_matches_for_round_returns_full_team_names():
    conn = connect(":memory:")
    load_roster(conn, parse_roster_file(ROSTER), captured_date="2026-06-04", season=SEASON)
    load_schedule(conn, parse_schedule_file(SCHEDULE), season=SEASON)
    rows = matches_for_round(conn, 1, season=SEASON)
    assert len(rows) == 5
    for r in rows:
        assert "Felt Billiards Team #" in r["home_team"]  # resolved to canonical
        assert r["date"] == "2025-10-02"
