"""Standings (team season record) parser + loader tests, pinned to real data."""

from __future__ import annotations

from pathlib import Path

import pytest

from src.db import connect, load_roster, load_schedule, load_team_record, standings
from src.parse.roster import parse_roster_file
from src.parse.schedule import parse_schedule_file
from src.parse.standings import parse_team_record_file

REPO = Path(__file__).resolve().parents[1]
RECORD = REPO / "fixtures" / "comp_sheet_season.mht"
ROSTER = REPO / "fixtures" / "roster_grid.html"
SCHEDULE = REPO / "fixtures" / "schedule.html"
SEASON = "test-season"

pytestmark = pytest.mark.skipif(
    not RECORD.exists(), reason="no comp_sheet_season fixture committed yet"
)


def test_parse_team_record_shape():
    rec = parse_team_record_file(RECORD)
    assert rec.team == "Ed's Balls"
    assert len(rec.results) == 27                      # full season
    played = [r for r in rec.results if r.home_points is not None]
    assert len(played) == 26                           # W27 not yet played
    assert rec.results[0].week == 1 and rec.results[0].date == "2025-10-02"


def _loaded():
    conn = connect(":memory:")
    load_roster(conn, parse_roster_file(ROSTER), captured_date="2026-06-04", season=SEASON)
    load_schedule(conn, parse_schedule_file(SCHEDULE), season=SEASON)
    return conn


def test_load_team_record_and_standings():
    conn = _loaded()
    rec = parse_team_record_file(RECORD)
    result = load_team_record(conn, rec, season=SEASON)
    assert result["loaded"] == 26 and result["unresolved"] == 0
    rows = {r["team"]: r for r in standings(conn, season=SEASON)}
    # Ed's Balls' standing is complete (all 26 of its matches loaded).
    eds = next(r for r in rows if "Ed's Balls" in r)
    assert rows[eds]["matches_played"] == 26
    assert rows[eds]["points"] == 1109                 # sum of Ed's match points


def test_record_reconciles_with_schedule():
    """The season record's weekly opponents must match the schedule fixtures."""
    conn = _loaded()
    rec = parse_team_record_file(RECORD)
    fixtures = {f.round: {f.home, f.away} for f in parse_schedule_file(SCHEDULE)
                if "Ed's Balls" in (f.home, f.away)}
    for r in rec.results:
        sched = fixtures.get(r.week)
        assert sched is not None
        assert {r.home, r.away} == sched, f"week {r.week}: {r.home}/{r.away} vs {sched}"
