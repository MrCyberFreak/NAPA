"""Phase 2 DB tests: load the (synthetic) roster, verify history + queries."""

from __future__ import annotations

import dataclasses
from pathlib import Path

from src.db import (
    connect,
    csr_history,
    load_roster,
    team_depth,
    team_roster_latest,
)
from src.parse.roster import parse_roster_file

REPO = Path(__file__).resolve().parents[1]
SYNTHETIC = REPO / "tests" / "data" / "synthetic_roster_grid.html"
SEASON = "test-season"


def _load_once(date="2026-06-04"):
    conn = connect(":memory:")
    players = parse_roster_file(SYNTHETIC)
    load_roster(conn, players, captured_date=date, season=SEASON)
    return conn, players


def test_load_populates_players_teams_members():
    conn, players = _load_once()
    n_players = conn.execute("SELECT COUNT(*) FROM players").fetchone()[0]
    n_teams = conn.execute("SELECT COUNT(*) FROM teams").fetchone()[0]
    n_members = conn.execute("SELECT COUNT(*) FROM team_members").fetchone()[0]
    n_caps = conn.execute("SELECT SUM(is_captain) FROM team_members").fetchone()[0]
    assert n_players == 82
    assert n_teams == 10
    assert n_members == 82
    assert n_caps == 10  # exactly one captain per team


def test_snapshot_is_append_only_by_date():
    # First capture.
    conn, players = _load_once(date="2026-06-04")
    # A later capture with shifted ratings (simulate Friday recompute drift).
    drifted = [dataclasses.replace(p, csr_8=p.csr_8 + 3) for p in players]
    load_roster(conn, drifted, captured_date="2026-06-05", season=SEASON)

    # Players didn't duplicate; snapshots grew to two per player.
    assert conn.execute("SELECT COUNT(*) FROM players").fetchone()[0] == 82
    assert conn.execute("SELECT COUNT(*) FROM skill_snapshots").fetchone()[0] == 164

    hist = csr_history(conn, "10000001")
    assert [r["captured_date"] for r in hist] == ["2026-06-04", "2026-06-05"]
    assert hist[1]["csr_8"] - hist[0]["csr_8"] == 3  # drift captured


def test_reload_same_date_is_idempotent():
    conn, players = _load_once(date="2026-06-04")
    load_roster(conn, players, captured_date="2026-06-04", season=SEASON)
    assert conn.execute("SELECT COUNT(*) FROM skill_snapshots").fetchone()[0] == 82
    assert conn.execute("SELECT COUNT(*) FROM team_members").fetchone()[0] == 82


def test_team_depth_reflects_7_to_11_distribution():
    conn, _ = _load_once()
    depth = {r["team"]: r["roster_size"] for r in team_depth(conn, season=SEASON)}
    assert max(depth.values()) == 11
    assert min(depth.values()) == 7
    assert sum(depth.values()) == 82
    assert depth["Cheat Code Felt Billiards #6"] == 11


def test_team_roster_latest_returns_ratings():
    conn, _ = _load_once()
    rows = team_roster_latest(conn, "Pocket Pals #1", season=SEASON)
    assert len(rows) == 7
    assert rows[0]["is_captain"] == 1  # captain sorted first
    for r in rows:
        assert all(r[c] is not None for c in ("csr_8", "csr_9", "csr_10"))
