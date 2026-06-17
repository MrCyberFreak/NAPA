"""Per-player career TOURNAMENT-MATCHES parser + loader tests (xTab=24).

Pinned to the real browser capture tests/data/tournament_24_10063698.html
(player 10063698 = Sam Trojanovich, xTab=24 / Tournaments > View All, start=0 =
page 1), plus inline-HTML edge-shape tests and the idempotency assertions that
mirror the match_history build's natural-key lesson (a re-harvest after a new
match prepends MUST NOT duplicate prior matches).
"""

from __future__ import annotations

from pathlib import Path

import pytest

from src.db import connect, init_db, load_tournament_matches
from src.parse.tournament import (_game_type_from_event, parse_tournament,
                                   parse_tournament_file)

REPO = Path(__file__).resolve().parents[1]
FIXTURE = REPO / "tests" / "data" / "tournament_24_10063698.html"

pytestmark = pytest.mark.skipif(
    not FIXTURE.exists(), reason="no pinned tournaments capture")


def _page():
    return parse_tournament_file(FIXTURE)


# --------------------------------------------------------------------------- #
# Parser — against the pinned real capture
# --------------------------------------------------------------------------- #

def test_subject_count_and_summary():
    subject, page = _page()
    assert subject == "10063698"          # profile owner = id in the URL
    assert page.source_tab == 24
    assert page.source_start == 0
    # 10 real match tables; the aggregate-summary table AND the 10 nested modal
    # tables (which repeat the players/RACE/SCORE rows) are excluded by the
    # bgcolor=002664 discriminator. 21 .table-bordered = 1 summary + 10 + 10.
    assert len(page.matches) == 10
    # Aggregate summary appears once, on the first page only.
    assert page.summary == {"total": 19, "wins": 9, "losses": 10, "win_pct": 47.4}


def test_next_start_pagination_detected():
    _, page = _page()
    assert page.next_start == 10          # NEXT>>> link &start=10 (page 1 of 2)


def test_first_match_left_subject_fields():
    _, page = _page()
    m = page.matches[0]                   # newest first
    assert m.tournament_name == "2025 NAPA CUESPEED MILE HIGH TRIFECTA"
    assert m.event_name == "OPEN 8-BALL CHAMPIONSHIP"
    assert m.game_type == 8               # derived from the event text
    assert m.played_date == "2025-08-09"  # "Played: Saturday, Aug 09, 2025"
    assert m.subject_side == "home"       # subject Sam is the LEFT column here
    assert m.subject_name == "Sam Trojanovich"
    assert m.opponent_name == "Josh Miller"
    assert m.subject_location == "Broomfield, Colorado"
    assert m.opponent_location == "Broomfield, Colorado"
    assert (m.subject_race, m.opp_race) == (5, 6)
    assert (m.subject_score, m.opp_score) == (2, 6)
    assert m.result == "L"                # subject (left) score 2 is red = LOST
    assert m.source_tab == 24 and m.source_start == 0 and m.page_index == 0


def test_third_match_right_subject_fields():
    _, page = _page()
    m = page.matches[2]                   # "Chris Sakich vs. Sam Trojanovich"
    assert m.tournament_name == "2024 NAPA NORTH AMERICAN OPEN CHAMPIONSHIPS"
    assert m.event_name == "OPEN 8-BALL CHAMPIONSHIP"
    assert m.game_type == 8
    assert m.played_date == "2024-12-07"
    assert m.subject_side == "away"       # subject is the RIGHT column here
    assert m.subject_name == "Sam Trojanovich"
    assert m.opponent_name == "Chris Sakich"
    # Subject (right) score 4 is red -> L; opponent (left) 6 is green.
    assert (m.subject_race, m.opp_race) == (6, 6)
    assert (m.subject_score, m.opp_score) == (4, 6)
    assert m.result == "L"


def test_subject_perspective_win_on_right():
    # idx 7: "Uttam Budathoki vs. Sam Trojanovich" — subject is RIGHT and WON
    # (the right SCORE font is green). Confirms perspective wiring on a win.
    _, page = _page()
    wins = [m for m in page.matches if m.result == "W"]
    assert wins, "the capture has tournament wins"
    for m in wins:
        # On a win the subject's score is at least their race (race reached).
        assert m.subject_score is not None and m.subject_race is not None
        assert m.subject_score >= m.subject_race
    # The subject's name is the owner on every kept row; every match has a side.
    for m in page.matches:
        assert m.subject_name == "Sam Trojanovich"
        assert m.subject_side in ("home", "away")
        assert m.game_type == 8           # this capture is all 8-ball


