"""Division registry tests — the DIVISIONS dict and URL templating.

Verifies the 16-entry registry (14 NoCo divisions + the 14050 rollover of 13077
+ the 14064 rollover of 13205), the per-division weekDay in the schedule URL,
the scrape activation flag, and the per-division archive root.
"""

from __future__ import annotations

import pytest

from src import config

# Every templated endpoint url() knows how to build.
ALL_URL_NAMES = (
    "roster_grid", "schedule", "scratch",
    "division", "leaderboard", "achievements", "weekly_scores",
    "live_scores", "profile", "livescores",
)


def test_registry_has_all_divisions():
    # 14 NoCo divisions + two season-rollovers: 14050 (of 13077, kept while 13077
    # still owes an R27 makeup and holds the 2025-26 history) and 14064 (of 13205,
    # Greeley Monday LC, R1 2026-06-22).
    assert len(config.DIVISIONS) == 16
    assert all(did == d.did for did, d in config.DIVISIONS.items())
    assert all(d.fmt in ("LC", "8") for d in config.DIVISIONS.values())


def test_every_division_has_a_slug():
    assert all(d.slug for d in config.DIVISIONS.values())


def test_slugs_unique_per_league_rollovers_share():
    # The slug is the stable LOGICAL-league key: distinct leagues -> distinct
    # slugs (esp. the three shared-venue LC/8-ball pairs, kept apart only by the
    # gameset token), but the two session-ids of the SAME league intentionally
    # SHARE one slug -- 13077 + its rollover 14050, and 13205 + its rollover 14064.
    from collections import Counter

    shared = {slug for slug, n in Counter(
        d.slug for d in config.DIVISIONS.values()).items() if n > 1}
    assert shared == {"thursday-big-table-felt-lc", "monday-greeley-lc"}
    assert sorted(did for did, d in config.DIVISIONS.items()
                  if d.slug == "thursday-big-table-felt-lc") == [13077, 14050]
    assert sorted(did for did, d in config.DIVISIONS.items()
                  if d.slug == "monday-greeley-lc") == [13205, 14064]


@pytest.mark.parametrize("did", list(config.DIVISIONS))
def test_every_division_builds_every_url(did):
    for name in ALL_URL_NAMES:
        u = config.url(name, did=did, week=1, week_number=27, player_id="10000000")
        assert u.startswith("https://")


def test_schedule_url_uses_registry_weekday():
    assert "weekDay=Tuesday" in config.url("schedule", did=13985)
    assert "weekDay=Friday" in config.url("schedule", did=13744)
    # The default division keeps its Thursday URL byte-identical.
    assert "weekDay=Thursday" in config.url("schedule", did=13077)
    assert "weekDay=Thursday" in config.url("schedule")  # did defaults to DID


def test_schedule_url_weekday_override_and_unknown_did_fallback():
    assert "weekDay=Sunday" in config.url("schedule", did=13985, week_day="Sunday")
    # Unknown did -> falls back to the module default WEEK_DAY.
    assert "weekDay=Thursday" in config.url("schedule", did=99999)


def test_active_divisions_match_rollout():
    # The CURATED active set, asserted against config.DIVISIONS directly so a
    # real discovered-rollover overlay can't perturb this list (the MERGED
    # active_dids() behavior is covered in test_registry_overlay). Rollout
    # COMPLETE: all 14 NoCo divisions active + the 14050 and 14064 rollovers
    # (added last, so they land at the tail), in REGISTRY (dict insertion) order.
    curated_active = [did for did, d in config.DIVISIONS.items() if d.scrape]
    assert curated_active == [13077, 13985, 14022, 13986, 13937, 13881,
                              13711, 13299, 13205, 13744, 13723, 13743,
                              13722, 13298, 14050, 14064]
    assert curated_active == list(config.DIVISIONS)  # every curated division active


def test_division_root_is_per_did():
    root = config.division_root(13985)
    assert root.parts[-3:] == ("data", "raw", "13985")
