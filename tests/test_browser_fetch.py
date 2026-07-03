"""Browser fetcher core tests (no real browser needed): challenge clearing,
the auto-week stop/abort classifier, and the per-division daily-scrape loop."""

from __future__ import annotations

import contextlib
import datetime as dt
from pathlib import Path

from src import browser_fetch, catchup, config, discovery, fetch
from src.browser_fetch import (
    BotChallengeError,
    _last_archived_week,
    _parse_weeks,
    _run_discovery,
    _walk_weeks,
    _week_complete_on_disk,
    capture_clearing_challenge,
    classify_index,
    fetch_divisions_browser,
)


@contextlib.contextmanager
def _fake_browser_page(headless=True):
    yield object()

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


# --------------------------------------------------------------------------- #
# Incremental resume: skip live-navigating weeks already complete on disk. This
# is the fix for the scheduled-run 90-min timeout — a caught-up division was
# re-walking ~27 weekly indexes (each paying the host challenge) every day.
# --------------------------------------------------------------------------- #


def test_auto_walk_skips_weeks_already_complete_on_disk():
    # Weeks 1-3 are already fully captured on disk -> NO live nav; the walk
    # resumes at the frontier (week 4) and finds season end at 5,6.
    by_week = {4: INDEX_OK, 5: INDEX_EMPTY, 6: INDEX_EMPTY}
    fetched: list[int] = []

    def fetch_index(wk):
        fetched.append(wk)
        return by_week[wk]

    done = {1, 2, 3}
    walked = list(_walk_weeks("auto", fetch_index, week_done=lambda wk: wk in done))
    assert [wk for wk, _ in walked] == [4]   # only the frontier week yielded
    assert fetched == [4, 5, 6]              # weeks 1-3 never navigated live


def test_auto_walk_still_fills_a_gap_below_the_frontier():
    # A not-done week among done weeks (e.g. a partial capture) is still navved.
    by_week = {2: INDEX_OK, 4: INDEX_OK, 5: INDEX_EMPTY, 6: INDEX_EMPTY}
    fetched: list[int] = []

    def fetch_index(wk):
        fetched.append(wk)
        return by_week[wk]

    done = {1, 3}  # weeks 2 and 4+ are NOT done -> must be navigated
    walked = list(_walk_weeks("auto", fetch_index, week_done=lambda wk: wk in done))
    assert fetched == [2, 4, 5, 6]           # 1 and 3 skipped, the gap at 2 filled
    assert [wk for wk, _ in walked] == [2, 4]


def test_week_done_predicate_reads_disk_and_frontier_is_never_done(tmp_path):
    import shutil

    scores = tmp_path / "scores"
    # week 1: index lists tid=42; 42.html is a real populated sheet -> complete
    w1 = scores / "week_01"
    w1.mkdir(parents=True)
    (w1 / "_index.html").write_text(
        '<a href="https://poolshooters.com/scores.php?did=13077&tid=42">x</a>',
        encoding="utf-8")
    shutil.copyfile("fixtures/score_sheet_w1.mht", w1 / "42.html")
    # week 2: index lists tid=43 but 43.html is an empty pre-play shell -> NOT complete
    w2 = scores / "week_02"
    w2.mkdir(parents=True)
    (w2 / "_index.html").write_text(
        '<a href="https://poolshooters.com/scores.php?did=13077&tid=43">x</a>',
        encoding="utf-8")
    shutil.copyfile("fixtures/score_sheet_empty_shell.html", w2 / "43.html")

    assert _week_complete_on_disk(scores, 1) is True
    assert _week_complete_on_disk(scores, 2) is False   # a shell -> re-fetch
    assert _week_complete_on_disk(scores, 3) is False   # no index on disk
    assert _last_archived_week(scores) == 2             # highest week with an index
    assert _last_archived_week(tmp_path / "absent") == 0

    # The frontier week (== last archived) is never treated as done, so a late
    # sheet added to the most-recent week is still re-navved. Mirror the predicate
    # backfill_score_sheets builds.
    last_arch = _last_archived_week(scores)

    def week_done(wk):
        return wk < last_arch and _week_complete_on_disk(scores, wk)

    assert week_done(1) is True    # below the frontier and complete -> skip
    assert week_done(2) is False   # the frontier itself -> always re-nav


def test_sheet_captured_rejects_empty_shell_so_it_is_refetched(tmp_path):
    # The resume guard must distinguish a real, populated score sheet from a
    # pre-season "NO MATCH(ES) PLAYED" shell. A shell is >500 bytes but parses
    # to zero games; if it counted as "captured", the backfill would never
    # re-fetch the populated sheet once the match is played (the 14050/14022
    # bug: a whole season of onboarding shells masked every real sheet).
    from src.browser_fetch import _sheet_captured

    shell = Path("fixtures/score_sheet_empty_shell.html")  # real 14050 R1 shell
    assert shell.stat().st_size > 500          # the old size-only check passed it
    assert _sheet_captured(shell) is False     # but it holds zero games -> re-fetch

    populated = Path("fixtures/score_sheet_w1.mht")
    assert _sheet_captured(populated) is True  # a real capture -> resume (skip)

    assert _sheet_captured(tmp_path / "missing.html") is False  # nothing on disk


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


