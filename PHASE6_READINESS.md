# PHASE6_READINESS.md — empirical groundwork for the forecasting model

> **RECOMPUTED 2026-06-20 against the full multi-division + multi-SEASON archive
> (42 recovered historical sessions, 2022-2026, now loaded and 100% match-linked).
> This is a major jump from the prior build: games 3,906 → 23,227, players 715 →
> 1,274, 56 divisions now carry games (was 13). Two NEW game types enter — F8
> (Felt-8-ball, `skill_snapshots.csr_f8`) and 7-ball (`csr_7b`) — alongside 10BP,
> from the historical LC+F8 / 7-ball divisions. The profile pass is now LOADED
> (full `profiles=True` rebuild — 708/708 profiles, 0 failures).**
> **The §5 `pairing_history` lifetime-H2H layer carries 48,076 directed edges over
> 704 players, all with per-game W-L splits (see §5). ONE caveat still bounds this
> build: every CSR snapshot is dated June 2026 (the roster grids,
> including the historical ones, were all captured in the 06-2026 backfill), but
> games now span 2022-2026 — so the ~83% of games that are historical carry the
> players' CURRENT (2026) CSR, not their rating at the time of play. The
> skill-difference signal for historical games is anachronistic; read §3 as a
> mostly-2026-CSR relationship.**
> The DESIGN decisions in PHASE6_DESIGN.md (base+adj, shrink-to-prior, per game
> type) are unaffected and reinforced (§1, §3a).

**Scope:** analysis only. No model was built, fit, or trained; no schema changed.
This is the input to the Phase 6 estimator-design decision.

**Source:** `data/napa.db`, rebuilt from the committed raw archive in the DATA.md
pass order (roster grids → schedules → score sheets → profiles). Row counts: **1,274 players, 5,043 skill snapshots, 535 teams, 6,198
matches, 23,227 games** (8 / 9 / 10 / 10BP / F8 / 7-ball = 13,119 / 4,637 / 5,264
/ 118 / 81 / 8), spanning **56 divisions** with games across the 2022-2026
seasons. Regenerate deterministically (seeded bootstrap) with
`python tools/phase6_readiness.py`.

Metric definitions (stated so the numbers are unambiguous):
- A **game** row in `games` is one race (handicapped match) between two players
  of a single game type. `home_score`/`away_score` = racks each won.
- A **rack** is one Bernoulli win/loss observation. A player's **racks** in a
  game type = Σ(`home_score`+`away_score`) over the races they played of that
  type — i.e. every rack they contested, won or lost. Total racks contested =
  **144,071** (8 / 9 / 10 / 10BP / F8 / 7-ball = 84,813 / 26,974 / 30,970 / 789 /
  462 / 63).
- **As-of CSR** for a game type = the player's most recent NON-NULL
  `skill_snapshots` value for that type. Snapshots span **2026-06-04 … 2026-06-20
  only** — staggered current-season grid captures. Because the historical roster
  grids were captured in the 06-2026 backfill, historical games are matched
  against the players' 2026 ratings, NOT a contemporaneous value (see §5).

---

## 1. Racks per player, split by game type — the shrinkage tail

Per-player rack counts collapse once you split by game type. **This is the
dominant signal for the estimator: most players are data-starved in 9-, 10-,
10BP-, F8- and 7-ball and must be shrunk toward their CSR.** Resolved players only
(8-digit id); subs (NULL id) are excluded from the per-player tables but their
racks count in the totals above.

| Game | players | min | median | mean | p90 | max | **<20 racks** | **<30 racks** |
|------|--------:|----:|-------:|-----:|----:|----:|--------------:|--------------:|
| 8-ball  | 1,175 | 2 | 76 | 141.0 | 384 | 1,108 | 234 (20%) | 328 (28%) |
| 9-ball  | 1,020 | 2 | **30** | 51.7 | 124 | 478 | 362 (35%) | **506 (50%)** |
| 10-ball | 1,020 | 2 | 33 | 59.3 | 149 | 559 | 343 (34%) | 474 (46%) |
| 10BP    |   105 | 2 | **10** | 15.0 | 33 |  82 | 84 (80%) | **93 (89%)** |
| F8      |    74 | 3 |  8 | 12.0 | 21 |  52 | 62 (84%) | 70 (95%) |
| 7-ball  |    11 | 5 | 10 | 11.5 | 20 |  20 |  9 (82%) | 11 (100%) |

