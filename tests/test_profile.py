"""Profile-summary parser + enrichment tests (synthetic fixture)."""

from __future__ import annotations

from pathlib import Path

from src.db import connect, init_db, load_profile, load_roster
from src.parse.profile import parse_profile_file
from src.parse.roster import parse_roster_file

REPO = Path(__file__).resolve().parents[1]
PROFILE = REPO / "tests" / "data" / "synthetic_profile.html"
ROSTER = REPO / "tests" / "data" / "synthetic_roster_grid.html"
SEASON = "test-season"


def test_parse_profile_summary_fields():
    p = parse_profile_file(PROFILE)
    assert p.player_id == "10000001"
    assert p.name == "Alex Stone"
    assert p.gender == "Male"
    assert p.home_base == "Fort Collins, CO"
    assert p.member_since == "2019-03-15"
    assert p.matches_played == 412
    assert p.as_of == "2026-06-04"
    assert p.current_csr == {8: 102, 9: 62, 10: 71}
    assert p.highest_csr == {8: 110, 9: 75, 10: 80}


def test_load_profile_enriches_existing_player():
    conn = connect(":memory:")
    load_roster(conn, parse_roster_file(ROSTER), captured_date="2026-06-04", season=SEASON)
    # Roster gave us the player with no demographics yet.
    before = conn.execute(
        "SELECT gender, home_base FROM players WHERE player_id='10000001'").fetchone()
    assert before["gender"] is None

    load_profile(conn, parse_profile_file(PROFILE))
    after = conn.execute(
        "SELECT name, gender, home_base, member_since FROM players WHERE player_id='10000001'"
    ).fetchone()
    assert after["gender"] == "Male"
    assert after["home_base"] == "Fort Collins, CO"
    assert after["member_since"] == "2019-03-15"
    # Player count unchanged — enrichment, not insertion.
    assert conn.execute("SELECT COUNT(*) FROM players").fetchone()[0] == 82


def test_load_profile_does_not_clobber_with_nulls():
    conn = connect(":memory:")
    init_db(conn)
    load_profile(conn, parse_profile_file(PROFILE))
    # Re-load a profile that's missing gender -> existing gender preserved.
    p = parse_profile_file(PROFILE)
    p.gender = None
    load_profile(conn, p)
    row = conn.execute(
        "SELECT gender FROM players WHERE player_id='10000001'").fetchone()
    assert row["gender"] == "Male"
