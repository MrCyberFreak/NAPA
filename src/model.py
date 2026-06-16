"""Phase 6 forecasting model — skill estimates, per-game win-prob curves, edge.

Implements the contract fixed in PHASE6_DESIGN.md, grounded in the empirical
findings of PHASE6_READINESS.md. **Pure stdlib, hand-rolled math** — matching the
project convention (src/ and tools/phase6_readiness.py use only math/statistics,
never numpy, even though it is installed). Reads ONLY from data/napa.db.

The model has three pieces:

1. Per-game skill→probability CURVE (§6, readiness §3/§3a).
   P(player wins a rack) = logistic(beta_g * (skill_A - skill_B)), one slope
   `beta_g` per game type, fitted by IRLS/Newton on the covered games. The curve
   passes through the origin (equal skill -> 0.50 — readiness §3 confirms ~49-50%
   at CSR parity). Per readiness §3a the per-type slopes are statistically
   indistinguishable, so each beta_g is fit **partially pooled** toward a shared
   pooled slope: thin games (9/10/10BP) borrow strength from 8-ball rather than
   chasing noise, while a game free to diverge as its data accrues.

2. Per-player, per-game skill ADJUSTMENT (§1). skill = base + adj, where base is
   the official NAPA CSR snapshot and adj is a CSR-point offset learned from the
   player's own rack results via a penalized (shrink-to-zero) logistic fit. Thin
   data -> adj pulled hard back to 0 -> the estimate falls back to the CSR prior.
   The shrinkage prior SD is set per game type by empirical Bayes.

3. MATCH win probability + EDGE (§3). The per-rack probability is turned into a
   race (match) win probability via the NAPA handicap race targets (src/race.py),
   then the edge = data-predicted match prob - 0.5 (the race is ~50/50 by design;
   readiness §3 showed the matrix under-compensates only at large CSR gaps, which
   is exactly where the edge is largest).

Fitting is league-wide (a player's skill accrues to one row regardless of
division — CLAUDE.md), then applied to whichever division/team the app scopes to.
"""

from __future__ import annotations

import math
import sqlite3
from dataclasses import dataclass

from . import config
from .race import race as race_lookup

# Game types the curve is fit for. 8/9/10 are stored as ints; 10BP as text.
# The scout grid uses 8/9/10; 10BP is fit when present (4-game divisions) but
# carried as the literal key it has in `games`.
CORE_GAMES: tuple[int, ...] = (8, 9, 10)

# --- Hyperparameters (documented, tunable) -------------------------------- #
# Curve partial-pooling prior: each game's slope ~ N(pooled, CURVE_PRIOR_SD^2),
# in logit-per-CSR-point units. The pooled slope lands near 0.020 (readiness's
# ~5.1pp per +10 CSR at the curve centre). 0.005 lets a data-rich game drift to
# its own MLE (~±1.25 pp/+10CSR at 1 SD) while a thin game stays near pooled.
CURVE_PRIOR_SD = 0.005
# adj empirical-Bayes prior SD (CSR points) is clamped to this range so a noisy
# estimate can't make the shrinkage vanish or over-tighten.
ADJ_PRIOR_SD_MIN = 3.0
ADJ_PRIOR_SD_MAX = 15.0
# Only players with at least this many racks in a game type inform the EB
# between-player variance estimate (thin players' unpenalized fits separate).
EB_MIN_RACKS = 12


# --------------------------------------------------------------------------- #
# Numerics (stable logistic + concave 1-D Newton with step-halving)
# --------------------------------------------------------------------------- #

def _sigmoid(z: float) -> float:
    """Numerically stable logistic."""
    if z >= 0:
        return 1.0 / (1.0 + math.exp(-z))
    e = math.exp(z)
    return e / (1.0 + e)


def _newton_1d(grad, hess, x0: float = 0.0, iters: int = 60, tol: float = 1e-9) -> float:
    """Maximize a smooth strictly-concave 1-D objective from its grad/hess.

    Damped Newton with step-halving — the objectives here (penalized logistic
    likelihoods) are strictly concave, so this always converges to the unique
    maximum. `grad`/`hess` are callables of x; `hess` is < 0.
    """
    x = x0
    for _ in range(iters):
        g = grad(x)
        if abs(g) < tol:
            break
        h = hess(x)
        if h >= -1e-15:  # guard: degenerate curvature
            break
        step = -g / h
        # Step-halving: keep the move from overshooting (|grad| must not grow).
        t = 1.0
        for _ in range(40):
            if abs(grad(x + t * step)) <= abs(g) or t < 1e-6:
                break
            t *= 0.5
        x += t * step
    return x


