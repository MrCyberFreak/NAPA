"""B4 division-scoping: collision safety, A1 name resolution, snapshot merge,
and profile-sourced player_divisions. All in-memory; no fixtures needed."""

from __future__ import annotations

from types import SimpleNamespace

from src.db import (
    _player_teams,
    connect,
    init_db,
    load_profile,
    load_roster,
    load_score_sheets,
    load_schedule,
)
from src.parse.roster import RosterPlayer
from src.parse.schedule import Fixture
from src.parse.weekly_scores import ScoreGame, ScoreSheet

SEASON_A = "2025-26"
SEASON_B = "2026-06-02"
DID_A = 13077
DID_B = 13985


def _rp(team, player, pid, csr8=50, csr9=50, csr10=50, sm=5, captain=False):
    return RosterPlayer(team=team, player=player, player_id=pid, csr_8=csr8,
                        csr_9=csr9, csr_10=csr10, session_matches=sm,
                        is_captain=captain)


def _sheet(home_team, away_team, date, home_player, away_player, game_type=8):
    return ScoreSheet(home_team=home_team, away_team=away_team, date=date, games=[
        ScoreGame(game_type=game_type, home_player=home_player, home_team=home_team,
                  away_player=away_player, away_team=away_team,
                  home_race=3, away_race=3, home_wins=3, away_wins=1),
    ])


def test_same_team_name_two_divisions_two_rows():
    conn = connect(":memory:")
    load_roster(conn, [_rp("Pocket Pals #1", "Alice A", "10000001")],
                "2026-06-01", season=SEASON_A, division_id=DID_A)
    load_roster(conn, [_rp("Pocket Pals #1", "Bob B", "10000002")],
                "2026-06-01", season=SEASON_B, division_id=DID_B)
    rows = conn.execute(
        "SELECT division_id FROM teams WHERE name = 'Pocket Pals #1' ORDER BY division_id"
    ).fetchall()
    assert [r["division_id"] for r in rows] == [DID_A, DID_B]


def test_same_pairing_same_date_two_divisions_two_game_rows():
    conn = connect(":memory:")
    load_roster(conn, [_rp("T1", "Alice A", "10000001"), _rp("T2", "Bob B", "10000002")],
                "2026-06-01", season=SEASON_A, division_id=DID_A)
    load_roster(conn, [_rp("U1", "Alice A", "10000001"), _rp("U2", "Bob B", "10000002")],
                "2026-06-01", season=SEASON_B, division_id=DID_B)
    load_score_sheets(conn, [_sheet("T1", "T2", "2026-06-06", "Alice A", "Bob B")],
                      season=SEASON_A, division_id=DID_A)
    load_score_sheets(conn, [_sheet("U1", "U2", "2026-06-06", "Alice A", "Bob B")],
                      season=SEASON_B, division_id=DID_B)
    rows = conn.execute(
        """SELECT division_id FROM games
           WHERE played_date = '2026-06-06' AND home_player_name = 'Alice A'
           ORDER BY division_id"""
    ).fetchall()
    assert [r["division_id"] for r in rows] == [DID_A, DID_B]


def test_mirror_dedup_stays_within_division():
    conn = connect(":memory:")
    load_score_sheets(conn, [_sheet("T1", "T2", "2026-06-06", "Alice A", "Bob B"),
                             _sheet("T2", "T1", "2026-06-06", "Bob B", "Alice A")],
                      season=SEASON_A, division_id=DID_A)
    n = conn.execute("SELECT COUNT(*) FROM games").fetchone()[0]
    assert n == 1  # the flipped duplicate within the division is deduped


def test_skill_snapshot_merges_partial_game_sets():
    conn = connect(":memory:")
    # 8-ball-only grid first (csr_9/csr_10 unknown there)...
    load_roster(conn, [_rp("U1", "Cara C", "10000003", csr8=90, csr9=None, csr10=None, sm=10)],
                "2026-06-01", season=SEASON_B, division_id=DID_B)
    # ...then a 3-game grid the same day: values must MERGE, not clobber.
    load_roster(conn, [_rp("T1", "Cara C", "10000003", csr8=90, csr9=70, csr10=60, sm=4)],
                "2026-06-01", season=SEASON_A, division_id=DID_A)
    row = conn.execute(
        "SELECT csr_8, csr_9, csr_10 FROM skill_snapshots WHERE player_id = '10000003'"
    ).fetchone()
    assert (row["csr_8"], row["csr_9"], row["csr_10"]) == (90, 70, 60)