Pooling across all game types (1,215 players, median **130** contested racks,
mean 231.6, p90 646, max 1,815; 173 players < 20 racks, 233 < 30) is deeper than
the prior single-season build (median 47) — four seasons of history add bulk for
the recurring core. But the per-TYPE tables still show the starvation: the median
9-ball player has 30 racks, 10-ball 33, and the niche games (10BP/F8/7-ball)
collapse to medians of **10 / 8 / 10** on 105 / 74 / 11-player bases. In 9-ball
**50% of players have < 30 racks**; 10BP / F8 / 7-ball are 89% / 95% / 100% under
30. Independent races per player are thinner still (pooled median **22**; per type
8/9/10/10BP/F8/7-ball medians 13/5/6/2/2/1), so racks within a race are correlated
and the effective sample is smaller than the raw rack count.

Subs (NULL id, not on a roster) contributed racks too — 8 / 9 / 10 / 10BP / F8 =
3,916 / 1,230 / 1,463 / 7 / 37 racks across 626 / 229 / 253 / 1 / 6 games (7-ball
had no sub games) — but they carry no CSR and are excluded from the per-player
tables (see §2).

**Implication:** a raw per-player, per-game empirical win-rate is unusable for the
majority of players in every game type but 8-ball. The estimator needs partial
pooling / shrinkage toward a CSR-derived prior (and CSR is the natural prior — see
§3). Multi-season history deepens the core but the per-type tail persists, and the
three niche games (10BP/F8/7-ball) are nearly all shrinkage.

---

## 2. CSR-at-match coverage — is the skill-difference signal available?

A game is "covered" when **both** players have a usable as-of CSR for that game
type. The **1,124 uncovered games (4.8%) are almost exactly the 1,115 sub games**
(a player with no roster row, hence no CSR) — coverage essentially never fails for
a missing rating, only for an unrostered player who has none. The ~9-game
remainder are historical F8/10BP games where a rostered player lacks that niche
type's rating.

| Game | covered / total | coverage |
|------|----------------:|---------:|
| 8-ball  | 12,492 / 13,119 | 95.2% |
| 9-ball  |  4,408 / 4,637 | 95.1% |
| 10-ball |  5,011 / 5,264 | 95.2% |
| 10BP    |    116 / 118 | 98.3% |
| F8      |     68 / 81 | 84.0% |
| 7-ball  |      8 / 8 | 100.0% |
| **All** | **22,103 / 23,227** | **95.2%** |

Coverage holds at ~95% league-wide (F8 is the one low type at 84% — its historical
divisions have more unrated participants). The skill-difference signal is reliably
available, and where it's missing it's missing because the player is unrostered
(no CSR exists), not because of data gaps. Modeling can train on the 22,103
two-CSR games and treat sub games as held-out / id-less. **But see §5: for
historical games the available CSR is the 2026 value, not contemporaneous.**

---

## 3. The key relationship — per-rack win-rate vs CSR difference

Games binned by (stronger CSR − weaker CSR), using each game's own type's CSR;
the **stronger** player's pooled **per-rack** win-rate (the modeling target) and
**per-match/race** win-rate (the handicapped outcome) per bin, with counts.
**Caveat (§5):** for the historical majority of games the CSR is the 2026 rating,
so the diff is approximate for those — the curve below mixes contemporaneous
(active-season) and anachronistic (historical) CSR.

### Pooled (all game types) — cleanest shape

| CSR diff | games | racks | rack WR (strong) | match WR (strong) |
|----------|------:|------:|-----------------:|------------------:|
| 0–2   | 1,502 |  8,856 | 50.0% | 49.8% |
| 3–5   | 1,907 | 10,979 | 52.4% | 51.2% |
| 6–10  | 3,027 | 17,731 | 55.1% | 53.1% |
| 11–15 | 2,675 | 15,331 | 58.2% | 54.7% |
| 16–20 | 2,335 | 13,773 | 61.0% | 55.2% |
| 21–30 | 4,019 | 24,476 | 65.0% | 56.3% |
| 31–45 | 3,487 | 22,421 | 71.9% | 60.7% |
| 46+   | 3,151 | 23,795 | **83.2%** | 67.1% |

**Two findings, both central to the model design:**

1. **The per-rack curve is monotonic and steep.** At CSR parity the stronger side
   wins ~50% of racks (coin flip — CSR difference ≈ 0 → no edge, which validates
   CSR as *the* signal). The per-rack win-rate then climbs smoothly to ~83% at the
   largest gaps. This is a clean, well-behaved skill→probability curve — the right
   shape for a latent-skill / logistic-in-CSR-difference link — and it holds up
   even with four seasons pooled and historical CSR being approximate.

