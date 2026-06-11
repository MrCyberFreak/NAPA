"""Division registry tests — the DIVISIONS dict and URL templating.

Verifies the 14-division registry, the per-division weekDay in the schedule
URL, the scrape activation flag, and the per-division archive root.
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


def test_registry_has_all_fourteen_divisions():
    assert len(config.DIVISIONS) == 14
    assert all(did == d.did for did, d in config.DIVISIONS.items())
    assert all(d.fmt in ("LC", "8") for d in config.DIVISIONS.values())


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
    # Deliberate tripwire: each onboarding flips ONE flag and extends this
    # list in the same PR (MULTIDIVISION_PLAN.md rollout, one at a time).
    assert config.active_dids() == [13077, 13985, 14022, 13986, 13937]


def test_division_root_is_per_did():
    root = config.division_root(13985)
    assert root.parts[-3:] == ("data", "raw", "13985")
