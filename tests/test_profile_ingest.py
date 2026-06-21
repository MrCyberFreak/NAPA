"""Incremental profile ingest (db --ingest-profiles): folds harvested profiles
into an EXISTING DB via idempotent upserts, with stat-only change detection.
Pinned to the real 10063698 (Sam Trojanovich) fixtures."""

from __future__ import annotations

import shutil
from pathlib import Path

import pytest

from src.db import connect, init_db, ingest_profiles, pairing_coverage

REPO = Path(__file__).resolve().parents[1]
PID = "10063698"
F = REPO / "fixtures"
MAIN = F / "profile_main.html"

pytestmark = pytest.mark.skipif(not MAIN.exists(), reason="no profile fixtures")


def _profile_dir(root: Path) -> Path:
    """Assemble a real harvested-shaped profile dir for PID under root/."""
    d = root / PID
    d.mkdir(parents=True)
    shutil.copyfile(MAIN, d / "main.html")
    shutil.copyfile(F / "profile_rivals.html", d / "rivals.html")
    shutil.copyfile(F / "profile_trends.html", d / "trends.html")
    shutil.copyfile(F / "profile_rival_record.html", d / "rival_10071539.html")
    shutil.copyfile(REPO / "tests/data/match_history_8ball_10063698.html", d / "match_2_0.html")
    shutil.copyfile(REPO / "tests/data/tournament_24_10063698.html", d / "match_24_0.html")
    return d


def _empty_db(tmp_path: Path) -> Path:
    db = tmp_path / "napa.db"
    conn = connect(str(db))
    init_db(conn)
    conn.close()
    return db


def _counts(db: Path) -> dict:
    conn = connect(str(db))
    try:
        return {t: conn.execute(f"SELECT COUNT(*) FROM {t}").fetchone()[0]
                for t in ("players", "pairing_history", "player_form",
                          "match_history", "tournament_matches")}
    finally:
        conn.close()


def test_ingest_profiles_loads_player(tmp_path):
    proot = tmp_path / "profiles"
    _profile_dir(proot)
    db = _empty_db(tmp_path)
    rep = ingest_profiles(db, player_ids=[PID], profiles_root=proot, force=True)
    assert rep["loaded"] == 1 and rep["failed"] == 0

    conn = connect(str(db))
    cov = pairing_coverage(conn)
    assert cov["directed_edges"] == 62                      # the RIVALS list
    row = conn.execute("SELECT total_matches, g8_l FROM pairing_history "
                       "WHERE player_id=? AND rival_id='10071539'", (PID,)).fetchone()
    assert row["total_matches"] == 2 and row["g8_l"] == 2   # the rival drill-down
    form = conn.execute("SELECT lifetime_w, d90_l FROM player_form "
                        "WHERE player_id=?", (PID,)).fetchone()
    assert form["lifetime_w"] == 85 and form["d90_l"] == 3
    peak = conn.execute("SELECT peak_csr_8 FROM players WHERE player_id=?", (PID,)).fetchone()
    assert peak["peak_csr_8"] == 100
    assert conn.execute("SELECT COUNT(*) FROM match_history WHERE subject_player_id=?",
                        (PID,)).fetchone()[0] > 0
    assert conn.execute("SELECT COUNT(*) FROM tournament_matches WHERE subject_player_id=?",
                        (PID,)).fetchone()[0] > 0
    conn.close()


def test_ingest_profiles_idempotent(tmp_path):
    proot = tmp_path / "profiles"
    _profile_dir(proot)
    db = _empty_db(tmp_path)
    ingest_profiles(db, player_ids=[PID], profiles_root=proot, force=True)
    before = _counts(db)
    ingest_profiles(db, player_ids=[PID], profiles_root=proot, force=True)  # again
    assert _counts(db) == before                            # no double-count


def test_ingest_profiles_change_detection(tmp_path):
    proot = tmp_path / "profiles"
    d = _profile_dir(proot)
    db = _empty_db(tmp_path)

    r1 = ingest_profiles(db, player_ids=[PID], profiles_root=proot)   # state on
    assert r1["loaded"] == 1 and r1["skipped_unchanged"] == 0

    r2 = ingest_profiles(db, player_ids=[PID], profiles_root=proot)   # unchanged
    assert r2["loaded"] == 0 and r2["skipped_unchanged"] == 1

    # a new harvested file changes the dir signature -> it reloads
    shutil.copyfile(F / "profile_rival_record.html", d / "rival_99999999.html")
    r3 = ingest_profiles(db, player_ids=[PID], profiles_root=proot)
    assert r3["loaded"] == 1

    # state file lives beside the DB, not in the real data/ dir
    assert (tmp_path / "profiles_ingest_state.json").exists()
