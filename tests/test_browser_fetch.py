"""Browser fetcher core tests (no real browser needed): challenge clearing,
the auto-week stop/abort classifier, and the per-division daily-scrape loop."""

from __future__ import annotations

from pathlib import Path

from src import browser_fetch, config, fetch
from src.browser_fetch import (
    BotChallengeError,
    _parse_weeks,
    _walk_weeks,
    capture_clearing_challenge,
    classify_index,
    fetch_divisions_browser,
)

CHALLENGE = (
    "<html><head><title>One moment, please...</title>"
    "<script>setTimeout(function(){window.location.reload();},5000)</script>"
    "</head></html>"
)
REAL = "<html><body>real roster grid</body></html>"


def test_clears_after_a_couple_reloads():
    seq = [CHALLENGE, CHALLENGE, REAL]
    i = {"n": 0}
    content, tries = capture_clearing_challenge(
        get_content=lambda: seq[min(i["n"], len(seq) - 1)],
        advance=lambda: i.__setitem__("n", i["n"] + 1),
        attempts=6,
    )
    assert "real" in content and not fetch.is_challenge(content)
    assert tries == 3


def test_gives_up_when_challenge_persists():
    content, tries = capture_clearing_challenge(
        get_content=lambda: CHALLENGE,
        advance=lambda: None,
        attempts=4,
    )
    assert fetch.is_challenge(content)
    assert tries == 4


# --------------------------------------------------------------------------- #
# Auto-week backfill: the pure stop/abort classifier + the week walk
# --------------------------------------------------------------------------- #

INDEX_OK = (
    '<html><body><a href="https://poolshooters.com/scores.php?did=13077&tid=42">'
    "view score sheet</a></body></html>"
)
INDEX_EMPTY = "<html><body>Weekly scores — no matches recorded.</body></html>"


def test_classify_index_ok_empty_abort():
    assert classify_index(INDEX_OK) == "ok"
    assert classify_index(INDEX_EMPTY) == "empty"          # cleared, zero sheet links
    assert classify_index("") == "abort"                   # failed nav
    assert classify_index(CHALLENGE) == "abort"            # uncleared challenge


def test_auto_walk_stops_after_two_consecutive_empties():
    by_week = {1: INDEX_OK, 2: INDEX_OK, 3: INDEX_EMPTY, 4: INDEX_EMPTY, 5: INDEX_OK}
    fetched: list[int] = []

    def fetch_index(wk):
        fetched.append(wk)
        return by_week[wk]

    walked = list(_walk_weeks("auto", fetch_index))
    assert [wk for wk, _ in walked] == [1, 2]
    assert fetched == [1, 2, 3, 4]  # stopped at the 2nd empty; week 5 never fetched


def test_auto_walk_resets_empty_count_on_a_played_week():
    by_week = {1: INDEX_OK, 2: INDEX_EMPTY, 3: INDEX_OK, 4: INDEX_EMPTY, 5: INDEX_EMPTY}
    walked = list(_walk_weeks("auto", lambda wk: by_week[wk]))
    assert [wk for wk, _ in walked] == [1, 3]  # the lone empty at 2 did not stop the walk


def test_walk_aborts_on_challenge_and_never_counts_it_as_empty():
    # A mid-run challenge must not silently truncate the backfill: it aborts
    # immediately (fail-soft; re-run resumes) instead of counting toward the stop.
    by_week = {1: INDEX_OK, 2: CHALLENGE, 3: INDEX_OK}
    fetched: list[int] = []

    def fetch_index(wk):
        fetched.append(wk)
        return by_week[wk]

    walked = list(_walk_weeks("auto", fetch_index))
    assert [wk for wk, _ in walked] == [1]
    assert fetched == [1, 2]  # aborted at the challenge; week 3 never fetched

    # Same for a failed nav ("" content) on an explicit week list.
    walked = list(_walk_weeks([5, 6, 7], lambda wk: "" if wk == 6 else INDEX_OK))
    assert [wk for wk, _ in walked] == [5]


def test_explicit_week_list_never_auto_stops_on_empties():
    walked = list(_walk_weeks([1, 2, 3], lambda wk: INDEX_EMPTY if wk < 3 else INDEX_OK))
    assert [wk for wk, _ in walked] == [3]  # 2 consecutive empties only stop "auto"


def test_parse_weeks_accepts_auto_ranges_and_lists():
    assert _parse_weeks("auto") == "auto"
    assert _parse_weeks("AUTO") == "auto"
    assert _parse_weeks("1-3") == [1, 2, 3]
    assert _parse_weeks("4,7") == [4, 7]


# --------------------------------------------------------------------------- #
# Daily-scrape division loop (fetch_pages_browser faked — no browser)
# --------------------------------------------------------------------------- #


def test_division_loop_passes_per_division_pages_and_root(monkeypatch):
    calls: list[tuple] = []

    def fake(pages=None, root=None, page=None, **kw):
        calls.append((list(pages), root, page))
        return {"roster_grid": root / "x" / "roster_grid.html", "schedule": None}

    monkeypatch.setattr(browser_fetch, "fetch_pages_browser", fake)
    shared_page = object()
    results = fetch_divisions_browser([13077, 13985], date="2026-06-10", page=shared_page)

    assert [c[0] for c in calls] == [fetch.archive_pages(13077), fetch.archive_pages(13985)]
    assert [c[1] for c in calls] == [config.division_root(13077), config.division_root(13985)]
    assert all(c[2] is shared_page for c in calls)  # ONE page reused across divisions
    assert results == {
        "13077": {"captured": ["roster_grid"], "unchanged": ["schedule"]},
        "13985": {"captured": ["roster_grid"], "unchanged": ["schedule"]},
    }


def test_division_loop_continues_past_a_nav_failed_division(monkeypatch):
    # A nav error makes fetch_pages_browser RETURN a partial dict (it stops that
    # division's remaining pages); the loop records it and moves on.
    def fake(pages=None, root=None, page=None, **kw):
        did = pages[0][1]["did"]
        return {} if did == 13077 else {"roster_grid": Path("p")}

    monkeypatch.setattr(browser_fetch, "fetch_pages_browser", fake)
    results = fetch_divisions_browser([13077, 13985], page=object())
    assert results == {
        "13077": {"captured": [], "unchanged": []},
        "13985": {"captured": ["roster_grid"], "unchanged": []},
    }


def test_division_loop_aborts_whole_run_on_uncleared_challenge(monkeypatch):
    # An uncleared challenge is HOST-WIDE: abort instead of hammering the rest.
    def fake(pages=None, root=None, page=None, **kw):
        did = pages[0][1]["did"]
        if did == 13985:
            raise BotChallengeError("uncleared", {"roster_grid": Path("p"), "schedule": None})
        return {"roster_grid": Path("p")}

    monkeypatch.setattr(browser_fetch, "fetch_pages_browser", fake)
    results = fetch_divisions_browser([13077, 13985, 14022], page=object())
    assert list(results) == ["13077", "13985"]  # 14022 skipped entirely
    # The aborted division's pre-abort partials still reach the heartbeat.
    assert results["13985"] == {"captured": ["roster_grid"], "unchanged": ["schedule"]}
