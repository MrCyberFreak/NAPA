"""division.php parser tests — the discovery probe.

Pins the three outcomes the sweep keys on: a NoCo HIT (real 14050 capture), a
non-NoCo HIT (resolved but slug not in the curated set), and a MISS (empty name
cell on an invalid did). Best-effort: garbage never raises.
"""

from __future__ import annotations

from pathlib import Path

from src import config
from src.parse.division import parse_division, parse_division_file

FIX = Path("fixtures")
NOCO_SLUGS = {d.slug for d in config.DIVISIONS.values()}


def test_noco_hit_real_page():
    dp = parse_division_file(FIX / "division_14050.html")
    assert dp.resolved is True
    assert dp.did == 14050
    assert dp.name == 'Thursday "Big Table Felt" No Limit LC League'
    assert dp.slug == "thursday-big-table-felt-lc"
    assert dp.location == "Englewood"
    assert dp.slug in NOCO_SLUGS  # a curated NoCo league


def test_nonnoco_hit_resolves_but_is_not_noco():
    dp = parse_division_file(FIX / "division_14040_nonnoco.html")
    assert dp.resolved is True
    assert dp.did == 14040
    assert dp.slug == "tuesday-wrangler-8ball"
    assert dp.location == "Whipple, Ohio"
    assert dp.slug not in NOCO_SLUGS  # read-and-discarded by the sweep


def test_miss_empty_name_cell():
    dp = parse_division_file(FIX / "division_miss.html")
    assert dp.resolved is False
    assert dp.name == ""
    assert dp.slug == ""
    assert dp.did is None  # value cells blank => no echoed did


def test_garbage_never_raises():
    dp = parse_division("<html><body>One moment, please...</body></html>")
    assert dp.resolved is False
    assert dp.name == ""
    assert dp.slug == ""
