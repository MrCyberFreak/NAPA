"""Two-source registry tests — config.divisions() merge of curated DIVISIONS
with the discovered-rollover overlay, plus the catchup.run_set linchpin.

Uses a hypothetical FUTURE rollover (14022 -> 99001) so the assertions don't
depend on the live curated set. The overlay file is redirected to a tmp path.
"""

from __future__ import annotations

import json

import pytest

from src import catchup, config


@pytest.fixture
def overlay(tmp_path, monkeypatch):
    p = tmp_path / "_registry.json"
    monkeypatch.setattr(config, "REGISTRY_PATH", p)
    # Isolate from the live discovered-historical inbox (also folded into
    # divisions()) so these overlay-merge assertions stay curated+overlay only.
    monkeypatch.setattr(config, "HISTORICAL_PATH", tmp_path / "_historical.json")

    def write(discovered):
        p.write_text(json.dumps({"discovered": discovered}), encoding="utf-8")

    return write


def test_empty_overlay_is_just_curated(overlay):
    overlay({})
    assert config.divisions() == config.DIVISIONS
    assert config.active_dids() == list(config.DIVISIONS)


def test_active_rollover_joins_the_live_set(overlay):
    overlay({"99001": {"slug": "wednesday-paradise-lc", "status": "active",
                       "weekday": "Wednesday", "predecessor": 14022}})
    divs = config.divisions()
    assert divs[99001].scrape is True
    assert divs[99001].slug == "wednesday-paradise-lc"
    assert 99001 in config.active_dids()
    assert 99001 in config.divisions_playing_on("Wednesday")


def test_rolled_predecessor_present_but_not_swept(overlay):
    overlay({"99002": {"slug": "wednesday-paradise-lc", "status": "rolled",
                       "weekday": "Wednesday", "successor": 99001}})
    divs = config.divisions()
    assert 99002 in divs                       # present (so catchup can carry it)
    assert divs[99002].scrape is False         # ...but excluded from the sweep
    assert 99002 not in config.active_dids()
    assert 99002 not in config.divisions_playing_on("Wednesday")


def test_run_set_keeps_a_rolled_but_queued_predecessor(overlay):
    # THE linchpin: a rolled predecessor queued for a makeup must survive
    # run_set's registry-order filter (config.divisions(), not config.DIVISIONS).
    overlay({"99002": {"slug": "wednesday-paradise-lc", "status": "rolled",
                       "weekday": "Wednesday", "successor": 99001}})
    queue = {"99002": {"reason": "pending-makeups", "since": "2026-06-18"}}
    assert 99002 in catchup.run_set([], queue)


def test_curated_wins_over_overlay(overlay):
    # An overlay entry for an already-curated did is ignored (graduation drop).
    overlay({"13985": {"slug": "bogus", "status": "active", "weekday": "Monday"}})
    assert config.divisions()[13985].slug == "tuesday-felt-laggers-lc"
    assert config.divisions()[13985].weekday == "Tuesday"


def test_slugless_overlay_entry_is_skipped(overlay):
    overlay({"99003": {"status": "active", "weekday": "Friday"}})  # no slug
    assert 99003 not in config.divisions()


def test_states_url_is_did_independent():
    assert config.url("states") == \
        "https://poolshooters.com/states.php?location=Colorado"