2. **The handicap holds *matches* near 50–61% across the whole mid-range and leaks
   only at the tail.** Match (race) win-rate stays compressed at ~50–56% from the
   3–5 bin through 21–30 even as the per-rack edge climbs from 52% to 65% — the
   race length absorbs it. Only at the extremes (31–45, 46+) does the matrix
   under-compensate: the stronger player takes 60.7% then 67.1% of matches. So the
   handicap balances typical mismatches but leaks edge at the tail — precisely the
   region where "your P minus the matrix-implied P" (the Phase 6 edge metric) is
   largest.

### Per game type (same binning; small bins are noisy)

**8-ball**

| diff | games | racks | rack WR | match WR |
|------|------:|------:|--------:|---------:|
| 0–2   |   768 |  4,683 | 50.2% | 50.4% |
| 3–5   |   938 |  5,637 | 52.3% | 50.3% |
| 6–10  | 1,571 |  9,675 | 55.3% | 52.9% |
| 11–18 | 2,111 | 12,657 | 58.8% | 54.5% |
| 19–30 | 2,700 | 16,751 | 64.6% | 57.0% |
| 31+   | 4,404 | 31,491 | 79.0% | 65.3% |

**9-ball**

| diff | games | racks | rack WR | match WR |
|------|------:|------:|--------:|---------:|
| 0–2   |   320 | 1,821 | 49.8% | 49.1% |
| 3–5   |   434 | 2,325 | 53.4% | 53.0% |
| 6–10  |   694 | 3,841 | 55.2% | 55.0% |
| 11–18 |   867 | 4,772 | 58.6% | 55.0% |
| 19–30 | 1,008 | 5,838 | 64.3% | 55.6% |
| 31+   | 1,085 | 7,147 | 75.5% | 60.5% |

**10-ball**

| diff | games | racks | rack WR | match WR |
|------|------:|------:|--------:|---------:|
| 0–2   |   400 | 2,268 | 50.0% | 49.8% |
| 3–5   |   519 | 2,924 | 51.9% | 51.4% |
| 6–10  |   743 | 4,100 | 54.9% | 52.4% |
| 11–18 | 1,089 | 6,127 | 59.9% | 55.6% |
| 19–30 | 1,170 | 6,928 | 63.9% | 54.0% |
| 31+   | 1,090 | 7,160 | 74.2% | 59.8% |