# --------------------------------------------------------------------------- #
# Raw observations pulled from the DB
# --------------------------------------------------------------------------- #

@dataclass(frozen=True)
class _Rack:
    """One game (race) reduced to a rack-level Bernoulli batch, from the
    perspective of fitting: `home` won `k` of `n` racks at CSR diff d=c_home-c_away."""
    game_type: object        # 8/9/10 (int) or '10BP' (str)
    home_id: str
    away_id: str
    c_home: int              # home base CSR for this game type
    c_away: int
    n: int                   # total racks contested (home_score + away_score)
    k: int                   # racks home won (home_score)


def _base_csr_map(conn: sqlite3.Connection) -> dict[str, dict[object, int]]:
    """player_id -> {game_type -> latest NON-NULL CSR}. Multi-division capture
    means the newest snapshot can carry a NULL for a game not in that division's
    grid; taking the latest non-null per type avoids spurious gaps (readiness
    'as-of CSR' definition)."""
    out: dict[str, dict[object, int]] = {}
    # captured_date ascending so later rows overwrite earlier -> ends on latest.
    for row in conn.execute(
        "SELECT player_id, captured_date, csr_8, csr_9, csr_10, csr_10bp "
        "FROM skill_snapshots ORDER BY captured_date"
    ):
        pid = row[0]
        d = out.setdefault(pid, {})
        for gt, val in ((8, row[2]), (9, row[3]), (10, row[4]), ("10BP", row[5])):
            if val is not None:
                d[gt] = val
    return out


def _covered_racks(conn: sqlite3.Connection, base: dict[str, dict[object, int]]) -> list[_Rack]:
    """The two-CSR games (readiness §2 'covered'): both players id-resolved AND
    both carry a base CSR for the game type. Sub games (NULL id / no CSR) drop
    out — exactly the readiness held-out set."""
    racks: list[_Rack] = []
    for row in conn.execute(
        "SELECT game_type, home_player_id, away_player_id, home_score, away_score "
        "FROM games "
        "WHERE home_player_id IS NOT NULL AND away_player_id IS NOT NULL "
        "  AND home_score IS NOT NULL AND away_score IS NOT NULL"
    ):
        gt, hid, aid, hs, as_ = row
        n = (hs or 0) + (as_ or 0)
        if n <= 0:
            continue
        ch = base.get(hid, {}).get(gt)
        ca = base.get(aid, {}).get(gt)
        if ch is None or ca is None:
            continue
        racks.append(_Rack(gt, hid, aid, ch, ca, n, hs))
    return racks


# --------------------------------------------------------------------------- #
# 1. Curve fit — per-game slope beta_g, partially pooled
# --------------------------------------------------------------------------- #

def _fit_slope(obs: list[tuple[float, int, int]], prior_mean: float, prior_sd: float | None) -> float:
    """Fit beta in P(win rack)=sigmoid(beta*d) by penalized Newton.

    obs = list of (d, n, k): CSR diff, trials, successes. A Gaussian prior
    N(prior_mean, prior_sd^2) on beta gives partial pooling; prior_sd=None fits
    the unpenalized pooled MLE.
    """
    inv_var = 0.0 if prior_sd is None else 1.0 / (prior_sd * prior_sd)

    def grad(b: float) -> float:
        g = -inv_var * (b - prior_mean)
        for d, n, k in obs:
            g += d * (k - n * _sigmoid(b * d))
        return g

    def hess(b: float) -> float:
        h = -inv_var
        for d, n, k in obs:
            p = _sigmoid(b * d)
            h -= d * d * n * p * (1.0 - p)
        return h

    return _newton_1d(grad, hess, x0=prior_mean)


# --------------------------------------------------------------------------- #
# 2. Adjustment fit — per player, per game, shrink-to-zero
# --------------------------------------------------------------------------- #

