"""Self-healing golden-dataset regression harness for the parse->DB pipeline.

Re-builds a scoped napa.db from the COMMITTED raw archive (the same builder the
capture tool froze, see tests/golden/harness.py) for three divisions chosen to
span the fragile parse paths -- 13077 (LC 8/9/10), 13298 (8-ball only), 13986
(adds the "10BP" text game_type) -- and asserts, for match points, racks,
wins/losses/win_pct (lifetime form), and hill-hill:

  1. every captured field is NON-NULL (a silent extraction failure blanks a field),
  2. every value EXACTLY matches the golden baseline (drift / corruption guard),
  3. no category is silently empty (a whole pass producing nothing).

Plus named regression guards for the two silent extraction failures we hit before
(PRs #64/#74): the empty "NO MATCH(ES) PLAYED" score-sheet shell and the
content-aware resume guard that distinguishes a shell from a populated sheet.

Rebaseline only after an intentional, verified pipeline change:
    python -m tools.golden_capture
"""

from __future__ import annotations

from pathlib import Path

import pytest

from src.browser_fetch import _sheet_captured
from src.db import connect, init_db, load_score_sheets
from src.parse.weekly_scores import parse_score_sheet_file
from tests.golden.harness import (build_division_db, extract_division,
                                   load_golden, MATCH_COLS, RACK_COLS,
                                   FORM_COLS, HILL_COLS)

REPO = Path(__file__).resolve().parents[1]
FIXTURES = REPO / "fixtures"

# Skip the whole archive-backed suite if the raw archive isn't present (e.g. a
# shallow checkout) -- the parse-level regression guards below still run.
_ARCHIVE_OK = (REPO / "data" / "raw" / "13077").is_dir()

CATEGORIES = {
    "match_points": MATCH_COLS,
    "racks": RACK_COLS,
    "form": FORM_COLS,
    "hill_hill": HILL_COLS,
}


@pytest.fixture(scope="session")
def golden():
    return load_golden()


@pytest.fixture(scope="session")
def built(tmp_path_factory, golden):
    """Build the scoped DB once for the whole module and extract every division's
    anchors via the same extractor the baseline used."""
    if not _ARCHIVE_OK:
        pytest.skip("raw archive (data/raw) not present")
    db = tmp_path_factory.mktemp("golden") / "napa.db"
    conn = build_division_db(db, golden["meta"]["dids"], golden["player_ids"])
    rebuilt = {str(did): extract_division(conn, did) for did in golden["meta"]["dids"]}
    conn.close()
    return rebuilt


def _dids(golden):
    return [str(d) for d in golden["meta"]["dids"]]


# --------------------------------------------------------------------------- #
# Golden assertions: non-null + exact-match, every division x every category
# --------------------------------------------------------------------------- #

@pytest.mark.skipif(not _ARCHIVE_OK, reason="raw archive not present")
@pytest.mark.parametrize("category", list(CATEGORIES))
def test_category_is_never_silently_empty(golden, category):
    """A whole extraction pass producing zero rows is the loudest silent failure;
    the baseline carries rows for every division x category, so the build must too."""
    for did in _dids(golden):
        assert golden["divisions"][did][category], \
            f"golden baseline empty for {did}/{category} -- recapture?"


@pytest.mark.skipif(not _ARCHIVE_OK, reason="raw archive not present")
@pytest.mark.parametrize("category,cols", list(CATEGORIES.items()))
def test_every_field_is_non_null(golden, category, cols):
    """The goal's core invariant: every captured field is non-null. 0 / False are
    valid values, so this is an explicit `is not None` check, not truthiness."""
    for did in _dids(golden):
        for row in golden["divisions"][did][category]:
            for col in cols:
                assert row[col] is not None, \
                    f"NULL {category}.{col} in division {did}: {row}"


@pytest.mark.skipif(not _ARCHIVE_OK, reason="raw archive not present")
@pytest.mark.parametrize("category", list(CATEGORIES))
def test_rebuild_matches_golden(built, golden, category):
    """The freshly-rebuilt anchors equal the frozen baseline, row-for-row. Any
    drift (a value changed, a field went NULL, rows dropped) fails here -- the
    self-healing loop's signal to trace the root cause.

    match_points is checked as a SUBSET (every frozen row must still rebuild,
    keyed by round+teams, with identical points) rather than row-for-row: an
    ACTIVE division's season keeps adding matches and filling earlier rounds in,
    which shifted the old fixed top-N sample and false-flagged rows that were
    still correct, merely pushed past the LIMIT. A genuine value change, a
    dropped/NULLed frozen match still fails -- only the season GROWING no longer
    does. The completed division (13077) is unaffected either way."""
    for did in _dids(golden):
        gold = golden["divisions"][did][category]
        rebuilt = built[did][category]
        if category == "match_points":
            by_key = {(r["round"], r["home_team"], r["away_team"]): r for r in rebuilt}
            for row in gold:
                key = (row["round"], row["home_team"], row["away_team"])
                assert key in by_key, \
                    f"golden match_points row missing from rebuild ({did}): {row}"
                assert by_key[key] == row, \
                    f"match_points drift in {did}: golden {row} -> rebuilt {by_key[key]}"
        else:
            assert rebuilt == gold, f"rebuild drift in {did}/{category}"