**10BP** (thin — one lineage's worth, read with care)

| diff | games | racks | rack WR | match WR |
|------|------:|------:|--------:|---------:|
| 0–2   |  7 |  45 | 35.6% | 14.3% |
| 3–5   |  6 |  37 | 48.6% | 33.3% |
| 6–10  | 10 |  60 | 40.0% | 10.0% |
| 11–18 | 28 | 169 | 60.4% | 60.7% |
| 19–30 | 25 | 167 | 62.9% | 52.0% |
| 31+   | 40 | 297 | 78.5% | 82.5% |

**F8** (thin — historical LC+F8 divisions only)

| diff | games | racks | rack WR | match WR |
|------|------:|------:|--------:|---------:|
| 0–2   |  7 |  39 | 51.3% | 57.1% |
| 3–5   | 10 |  56 | 44.6% | 50.0% |
| 6–10  |  7 |  39 | 48.7% | 28.6% |
| 11–18 | 12 |  66 | 60.6% | 66.7% |
| 19–30 | 15 |  73 | 60.3% | 60.0% |
| 31+   | 17 | 106 | 77.4% | 70.6% |

**7-ball** (8 games total — uninterpretable, listed for completeness)

| diff | games | racks | rack WR | match WR |
|------|------:|------:|--------:|---------:|
| 6–10  | 2 | 16 | 50.0% | 50.0% |
| 11–18 | 2 | 17 | 52.9% | 50.0% |
| 19–30 | 2 | 15 | 73.3% | 100.0% |
| 31+   | 2 | 15 | 60.0% | 0.0% |

The four populated curves (8/9/10/10BP) carry the same upward rack-WR trend; F8 is
directionally similar on a thin base, and 7-ball (8 games) is noise. The small
bins (10BP/F8 at small gaps, 7-ball entirely) are too thin to read on their own —
reinforcing §1: per-type effects must borrow strength (pooled CSR-difference link
with per-game offsets), not be estimated bin-by-bin.

### 3a. Is the 9-ball curve flatter? (called-9 slop hypothesis)

**Hypothesis being tested.** This league requires the 9 to be *called*, but slop
keeps the rack alive. The conjecture is that this lets weaker players hang around
and steal racks, **compressing the skill→win-rate relationship in 9-ball
specifically** — a flatter per-rack curve than the other game types.

Two descriptive flatness measures per game type (plain summary statistics of the
observed racks — *not* a fitted forecasting model):

**(a) Rise from small to large CSR gap** (pooled rack-WR, stronger player):

| Game | small gap ≤10 (racks) | large gap ≥20 (racks) | **rise** |
|------|----------------------:|----------------------:|---------:|
| 8-ball  | 53.3% (19,995) | 74.4% (46,889) | **+21.2 pp** |
| 9-ball  | 53.4% (7,987)  | 70.7% (12,567) | **+17.2 pp** |
| 10-ball | 52.8% (9,292)  | 69.6% (13,363) | **+16.8 pp** |
| 10BP    | 40.8% (142)    | 73.7% (453)    | **+32.9 pp** |
| F8      | 47.8% (134)    | 71.8% (174)    | **+24.1 pp** |
| 7-ball  | 50.0% (16)     | 66.7% (30)     | **+16.7 pp** |

**(b) Slope of a rack-weighted linear-probability fit** (pp of rack-WR per +10
CSR points), with a **game-clustered bootstrap 95% CI** (3,000 reps, resampling
whole races so correlated racks-within-a-race don't inflate precision):

| Game | slope (pp / +10 CSR) | 95% CI | races | racks |
|------|---------------------:|:------:|------:|------:|
| 8-ball  | +4.89 | [4.77, 5.01] | 12,492 | 80,894 |
| 9-ball  | +5.08 | [4.78, 5.39] |  4,408 | 25,744 |
| 10-ball | +5.17 | [4.85, 5.47] |  5,011 | 29,507 |
| 10BP    | +7.89 | [6.33, 9.60] |    116 |    775 |
| F8      | +5.83 | [3.86, 9.20] |     68 |    379 |
| 7-ball  | +1.78 | [-4.50, 19.90] |    8 |     63 |

Pairwise (independent bootstrap): P(slope₈ > slope₉) = **0.12**, P(slope₉ >
slope₁₀) = **0.35**, P(slope₈ > slope₁₀) = **0.05**. 10BP is clearly steepest of
the populated types (P(·>10BP) ≈ 0.00) but rests on 116 races; F8 (68 races) and
7-ball (8 races) are too thin to rank.

**Verdict: no — 9-ball is NOT flatter.** Its slope (5.08) sits in the *middle* of
the three core games, not the lowest. With four seasons of data the CIs have
tightened (8-ball [4.77, 5.01]) and a small ordering has emerged: the **flattest**
core game is now **8-ball** (4.89), with 10-ball steepest (5.17) — P(slope₈ >
slope₁₀) = 0.05 is approaching significance. That is the *opposite* of the
hypothesis, which singled out 9-ball. The core slopes remain close (all ~4.9–5.2
pp / +10 CSR) and 9-ball vs 10-ball is a coin flip (P = 0.35). The called-9 slop
mechanism remains **unconfirmed and contradicted in direction**; the data do not
detect it.

**Design consequence (unchanged, reinforced).** Don't hard-code a flatter 9-ball
curve. Fit the skill→prob curve **per game type but partially pooled toward a
shared slope**, so the thin 9/10/10BP/F8/7-ball curves borrow strength from 8-ball
rather than chasing noise. Keep each curve free to diverge as data accrues, and
revisit this test next season. (See PHASE6_DESIGN.md §"Per-game curves".)

---

## 4. Pairing depth — `games` is not H2H training data

Distinct head-to-head pairings observed in `games`, by meeting count (unordered
player pairs, pooled across divisions and seasons):

| meetings | pairs | share |
|----------|------:|------:|
| 1 | 11,300 | 71% |
| 2 |  3,033 | 19% |
| 3 |    924 | 6%  |
| 4 |    381 | 2%  |
| 5 |    149 | 1%  |
| 6+ |    118 | 1%  |

- **15,905 distinct pairings** (by name), **median 1**, mean 1.46, max 13 meetings.
- Id-resolved pairs only (both sides rostered): 15,141 pairs, same median 1.

**71% of pairings were played exactly once** (down from 84% in the single-season
build — four seasons add repeat meetings, and the max rises to 13). But the median
is still 1 and the mean barely 1.46: a per-pair empirical H2H record remains
statistically meaningless for the bulk of pairings. The model cannot key on
observed pairwise matchups; it must pool through latent player skill, with the
pairing graph used only as a prior — confirming the architecture DATA.md
anticipated.

---

## 5. Data caveats that affect modeling

- **CSR is 2026-only; games span 2022-2026 (the biggest caveat this build).**
  Every `skill_snapshots` row is dated **2026-06-04 … 2026-06-20** — the roster
  grids, including the 42 historical sessions', were all captured in the 06-2026
  backfill. So a 2022 or 2023 game is matched against the players' **2026** CSR,
  not their rating at the time. ~83% of games (the historical majority) carry this
  anachronism. The §3 curve survives it (still clean and monotonic), but the
  skill term for historical games is approximate; treat it as a static, current
  estimate of relative skill, and weight or flag historical games accordingly when
  fitting. True contemporaneous historical CSR is not recoverable from the current
  grid captures.
- **`pairing_history` (lifetime H2H) is now LOADED.** A full `profiles=True`
  rebuild loaded **708/708 profiles (0 failures)**, giving **48,076 directed
  RIVALS edges** over **704 subjects** — **36,022 distinct unordered pairings**
  (33% reciprocal/both-sided), and **all 48,076 edges carry per-game W-L splits
  (100% drilled)**. This layer is AGGREGATE lifetime W-L (no rack detail, no
  opponent-skill-at-time), kept separate from `games` per the hard rules.
  **Densification value:** of the 15,141 id-resolved game pairings (§4), **13,174
  (87%) also have a lifetime H2H edge**, and **22,848 lifetime pairings are NOT in
  this season's games** — extra prior signal the games window alone never sees. Use
  it as an aggregate-lifetime H2H prior, NOT as rack-level training data.
- **Pending makeups: 30 across the league** (date ≤ 2026-06-20, byes excluded),
  surfaced by `db.pending_matches(as_of)`. These are genuine off-schedule makeups
  / not-yet-played, not capture lag (14022's R1 is now posted and dropped off):
  13723 (7), 13744 (5), 13743 (5), 13077 (4), 13937 (3), 13711 (2), 13722 (2),
  plus the shared 13298/13299 Dec-R1 phantom (1 each). Not data to impute — any
  train/test split must treat them as absent.
- **CSR scale (latest snapshot, per game type):** 8-ball 0–147 (n=1,272), 9-ball
  6–130 (n=1,264), 10-ball 7–131 (n=1,264), 10BP 17–114 (n=205), F8 20–129
  (n=163), 7-ball 35–144 (n=66). A few players carry no `csr_8` (9/10-only "DP LC"
  divisions); 10BP/F8/7-ball exist only for their respective niche divisions —
  wide enough that the §3 difference bins are populated across the range for the
  core types.

---

## Readiness summary (what this implies for the estimator)

1. **Shrinkage is mandatory, per game type.** Raw per-player rack rates are
   unusable for most players outside 8-ball (medians 30/33/10/8/10 racks in
   9/10/10BP/F8/7-ball; 50%/46%/89%/95%/100% under 30). Four seasons deepen the
   core but the per-type tail persists; partial pooling toward a CSR-based prior is
   required, not optional.
2. **CSR difference is a strong, available, monotonic predictor** — ~50% at parity
   rising to ~83% per-rack at the extremes, available for 95.2% of games (the other
   4.8% are almost exactly the id-less sub games). **But the skill term is
   2026-only**: historical games carry current, not contemporaneous, CSR (caveat 1).
3. **A latent-skill / logistic-in-CSR-difference rack model with per-game-type
   structure** fits the evidence: clean curve shape across the populated game
   types, thin per-pair data (median 1 meeting) ruling out empirical H2H, and core
   slopes too close to separate (partial pooling toward a shared slope).
4. **The handicap balances the whole mid-range and leaks only at the tail** — the
   edge metric ("your P minus matrix-implied P") will be largest in the 31+ /46+
   CSR-gap region, where the race matrix under-compensates (60.7% then 67.1% match
   WR).
5. **Honour the caveats:** treat CSR as static / 2026-valued (historical games are
   anachronistic) and exclude the 30 pending makeups. `pairing_history` is now
   loaded (48,076 directed edges over 704 subjects, fully drilled to per-game W-L)
   and usable as an aggregate-lifetime H2H prior — never as rack-level training data.
