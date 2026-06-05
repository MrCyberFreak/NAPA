"""Profile RIVALS/H2H parser + pairing_history loader tests (real fixtures)."""

from __future__ import annotations

from pathlib import Path

import pytest

from src.db import connect, load_rivals, pairing_coverage
from src.parse.profile import parse_profile_rivals, parse_h2h_summary

REPO = Path(__file__).resolve().parents[1]
RIVALS = REPO / "fixtures" / "profile_rivals.html"
H2H = REPO / "fixtures" / "profile_h2h.html"

pytestmark = pytest.mark.skipif(not RIVALS.exists(), reason="no profile fixtures")


def _read(p):
    return p.read_text(encoding="utf-8", errors="replace")


def test_parse_rivals_list():
    subject, rivals = parse_profile_rivals(_read(RIVALS))
    assert subject == "10063698"               # Sam Trojanovich
    assert len(rivals) == 62                    # lifetime opponents
    assert all(len(r.rival_id) == 8 and r.rival_id.isdigit() for r in rivals)
    assert ("10071539", "Aaron Allen") in [(r.rival_id, r.name) for r in rivals]


def test_h2h_summary():
    h = parse_h2h_summary(_read(H2H))
    assert h.total_matches == 31
    assert h.per_game.get(8) == (10, 3)         # 8-ball lifetime H2H W-L


def test_load_rivals_into_pairing_history():
    conn = connect(":memory:")
    subject, rivals = parse_profile_rivals(_read(RIVALS))
    n = load_rivals(conn, subject, rivals, captured_date="2026-06-05")
    assert n == 62
    cov = pairing_coverage(conn)
    assert cov["subjects"] == 1
    assert cov["directed_edges"] == 62
    assert cov["distinct_pairings"] == 62       # one subject -> 62 unique pairs
    # idempotent
    load_rivals(conn, subject, rivals)
    assert conn.execute("SELECT COUNT(*) FROM pairing_history").fetchone()[0] == 62


RIVAL_DD = REPO / "fixtures" / "profile_rival_h2h.html"


@pytest.mark.skipif(not RIVAL_DD.exists(), reason="no rival drill-down fixture")
def test_parse_rival_h2h_and_load():
    from src.parse.profile import parse_rival_h2h
    from src.db import connect, update_pairing_h2h
    pg = parse_rival_h2h(_read(RIVAL_DD))
    assert pg[8] == (2, 1, 0, 2)        # Sam vs Aaron Allen: 8-ball 2 played, 1 lag, 0-2
    conn = connect(":memory:")
    update_pairing_h2h(conn, "10063698", "10071539", pg, rival_name="Aaron Allen")
    row = conn.execute(
        "SELECT total_matches, lags_won, g8_w, g8_l FROM pairing_history "
        "WHERE player_id='10063698' AND rival_id='10071539'").fetchone()
    assert row["total_matches"] == 2 and row["lags_won"] == 1
    assert row["g8_w"] == 0 and row["g8_l"] == 2