def _fit_offset(obs: list[tuple[int, int, int]], beta: float, prior_sd: float) -> float:
    """Fit a player's CSR offset delta: P(player wins rack)=sigmoid(beta*(c_self+delta-c_opp)),
    with a N(0, prior_sd^2) shrink-to-zero prior. obs = (c_opp_minus_c_self, n, k)
    where the base diff is c_self-c_opp = -(c_opp_minus_c_self); we pass the
    per-game base diff directly. Concave + quadratic prior -> always finite max."""
    inv_var = 1.0 / (prior_sd * prior_sd)

    def z(delta: float, base_diff: float) -> float:
        return beta * (base_diff + delta)

    def grad(delta: float) -> float:
        g = -inv_var * delta
        for base_diff, n, k in obs:
            g += beta * (k - n * _sigmoid(z(delta, base_diff)))
        return g

    def hess(delta: float) -> float:
        h = -inv_var
        for base_diff, n, k in obs:
            p = _sigmoid(z(delta, base_diff))
            h -= beta * beta * n * p * (1.0 - p)
        return h

    return _newton_1d(grad, hess, x0=0.0)


def _unpenalized_offset_info(obs: list[tuple[int, int, int]], beta: float) -> tuple[float, float]:
    """(delta_hat, fisher_info) for the UNpenalized fit — used by empirical Bayes
    to estimate the between-player variance. Clamped to avoid separation blowups."""
    inv_var = 0.0

    def z(delta, base_diff):
        return beta * (base_diff + delta)

    def grad(delta):
        g = 0.0
        for base_diff, n, k in obs:
            g += beta * (k - n * _sigmoid(z(delta, base_diff)))
        return g

    def hess(delta):
        h = 0.0
        for base_diff, n, k in obs:
            p = _sigmoid(z(delta, base_diff))
            h -= beta * beta * n * p * (1.0 - p)
        return h

    # mild ridge only to keep Newton finite during EB, then read info at the MLE
    def grad_r(delta):
        return grad(delta) - 1e-6 * delta

    def hess_r(delta):
        return hess(delta) - 1e-6

    dh = _newton_1d(grad_r, hess_r, x0=0.0)
    dh = max(-80.0, min(80.0, dh))
    info = -hess(dh)
    return dh, info


def _eb_prior_sd(per_player_obs: list[list[tuple[int, int, int]]], beta: float) -> float:
    """Empirical-Bayes between-player SD of the offset for one game type.
    Method of moments on well-observed players: Var(delta_hat) = sigma^2 + E[1/I],
    so sigma^2 = mean(delta_hat^2) - mean(1/I), clamped to a sane CSR range."""
    sq = []
    samp_var = []
    for obs in per_player_obs:
        if sum(n for _, n, _ in obs) < EB_MIN_RACKS:
            continue
        dh, info = _unpenalized_offset_info(obs, beta)
        if info <= 1e-9:
            continue
        sq.append(dh * dh)
        samp_var.append(1.0 / info)
    if not sq:
        return ADJ_PRIOR_SD_MIN
    var = (sum(sq) / len(sq)) - (sum(samp_var) / len(samp_var))
    sd = math.sqrt(var) if var > 0 else ADJ_PRIOR_SD_MIN
    return max(ADJ_PRIOR_SD_MIN, min(ADJ_PRIOR_SD_MAX, sd))


# --------------------------------------------------------------------------- #
# Public model
# --------------------------------------------------------------------------- #

@dataclass(frozen=True)
class Estimate:
    """One player's skill in one game type (§1/§2 display contract)."""
    game: object             # 8/9/10 or '10BP'
    base: int                # official NAPA CSR (the prior)
    adj: float               # data-driven offset, shrunk to 0 when data is thin
    n_races: int             # races backing the adjustment (the §2 'games' count)
    n_racks: int

    @property
    def skill(self) -> float:
        return self.base + self.adj


@dataclass(frozen=True)
class Matchup:
    """A vs B in one game type: the §3 outputs."""
    game: object
    race_a: int
    race_b: int
    rack_prob_a: float       # P(A wins a single rack)
    match_prob_a: float      # P(A wins the handicapped race)
    edge_a: float            # match_prob_a - 0.5 (handicap-expected ~ 0.5 by design)