@pytest.mark.skipif(not _ARCHIVE_OK, reason="raw archive not present")
def test_10bp_text_game_type_is_anchored(golden):
    """13986's racks must include the fragile "10BP" text game_type -- the path
    that silently conflates with plain 10-ball if the BP regex regresses."""
    racks = golden["divisions"]["13986"]["racks"]
    assert any(r["game_type"] == "10BP" for r in racks), \
        "no 10BP rack anchored for 13986 -- the BP parse path is unguarded"
    # 8-ball-only division must carry only 8-ball racks (no phantom 9/10).
    assert {r["game_type"] for r in golden["divisions"]["13298"]["racks"]} == {8}


@pytest.mark.skipif(not _ARCHIVE_OK, reason="raw archive not present")
def test_name_to_id_resolution_is_anchored(golden):
    """Guard the silent name->id resolution failure class. If _resolve_player_id
    (db.py) regressed to return None for everyone, every rack would KEEP its
    home/away player_name (the natural key, never NULL) so the older anchors still
    matched -- the collapse was invisible. The rack anchors now freeze the resolved
    home_player_id/away_player_id VALUES (exact-matched by test_rebuild_matches_
    golden), and here we assert at least some are non-null per division, so an
    all-NULL collapse can't pass. Subs legitimately keep NULL, hence '>0', not
    'all non-null'."""
    for did in _dids(golden):
        racks = golden["divisions"][did]["racks"]
        resolved = sum(1 for r in racks for k in ("home_player_id", "away_player_id")
                       if r.get(k) is not None)
        assert resolved > 0, \
            f"no resolved player ids anchored for {did} -- the resolution guard is blind"


# --------------------------------------------------------------------------- #
# Named regression guards for the two prior silent extraction failures
# --------------------------------------------------------------------------- #

EMPTY_SHELL = FIXTURES / "score_sheet_empty_shell.html"
REAL_SHEETS = ["score_sheet_w1.mht", "score_sheet_10bp_13986.html",
               "score_sheet_f8_10874.html"]


@pytest.mark.skipif(not EMPTY_SHELL.exists(), reason="empty-shell fixture absent")
def test_empty_shell_parses_to_zero_games():
    """The "NO MATCH(ES) PLAYED" shell must parse to ZERO games -- it is >500 bytes
    of real HTML, which is exactly why a size-only check mistook it for captured
    data and stranded the populated sheet (PR #64)."""
    sh = parse_score_sheet_file(EMPTY_SHELL)
    assert sh.games == []
    assert sh.home_team and sh.date  # the shell still carries the matchup header


@pytest.mark.parametrize("name", REAL_SHEETS)
def test_populated_sheet_parses_to_games(name):
    path = FIXTURES / name
    if not path.exists():
        pytest.skip(f"{name} not committed")
    assert parse_score_sheet_file(path).games, f"{name} parsed to zero games"


def test_f8_text_game_type_parses():
    """F8 (fortune 8-ball) canonicalizes to the text game_type "F8" (like 10BP) --
    a fragile non-int path live in dids 10874/10993 but ABSENT from the 3 golden
    divisions, so the archive->DB golden layer never exercises it. Anchor it at the
    parse layer against the committed fixture so a regression in the F8 regex
    (weekly_scores._F8_GAME_RE) is caught here, not silently."""
    path = FIXTURES / "score_sheet_f8_10874.html"
    if not path.exists():
        pytest.skip("score_sheet_f8_10874.html not committed")
    sh = parse_score_sheet_file(path)
    assert any(g.game_type == "F8" for g in sh.games), \
        "no F8 game_type parsed -- the fortune-8-ball path regressed"


@pytest.mark.skipif(not EMPTY_SHELL.exists(), reason="empty-shell fixture absent")
def test_resume_guard_distinguishes_shell_from_populated():
    """The content-aware resume guard (PR #64): a shell is NOT captured (re-fetch
    it once the match is played); a populated sheet IS captured (don't re-fetch)."""
    assert _sheet_captured(EMPTY_SHELL) is False
    for name in REAL_SHEETS:
        path = FIXTURES / name
        if path.exists():
            assert _sheet_captured(path) is True, f"{name} wrongly seen as un-captured"


@pytest.mark.skipif(not EMPTY_SHELL.exists(), reason="empty-shell fixture absent")
def test_loading_empty_shell_adds_no_games():
    """End-to-end: loading the empty shell must not inject phantom rows, and a real
    sheet must load > 0 -- so a regression can't silently empty the games table."""
    conn = connect(":memory:")
    init_db(conn)
    before = conn.execute("SELECT COUNT(*) FROM games").fetchone()[0]
    load_score_sheets(conn, [parse_score_sheet_file(EMPTY_SHELL)], season="test-season")
    assert conn.execute("SELECT COUNT(*) FROM games").fetchone()[0] == before

    real = FIXTURES / "score_sheet_10bp_13986.html"
    if real.exists():
        res = load_score_sheets(conn, [parse_score_sheet_file(real)], season="test-season")
        assert res["loaded"] > 0
