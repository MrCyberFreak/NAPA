# PHASE6_READINESS.md — empirical groundwork for the forecasting model

**Scope:** analysis only. No model was built, fit, or trained; no schema changed.
This is the input to the Phase 6 estimator-design decision.

**Source:** `data/napa.db`, rebuilt from the committed raw archive in the
DATA.md order (2 dated roster grids → schedule → 27 weeks of score sheets →
profiles). Verified row counts match DATA.md: 85 players, 170 skill snapshots,
135 matches, **657 games**, 7,731 pairing rows, 85 form snapshots.

Metric definitions (stated so the numbers are unambiguous):
- A **game** row in `games` is one race (handicapped match) between two players
  of a single game type. `home_score`/`away_score` = racks each won.
- A **rack** is one Bernoulli win/loss observation. A player's **racks** in a
  game type = Σ(`home_score`+`away_score`) over the races they played of that
  type — i.e. every rack they contested, won or lost. Total racks contested =
  **4,250** (8/9/10 = 2,300 / 845 / 1,105).
- **As-of CSR** for a game = the player's CueSpeed rating for that game type
  from the latest `skill_snapshots` row (the two snapshot dates, 2026-06-04/05,
  are the end-of-season ratings — all 85 rostered players carry non-null 8/9/10).

---

## 1. Racks per player, split by game type — the shrinkage tail

Per-player rack counts collapse once you split by game type, because the season
is ~52% 8-ball and the other two games are thin. **This is the dominant signal
for the estimator: most players are data-starved in 9- and 10-ball and must be
shrunk toward their CSR.**

| Game | players | min | median | mean | p90 | max | **<20 racks** | **<30 racks** |
|------|--------:|----:|-------:|-----:|----:|----:|--------------:|--------------:|
| 8-ball  | 79 | 6 | 51 | 52.3 | 95 | 147 | 15 (19%) | 25 (32%) |
| 9-ball  | 71 | 3 | **17** | 22.0 | 39 | 82 | **39 (55%)** | **54 (76%)** |
| 10-ball | 71 | 3 | 25 | 30.0 | 58 | 101 | 25 (35%) | 42 (59%) |

Pooled across all three games the picture looks comfortable (81 players, median
**103** contested racks, mean 96.6, p90 169, max 225; only 6 players < 20 and 12
< 30) — but the model is **per game type**, so the per-type rows above are the
operative numbers. In 9-ball **three quarters of players have < 30 racks** and
the median player has just 17; even 10-ball has 59% under 30. Independent races
per player are thinner still (median **16** races/player across all types), so
the racks within a race are correlated and the effective sample is smaller than
the raw rack count.

> Note: DATA.md's prose summary cites "racks/player median 74" — that appears to
> use an earlier/different attribution; the figures here are recomputed directly
> from the current DB with the definition stated above.

Subs (NULL player_id, not on the roster) contributed racks too — 8/9/10 =
453/115/83 racks across 95 games — but they carry no CSR and are excluded from
the per-player tables (see §2).

**Implication:** a raw per-player, per-game empirical win-rate is unusable for
the majority of players in 9/10-ball. The estimator needs partial pooling /
shrinkage toward a CSR-derived prior (and CSR is the natural prior — see §3).

---

## 2. CSR-at-match coverage — is the skill-difference signal available?

A game is "covered" when **both** players have a usable as-of CSR for that game
type. Coverage fails only when one side is a sub with no resolved 8-digit id
(every resolved player has all three ratings).

| Game | covered / total | coverage |
|------|----------------:|---------:|
| 8-ball  | 280 / 340 | 82.4% |
| 9-ball  | 119 / 140 | 85.0% |
| 10-ball | 163 / 177 | 92.1% |
| **All** | **562 / 657** | **85.5%** |

The **95 uncovered games (14.5%) are exactly the games with a sub on one side.**
The skill-difference signal is reliably available for the large majority of
games, and where it's missing it's missing because the player is unrostered
(no CSR exists), not because of data gaps. Modeling can train on the 562
two-CSR games and treat sub games as held-out / id-less.

---

## 3. The key relationship — per-rack win-rate vs CSR difference

Games binned by (stronger CSR − weaker CSR); the **stronger** player's pooled
**per-rack** win-rate (the modeling target) and **per-match/race** win-rate
(the handicapped outcome) reported per bin, with counts.

### Pooled (all game types) — cleanest shape

| CSR diff | games | racks | rack WR (strong) | match WR (strong) |
|----------|------:|------:|-----------------:|------------------:|
| 0–2   | 37  | 213 | 46.5% | 35.1% |
| 3–5   | 39  | 252 | 52.0% | 56.4% |
| 6–10  | 65  | 409 | 56.7% | 53.8% |
| 11–15 | 53  | 310 | 59.4% | 54.7% |
| 16–20 | 72  | 446 | 59.6% | 50.0% |
| 21–30 | 108 | 679 | 62.0% | 43.5% |
| 31–45 | 89  | 559 | 68.0% | 48.3% |
| 46+   | 92  | 689 | **84.3%** | 72.8% |

