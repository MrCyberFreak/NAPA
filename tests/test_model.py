"""Phase 6 forecasting-model tests.

Deterministic (no RNG): synthetic data is generated so the maximum-likelihood
answer is known in closed form, then we assert the fit recovers it. The model
reads only two tables (skill_snapshots, games), so the fixtures build a bare
in-memory DB with just those.
"""

from __future__ import annotations

import math
import sqlite3

import pytest

from src.model import (
    CORE_GAMES,
    Model,
    _fit_offset,
    _fit_slope,
    _sigmoid,
    match_win_prob,
)


# --------------------------------------------------------------------------- #
# Fixtures — a bare DB with only the two tables the model reads
# --------------------------------------------------------------------------- #

def _make_db(snapshots, games) -> sqlite3.Connection:
    """snapshots: (player_id, csr_8, csr_9, csr_10, csr_10bp).
    games: (game_type, home_id, away_id, home_score, away_score)."""
    c = sqlite3.connect(":memory:")
    c.row_factory = sqlite3.Row
    c.execute("CREATE TABLE skill_snapshots (player_id TEXT, captured_date TEXT, "
              "csr_8 INT, csr_9 INT, csr_10 INT, csr_10bp INT, session_matches INT)")
    c.execute("CREATE TABLE games (game_id INTEGER PRIMARY KEY, game_type, "
              "home_player_id TEXT, away_player_id TEXT, home_score INT, away_score INT)")
    for pid, c8, c9, c10, cbp in snapshots:
        c.execute("INSERT INTO skill_snapshots VALUES (?,?,?,?,?,?,?)",
                  (pid, "2026-06-04", c8, c9, c10, cbp, None))
    for gt, hid, aid, hs, as_ in games:
        c.execute("INSERT INTO games (game_type, home_player_id, away_player_id, "
                  "home_score, away_score) VALUES (?,?,?,?,?)", (gt, hid, aid, hs, as_))
    c.commit()
    return c


# --------------------------------------------------------------------------- #
# match_win_prob — the race-aware match probability
# --------------------------------------------------------------------------- #

def test_match_prob_even_race_even_skill_is_half():
    assert match_win_prob(0.5, 3, 3) == pytest.approx(0.5)
    assert match_win_prob(0.5, 5, 5) == pytest.approx(0.5)


def test_match_prob_shorter_race_favored_at_even_per_rack():
    # Same per-rack coin flip, but A only needs 3 while B needs 5 -> A favored.
    assert match_win_prob(0.5, 3, 5) > 0.5
    assert match_win_prob(0.5, 5, 3) < 0.5
    # symmetric complement
    assert match_win_prob(0.5, 3, 5) == pytest.approx(1 - match_win_prob(0.5, 5, 3))


def test_match_prob_monotonic_and_bounded():
    assert match_win_prob(1.0, 5, 5) == pytest.approx(1.0)
    assert match_win_prob(0.0, 5, 5) == pytest.approx(0.0)
    ps = [match_win_prob(p, 5, 5) for p in (0.3, 0.45, 0.5, 0.55, 0.7)]
    assert ps == sorted(ps)  # increasing in per-rack prob


def test_match_prob_general_symmetry():
    # P(A wins) == 1 - P(B wins) with roles/odds flipped.
    for p, ra, rb in [(0.6, 4, 3), (0.35, 5, 2), (0.5, 7, 4)]:
        assert match_win_prob(p, ra, rb) == pytest.approx(1 - match_win_prob(1 - p, rb, ra))


# --------------------------------------------------------------------------- #
# Curve fit — slope recovery + parity + partial pooling
# --------------------------------------------------------------------------- #

def test_fit_slope_recovers_known_beta():
    # Generate (diff, n, k) with k = n*sigmoid(beta0*diff): the score equation is
    # solved exactly at beta0, so the MLE must recover it (rounding aside).
    beta0 = 0.02
    n = 2000
    obs = [(d, n, round(n * _sigmoid(beta0 * d)))
           for d in (-40, -25, -12, -5, 0, 5, 12, 25, 40)]
    fitted = _fit_slope(obs, prior_mean=0.0, prior_sd=None)
    assert fitted == pytest.approx(beta0, abs=2e-3)