# --------------------------------------------------------------------------- #
# Parser — game-type derivation + inline edge shapes
# --------------------------------------------------------------------------- #

def test_game_type_from_event_vocabulary():
    assert _game_type_from_event("OPEN 8-BALL CHAMPIONSHIP") == 8
    assert _game_type_from_event("LADIES 9-BALL CHAMPIONSHIP") == 9
    assert _game_type_from_event("SENIORS 10-BALL CHAMPIONSHIP") == 10
    assert _game_type_from_event("OPEN 7-BALL CHAMPIONSHIP") == 7
    assert _game_type_from_event("OPEN FAST 8 CHAMPIONSHIP") == "Fast8"
    assert _game_type_from_event("OPEN LAGGER'S CHOICE CHAMPIONSHIP") == "LC"
    # Table-size qualifiers strip to the same game type.
    assert _game_type_from_event("OPEN BAR BOX 10-BALL CHAMPIONSHIP") == 10
    assert _game_type_from_event("OPEN BIG TABLE 10-BALL CHAMPIONSHIP") == 10
    assert _game_type_from_event(None) is None


def test_game_type_unknown_token_raises():
    # A NEW event type must be caught, not silently NULLed (CLAUDE.md grid rule).
    with pytest.raises(ValueError):
        _game_type_from_event("OPEN ONE-POCKET CHAMPIONSHIP")


def _match_html(tourn, event, played, left, right, *, lrace=5, rrace=5,
                lscore=5, rscore=4, lcolor="green", rcolor="red"):
    return f"""
    <table class="table table-bordered"><tbody>
      <tr bgcolor="002664"><td align="center" colspan="3">
        <font color="WHITE"><strong>{tourn}</strong></font></td></tr>
      <tr bgcolor="002664"><td align="center" colspan="3"><font color="WHITE">
        {event}<br><small>Played: {played}</small></font></td></tr>
      <tr bgcolor="EEEEEE"><td width="45%" align="RIGHT">{left}
        <br><small>Broomfield, Colorado</small></td>
        <td width="10%" align="center">vs.</td>
        <td width="45%">{right}<br><small>Denver, Colorado</small></td></tr>
      <tr bgcolor="EEEEEE"><td align="RIGHT">{lrace}</td>
        <td align="CENTER"><strong>RACE</strong></td>
        <td align="LEFT">{rrace}</td></tr>
      <tr><td align="RIGHT" bgcolor="DDDDDD"><strong>
        <font color="{lcolor}">{lscore}</font></strong></td>
        <td align="CENTER" bgcolor="EEEEEE"><strong>SCORE</strong></td>
        <td align="LEFT" bgcolor="DDDDDD"><strong>
        <font color="{rcolor}">{rscore}</font></strong></td></tr>
      <tr><td align="CENTER" colspan="3"><small>
        <a href="#">[more match details]</a></small></td></tr>
    </tbody></table>"""


def _page_html(matches, *, owner="Alpha Beta", pid="10000001", next_start=None):
    body = "".join(_match_html(*m) for m in matches)
    nxt = (f'<div align="CENTER"><a href="stats.php?playerID={pid}&xTab=24'
           f'&start={next_start}"><strong>NEXT&gt;&gt;&gt;</strong></a></div>'
           if next_start is not None else "")
    return (f'<html><body><a href="stats.php?playerID={pid}">Owner</a>'
            f'<h2>{owner}</h2>' + body + nxt + '</body></html>')


def test_subject_side_none_when_name_unmatched():
    # Owner display name matches neither side (sub / variant) -> side None, but the
    # row is KEPT (defaults subject=left so it is still keyed). Mirrors match_history.
    html = _page_html(
        [("2025 X OPEN", "OPEN 9-BALL CHAMPIONSHIP", "Friday, May 02, 2025",
          "Carl Doe", "Dave Roe")], owner="Nobody Here")
    subject, page = parse_tournament(html)
    assert len(page.matches) == 1
    m = page.matches[0]
    assert m.subject_side is None
    assert m.result is None               # no perspective without a side
    assert m.game_type == 9
    # Defaulted to left so the natural key is still populated, never dropped.
    assert m.subject_name == "Carl Doe" and m.opponent_name == "Dave Roe"