# --------------------------------------------------------------------------- #
# Season-rollover discovery wired into scheduled_run (no real browser)
# --------------------------------------------------------------------------- #


def test_run_discovery_is_failsoft_on_a_states_challenge(monkeypatch):
    # An uncleared states.php challenge must NEVER crash the run — _run_discovery
    # swallows it and returns no rollovers (the page scrape still proceeds).
    def boom(*a, **k):
        raise BotChallengeError("states challenge")

    monkeypatch.setattr(browser_fetch, "fetch_states", boom)
    assert _run_discovery("2026-06-18", "2026-06-18", object()) == set()


def test_run_discovery_alerts_and_skips_on_zero_noco_rows(monkeypatch, tmp_path, capsys):
    # A challenge-free page with 0 NoCo rows means the group header changed —
    # alert, don't silently reconcile it as "no rollovers".
    monkeypatch.setattr(browser_fetch, "fetch_states", lambda *a, **k: None)
    monkeypatch.setattr(browser_fetch, "_STATES_ROOT", tmp_path)
    day = tmp_path / "2026-06-18"
    day.mkdir()
    (day / "states.html").write_text("<html><body>no group here</body></html>",
                                     encoding="utf-8")
    assert _run_discovery("2026-06-18", "2026-06-18", object()) == set()
    assert "ALERT" in capsys.readouterr().out


def _stub_scheduled_io(monkeypatch):
    """Neutralize scheduled_run's disk/network side effects for wiring tests."""
    monkeypatch.setattr(browser_fetch, "_browser_page", _fake_browser_page)
    monkeypatch.setattr(browser_fetch, "backfill_score_sheets", lambda *a, **k: None)
    monkeypatch.setattr(browser_fetch, "_pending_for_divisions", lambda *a, **k: {})
    monkeypatch.setattr(catchup, "load_queue", lambda *a, **k: {})
    monkeypatch.setattr(catchup, "save_queue", lambda *a, **k: None)
    monkeypatch.setattr(fetch, "write_heartbeat", lambda *a, **k: None)


def test_scheduled_run_folds_an_active_rollover_into_the_scrape_set(tmp_path, monkeypatch):
    # Discovery registers an active rollover (off its weekday); scheduled_run
    # must fold it into THIS run's scrape set via config.divisions().
    monkeypatch.setattr(config, "REGISTRY_PATH", tmp_path / "_registry.json")
    _stub_scheduled_io(monkeypatch)

    def fake_discovery(date_str, run_date_iso, page):
        discovery.save_registry({"discovered": {"99001": {
            "slug": "wednesday-paradise-lc", "status": "active",
            "weekday": "Wednesday", "predecessor": 14022}}, "unknown": {}})
        return {99001}

    monkeypatch.setattr(browser_fetch, "_run_discovery", fake_discovery)
    seen = {}

    def fake_scrape(dids, date=None, page=None, **k):
        seen["dids"] = list(dids)
        return {str(d): {"captured": [], "unchanged": []} for d in dids}

    monkeypatch.setattr(browser_fetch, "fetch_divisions_browser", fake_scrape)
    out = browser_fetch.scheduled_run(run_date=dt.date(2026, 6, 21))  # Sunday: due empty
    assert 99001 in seen["dids"]
    assert out["discovered"] == [99001]


def test_scheduled_run_is_discovery_only_when_nothing_to_scrape(monkeypatch):
    # Nothing due (Sunday => yesterday Saturday, no division plays), queue empty,
    # no rollover -> discovery ran but no page scrape.
    _stub_scheduled_io(monkeypatch)
    monkeypatch.setattr(browser_fetch, "_run_discovery", lambda *a, **k: set())
    scraped = {"called": False}

    def fake_scrape(*a, **k):
        scraped["called"] = True
        return {}

    monkeypatch.setattr(browser_fetch, "fetch_divisions_browser", fake_scrape)
    out = browser_fetch.scheduled_run(run_date=dt.date(2026, 6, 21))
    assert out["scraped"] == [] and scraped["called"] is False


def test_scheduled_all_divisions_scrapes_all_but_backfills_due_only(monkeypatch):
    # all_divisions=True must SCRAPE every active division (daily refresh) yet
    # keep BACKFILL targeted to the day-after-play due set (host-friendly).
    _stub_scheduled_io(monkeypatch)
    monkeypatch.setattr(browser_fetch, "_run_discovery", lambda *a, **k: set())
    scraped = {}
    backfilled = []
    monkeypatch.setattr(browser_fetch, "fetch_divisions_browser",
                        lambda dids, **k: (scraped.update(dids=list(dids)),
                                           {str(d): {"captured": ["roster_grid"],
                                                     "unchanged": []} for d in dids})[1])
    monkeypatch.setattr(browser_fetch, "backfill_score_sheets",
                        lambda *a, **k: backfilled.append(k.get("did")))
    # Friday run -> yesterday Thursday -> due = the Thursday divisions (13077, 14050).
    browser_fetch.scheduled_run(run_date=dt.date(2026, 6, 19), all_divisions=True)
    assert set(scraped["dids"]) == set(config.active_dids())   # scraped ALL active
    assert set(backfilled) == {13077, 14050}                    # backfilled DUE only