class Model:
    """Fitted league-wide forecasting model. Build with Model.fit(conn)."""

    def __init__(self, slopes: dict[object, float], pooled_slope: float,
                 base: dict[str, dict[object, int]],
                 adj: dict[str, dict[object, tuple[float, int, int]]],
                 adj_prior_sd: dict[object, float]):
        self.slopes = slopes              # game_type -> beta_g
        self.pooled_slope = pooled_slope
        self._base = base                 # player_id -> {game -> base CSR}
        self._adj = adj                   # player_id -> {game -> (adj, n_races, n_racks)}
        self.adj_prior_sd = adj_prior_sd  # game_type -> EB prior SD

    # -- construction ------------------------------------------------------- #
    @classmethod
    def fit(cls, conn: sqlite3.Connection) -> "Model":
        base = _base_csr_map(conn)
        racks = _covered_racks(conn, base)

        # group covered racks by game type
        by_game: dict[object, list[_Rack]] = {}
        for r in racks:
            by_game.setdefault(r.game_type, []).append(r)

        # (1) pooled slope across ALL covered games, then per-game partial pool
        pooled_obs = [(float(r.c_home - r.c_away), r.n, r.k) for r in racks]
        pooled = _fit_slope(pooled_obs, prior_mean=0.0, prior_sd=None) if pooled_obs else 0.0
        slopes: dict[object, float] = {}
        for gt, rs in by_game.items():
            obs = [(float(r.c_home - r.c_away), r.n, r.k) for r in rs]
            slopes[gt] = _fit_slope(obs, prior_mean=pooled, prior_sd=CURVE_PRIOR_SD)

        # (2) per-player offsets per game type, EB shrink-to-zero
        # gather each player's racks per game (from their own perspective)
        # player -> game -> list[(base_diff_self_minus_opp, n, k_self)]
        pobs: dict[str, dict[object, list[tuple[int, int, int]]]] = {}
        for r in racks:
            # home perspective
            pobs.setdefault(r.home_id, {}).setdefault(r.game_type, []).append(
                (r.c_home - r.c_away, r.n, r.k))
            # away perspective
            pobs.setdefault(r.away_id, {}).setdefault(r.game_type, []).append(
                (r.c_away - r.c_home, r.n, r.n - r.k))

        adj_prior_sd: dict[object, float] = {}
        for gt, rs in by_game.items():
            beta = slopes[gt]
            per_player = [p[gt] for p in pobs.values() if gt in p]
            adj_prior_sd[gt] = _eb_prior_sd(per_player, beta)

        adj: dict[str, dict[object, tuple[float, int, int]]] = {}
        for pid, games in pobs.items():
            for gt, obs in games.items():
                beta = slopes[gt]
                delta = _fit_offset(obs, beta, adj_prior_sd[gt])
                n_races = len(obs)
                n_racks = sum(n for _, n, _ in obs)
                adj.setdefault(pid, {})[gt] = (delta, n_races, n_racks)

        return cls(slopes, pooled, base, adj, adj_prior_sd)

    # -- estimates ---------------------------------------------------------- #
    def estimate(self, player_id: str, game: object) -> Estimate | None:
        """The §1 base+adj estimate, or None if the player has no CSR for `game`."""
        b = self._base.get(player_id, {}).get(game)
        if b is None:
            return None
        a, n_races, n_racks = self._adj.get(player_id, {}).get(game, (0.0, 0, 0))
        return Estimate(game=game, base=b, adj=a, n_races=n_races, n_racks=n_racks)

    # -- curve + match prob ------------------------------------------------- #
    def rack_prob(self, skill_a: float, skill_b: float, game: object) -> float:
        """P(A wins a single rack) from the per-game curve."""
        beta = self.slopes.get(game, self.pooled_slope)
        return _sigmoid(beta * (skill_a - skill_b))

    def matchup(self, player_a: str, player_b: str, game: object) -> Matchup | None:
        """Full §3 matchup outputs for A vs B in one game type, or None if either
        player lacks a CSR for it."""
        ea = self.estimate(player_a, game)
        eb = self.estimate(player_b, game)
        if ea is None or eb is None:
            return None
        p = self.rack_prob(ea.skill, eb.skill, game)
        race_a, race_b = race_lookup(ea.base, eb.base)  # handicap from official CSR
        mp = match_win_prob(p, race_a, race_b)
        return Matchup(game=game, race_a=race_a, race_b=race_b,
                       rack_prob_a=p, match_prob_a=mp, edge_a=mp - 0.5)


def match_win_prob(p: float, race_a: int, race_b: int) -> float:
    """P(A wins a race-to-(race_a) vs race-to-(race_b)) given per-rack P(A)=p.

    The race ends when someone reaches their target; equivalently, over a fixed
    race_a+race_b-1 racks exactly one side reaches its target first, so A wins iff
    A takes >= race_a of those racks. Exact (binomial sum), targets are small."""
    if race_a <= 0:
        return 1.0
    if race_b <= 0:
        return 0.0
    total = race_a + race_b - 1
    prob = 0.0
    for j in range(race_a, total + 1):
        prob += math.comb(total, j) * (p ** j) * ((1.0 - p) ** (total - j))
    return prob