def test_modal_and_summary_not_counted_as_matches():
    # A page with a summary table + a match + the match's modal-shaped table:
    # only the 002664-bannered match is counted.
    html = """<html><body>
      <a href="stats.php?playerID=10000001">Owner</a><h2>Alpha Beta</h2>
      <table class="table table-bordered"><tbody>
        <tr bgcolor="BB133E"><td><font color="WHITE">TOURNAMENT MATCHES</font></td></tr>
        <tr bgcolor="b4f596"><td>TOURNAMENT MATCHES: 1</td></tr>
      </tbody></table>""" + _match_html(
        "2025 Y OPEN", "OPEN 8-BALL CHAMPIONSHIP", "Saturday, Jun 01, 2024",
        "Alpha Beta", "Rival Z") + """
      <table class="table table-bordered"><tbody>
        <tr bgcolor="EEEEEE"><td align="RIGHT">Alpha Beta</td><td>vs.</td>
          <td>Rival Z</td></tr>
        <tr bgcolor="EEEEEE"><td>5</td><td><strong>RACE</strong></td><td>4</td></tr>
        <tr><td bgcolor="green"><font color="white">5</font></td>
          <td><strong>SCORE</strong></td>
          <td bgcolor="red"><font color="white">4</font></td></tr>
      </tbody></table></body></html>"""
    _, page = parse_tournament(html)
    assert len(page.matches) == 1         # modal + summary excluded
    assert page.summary == {"total": 1, "wins": None, "losses": None, "win_pct": None}


# --------------------------------------------------------------------------- #
# Loader — idempotency + natural key (the match_history lesson)
# --------------------------------------------------------------------------- #

def test_load_idempotent_reload():
    conn = connect(":memory:")
    init_db(conn)
    subject, page = _page()
    rep = load_tournament_matches(conn, subject, page.matches, "2026-06-16")
    assert rep["loaded"] == 10 and rep["skipped"] == 0
    assert conn.execute("SELECT COUNT(*) FROM tournament_matches").fetchone()[0] == 10
    # Reload the same page -> upserts in place, never doubles.
    load_tournament_matches(conn, subject, page.matches, "2026-06-16")
    assert conn.execute("SELECT COUNT(*) FROM tournament_matches").fetchone()[0] == 10


def test_load_persists_subject_perspective_fields():
    conn = connect(":memory:")
    init_db(conn)
    subject, page = _page()
    load_tournament_matches(conn, subject, page.matches, "2026-06-16")
    row = conn.execute(
        """SELECT result, subject_side, game_type, subject_score, opp_score,
                  subject_race, opp_race, event_name, source_tab, captured_date
           FROM tournament_matches
           WHERE played_date='2025-08-09' AND opponent_name='Josh Miller'""").fetchone()
    assert row["result"] == "L"
    assert row["subject_side"] == "home"
    assert row["game_type"] == "8"        # stored as TEXT (variants share the column)
    assert (row["subject_score"], row["opp_score"]) == (2, 6)
    assert (row["subject_race"], row["opp_race"]) == (5, 6)
    assert row["event_name"] == "OPEN 8-BALL CHAMPIONSHIP"
    assert row["source_tab"] == 24
    assert row["captured_date"] == "2026-06-16"