**Two findings, both central to the model design:**

1. **The per-rack curve is monotonic and steep.** At CSR parity the stronger
   side wins ~50% of racks (coin flip — CSR difference ≈ 0 → no edge, which
   validates CSR as *the* signal). The per-rack win-rate then climbs smoothly to
   ~84% at the largest gaps. This is a clean, well-behaved skill→probability
   curve — the right shape for a latent-skill / logistic-in-CSR-difference link.

2. **The handicap pushes *matches* toward 50/50, but only in the middle.** The
   match (race) win-rate stays compressed near 50% across the mid-range bins
   (where the per-rack edge is large but the race length absorbs it) — at 21–30
   CSR points the stronger player wins more racks (62%) yet *loses* the match
   slightly more often (43.5%). At the extreme (46+ CSR) the race matrix
   **under-compensates**: the stronger player still takes 72.8% of matches.
   So the handicap balances typical mismatches but leaks edge at the tails —
   precisely the region where "your P minus the matrix-implied P" (the Phase 6
   edge metric) is largest.

### Per game type (same binning; small bins are noisy)

**8-ball**

| diff | games | racks | rack WR | match WR |
|------|------:|------:|--------:|---------:|
| 0–2   | 15  | 92  | 52.2% | 53.3% |
| 3–5   | 20  | 144 | 46.5% | 40.0% |
| 6–10  | 31  | 198 | 54.5% | 51.6% |
| 11–18 | 48  | 285 | 59.3% | 56.2% |
| 19–30 | 58  | 358 | 60.9% | 46.6% |
| 31+   | 104 | 746 | 78.6% | 64.4% |

**9-ball**

| diff | games | racks | rack WR | match WR |
|------|------:|------:|--------:|---------:|
| 0–2   | 8  | 41  | 39.0% | 12.5% |
| 3–5   | 9  | 51  | 51.0% | 55.6% |
| 6–10  | 17 | 113 | 60.2% | 64.7% |
| 11–18 | 19 | 106 | 54.7% | 31.6% |
| 19–30 | 36 | 233 | 62.2% | 41.7% |
| 31+   | 28 | 175 | 74.3% | 53.6% |

**10-ball**

| diff | games | racks | rack WR | match WR |
|------|------:|------:|--------:|---------:|
| 0–2   | 14 | 80  | 43.8% | 28.6% |
| 3–5   | 10 | 57  | 66.7% | 90.0% |
| 6–10  | 17 | 98  | 57.1% | 47.1% |
| 11–18 | 30 | 183 | 62.3% | 60.0% |
| 19–30 | 42 | 270 | 61.9% | 45.2% |
| 31+   | 49 | 327 | 74.9% | 57.1% |

The per-type curves carry the same upward rack-WR trend but the individual bins
(especially 9-ball, where total racks are smallest) are too thin to read on
their own — reinforcing §1: per-type effects must borrow strength (pooled
CSR-difference link with per-game offsets), not be estimated bin-by-bin.

### 3a. Is the 9-ball curve flatter? (called-9 slop hypothesis)