def test_curve_parity_is_half_and_monotonic():
    # The slope is only identifiable from games with a CSR gap, so seed several
    # players across the CSR range with stronger-wins-more results.
    beta0 = 0.02
    csrs = {"P40": 40, "P50": 50, "P60": 60, "P70": 70, "P80": 80}
    snaps = [(pid, c, None, None, None) for pid, c in csrs.items()]
    games = []
    ids = list(csrs)
    for i, h in enumerate(ids):
        for a in ids[i + 1:]:
            d = csrs[h] - csrs[a]
            n = 200
            games.append((8, h, a, round(n * _sigmoid(beta0 * d)), n - round(n * _sigmoid(beta0 * d))))
    m = Model.fit(_make_db(snaps, games))
    assert m.slopes[8] > 0
    assert m.rack_prob(60, 60, 8) == pytest.approx(0.5)   # parity -> coin flip
    lo = m.rack_prob(60, 50, 8)
    hi = m.rack_prob(80, 50, 8)
    assert 0.5 < lo < hi < 1.0                            # monotonic in the gap


def test_partial_pooling_pulls_thin_slope_toward_pooled():
    pooled = 0.02
    # A thin game with an extreme empirical slope (few racks): a tiny sample that
    # alone would imply a very steep slope.
    thin = [(40, 6, 6)]  # 6/6 wins at diff 40 -> unpenalized slope wants huge
    free = _fit_slope(thin, prior_mean=pooled, prior_sd=1e6)      # ~no prior
    pulled = _fit_slope(thin, prior_mean=pooled, prior_sd=0.003)  # real prior
    assert free > pulled                       # the prior pulls it down
    assert abs(pulled - pooled) < abs(free - pooled)  # ...toward pooled


# --------------------------------------------------------------------------- #
# Adjustment fit — shrink-to-zero with trust scaling in games
# --------------------------------------------------------------------------- #

def test_offset_zero_data_is_zero():
    assert _fit_offset([], beta=0.02, prior_sd=5.0) == pytest.approx(0.0)


def test_offset_direction_and_shrinkage_by_volume():
    beta = 0.02
    # base_diff 0 (even CSR) but the player wins 70% of racks -> skill > CSR -> +adj.
    many = [(0, 1000, 700)]
    few = [(0, 10, 7)]
    d_many = _fit_offset(many, beta, prior_sd=8.0)
    d_few = _fit_offset(few, beta, prior_sd=8.0)
    assert d_many > 0 and d_few > 0                 # over-performance -> positive
    assert d_many > d_few                            # more data -> trusted further
    # under-performance flips the sign
    assert _fit_offset([(0, 1000, 300)], beta, prior_sd=8.0) < 0


def test_offset_tighter_prior_shrinks_harder():
    beta = 0.02
    obs = [(0, 200, 140)]  # 70% over 200 racks
    loose = _fit_offset(obs, beta, prior_sd=20.0)
    tight = _fit_offset(obs, beta, prior_sd=2.0)
    assert loose > tight > 0


# --------------------------------------------------------------------------- #
# Model integration — estimates, fallback, matchup outputs
# --------------------------------------------------------------------------- #

def test_estimate_none_without_csr():
    db = _make_db(
        snapshots=[("A", 50, None, None, None), ("B", 50, None, None, None)],
        games=[(8, "A", "B", 5, 5)],
    )
    m = Model.fit(db)
    assert m.estimate("A", 8) is not None
    assert m.estimate("A", 9) is None        # no 9-ball CSR
    assert m.estimate("ghost", 8) is None    # unknown player


def test_estimate_thin_data_falls_back_to_csr():
    # One rack -> adj must be shrunk hard toward 0, estimate ~= the CSR prior.
    db = _make_db(
        snapshots=[("A", 50, None, None, None), ("B", 50, None, None, None)],
        games=[(8, "A", "B", 1, 0)],
    )
    m = Model.fit(db)
    e = m.estimate("A", 8)
    assert e.base == 50
    assert e.n_races == 1
    assert abs(e.adj) < 3.0                   # falls back near CSR


def test_matchup_outputs_present_and_edge_definition():
    db = _make_db(
        snapshots=[("A", 80, None, None, None), ("B", 50, None, None, None)],
        games=[(8, "A", "B", 5, 3)],
    )
    m = Model.fit(db)
    mu = m.matchup("A", "B", 8)
    assert mu is not None
    assert mu.race_a >= mu.race_b             # stronger A races to the higher number
    assert 0.0 <= mu.rack_prob_a <= 1.0
    assert mu.edge_a == pytest.approx(mu.match_prob_a - 0.5)
    assert m.matchup("A", "B", 9) is None     # no 9-ball CSR either side


def test_core_games_constant():
    assert CORE_GAMES == (8, 9, 10)