def test_reharvest_after_new_match_is_idempotent():
    # WHY the key is the natural identity, NOT (source_start, page_index): the
    # source lists matches newest-first, so a newly-played match PREPENDS and
    # shifts every prior match's page position. A stream-position key would
    # re-insert all the shifted matches as new rows; the natural key upserts them
    # in place. This is the regression the league match_history build hit.
    conn = connect(":memory:")
    init_db(conn)
    # First harvest: two matches (A newest, B older).
    h1 = _page_html([
        ("2025 STATE", "OPEN 8-BALL CHAMPIONSHIP", "Saturday, May 10, 2025",
         "Alpha Beta", "Rival A"),
        ("2025 STATE", "OPEN 8-BALL CHAMPIONSHIP", "Saturday, May 03, 2025",
         "Alpha Beta", "Rival B"),
    ])
    s1, p1 = parse_tournament(h1)
    load_tournament_matches(conn, s1, p1.matches, "2025-05-11")
    assert conn.execute("SELECT COUNT(*) FROM tournament_matches").fetchone()[0] == 2
    # Second harvest after a NEW match C is played — it prepends, shifting A,B down.
    h2 = _page_html([
        ("2025 STATE", "OPEN 8-BALL CHAMPIONSHIP", "Saturday, May 17, 2025",
         "Alpha Beta", "Rival C"),     # NEW, page_index 0
        ("2025 STATE", "OPEN 8-BALL CHAMPIONSHIP", "Saturday, May 10, 2025",
         "Alpha Beta", "Rival A"),     # was idx0, now idx1
        ("2025 STATE", "OPEN 8-BALL CHAMPIONSHIP", "Saturday, May 03, 2025",
         "Alpha Beta", "Rival B"),     # was idx1, now idx2
    ])
    s2, p2 = parse_tournament(h2)
    load_tournament_matches(conn, s2, p2.matches, "2025-05-18")
    # Exactly 3 distinct matches — A and B were NOT duplicated despite shifting.
    assert conn.execute("SELECT COUNT(*) FROM tournament_matches").fetchone()[0] == 3
    opps = {r[0] for r in conn.execute(
        "SELECT opponent_name FROM tournament_matches")}
    assert opps == {"Rival A", "Rival B", "Rival C"}


def test_same_natural_key_collapses_like_match_history():
    # KNOWN LIMITATION (identical to match_history/games): two matches sharing the
    # ENTIRE natural key (subject, date, tournament, opponent, event) collapse to
    # one row — the source exposes no per-match id. Accepted for re-harvest
    # idempotency. (event_name in the key keeps a same-day 8 vs 9-ball pairing
    # against the same opponent from collapsing.)
    conn = connect(":memory:")
    init_db(conn)
    html = _page_html([
        ("2025 STATE", "OPEN 8-BALL CHAMPIONSHIP", "Saturday, Jun 07, 2025",
         "Alpha Beta", "Carl Doe", ),
        ("2025 STATE", "OPEN 8-BALL CHAMPIONSHIP", "Saturday, Jun 07, 2025",
         "Alpha Beta", "Carl Doe"),    # same natural key
    ])
    subject, page = parse_tournament(html)
    assert len(page.matches) == 2                      # parser keeps both raw rows
    rep = load_tournament_matches(conn, subject, page.matches, "2026-06-16")
    assert rep["loaded"] == 2 and rep["skipped"] == 0  # both attempted
    assert conn.execute(
        "SELECT COUNT(*) FROM tournament_matches").fetchone()[0] == 1  # collapsed
    # A different event vs the same opponent same day does NOT collapse.
    html2 = _page_html([
        ("2025 STATE", "OPEN 9-BALL CHAMPIONSHIP", "Saturday, Jun 07, 2025",
         "Alpha Beta", "Carl Doe"),
    ])
    s2, p2 = parse_tournament(html2)
    load_tournament_matches(conn, s2, p2.matches, "2026-06-16")
    assert conn.execute(
        "SELECT COUNT(*) FROM tournament_matches").fetchone()[0] == 2


def test_load_skips_rows_missing_key_columns():
    # A row with no opponent name / date can't form the PK -> skipped + counted.
    conn = connect(":memory:")
    init_db(conn)
    html = _page_html(
        [("2025 X", "OPEN 8-BALL CHAMPIONSHIP", "Saturday, Jun 01, 2025",
          "Alpha Beta", "")], owner="Alpha Beta")
    subject, page = parse_tournament(html)
    rep = load_tournament_matches(conn, subject, page.matches)
    assert rep["loaded"] == 0 and rep["skipped"] == 1
    assert conn.execute("SELECT COUNT(*) FROM tournament_matches").fetchone()[0] == 0


def test_load_no_subject_is_noop():
    conn = connect(":memory:")
    init_db(conn)
    rep = load_tournament_matches(conn, "", [])
    assert rep["loaded"] == 0
    assert conn.execute("SELECT COUNT(*) FROM tournament_matches").fetchone()[0] == 0
