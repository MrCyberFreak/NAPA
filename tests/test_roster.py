"""Roster-grid parser tests, pinned to fixtures.

Three layers:
1. Always-on logic tests against a synthetic fixture (tests/data/) that mirrors
   the documented roster-grid format with the exact 10-team / 82-player shape.
2. A strict regression guard that auto-activates when a REAL captured roster
   grid lands in fixtures/ (roster*grid*.mht|.html). Same invariants — this is
   the guard against the "truncate-to-8" bug the plan warns about.
3. Header-driven CSR shapes (B6): one pinned capture per known grid header
   ("CSR 8 - 9 - 10" / bare "CSR" / "CSR 9 - 10") + the mismatch guard.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from src.parse.roster import parse_roster, parse_roster_file, roster_summary

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


# --------------------------------------------------------------------------- #
# Layer 3 — header-driven CSR shapes (B6). The grid's CSR header column is
# AUTHORITATIVE for the division's game set; one pinned capture per shape
# (promoted from the B1 recon, captured 2026-06-10).
# --------------------------------------------------------------------------- #

GRID_13985 = REPO / "fixtures" / "roster_grid_13985.html"        # "CSR 8 - 9 - 10"
GRID_13298 = REPO / "fixtures" / "roster_grid_8ball_13298.html"  # bare "CSR"
GRID_13744 = REPO / "fixtures" / "roster_grid_2game_13744.html"  # "CSR 9 - 10"
GRID_14022 = REPO / "fixtures" / "roster_grid_4game_14022.html"  # "CSR 8 - 9 - 10 - 10BP"
GRID_10102 = REPO / "fixtures" / "roster_grid_smjoin_10102.html" # "CSR 8 - 9 - 10 - SM" (old, dash-joined SM)


def test_three_game_grid_13985():
    """3-game LC shape, second division (13985) — multi-division regression."""
    players = parse_roster_file(GRID_13985)
    summary = roster_summary(players)
    assert summary["n_players"] == 76
    assert summary["n_teams"] == 10
    assert all(None not in (p.csr_8, p.csr_9, p.csr_10) for p in players)
    p = {p.player_id: p for p in players}["10080888"]
    assert p.player == "Vanessa Davila"
    assert (p.csr_8, p.csr_9, p.csr_10) == (43, 36, 40)
    assert p.session_matches == 2
    assert p.is_captain


def test_eight_ball_grid_13298():
    """Bare "CSR" header — ONE value per row, mapped to csr_8 only.

    88 players across the ~98-row grid (10 of the rows are team headers);
    the pre-B6 parser produced ZERO players here (triple regex never matched).
    """
    players = parse_roster_file(GRID_13298)
    summary = roster_summary(players)
    assert summary["n_players"] == 88
    assert summary["n_teams"] == 10
    assert all(p.csr_8 is not None for p in players)
    assert all(p.csr_9 is None and p.csr_10 is None for p in players)
    p = {p.player_id: p for p in players}["10054683"]
    assert p.player == "Ruben Vasquez"
    assert p.csr_8 == 90
    assert p.session_matches == 10
    assert p.is_captain
    assert p.spread is None  # one rated game -> no cross-game spread


def test_two_game_dp_grid_13744():
    """"CSR 9 - 10" header — the shape the pre-B6 parser silently mangled
    (9-ball CSR -> csr_8, 10-ball -> csr_9, SM swallowed as csr_10)."""
    players = parse_roster_file(GRID_13744)
    summary = roster_summary(players)
    assert summary["n_players"] == 67
    assert summary["n_teams"] == 8
    assert all(p.csr_8 is None for p in players)
    assert all(p.csr_9 is not None and p.csr_10 is not None for p in players)
    p = {p.player_id: p for p in players}["10024436"]
    assert p.player == "Len LaMaster"
    assert (p.csr_9, p.csr_10) == (77, 58)  # NOT csr_8=77 / csr_9=58 ...
    assert p.session_matches == 9           # ... and SM is NOT a rating
    assert p.is_captain
    assert p.spread == 19


def test_four_game_grid_14022():
    """"CSR 8 - 9 - 10 - 10BP" — the fourth shape (14022 "Paradise", captured
    2026-06-11). Fired the onboarding header guard: a NEW rated game (10BP)
    that the pre-fix parser read as a duplicate 10. Small 4-team division —
    the 7-11 size guard is 13077-specific and does not apply here."""
    players = parse_roster_file(GRID_14022)
    summary = roster_summary(players)
    assert summary["n_players"] == 28
    assert summary["n_teams"] == 4
    assert summary["team_sizes"] == {
        "Pooligan The Paradise Tavern Team #1": 6,
        "Dazed and Confusede The Paradise Tavern Team #2": 8,
        "Okay 5 The Paradise Tavern Team #3": 6,
        "Eat, Shoot and Die The Paradise Tavern Team #4": 8,
    }
    assert all(c == 1 for c in summary["captains_per_team"].values())
    assert all(None not in (p.csr_8, p.csr_9, p.csr_10, p.csr_10bp)
               for p in players)
    p = {p.player_id: p for p in players}["10081737"]
    assert p.player == "Leanetta Malone"
    assert (p.csr_8, p.csr_9, p.csr_10, p.csr_10bp) == (16, 30, 29, 30)
    assert p.session_matches == 0
    assert p.is_captain
    assert p.spread == 14  # 30 - 16; the 10BP rating counts toward the spread


def test_smjoin_grid_10102():
    """OLD grid shape (historical-session backfill): the header DASH-joins SM
    ("CSR 8 - 9 - 10 - SM") and each player's CSR run dash-joins the SM value
    ("50 - 53 - 56 - 18"). The pre-fix parser RAISED here (4 values vs 3 games);
    the fix splits the trailing dash-joined value off as SM, not a 4th game.
    Captured live from the dead division 10102 (2022-23 season)."""
    players = parse_roster_file(GRID_10102)
    summary = roster_summary(players)
    assert summary["n_players"] == 69
    assert summary["n_teams"] == 9
    assert summary["n_captains"] == 9            # one captain per team
    # 3-game LC shape: 8/9/10 rated, no 10BP, and SM is its OWN column (not a rating).
    assert all(None not in (p.csr_8, p.csr_9, p.csr_10) for p in players)
    assert all(p.csr_10bp is None for p in players)
    assert all(p.session_matches is not None for p in players)
    p = {p.player_id: p for p in players}["10050893"]
    assert p.player == "Kevin Pikus"
    assert (p.csr_8, p.csr_9, p.csr_10) == (50, 53, 56)
    assert p.session_matches == 18               # the dash-joined trailing value is SM ...
    assert p.csr_10bp is None                    # ... NOT a fourth game rating
    assert p.is_captain
    assert p.spread == 6                         # 56 - 50


def test_unknown_csr_game_token_raises():
    """A header declaring a game the system can't store must RAISE — a new
    game label means schema/parser extension, never a silent skip."""
    html = """
    <table>
      <tr><td>#</td><td>Mystery Team #1</td><td>CSR<br>8 - 9 - 10 - 10XY</td><td>SM</td></tr>
      <tr><td>1</td><td>Some Player (C)<br>10000098</td><td>50 - 50 - 50 - 50</td><td>0</td></tr>
    </table>
    """
    with pytest.raises(ValueError) as exc:
        parse_roster(html)
    assert "10XY" in str(exc.value)


def test_csr_count_header_mismatch_raises():
    """A row whose value count contradicts its header must RAISE — silent
    positional mapping is exactly the corruption the header parse kills."""
    html = """
    <table>
      <tr><td>#</td><td>Trap Team #1</td><td>CSR<br>8 - 9 - 10</td><td>SM</td></tr>
      <tr><td>1</td><td>Two Values (C)<br>10000099</td><td>77 - 58</td><td>9</td></tr>
    </table>
    """
    with pytest.raises(ValueError) as exc:
        parse_roster(html)
    # The message must carry both the header text and the offending row.
    assert "8 - 9 - 10" in str(exc.value)
    assert "10000099" in str(exc.value)
