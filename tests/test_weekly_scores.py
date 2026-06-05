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


# --- score sheet (scores.php) — authoritative per-game grain --------------- #

SHEET = REPO / "fixtures" / "score_sheet_w1.mht"


@pytest.mark.skipif(not SHEET.exists(), reason="no score_sheet fixture")
def test_parse_score_sheet():
    from src.parse.weekly_scores import parse_score_sheet_file
    sh = parse_score_sheet_file(SHEET)
    assert sh.home_team == "Ed's Balls" and sh.away_team == "Pocket Predators"
    assert sh.date == "2025-10-02"
    assert len(sh.games) == 5
    assert {g.game_type for g in sh.games} <= {8, 9, 10}
    g0 = sh.games[0]
    assert g0.game_type == 10 and g0.home_player == "Adam DeLaPena"
    assert g0.home_race == 3 and g0.away_race == 7 and g0.home_wins == 3
    assert g0.home_won is True


@pytest.mark.skipif(not SHEET.exists(), reason="no score_sheet fixture")
def test_load_score_sheets_populates_games_with_type():
    from src.parse.weekly_scores import parse_score_sheet_file
    from src.db import load_score_sheets
    conn = _loaded_db()
    sh = parse_score_sheet_file(SHEET)
    result = load_score_sheets(conn, [sh], season=SEASON)
    assert result["loaded"] == 5
    rows = conn.execute(
        "SELECT game_type, home_race, away_race FROM games WHERE game_type IS NOT NULL").fetchall()
    assert len(rows) == 5
    assert all(r["game_type"] in (8, 9, 10) for r in rows)
    # links to the W1 Ed's Balls vs Pocket Predators match
    linked = conn.execute("SELECT COUNT(*) FROM games WHERE match_id IS NOT NULL").fetchone()[0]
    assert linked == 5


@pytest.mark.skipif(not SHEET.exists(), reason="no score_sheet fixture")
def test_score_sheet_mirror_dedup():
    """Loading the same match from the opponent's (flipped) sheet doesn't dupe."""
    from src.parse.weekly_scores import parse_score_sheet_file, ScoreSheet, ScoreGame
    from src.db import load_score_sheets
    conn = _loaded_db()
    sh = parse_score_sheet_file(SHEET)
    load_score_sheets(conn, [sh], season=SEASON)
    # build the mirror: swap home/away for each game and the matchup
    mirror = ScoreSheet(home_team=sh.away_team, away_team=sh.home_team, date=sh.date,
                        games=[ScoreGame(g.game_type, g.away_player, g.away_team,
                                         g.home_player, g.home_team, g.away_race,
                                         g.home_race, g.away_wins, g.home_wins)
                               for g in sh.games])
    result = load_score_sheets(conn, [mirror], season=SEASON)
    assert result["deduped"] == 5
    assert conn.execute("SELECT COUNT(*) FROM games").fetchone()[0] == 5
