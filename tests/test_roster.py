"""Roster-grid parser tests, pinned to fixtures.

Two layers:
1. Always-on logic tests against a synthetic fixture (tests/data/) that mirrors
   the documented roster-grid format with the exact 10-team / 82-player shape.
2. A strict regression guard that auto-activates when a REAL captured roster
   grid lands in fixtures/ (roster*grid*.mht|.html). Same invariants — this is
   the guard against the "truncate-to-8" bug the plan warns about.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from src.parse.roster import parse_roster_file, roster_summary

REPO = Path(__file__).resolve().parents[1]
SYNTHETIC = REPO / "tests" / "data" / "synthetic_roster_grid.html"

# Verified division shape (as of 2026-06-04) — see build plan.
EXPECTED_SIZES = {
    "Cheat Code Felt Billiards #6": 11,
    "Pocket Predators Felt Billiards #8": 10,
    '"And then?" Felt Billiards #10': 9,
    "Ed's Balls #3": 8,
    "Doug's Team #4": 8,
    "Barbarians #5": 8,
    "Pocket Pals #1": 7,
    "The Furies #2": 7,
    "5 Amigos #7": 7,
    "Trap Gods #9": 7,
}
EXPECTED_TOTAL = 82
EXPECTED_TEAMS = 10


def _find_real_fixture() -> Path | None:
    fx = REPO / "fixtures"
    if not fx.is_dir():
        return None
    for pattern in ("roster*grid*.mht", "roster*grid*.mhtml",
                    "roster*grid*.html", "roster*grid*.htm"):
        hits = sorted(fx.glob(pattern))
        if hits:
            return hits[0]
    return None


def _assert_division_shape(players):
    summary = roster_summary(players)
    assert summary["n_teams"] == EXPECTED_TEAMS, summary["team_sizes"]
    assert summary["n_players"] == EXPECTED_TOTAL, summary["team_sizes"]
    # Guard against the truncate-to-8 bug: exact per-team sizes, 7–11.
    assert summary["team_sizes"] == EXPECTED_SIZES
    assert all(7 <= n <= 11 for n in summary["team_sizes"].values())
    # Exactly one captain per team.
    assert summary["n_captains"] == EXPECTED_TEAMS
    assert all(c == 1 for c in summary["captains_per_team"].values())


# --------------------------------------------------------------------------- #
# Layer 1 — always-on logic tests (synthetic fixture)
# --------------------------------------------------------------------------- #

def test_synthetic_division_shape():
    players = parse_roster_file(SYNTHETIC)
    _assert_division_shape(players)


def test_synthetic_player_fields_well_formed():
    players = parse_roster_file(SYNTHETIC)
    assert players, "parser returned no players"
    ids = set()
    for p in players:
        assert p.team
        assert p.player and not p.player.endswith("(C)")
        assert len(p.player_id) == 8 and p.player_id.isdigit()
        for csr in (p.csr_8, p.csr_9, p.csr_10):
            assert isinstance(csr, int) and 0 < csr < 1000
        assert p.session_matches is None or isinstance(p.session_matches, int)
        ids.add(p.player_id)
    assert len(ids) == len(players), "player IDs should be unique"


def test_spread_is_max_minus_min():
    players = parse_roster_file(SYNTHETIC)
    # The first captain carries the documented 102/62/71 example -> spread 40.
    by_id = {p.player_id: p for p in players}
    special = by_id["10000001"]
    assert (special.csr_8, special.csr_9, special.csr_10) == (102, 62, 71)
    assert special.spread == 40


# --------------------------------------------------------------------------- #
# Layer 2 — strict guard against the REAL capture (auto-skips until present)
# --------------------------------------------------------------------------- #

@pytest.mark.skipif(_find_real_fixture() is None,
                    reason="no real roster-grid fixture committed yet")
def test_real_roster_division_shape():
    players = parse_roster_file(_find_real_fixture())
    _assert_division_shape(players)
