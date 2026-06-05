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


MAIN = REPO / "fixtures" / "profile_main.html"
TRENDS = REPO / "fixtures" / "profile_trends.html"


@pytest.mark.skipif(not MAIN.exists(), reason="no main fixture")
def test_cuespeed_current_and_peak():
    from src.parse.profile import parse_cuespeed
    from src.db import connect, load_cuespeed
    cs = parse_cuespeed(_read(MAIN))
    assert cs.current[8] == (95, "2026-04-30")
    assert cs.peak[8] == (100, "2024-09-19")
    assert cs.peak[9] == (80, "2026-05-07") and cs.peak[10] == (81, "2026-05-14")
    conn = connect(":memory:")
    load_cuespeed(conn, "10063698", cs)
    row = conn.execute("SELECT peak_csr_8, peak_on_8, peak_csr_9 FROM players "
                       "WHERE player_id='10063698'").fetchone()
    assert row["peak_csr_8"] == 100 and row["peak_on_8"] == "2024-09-19" and row["peak_csr_9"] == 80


@pytest.mark.skipif(not TRENDS.exists(), reason="no trends fixture")
def test_trends_form_windows():
    from src.parse.profile import parse_trends
    from src.db import connect, load_trends
    f = parse_trends(_read(TRENDS))
    assert (f.lifetime_played, f.lifetime_w, f.lifetime_l) == (128, 85, 43)
    assert f.lifetime_win_pct == 66 and abs(f.avg_ppm - 11.26) < 1e-6
    assert (f.last10_w, f.last10_l) == (7, 3) and f.last10_assessment == "Highly recommended."
    assert f.d30 == (2, 1, 1) and f.d60 == (5, 3, 2) and f.d90 == (6, 3, 3)
    conn = connect(":memory:")
    load_trends(conn, "10063698", f, captured_date="2026-06-05")
    row = conn.execute("SELECT lifetime_w, last10_assessment, d90_l FROM player_form "
                       "WHERE player_id='10063698'").fetchone()
    assert row["lifetime_w"] == 85 and row["d90_l"] == 3
