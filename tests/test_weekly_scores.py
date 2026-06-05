"""Live-scores (games grain) parser + loader tests, pinned to real fixtures."""

from __future__ import annotations

from pathlib import Path

import pytest

from src.db import connect, load_games, load_roster, load_schedule, player_game_log
from src.parse.roster import parse_roster_file
from src.parse.schedule import parse_schedule_file
from src.parse.weekly_scores import parse_live_scores_file

REPO = Path(__file__).resolve().parents[1]
LIVE = REPO / "fixtures" / "live_scores.mht"
ROSTER = REPO / "fixtures" / "roster_grid.html"
SCHEDULE = REPO / "fixtures" / "schedule.html"
SEASON = "test-season"

pytestmark = pytest.mark.skipif(
    not LIVE.exists(), reason="no real live_scores fixture committed yet"
)


def test_parse_live_scores_shape():
    games = parse_live_scores_file(LIVE)
    assert len(games) == 5                       # 5 boards of one match captured
    for g in games:
        assert g.date == "2026-05-28"            # round 26
        assert g.home.player and g.away.player
        assert g.home.sl and g.away.sl           # per-game CueSpeed present
        assert g.home.racks_won >= 0 and g.away.racks_won >= 0


def test_winner_detection():
    games = {(g.home.player, g.away.player): g for g in parse_live_scores_file(LIVE)}
    g = games[("Scotty Mullins, Jr.", "Tony Caballeros")]
    assert g.home.racks_won == 8 and g.away.racks_won == 0
    assert g.home_won is True
    g2 = games[("Anna Cusic", "Hector Cisneros")]
    assert g2.away.is_race_winner and g2.home_won is False


def _loaded_db():
    conn = connect(":memory:")
    load_roster(conn, parse_roster_file(ROSTER), captured_date="2026-06-04", season=SEASON)
    load_schedule(conn, parse_schedule_file(SCHEDULE), season=SEASON)
    return conn


def test_load_games_resolves_ids_and_links_matches():
    conn = _loaded_db()
    result = load_games(conn, parse_live_scores_file(LIVE), season=SEASON)
    assert result["games"] == 5
    # 1 sub in this capture (Scotty Mullins, Jr.) -> exactly one unresolved slot.
    assert result["unresolved_player_slots"] == 1
    # All five team-pairs are real round-26 matches -> all linked.
    assert result["linked_to_match"] == 5
    rows = conn.execute("SELECT COUNT(*) FROM games").fetchone()[0]
    assert rows == 5
    # Idempotent reload.
    load_games(conn, parse_live_scores_file(LIVE), season=SEASON)
    assert conn.execute("SELECT COUNT(*) FROM games").fetchone()[0] == 5


def test_subs_stored_with_null_id_not_dropped():
    conn = _loaded_db()
    load_games(conn, parse_live_scores_file(LIVE), season=SEASON)
    row = conn.execute(
        "SELECT home_player_id FROM games WHERE home_player_name = ?",
        ("Scotty Mullins, Jr.",),
    ).fetchone()
    assert row is not None and row["home_player_id"] is None  # sub kept, id NULL


def test_player_game_log():
    conn = _loaded_db()
    load_games(conn, parse_live_scores_file(LIVE), season=SEASON)
    hector = conn.execute(
        "SELECT player_id FROM players WHERE name = 'Hector Cisneros'").fetchone()["player_id"]
    log = player_game_log(conn, hector)
    assert len(log) == 1
    assert log[0]["player_won"] in (0, 1)
