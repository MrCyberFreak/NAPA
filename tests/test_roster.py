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

EXPECTED_TEAMS = 10

# Synthetic fixture shape (the plan's seed data: 82 players).
SYNTHETIC_SIZES = {
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
SYNTHETIC_TOTAL = 82

# REAL division shape, pinned from the live capture in fixtures/roster_grid.html
# (browser-fetched 2026-06-04). 86 players — the roster grew vs the plan's seed
# (subs joined); team names carry the full "Felt Billiards Team #N" form.
REAL_SIZES = {
    "Pocket Pals Felt Billiards Team #1": 7,
    "The Furies Felt Billiards Team #2": 8,
    "Ed's Balls Felt Billiards Team #3": 8,
    "Doug's Team Felt Billiards Team #4": 8,
    "Barbarians Felt Billiards Team #5": 8,
    "Cheat Code Felt Billiards Team #6": 11,
    "5 Amigos Felt Billiards Team #7": 8,
    "Pocket Predators Felt Billiards Team #8": 10,
    "Trap Gods Felt Billiards Team #9": 8,
    '"And then?" Felt Billiards Team #10': 10,
}
REAL_TOTAL = 86


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


def _assert_division_shape(players, expected_sizes, expected_total):
    summary = roster_summary(players)
    assert summary["n_teams"] == EXPECTED_TEAMS, summary["team_sizes"]
    assert summary["n_players"] == expected_total, summary["team_sizes"]
    # Guard against the truncate-to-8 bug: exact per-team sizes, 7–11.
    assert summary["team_sizes"] == expected_sizes
    assert all(7 <= n <= 11 for n in summary["team_sizes"].values())
    # Exactly one captain per team.
    assert summary["n_captains"] == EXPECTED_TEAMS
    assert all(c == 1 for c in summary["captains_per_team"].values())


# --------------------------------------------------------------------------- #
# Layer 1 — always-on logic tests (synthetic fixture)
# --------------------------------------------------------------------------- #

def test_synthetic_division_shape():
    players = parse_roster_file(SYNTHETIC)
    _assert_division_shape(players, SYNTHETIC_SIZES, SYNTHETIC_TOTAL)


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
    _assert_division_shape(players, REAL_SIZES, REAL_TOTAL)


@pytest.mark.skipif(_find_real_fixture() is None,
                    reason="no real roster-grid fixture committed yet")
def test_real_roster_fields_well_formed():
    """Parser correctness against the real DOM: dash-separated CSRs, real IDs."""
    players = parse_roster_file(_find_real_fixture())
    seen = set()
    for p in players:
        assert p.team and p.player and not p.player.endswith("(C)")
        assert len(p.player_id) == 8 and p.player_id.isdigit()
        for csr in (p.csr_8, p.csr_9, p.csr_10):
            assert isinstance(csr, int) and 0 < csr < 1000
        # A player can be rostered on multiple teams (real: Kat Plavnick is on
        # two), so IDs are NOT globally unique — but each (team, id) is.
        key = (p.team, p.player_id)
        assert key not in seen, f"duplicate row within a team: {key}"
        seen.add(key)


@pytest.mark.skipif(_find_real_fixture() is None,
                    reason="no real roster-grid fixture committed yet")
def test_real_roster_allows_multi_team_players():
    """Real-world invariant: at least one player is rostered on >1 team — the
    parser must preserve those rows (don't dedupe by id), per the subs rule."""
    players = parse_roster_file(_find_real_fixture())
    teams_per_id: dict[str, set[str]] = {}
    for p in players:
        teams_per_id.setdefault(p.player_id, set()).add(p.team)
    multi = {pid: ts for pid, ts in teams_per_id.items() if len(ts) > 1}
    assert multi, "expected at least one multi-team player in the real roster"
