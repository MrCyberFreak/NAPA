"""Per-player career match-history parser + loader tests.

Pinned to the real browser capture tests/data/match_history_8ball_10063698.html
(player 10063698 = Sam Trojanovich, xTab=2 / 8-ball, start=0 = page 1), plus
inline-HTML edge-shape tests and an idempotent-reload assertion.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from src.db import connect, init_db, load_match_history
from src.parse.match_history import (TAB_GAME_TYPE, parse_match_history,
                                     parse_match_history_file)

REPO = Path(__file__).resolve().parents[1]
FIXTURE = REPO / "tests" / "data" / "match_history_8ball_10063698.html"

pytestmark = pytest.mark.skipif(
    not FIXTURE.exists(), reason="no pinned match-history capture")


def _page():
    return parse_match_history_file(FIXTURE, source_tab=2, source_start=0)


# --------------------------------------------------------------------------- #
# Parser — against the pinned real capture
# --------------------------------------------------------------------------- #

def test_subject_game_type_and_count():
    subject, page = _page()
    assert subject == "10063698"          # profile owner = id in the URL
    assert page.game_type == 8            # from the tab, not the page body
    assert page.source_tab == 2
    # 9 real match tables; the tournament-performance interstitial is excluded.
    assert len(page.matches) == 9


def test_next_start_pagination_detected():
    _, page = _page()
    assert page.next_start == 10          # NEXT>>> link &start=10


def test_first_match_fields():
    _, page = _page()
    m = page.matches[0]                   # newest first = Apr. 30 '26
    assert m.result == "L"                # subject perspective
    assert m.played_date == "2026-04-30"
    assert m.subject_csr == 95
    assert m.division_id == 13077         # current season
    assert m.division_name == 'Thursday "Big Table Felt" No Limit LC League'
    assert m.venue == "Felt Billiards"
    assert m.home_player_name == "Austin Trail"
    assert m.away_player_name == "Sam Trojanovich"
    assert m.subject_side == "away"       # subject is the away column here
    assert m.opponent_name == "Austin Trail"
    assert m.is_makeup is True            # "(mm)" small tag on the MATCH label
    assert (m.home_race, m.away_race) == (3, 9)
    assert (m.home_wins, m.away_wins) == (3, 4)
    assert (m.home_score, m.away_score) == (14, 3)
    assert m.source_start == 0


def test_second_match_fields_prior_season_division():
    _, page = _page()
    m = page.matches[1]                   # Sep. 11 '25
    assert m.result == "W"
    assert m.played_date == "2025-09-11"
    assert m.subject_csr == 96
    assert m.division_id == 12399         # PRIOR-SEASON division, kept (not filtered)
    assert m.division_name == 'Thursday "Big Table Felt" No Limit LC League'
    assert m.home_player_name == "Sam Trojanovich"
    assert m.away_player_name == "Matthew Winfield"
    assert m.subject_side == "home"
    assert m.opponent_name == "Matthew Winfield"
    assert m.is_makeup is False
    assert (m.home_race, m.away_race) == (3, 8)
    assert (m.home_wins, m.away_wins) == (3, 6)
    assert (m.home_score, m.away_score) == (14, 4)


def test_subject_perspective_result_vs_score():
    # Apr.30: subject (away) result is 'L' even though away #WINS (4) > home (3) —
    # the W/L letter is authoritative, NOT the racks. Confirms perspective wiring.
    _, page = _page()
    m = page.matches[0]
    assert m.subject_side == "away" and m.result == "L"
    assert m.away_wins > m.home_wins      # racks alone do NOT decide the W/L


def test_makeup_flags_across_page():
    _, page = _page()
    # Apr.30 (idx 0) and Jul.25 (idx 4) are the two makeups; the rest are not.
    assert [m.is_makeup for m in page.matches] == \
        [True, False, False, False, True, False, False, False, False]


def test_every_match_has_subject_side_and_csr_in_capture():
    _, page = _page()
    for m in page.matches:
        assert m.subject_side in ("home", "away")  # subject is always one of the two
        assert m.subject_csr is not None           # this capture has CSR everywhere
        assert m.game_type == 8


# --------------------------------------------------------------------------- #
# Parser — inline-HTML edge shapes
# --------------------------------------------------------------------------- #

def test_game_type_from_tab_not_label():
    # The per-game stat label reads '9-B' on tab 3, but game_type comes from the tab.
    _, page = parse_match_history("<html></html>", source_tab=3)
    assert page.game_type == 9
    _, page = parse_match_history("<html></html>", game_type=10)
    assert page.source_tab == 4
    assert TAB_GAME_TYPE == {2: 8, 3: 9, 4: 10}


def test_no_match_tables_yields_zero_rows_and_no_next():
    # Empty-tab shape: banner + summary, no width:950px header, no NEXT link.
    html = """<html><body>
      <a href="stats.php?playerID=10063698">Owner</a>
      <h2>Owner Name</h2>
      <table><tr><td bgcolor="BB133E">LEAGUE 9-BALL MATCHES</td></tr></table>
      <table><tr><td>League Matches:</td><td>0</td></tr></table>
    </body></html>"""
    subject, page = parse_match_history(html, source_tab=3, source_start=0)
    assert subject == "10063698"
    assert page.matches == []
    assert page.next_start is None


def test_tournament_interstitial_skipped():
    # A nested colspan=9 tournament-performance table has no width:950px header row.
    html = """<html><body><h2>X</h2>
      <table><tr><td bgcolor="yellow"><table><tr>
        <td colspan="9">TOURNAMENT PERFORMANCE New SL: 93</td></tr></table></td></tr></table>
    </body></html>"""
    _, page = parse_match_history(html, source_tab=2)
    assert page.matches == []


def test_subject_side_none_when_name_unmatched():
    # Owner display name matches neither MATCH name (sub / variant) -> side None.
    html = """<html><body>
      <a href="stats.php?playerID=10000001">Owner</a><h2>Nobody Here</h2>
      <table class="table-bordered"><tbody>
        <tr style="width:950px">
          <th bgcolor="green"><span>W</span></th>
          <th>Jun. 01 '25</th><th><span>CSR: 80</span></th></tr>
        <tr><td><strong>VENUE</strong></td><td colspan="2">Some Hall</td></tr>
        <tr><td><strong>DIVISION</strong></td><td colspan="2">
          <a href="division.php?did=13077"><strong>13077 Test League</strong></a></td></tr>
        <tr><td><strong>MATCH</strong></td>
          <td>Alpha<br>Beta</td><td>Gamma<br>Delta</td></tr>
        <tr><td><strong>RACE</strong></td><td>5</td><td>5</td></tr>
        <tr><td><strong># WINS</strong></td><td>5</td><td>3</td></tr>
        <tr><td><strong>SCORE</strong></td><td>10</td><td>6</td></tr>
      </tbody></table></body></html>"""
    _, page = parse_match_history(html, source_tab=2)
    assert len(page.matches) == 1
    m = page.matches[0]
    assert m.subject_side is None
    assert m.home_player_name == "Alpha Beta" and m.away_player_name == "Gamma Delta"
    assert m.result == "W"                 # raw W/L kept even with side unknown
    assert m.division_id == 13077          # href did wins


# --------------------------------------------------------------------------- #
# Loader — idempotency + key
# --------------------------------------------------------------------------- #

def test_load_match_history_idempotent():
    conn = connect(":memory:")
    init_db(conn)
    subject, page = _page()
    rep = load_match_history(conn, subject, page.game_type, page.matches, "2026-06-16")
    assert rep["loaded"] == 9 and rep["skipped"] == 0
    assert conn.execute("SELECT COUNT(*) FROM match_history").fetchone()[0] == 9
    # Reload the same page -> overwrites in place, never doubles.
    load_match_history(conn, subject, page.game_type, page.matches, "2026-06-16")
    assert conn.execute("SELECT COUNT(*) FROM match_history").fetchone()[0] == 9


def test_load_match_history_persists_fields():
    conn = connect(":memory:")
    init_db(conn)
    subject, page = _page()
    load_match_history(conn, subject, page.game_type, page.matches, "2026-06-16")
    row = conn.execute(
        """SELECT result, subject_csr, division_id, division_name, venue,
                  subject_side, is_makeup, source_tab, source_start, captured_date
           FROM match_history WHERE played_date='2026-04-30'""").fetchone()
    assert row["result"] == "L"
    assert row["subject_csr"] == 95
    assert row["division_id"] == 13077
    assert row["venue"] == "Felt Billiards"
    assert row["subject_side"] == "away"
    assert row["is_makeup"] == 1
    assert row["source_tab"] == 2
    assert row["source_start"] == 0
    assert row["captured_date"] == "2026-06-16"
    # Prior-season division row is stored, not filtered.
    assert conn.execute(
        "SELECT COUNT(*) FROM match_history WHERE division_id=12399").fetchone()[0] == 8


def _match_html(res, bg, date, home, away, *, mm="", hw=5, aw=2, hs=10, as_=4):
    return f"""
      <table class="table-bordered"><tbody>
        <tr style="width:950px"><th bgcolor="{bg}"><span>{res}</span></th>
          <th>{date}</th><th><span>CSR: 80</span></th></tr>
        <tr><td><strong>DIVISION</strong></td><td colspan="2">
          <a href="division.php?did=13077"><strong>13077 Test League</strong></a></td></tr>
        <tr><td><strong>MATCH{mm}</strong></td><td>{home}</td><td>{away}</td></tr>
        <tr><td><strong>RACE</strong></td><td>5</td><td>5</td></tr>
        <tr><td><strong># WINS</strong></td><td>{hw}</td><td>{aw}</td></tr>
        <tr><td><strong>SCORE</strong></td><td>{hs}</td><td>{as_}</td></tr>
      </tbody></table>"""


def _page_html(matches):
    body = "".join(_match_html(*m) for m in matches)
    return ('<html><body><a href="stats.php?playerID=10000001">Owner</a>'
            '<h2>Alpha Beta</h2>' + body + '</body></html>')


def test_same_opponent_same_date_collapses_like_games():
    # KNOWN LIMITATION (identical to `games`): two matches vs the SAME opponent on
    # the SAME date with the SAME home/away orientation share the entire natural key
    # and the source exposes no per-match id, so they collapse to one row (last load
    # wins). This is the accepted trade-off for re-harvest idempotency.
    conn = connect(":memory:")
    init_db(conn)
    html = _page_html([
        ("W", "green", "Jun. 01 '26", "Alpha Beta", "Carl Doe"),
        ("L", "red", "Jun. 01 '26", "Alpha Beta", "Carl Doe"),  # same key
    ])
    subject, page = parse_match_history(html, source_tab=2)
    assert len(page.matches) == 2                      # parser keeps both raw rows
    rep = load_match_history(conn, subject, page.game_type, page.matches, "2026-06-16")
    assert rep["loaded"] == 2 and rep["skipped"] == 0  # both attempted
    assert conn.execute("SELECT COUNT(*) FROM match_history").fetchone()[0] == 1  # collapsed


def test_reharvest_after_new_match_is_idempotent():
    # WHY the key is the natural identity, NOT (source_start, page_index): matches
    # are listed newest-first, so a newly-played match PREPENDS and shifts every
    # prior match's page position. A stream-position key would re-insert all the
    # shifted matches as new rows on the next harvest; the natural key upserts them
    # in place. This is the regression a stream-position key fails.
    conn = connect(":memory:")
    init_db(conn)
    # First harvest: two matches (A newest, B older).
    h1 = _page_html([
        ("W", "green", "May. 10 '26", "Alpha Beta", "Rival A"),   # page_index 0
        ("L", "red", "May. 03 '26", "Alpha Beta", "Rival B"),     # page_index 1
    ])
    s1, p1 = parse_match_history(h1, source_tab=2)
    load_match_history(conn, s1, p1.game_type, p1.matches, "2026-05-11")
    assert conn.execute("SELECT COUNT(*) FROM match_history").fetchone()[0] == 2
    # Second harvest after a NEW match C is played — it prepends, shifting A,B down.
    h2 = _page_html([
        ("W", "green", "May. 17 '26", "Alpha Beta", "Rival C"),   # NEW, page_index 0
        ("W", "green", "May. 10 '26", "Alpha Beta", "Rival A"),   # was idx0, now idx1
        ("L", "red", "May. 03 '26", "Alpha Beta", "Rival B"),     # was idx1, now idx2
    ])
    s2, p2 = parse_match_history(h2, source_tab=2)
    load_match_history(conn, s2, p2.game_type, p2.matches, "2026-05-18")
    # Exactly 3 distinct matches — A and B were NOT duplicated despite shifting.
    assert conn.execute("SELECT COUNT(*) FROM match_history").fetchone()[0] == 3
    opps = {r[0] for r in conn.execute(
        "SELECT away_player_name FROM match_history")}
    assert opps == {"Rival A", "Rival B", "Rival C"}


def test_load_match_history_skips_rows_missing_key_columns():
    # A row with no opponent name / date can't form the PK -> skipped + counted.
    conn = connect(":memory:")
    init_db(conn)
    html = """<html><body>
      <a href="stats.php?playerID=10000001">Owner</a><h2>Alpha Beta</h2>
      <table class="table-bordered"><tbody>
        <tr style="width:950px"><th bgcolor="green"><span>W</span></th>
          <th>Jun. 01 '25</th><th><span>CSR: 80</span></th></tr>
        <tr><td><strong>DIVISION</strong></td><td colspan="2">
          <a href="division.php?did=13077"><strong>13077 Test League</strong></a></td></tr>
        <tr><td><strong>MATCH</strong></td><td>Alpha<br>Beta</td><td></td></tr>
        <tr><td><strong># WINS</strong></td><td>5</td><td>0</td></tr>
      </tbody></table></body></html>"""
    subject, page = parse_match_history(html, source_tab=2)
    rep = load_match_history(conn, subject, page.game_type, page.matches)
    assert rep["loaded"] == 0 and rep["skipped"] == 1
    assert conn.execute("SELECT COUNT(*) FROM match_history").fetchone()[0] == 0