def test_csr_disagreement_warns_but_loads(capsys):
    conn = connect(":memory:")
    load_roster(conn, [_rp("T1", "Dan D", "10000004", csr8=80)],
                "2026-06-01", season=SEASON_A, division_id=DID_A)
    result = load_roster(conn, [_rp("U1", "Dan D", "10000004", csr8=85)],
                         "2026-06-01", season=SEASON_B, division_id=DID_B)
    assert result["csr_conflicts"] == 1
    assert "CSR DISAGREEMENT" in capsys.readouterr().out
    row = conn.execute(
        "SELECT csr_8 FROM skill_snapshots WHERE player_id = '10000004'").fetchone()
    assert row["csr_8"] == 85  # last write wins after the warn


def test_name_resolution_prefers_division_roster():
    conn = connect(":memory:")
    # Two distinct players share a name, rostered in different divisions.
    load_roster(conn, [_rp("T1", "Jo Smith", "10000005")],
                "2026-06-01", season=SEASON_A, division_id=DID_A)
    load_roster(conn, [_rp("U1", "Jo Smith", "10000006")],
                "2026-06-01", season=SEASON_A, division_id=DID_B)
    pid_a, teams_a, amb_a = _player_teams(conn, "Jo Smith", SEASON_A, DID_A)
    pid_b, teams_b, amb_b = _player_teams(conn, "Jo Smith", SEASON_A, DID_B)
    assert (pid_a, amb_a) == ("10000005", False) and teams_a == {"T1"}
    assert (pid_b, amb_b) == ("10000006", False) and teams_b == {"U1"}


def test_name_resolution_unique_league_wide_fallback_and_ambiguity():
    conn = connect(":memory:")
    load_roster(conn, [_rp("U1", "Pat Lee", "10000007")],
                "2026-06-01", season=SEASON_B, division_id=DID_B)
    # Not rostered in division A, but unique league-wide: the sub gets their id.
    pid, teams, amb = _player_teams(conn, "Pat Lee", SEASON_A, DID_A)
    assert (pid, teams, amb) == ("10000007", set(), False)
    # A second league-wide player of the same name makes it ambiguous -> NULL.
    load_roster(conn, [_rp("V1", "Pat Lee", "10000008")],
                "2026-06-01", season=SEASON_B, division_id=13298)
    pid, teams, amb = _player_teams(conn, "Pat Lee", SEASON_A, DID_A)
    assert (pid, amb) == (None, True)


def test_unknown_sub_resolves_to_null_not_error():
    conn = connect(":memory:")
    init_db(conn)
    pid, teams, amb = _player_teams(conn, "Total Stranger", SEASON_A, DID_A)
    assert (pid, teams, amb) == (None, set(), False)


def test_load_profile_records_player_divisions():
    conn = connect(":memory:")
    profile = SimpleNamespace(player_id="10000009", name="Eve E", gender=None,
                              home_base=None, member_since=None, as_of="2026-06-10",
                              current_csr=None, divisions=[DID_A, DID_B])
    load_profile(conn, profile)
    rows = conn.execute(
        "SELECT division_id FROM player_divisions WHERE player_id = '10000009' "
        "ORDER BY division_id").fetchall()
    assert [r["division_id"] for r in rows] == [DID_A, DID_B]
    multi = conn.execute(
        """SELECT player_id FROM player_divisions
           GROUP BY player_id HAVING COUNT(*) > 1""").fetchall()
    assert [r["player_id"] for r in multi] == ["10000009"]


def test_schedule_resolves_within_division_only():
    conn = connect(":memory:")
    load_roster(conn, [_rp("The Furies Felt Billiards Team #2", "Flo F", "10000010")],
                "2026-06-01", season=SEASON_A, division_id=DID_A)
    load_roster(conn, [_rp("The Furies Wreckroom Team #3", "Gus G", "10000011")],
                "2026-06-01", season=SEASON_A, division_id=DID_B)
    # Prefix "The Furies" is unique WITHIN each division, so both resolve.
    r = load_schedule(conn, [Fixture(round=1, date="2026-06-06",
                                     home="The Furies", away="The Furies",
                                     location=None, comp_sheet=False)],
                      season=SEASON_A, division_id=DID_A)
    # home == away is degenerate but proves the division-scoped resolver found
    # exactly one candidate (the 13077 team) rather than tripping on 13985's.
    assert r["unresolved"] == 0
