"""Match-POINT results mined off the weekly-scores INDEX (the outcome layer):
parser pinned to a real fixture, loader checked for home/away alignment and the
0-0 = not-played rule. This is the page already fetched for sheet URLs; here we
also capture the official match totals (matches.home/away_points)."""

from __future__ import annotations

from pathlib import Path

from src.db import connect, init_db, load_match_results
from src.parse.standings import MatchResult
from src.parse.weekly_scores import parse_week_results_file

REPO = Path(__file__).resolve().parents[1]
INDEX = REPO / "fixtures" / "weekly_scores_w1.mht"   # 13077 Round 1 index


def test_parse_week_results_shape():
    results = parse_week_results_file(INDEX)
    assert len(results) == 5                          # 5 matches, 10 teams
    assert all(r.week == 1 for r in results)
    assert all(r.date == "2025-10-02" for r in results)
    # every played match distributes points (no phantom 0-0 in this index)
    assert all(r.home_points and r.away_points for r in results)
    furies = next(r for r in results if "The Furies" in (r.home, r.away))
    pts = {furies.home: furies.home_points, furies.away: furies.away_points}
    assert pts == {"The Furies": 57, "Trap Gods": 38}


def _seed(conn, season, did, names):
    conn.execute("INSERT INTO divisions (division_id) VALUES (?)", (did,))
    for n in names:
        conn.execute("INSERT INTO teams (division_id, name, season) VALUES (?, ?, ?)",
                     (did, n, season))
    conn.commit()
    return lambda n: conn.execute(
        "SELECT team_id FROM teams WHERE name = ?", (n,)).fetchone()[0]


def test_load_match_results_aligns_to_schedule_and_skips_0_0():
    conn = connect(":memory:")
    init_db(conn)
    season, did = "test-season", 1
    tid = _seed(conn, season, did,
                ["The Furies", "Trap Gods", "Ed's Balls", "Pocket Predators"])
    # Scheduled orientation: Furies HOME vs Trap Gods AWAY; Ed's HOME vs Predators.
    conn.execute("INSERT INTO matches (division_id, season, round, home_team_id, away_team_id)"
                 " VALUES (?, ?, 1, ?, ?)", (did, season, tid("The Furies"), tid("Trap Gods")))
    conn.execute("INSERT INTO matches (division_id, season, round, home_team_id, away_team_id)"
                 " VALUES (?, ?, 1, ?, ?)", (did, season, tid("Ed's Balls"), tid("Pocket Predators")))
    conn.commit()

    rep = load_match_results(conn, [
        # index lists this pair AWAY-first — alignment must follow the schedule.
        MatchResult(1, "2025-10-02", "Trap Gods", 38, "The Furies", 57),
        MatchResult(1, "2025-10-02", "Ed's Balls", 0, "Pocket Predators", 0),  # not played
    ], season=season, division_id=did)
    assert rep == {"results": 2, "loaded": 1, "unresolved": 0, "skipped": 1}

    played = conn.execute("SELECT home_points, away_points FROM matches WHERE home_team_id = ?",
                          (tid("The Furies"),)).fetchone()
    assert (played["home_points"], played["away_points"]) == (57, 38)  # not (38, 57)
    pending = conn.execute("SELECT home_points, away_points FROM matches WHERE home_team_id = ?",
                           (tid("Ed's Balls"),)).fetchone()
    assert pending["home_points"] is None and pending["away_points"] is None  # 0-0 left unset


def test_load_match_results_counts_unresolved_team():
    conn = connect(":memory:")
    init_db(conn)
    season, did = "test-season", 2
    tid = _seed(conn, season, did, ["The Furies", "Trap Gods"])
    conn.execute("INSERT INTO matches (division_id, season, round, home_team_id, away_team_id)"
                 " VALUES (?, ?, 1, ?, ?)", (did, season, tid("The Furies"), tid("Trap Gods")))
    conn.commit()
    rep = load_match_results(conn, [
        MatchResult(1, "2025-10-02", "The Furies", 57, "Ghosts", 38),  # 'Ghosts' unknown
    ], season=season, division_id=did)
    assert rep["loaded"] == 0 and rep["unresolved"] == 1
