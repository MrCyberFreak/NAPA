"""Flex / individual-point-standings parser tests.

Pinned to a real 14050 capture (fixtures/flex_14050.html). Verifies the
header-driven column map, the embedded ratings split, and that a missing
standings table raises loudly.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from src.parse.flex import FlexRow, parse_flex, parse_flex_file

FIX = Path("fixtures")


def test_parses_real_14050_capture():
    fs = parse_flex_file(FIX / "flex_14050.html")
    assert fs.did == 14050
    assert fs.min_matches == 20
    assert len(fs.rows) >= 30          # 39 players in this capture
    # Ranks are 1..N, contiguous and ordered.
    ranks = [r.rank for r in fs.rows]
    assert ranks[0] == 1
    assert ranks == sorted(ranks)


def test_first_row_fields_and_ratings():
    fs = parse_flex_file(FIX / "flex_14050.html")
    top = fs.rows[0]
    assert top.player == "Ed Kiefer"
    assert top.ratings == (77, 54, 49)
    assert top.ratings_raw == "(77, 54, 49)"
    assert top.ap == 20
    assert top.mp == 1
    assert top.ff_20 == 0
    assert top.ff_14 == 0
    assert top.adj_ap == 20
    assert top.adj_mp == 1            # parsed out of the bracketed "[ 1 ]"
    assert top.avg_ppm == 20.00


def test_every_row_has_a_name_and_no_parens_leak():
    fs = parse_flex_file(FIX / "flex_14050.html")
    for r in fs.rows:
        assert r.player and "(" not in r.player   # ratings stripped from the name
        assert isinstance(r, FlexRow)


def test_missing_table_raises():
    with pytest.raises(ValueError):
        parse_flex("<html><body>One moment, please...</body></html>")
