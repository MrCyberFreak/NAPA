"""Day-after-play scheduling + the catch-up queue.

Covers the pure pieces of the post-rollout scrape redesign:
- config.divisions_playing_on / divisions_due — which divisions a given run
  pulls (the day-after-play selector);
- src.catchup — the carry-forward queue that re-pulls skipped captures and
  outstanding makeups on the next run regardless of which division played.
"""

from __future__ import annotations

import datetime as dt
import json

import pytest

from src import catchup, config

# Registry-derived expected sets, so these tests don't hardcode the active list
# (it grows as divisions onboard — the rollout tripwire in test_config.py owns
# the exact membership; here we only assert the scheduling SHAPE).
MONDAY = config.divisions_playing_on("Monday")
TUESDAY = config.divisions_playing_on("Tuesday")
FRIDAY = config.divisions_playing_on("Friday")


# --------------------------------------------------------------------------- #
# config.divisions_due — the day-after-play selector
# --------------------------------------------------------------------------- #

def test_playing_on_matches_registry_weekday():
    for did in config.divisions_playing_on("Friday", active_only=False):
        assert config.DIVISIONS[did].weekday == "Friday"
    # No division plays Saturday in NoCo.
    assert config.divisions_playing_on("Saturday", active_only=False) == []


def test_playing_on_active_only_filters_unflipped():
    everything = config.divisions_playing_on("Friday", active_only=False)
    active = config.divisions_playing_on("Friday", active_only=True)
    assert set(active) <= set(everything)
    assert all(config.DIVISIONS[d].scrape for d in active)


def test_due_is_yesterdays_league_night():
    # A Tuesday run is due the divisions that played Monday night.
    tuesday = dt.date(2026, 6, 16)  # a Tuesday
    assert tuesday.strftime("%A") == "Tuesday"
    assert config.divisions_due(tuesday) == config.divisions_playing_on("Monday")
    # A Saturday run is due Friday's divisions (the 4 DP/Friday divisions).
    saturday = dt.date(2026, 6, 20)
    assert saturday.strftime("%A") == "Saturday"
    assert config.divisions_due(saturday) == config.divisions_playing_on("Friday")


def test_due_sunday_run_after_saturday_is_empty():
    # Nobody plays Saturday, so the Sunday-morning run has no day-after due set
    # (only carryover, if any, gets pulled).
    sunday = dt.date(2026, 6, 21)
    assert sunday.strftime("%A") == "Sunday"
    assert config.divisions_due(sunday) == []


def test_due_registry_order_preserved():
    due = config.divisions_due(dt.date(2026, 6, 16), active_only=False)
    assert due == [d for d in config.DIVISIONS if d in set(due)]


# --------------------------------------------------------------------------- #
# catchup queue — load/save/run_set
# --------------------------------------------------------------------------- #

def test_queue_roundtrip(tmp_path):
    path = tmp_path / "_catchup.json"
    q = {"13881": {"reason": "scrape-skipped", "since": "2026-06-12"}}
    catchup.save_queue(q, path=path, run_date="2026-06-12")
    assert catchup.load_queue(path) == q
    # The file is human-diffable JSON with a divisions map.
    blob = json.loads(path.read_text())
    assert blob["divisions"] == q and blob["run_date"] == "2026-06-12"


def test_load_missing_or_garbage_is_empty(tmp_path):
    assert catchup.load_queue(tmp_path / "nope.json") == {}
    bad = tmp_path / "bad.json"
    bad.write_text("{not json")
    assert catchup.load_queue(bad) == {}


def test_run_set_unions_due_and_queue_in_registry_order():
    due = config.divisions_playing_on("Monday", active_only=False)
    queue = {"13299": {"reason": "pending-makeups", "since": "2026-06-01"}}
    rs = catchup.run_set(due, queue)
    assert 13299 in rs
    assert set(due) <= set(rs)
    assert rs == [d for d in config.DIVISIONS if d in set(rs)]  # registry order
    # idempotent on a division both due and queued (no duplicate)
    assert len(rs) == len(set(rs))


# --------------------------------------------------------------------------- #
# catchup.reconcile — the carry-forward decision
# --------------------------------------------------------------------------- #

def _complete(did: int) -> dict:
    """A results entry where every expected page was captured."""
    from src import fetch
    return {"captured": [name for name, _ in fetch.archive_pages(did)], "unchanged": []}


def test_reconcile_drops_clean_capture_with_no_makeups():
    did = config.active_dids()[0]
    q = catchup.reconcile([did], {str(did): _complete(did)}, {did: []}, {}, "2026-06-12")
    assert str(did) not in q


def test_reconcile_requeues_skipped_division():
    # A division absent from results was never reached (upstream abort).
    did = config.active_dids()[0]
    q = catchup.reconcile([did], {}, {}, {}, "2026-06-12")
    assert q[str(did)]["reason"] == "scrape-skipped"


def test_reconcile_requeues_partial_capture():
    did = config.active_dids()[0]
    partial = {"captured": ["roster_grid"], "unchanged": []}  # missing pages
    q = catchup.reconcile([did], {str(did): partial}, {did: []}, {}, "2026-06-12")
    assert q[str(did)]["reason"] == "scrape-incomplete"


def test_reconcile_requeues_fresh_makeups_with_rounds():
    did = config.active_dids()[0]
    pending = [{"round": 6, "date": "2026-06-08"}, {"round": 7, "date": "2026-06-08"}]
    q = catchup.reconcile([did], {str(did): _complete(did)}, {did: pending}, {},
                          "2026-06-12")
    assert q[str(did)]["reason"] == "pending-makeups"
    assert q[str(did)]["rounds"] == [6, 7]


def test_reconcile_ages_out_stale_phantom_makeup():
    did = config.active_dids()[0]
    # A "pending" fixture from last December is a phantom, not an owed makeup.
    pending = [{"round": 1, "date": "2025-12-16"}]
    q = catchup.reconcile([did], {str(did): _complete(did)}, {did: pending}, {},
                          "2026-06-12")
    assert str(did) not in q


def test_reconcile_preserves_since_across_runs():
    did = config.active_dids()[0]
    prev = {str(did): {"reason": "scrape-skipped", "since": "2026-06-01"}}
    q = catchup.reconcile([did], {}, {}, prev, "2026-06-12")
    assert q[str(did)]["since"] == "2026-06-01"  # waiting since the first miss
