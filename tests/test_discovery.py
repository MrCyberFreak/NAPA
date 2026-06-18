"""Season-rollover reconcile tests.

Uses a hypothetical FUTURE rollover (14022 -> 99001) so the assertions don't
depend on the live curated set, plus an unknown-slug new-league case and the
end-to-end merge through config.divisions().
"""

from __future__ import annotations

import pytest

from src import config, discovery
from src.discovery import reconcile_registry
from src.parse.states import NOCO_GROUP, StatesRow

EMPTY = {"discovered": {}, "unknown": {}}


def _row(did, slug, weekday="Wednesday", name='Wednesday "X" No Limit LC'):
    return StatesRow(did=did, name=name, slug=slug, weekday=weekday,
                     venue="X", gameset="lc", group=NOCO_GROUP)


def test_rollover_of_curated_league_registers_active_with_lineage():
    # 14022 (curated, wednesday-paradise-lc) rolls to a new non-curated did.
    res = reconcile_registry([_row(99001, "wednesday-paradise-lc")], EMPTY, "2026-09-01")
    d = res.registry["discovered"]
    assert d["99001"]["status"] == "active"
    assert d["99001"]["predecessor"] == 14022
    assert 99001 in res.newly_activated
    # 14022 dropped off states.php (absent from rows) -> rolled, successor linked.
    assert d["14022"]["status"] == "rolled"
    assert d["14022"]["successor"] == 99001


def test_unknown_slug_is_alert_only_never_merged():
    res = reconcile_registry([_row(98000, "thursday-newplace-9ball", "Thursday")],
                             EMPTY, "2026-09-01")
    assert "98000" not in res.registry["discovered"]
    assert res.registry["unknown"]["98000"]["slug"] == "thursday-newplace-9ball"
    assert res.unknown and not res.newly_activated


def test_curated_did_on_states_is_a_noop():
    # A curated did (14050) on states.php yields no overlay entry and no alert.
    res = reconcile_registry([_row(14050, "thursday-big-table-felt-lc", "Thursday")],
                             EMPTY, "2026-09-01")
    assert res.registry["discovered"] == {}
    assert res.registry["unknown"] == {}
    assert not res.newly_activated


def test_idempotent_second_run_preserves_since_and_clears_newly():
    rows = [_row(99001, "wednesday-paradise-lc")]
    first = reconcile_registry(rows, EMPTY, "2026-09-01")
    second = reconcile_registry(rows, first.registry, "2026-09-08")
    assert not second.newly_activated                                  # already active
    assert second.registry["discovered"]["99001"]["since"] == "2026-09-01"   # preserved
    assert second.registry["discovered"]["14022"]["status"] == "rolled"      # lineage kept


def test_reconcile_output_feeds_config_divisions(tmp_path, monkeypatch):
    monkeypatch.setattr(config, "REGISTRY_PATH", tmp_path / "_registry.json")
    res = reconcile_registry([_row(99001, "wednesday-paradise-lc")],
                             discovery.load_registry(), "2026-09-01")
    discovery.save_registry(res.registry, run_date="2026-09-01")

    divs = config.divisions()
    assert divs[99001].scrape is True and divs[99001].slug == "wednesday-paradise-lc"
    assert 99001 in config.active_dids()
    # 14022 stays curated (curated wins); the overlay 'rolled' entry is ignored.
    assert divs[14022].scrape is True
