"""states.php parser tests — pinned to the recon capture.

Verifies NoCo-only scoping (El Paso + Mesa excluded), the 13077->14050 rollover
slug, and that the three shared-venue LC/8-ball pairs get DISTINCT slugs.
"""

from __future__ import annotations

from pathlib import Path

from src import config
from src.parse.states import (NOCO_GROUP, parse_states_file,
                              slug_from_states_name)

RECON = Path("data/raw/_recon/states_colorado_2026-06-17.html")

# El Paso (NAPA of the Rockies 2.0) + Mesa NAPA dids — must never appear.
OUT_OF_SCOPE = {13966, 13942, 13782, 13781, 13667,
                13576, 13575, 13559, 13558, 13557, 13519}


def _rows():
    return {r.did: r for r in parse_states_file(RECON)}


def test_parses_exactly_14_noco_rows():
    rows = parse_states_file(RECON)
    assert len(rows) == 14
    assert all(r.group == NOCO_GROUP for r in rows)


def test_excludes_el_paso_and_mesa():
    assert OUT_OF_SCOPE.isdisjoint(_rows())


def test_14050_rollover_present_13077_gone():
    rows = _rows()
    assert rows[14050].slug == "thursday-big-table-felt-lc"
    assert 13077 not in rows  # 13077 has rolled off states.php; 14050 replaces it


def test_shared_venue_pairs_get_distinct_slugs():
    rows = _rows()
    assert rows[13744].slug == "friday-dp-broomfield-westminster-lc"
    assert rows[13743].slug == "friday-dp-broomfield-westminster-8ball"
    assert rows[13723].slug == "friday-piazza-friday-dp-lc"
    assert rows[13722].slug == "friday-piazza-friday-dp-8ball"
    assert rows[13299].slug == "tuesday-piazzas-tuesday-lc"
    assert rows[13298].slug == "tuesday-piazzas-tuesday-8ball"
    # All 14 slugs distinct on the page (no two live NoCo divisions collide).
    slugs = [r.slug for r in parse_states_file(RECON)]
    assert len(set(slugs)) == 14


def test_every_noco_row_slug_matches_a_curated_division():
    curated = {d.slug for d in config.DIVISIONS.values()}
    assert all(r.slug in curated for r in parse_states_file(RECON))


def test_slug_normalizer_units():
    assert slug_from_states_name('Thursday "Big Table Felt" No Limit LC ') == \
        "thursday-big-table-felt-lc"                       # trailing space anchored
    assert slug_from_states_name('Wednesday "Pharaoh\'s" No Limit LC') == \
        "wednesday-pharaohs-lc"                            # apostrophe dropped
    assert slug_from_states_name('Friday "DP Broomfield Westminster" No Limit 8-ball') == \
        "friday-dp-broomfield-westminster-8ball"           # 8-ball token
    assert slug_from_states_name('Wednesday "WednesdayLC" Standard Limit LC') == \
        "wednesday-wednesdaylc-lc"                          # play-type word ignored