**Hypothesis being tested.** This league requires the 9 to be *called*, but slop
keeps the rack alive (you don't lose for a slopped ball, the game continues). The
conjecture is that this lets weaker players hang around and steal racks, which
would **compress the skill→win-rate relationship in 9-ball specifically** —
i.e. a flatter per-rack curve than 8- and 10-ball.

Two descriptive flatness measures per game type (these are plain summary
statistics of the observed racks — *not* a fitted forecasting model):

**(a) Rise from small to large CSR gap** (pooled rack-WR, stronger player):

| Game | small gap ≤10 (racks) | large gap ≥20 (racks) | **rise** |
|------|----------------------:|----------------------:|---------:|
| 8-ball  | 51.4% (434)  | 73.2% (1069) | **+21.8 pp** |
| 9-ball  | 53.7% (205)  | 67.4% (408)  | **+13.7 pp** |
| 10-ball | 54.9% (235)  | 69.4% (579)  | **+14.5 pp** |

**(b) Slope of a rack-weighted linear-probability fit** (pp of rack-WR per +10
CSR points), with a **game-clustered bootstrap 95% CI** (3,000 reps, resampling
whole races so correlated racks-within-a-race don't inflate precision):

| Game | slope (pp / +10 CSR) | 95% CI | races | racks |
|------|---------------------:|:------:|------:|------:|
| 8-ball  | +5.31 | [4.62, 6.10] | 276 | 1,823 |
| 9-ball  | +5.09 | [3.17, 7.32] | 117 | 719 |
| 10-ball | +4.67 | [3.30, 5.90] | 162 | 1,015 |

Pairwise (independent bootstrap): P(slope₈ > slope₉) = **0.57** (a coin flip),
P(slope₈ > slope₁₀) = 0.81, P(slope₁₀ > slope₉) = 0.34.

**Verdict: no — 9-ball is NOT meaningfully flatter on this season's data.** The
two measures even disagree on the ranking of 9 vs 10: by "rise" 9-ball is
marginally the flattest, but by slope it sits *between* 8 and 10. Its slope point
estimate (5.09) is statistically tied with 8-ball (0.57 ≈ even odds), and its 95%
CI is enormous — [3.17, 7.32] — because the 9-ball sample is the thinnest (117
covered races, 719 racks, vs 1,823 for 8-ball). **All three CIs overlap heavily;
the per-rack slopes are indistinguishable (~4.7–5.3 pp / +10 CSR).**

The most one can say is a weak hint that 8-ball is the *steepest* and 10-ball the
*flattest* (P = 0.81), with 9-ball ambiguous — which is the opposite of the
hypothesis singling out 9-ball. The called-9 slop mechanism remains plausible but
**unconfirmed**; the data cannot yet detect it.

**Design consequence.** Don't hard-code a flatter 9-ball curve. Fit the
skill→prob curve **per game type but partially pooled toward a shared slope**, so
the thin 9/10-ball curves borrow strength from 8-ball rather than chasing noise.
Keep 9-ball's curve free to diverge as data accrues, and revisit this test next
season. (See PHASE6_DESIGN.md §"Per-game curves".)

---

## 4. Pairing depth — `games` is not H2H training data

Distinct head-to-head pairings observed this season in `games`, by meeting count
(unordered player pairs):

| meetings | pairs | share |
|----------|------:|------:|
| 1 | 530 | 90% |
| 2 | 59  | 10% |
| 3 | 3   | 1%  |

- **592 distinct pairings**, **median 1**, mean 1.11, max 3 meetings.
- Id-resolved pairs only (both sides rostered): 503 pairs, same median 1.

**90% of pairings were played exactly once.** A single-session empirical H2H
record is statistically meaningless. The model cannot key on observed pairwise
matchups; it must pool through latent player skill, with the pairing graph used
only as a prior — confirming the architecture DATA.md anticipated.

---

## 5. Data caveats that affect modeling

- **Pending makeups (4 incomplete matches)** — scheduled, date passed, no games
  loaded: R25 5 Amigos vs Pocket Pals, R26 The Furies vs 5 Amigos, R26 Doug's
  Team vs Barbarians, R27 Pocket Predators vs The Furies. These are not missing
  data to impute — they are unplayed. Standings are not final; any train/test
  split or as-of evaluation must treat these as absent, and a re-pull by actual
  play-date will add their score sheets later.
- **`pairing_history` is aggregate lifetime W-L only — never rack-level.** Its
  7,731 directed edges / 6,620 undirected pairs carry per-game W-L counts
  (`g8_w/g8_l/…`, `total_matches`, `lags_won`) but **no rack scores and no
  opponent-skill-at-time**. Lifetime depth is still thin (mean 2.0, median 1
  meeting per directed edge; max 21). It is a **prior on pairings, not training
  rows** — it must stay out of the rack-level likelihood and feed only the skill
  prior.
- **Two CSR snapshot dates** (2026-06-04/05, end-of-season). As-of CSR is
  effectively the final rating, not a true time-of-match value. The mid-season
  drift the schema was built to capture is not yet dense enough to give each game
  its contemporaneous CSR; treat the skill term as static-per-season for now.
- **CSR scale (latest snapshot):** 8-ball 4–136, 9-ball 9–119, 10-ball 10–108 —
  wide enough that the §3 difference bins are well populated across the range.

---

## Readiness summary (what this implies for the estimator)

1. **Shrinkage is mandatory, per game type.** Raw per-player rack rates are
   unusable for most players in 9/10-ball (medians 17/25 racks; 76%/59% under 30).
   Partial pooling toward a CSR-based prior is required, not optional.
2. **CSR difference is a strong, available, monotonic predictor** — ~50% at
   parity rising to ~84% per-rack at the extremes, available for 85.5% of games
   (the other 14.5% are id-less subs).
3. **A latent-skill / logistic-in-CSR-difference rack model with per-game-type
   structure** fits the evidence: clean curve shape, thin per-pair data (median
   1 meeting) ruling out empirical H2H, and a pairing-history prior to lean on.
4. **The handicap balances the middle and leaks at the tails** — the edge metric
   ("your P minus matrix-implied P") will be largest in the 46+ CSR-gap region,
   where the race matrix under-compensates (72.8% match WR).
5. **Honour the caveats:** exclude the 4 pending makeups, keep `pairing_history`
   in the prior only, and treat CSR as static-per-season until drift snapshots
   densify.
