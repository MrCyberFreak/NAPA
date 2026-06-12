# PHASE6_READINESS.md — empirical groundwork for the forecasting model

> **RECOMPUTED 2026-06-12 against the full multi-division archive.** Every number
> below now pools across the league (12 of the 14 divisions carry games) instead
> of division 13077 alone — this supersedes the original 13077-only analysis
> (which held 85 players / 657 games). A **fourth game type, 10BP**, enters here
> (the 4-game divisions 13986/14022, keyed to `skill_snapshots.csr_10bp`).
> Two caveats on completeness, both self-healing (see §5): 13722's score sheets
> and 14022's R1 results are not yet captured, so those divisions contribute no
> games; and the profile pass is excluded (`profiles=False`, deferred harvests),
> so `pairing_history`/`player_form` are empty. The DESIGN decisions in
> PHASE6_DESIGN.md (base+adj, shrink-to-prior, per game type) are unaffected —
> and are reinforced (§1, §3a).

**Scope:** analysis only. No model was built, fit, or trained; no schema changed.
This is the input to the Phase 6 estimator-design decision.

**Source:** `data/napa.db`, rebuilt from the committed raw archive in the DATA.md
pass order (roster grids → schedules → score sheets), all 14 registry divisions;
the profile pass is excluded. Row counts: **707 players, 1,164 skill snapshots,
135 teams, 1,634 matches, 3,667 games** (8 / 9 / 10 / 10BP = 1,903 / 812 / 864 /
88), spanning **12 divisions** with games. Regenerate deterministically (seeded
bootstrap) with `python tools/phase6_readiness.py`.

Metric definitions (stated so the numbers are unambiguous):
- A **game** row in `games` is one race (handicapped match) between two players
  of a single game type. `home_score`/`away_score` = racks each won.
- A **rack** is one Bernoulli win/loss observation. A player's **racks** in a
  game type = Σ(`home_score`+`away_score`) over the races they played of that
  type — i.e. every rack they contested, won or lost. Total racks contested =
  **22,719** (8 / 9 / 10 / 10BP = 12,194 / 4,839 / 5,086 / 600).
- **As-of CSR** for a game type = the player's most recent NON-NULL
  `skill_snapshots` value for that type. (Multi-division capture means a player
  can have several snapshot dates from different divisions' grids; taking the
  latest non-null per game type avoids spurious gaps when the newest grid is an
  8-ball-only division.) Snapshots span 2026-06-04 … 2026-06-12 — staggered
  season-ends, not a single date (§5).

---

## 1. Racks per player, split by game type — the shrinkage tail

Per-player rack counts collapse once you split by game type. **This is the
dominant signal for the estimator: most players are data-starved in 9-, 10-, and
10BP-ball and must be shrunk toward their CSR.** Resolved players only (8-digit
id); subs (NULL id) are excluded from the per-player tables but their racks count
in the totals above.

| Game | players | min | median | mean | p90 | max | **<20 racks** | **<30 racks** |
|------|--------:|----:|-------:|-----:|----:|----:|--------------:|--------------:|
| 8-ball  | 518 | 2 | 28 | 45.4 | 108 | 218 | 211 (41%) | 263 (51%) |
| 9-ball  | 432 | 2 | **15** | 21.7 | 48 | 112 | **256 (59%)** | **334 (77%)** |
| 10-ball | 443 | 2 | 17 | 22.2 | 48 | 102 | 247 (56%) | 328 (74%) |
| 10BP    |  70 | 3 | **12** | 16.9 | 37 |  82 | 53 (76%) | **59 (84%)** |

Pooling across all game types (620 players, median **38** contested racks, mean
70.8, p90 181, max 391; 195 players < 20 racks, 264 < 30) is **worse**, not
better, than 13077 alone was (which had median 103) — because the league-wide
pool is dominated by thin-participation players: **68% of players appear in only
ONE division** and only **32% (196 players) span more than one**, so
cross-division pooling rescues a minority. Most players' evidence is one
division's staggered (18/21/27-week) — and sometimes partial — season. In 9-ball
**77% of players have < 30 racks** and the median player has just 15; 10-ball is
74% under 30; 10BP is 84% under 30 on a 70-player base. Independent races per
player are thinner still (pooled median **7**; per type 8/9/10/10BP medians
5/3/3/2), so racks within a race are correlated and the effective sample is
smaller than the raw rack count.

Subs (NULL id, not on a roster) contributed racks too — 8 / 9 / 10 / 10BP =
846 / 303 / 320 / 14 racks across 130 / 56 / 54 / 2 games — but they carry no CSR
and are excluded from the per-player tables (see §2).

**Implication:** a raw per-player, per-game empirical win-rate is unusable for
the majority of players in every game type but 8-ball. The estimator needs
partial pooling / shrinkage toward a CSR-derived prior (and CSR is the natural
prior — see §3). Pooling across divisions does NOT remove the need; it deepens it.

---

## 2. CSR-at-match coverage — is the skill-difference signal available?

A game is "covered" when **both** players have a usable as-of CSR for that game
type. The **242 uncovered games (6.6%) are EXACTLY the 242 games with a sub on
one side** (8 / 9 / 10 / 10BP sub games = 130 / 56 / 54 / 2) — coverage never
fails for a missing rating, only for an unrostered player who has none. Every
resolved player who played a game type carries that type's CSR.

| Game | covered / total | coverage |
|------|----------------:|---------:|
| 8-ball  | 1,773 / 1,903 | 93.2% |
| 9-ball  |   756 / 812 | 93.1% |
| 10-ball |   810 / 864 | 93.8% |
| 10BP    |    86 / 88 | 97.7% |
| **All** | **3,425 / 3,667** | **93.4%** |

Coverage is markedly higher than the 13077-only 85.5% — across the league subs
are a smaller fraction of games. The skill-difference signal is reliably
available, and where it's missing it's missing because the player is unrostered
(no CSR exists), not because of data gaps. Modeling can train on the 3,425
two-CSR games and treat sub games as held-out / id-less.

---

## 3. The key relationship — per-rack win-rate vs CSR difference

Games binned by (stronger CSR − weaker CSR), using each game's own type's CSR;
the **stronger** player's pooled **per-rack** win-rate (the modeling target) and
**per-match/race** win-rate (the handicapped outcome) per bin, with counts.

### Pooled (all game types) — cleanest shape

| CSR diff | games | racks | rack WR (strong) | match WR (strong) |
|----------|------:|------:|-----------------:|------------------:|
| 0–2   | 246 | 1,432 | 49.0% | 45.9% |
| 3–5   | 304 | 1,768 | 52.4% | 51.3% |
| 6–10  | 492 | 2,755 | 55.7% | 51.8% |
| 11–15 | 413 | 2,332 | 59.3% | 55.9% |
| 16–20 | 384 | 2,318 | 61.9% | 56.5% |
| 21–30 | 648 | 3,971 | 64.3% | 53.1% |
| 31–45 | 511 | 3,329 | 71.0% | 58.1% |
| 46+   | 427 | 3,331 | **83.8%** | 68.6% |

**Two findings, both central to the model design:**

1. **The per-rack curve is monotonic and steep.** At CSR parity the stronger
   side wins ~49% of racks (coin flip — CSR difference ≈ 0 → no edge, which
   validates CSR as *the* signal). The per-rack win-rate then climbs smoothly to
   ~84% at the largest gaps. This is a clean, well-behaved skill→probability
   curve — the right shape for a latent-skill / logistic-in-CSR-difference link.

2. **The handicap holds *matches* near 50–56% across the whole mid-range and
   leaks only at the tail.** Match (race) win-rate stays compressed at 51–58%
   from the 3–5 bin through 31–45 even as the per-rack edge climbs from 52% to
   71% — the race length absorbs it. Only at the extreme (46+ CSR) does the race
   matrix **under-compensate**: the stronger player still takes 68.6% of matches.
   (The 13077-only data showed a mid-range *inversion* at 21–30 — stronger losing
   matches more often — that was small-sample noise; with 12 divisions the
   mid-range is flat-near-even.) So the handicap balances typical mismatches but
   leaks edge at the tail — precisely the region where "your P minus the
   matrix-implied P" (the Phase 6 edge metric) is largest.

### Per game type (same binning; small bins are noisy)

**8-ball**

| diff | games | racks | rack WR | match WR |
|------|------:|------:|--------:|---------:|
| 0–2   | 108 |   642 | 50.5% | 50.0% |
| 3–5   | 139 |   846 | 52.0% | 50.4% |
| 6–10  | 215 | 1,239 | 54.2% | 48.8% |
| 11–18 | 307 | 1,811 | 60.3% | 58.6% |
| 19–30 | 422 | 2,574 | 64.1% | 54.0% |
| 31+   | 582 | 4,236 | 78.4% | 63.7% |

**9-ball**

| diff | games | racks | rack WR | match WR |
|------|------:|------:|--------:|---------:|
| 0–2   |  58 |   349 | 48.4% | 43.1% |
| 3–5   |  75 |   416 | 52.2% | 49.3% |
| 6–10  | 129 |   741 | 56.1% | 55.8% |
| 11–18 | 144 |   809 | 57.5% | 49.3% |
| 19–30 | 178 | 1,098 | 64.3% | 52.8% |
| 31+   | 172 | 1,123 | 75.7% | 59.9% |

**10-ball**

| diff | games | racks | rack WR | match WR |
|------|------:|------:|--------:|---------:|
| 0–2   |  74 |   399 | 47.4% | 43.2% |
| 3–5   |  86 |   478 | 53.6% | 55.8% |
| 6–10  | 136 |   701 | 57.8% | 52.9% |
| 11–18 | 172 |   955 | 60.7% | 56.4% |
| 19–30 | 185 | 1,139 | 64.3% | 54.6% |
| 31+   | 157 | 1,094 | 75.1% | 59.9% |

**10BP** (one division's worth — thin, read with care)

| diff | games | racks | rack WR | match WR |
|------|------:|------:|--------:|---------:|
| 0–2   |  6 |  42 | 45.2% | 33.3% |
| 3–5   |  4 |  28 | 46.4% | 25.0% |
| 6–10  | 12 |  74 | 58.1% | 50.0% |
| 11–18 | 17 | 108 | 60.2% | 58.8% |
| 19–30 | 20 | 127 | 63.8% | 55.0% |
| 31+   | 27 | 207 | 78.7% | 81.5% |

All four per-type curves carry the same upward rack-WR trend, but the individual
bins (especially 10BP, and 9-ball at small gaps) are too thin to read on their
own — reinforcing §1: per-type effects must borrow strength (pooled
CSR-difference link with per-game offsets), not be estimated bin-by-bin.

### 3a. Is the 9-ball curve flatter? (called-9 slop hypothesis)

**Hypothesis being tested.** This league requires the 9 to be *called*, but slop
keeps the rack alive (you don't lose for a slopped ball, the game continues). The
conjecture is that this lets weaker players hang around and steal racks, which
would **compress the skill→win-rate relationship in 9-ball specifically** —
i.e. a flatter per-rack curve than the other game types.

Two descriptive flatness measures per game type (plain summary statistics of the
observed racks — *not* a fitted forecasting model):

**(a) Rise from small to large CSR gap** (pooled rack-WR, stronger player):

| Game | small gap ≤10 (racks) | large gap ≥20 (racks) | **rise** |
|------|----------------------:|----------------------:|---------:|
| 8-ball  | 52.6% (2,727) | 73.3% (6,574) | **+20.7 pp** |
| 9-ball  | 53.3% (1,506) | 70.1% (2,175) | **+16.8 pp** |
| 10-ball | 53.9% (1,578) | 69.8% (2,109) | **+15.9 pp** |
| 10BP    | 52.1% (144)   | 74.4% (324)   | **+22.3 pp** |

**(b) Slope of a rack-weighted linear-probability fit** (pp of rack-WR per +10
CSR points), with a **game-clustered bootstrap 95% CI** (3,000 reps, resampling
whole races so correlated racks-within-a-race don't inflate precision):

| Game | slope (pp / +10 CSR) | 95% CI | races | racks |
|------|---------------------:|:------:|------:|------:|
| 8-ball  | +4.99 | [4.66, 5.32] | 1,773 | 11,348 |
| 9-ball  | +5.26 | [4.51, 6.06] |   756 |  4,536 |
| 10-ball | +5.15 | [4.40, 5.88] |   810 |  4,766 |
| 10BP    | +7.04 | [5.29, 9.06] |    86 |    586 |

Pairwise (independent bootstrap): P(slope₈ > slope₉) = **0.26**, P(slope₉ >
slope₁₀) = **0.59** (a coin flip), P(slope₈ > slope₁₀) = 0.35. 10BP looks steepest
(P(·>10BP) ≈ 0.01–0.03) but rests on 86 races with a huge CI [5.29, 9.06].

**Verdict: no — 9-ball is NOT flatter; if anything it is the steepest of the
three core games.** Its slope point estimate (5.26) is the highest of 8/9/10 and
its rise-measure ranking flipped from the 13077-only data — yet the difference is
not significant: P(slope₉ > slope₁₀) = 0.59 is a coin flip and P(slope₈ > slope₉)
= 0.26 only weakly favors 9-ball. **The 8/9/10 CIs overlap heavily (all within
~4.4–6.1); the per-rack slopes are statistically indistinguishable (~5.0–5.3 pp
/ +10 CSR).** The one clear signal is that 8-ball is the *flattest* point
estimate — the opposite of the hypothesis singling out 9-ball. The called-9 slop
mechanism remains plausible but **unconfirmed and contradicted in direction**;
the data cannot detect it.

**Design consequence (unchanged, reinforced).** Don't hard-code a flatter 9-ball
curve. Fit the skill→prob curve **per game type but partially pooled toward a
shared slope**, so the thin 9/10/10BP curves borrow strength from 8-ball rather
than chasing noise. Keep each curve free to diverge as data accrues, and revisit
this test next season. (See PHASE6_DESIGN.md §"Per-game curves".)

---

## 4. Pairing depth — `games` is not H2H training data

Distinct head-to-head pairings observed in `games`, by meeting count (unordered
player pairs, pooled across divisions):

| meetings | pairs | share |
|----------|------:|------:|
| 1 | 2,657 | 85% |
| 2 |   403 | 13% |
| 3 |    47 | 2%  |
| 4 |    12 | 0%  |
| 5 |     3 | 0%  |

- **3,122 distinct pairings** (by name), **median 1**, mean 1.17, max 5 meetings.
- Id-resolved pairs only (both sides rostered): 2,907 pairs, same median 1.

**85% of pairings were played exactly once.** A single-meeting empirical H2H
record is statistically meaningless, and pooling across the league did not create
depth (the max is 5 meetings, the mean barely above 1). The model cannot key on
observed pairwise matchups; it must pool through latent player skill, with the
pairing graph used only as a prior — confirming the architecture DATA.md
anticipated.

---

## 5. Data caveats that affect modeling

- **Pending matches: 80 across the league as of 2026-06-12, but this is mostly
  capture lag, not unplayed games.** Surfaced by `db.pending_matches(as_of)`
  (bye-filtered, division-scoped). It conflates three things:
  - **13722 (50)** — its ENTIRE slate shows pending because its score sheets are
    not yet loaded (host bot-challenge escalation during rollout). These are
    captured-but-owed, self-healing via the day-after-play cron + catch-up queue;
    NOT unplayed.
  - **14022 (2)** — R1 results not yet posted on the site (season started
    2026-06-10).
  - **~28 genuine off-schedule makeups** across 13077 (4), 13723 (7), 13744 (5),
    13743 (5), 13937 (3), 13711 (2), plus the shared 13298/13299 Dec-R1 phantom.

  These are not missing data to impute — they are unplayed or not-yet-captured.
  Any train/test split or as-of evaluation must treat them as absent; a re-pull
  by actual play-date adds their score sheets later (and drops 13722/14022 in).
- **`pairing_history` is NOT loaded in this DB** (profiles pass excluded — the 6
  newly-onboarded divisions' harvests are deferred). The lifetime aggregate
  W-L / RIVALS layer (a prior on pairings, never rack-level, never in `games`)
  must be recomputed once the harvests land before it can feed the skill prior.
- **Snapshots span six dates (2026-06-04 … 06-12), not one** — staggered
  season-ends across divisions. As-of CSR is effectively each division's
  end-of-season rating, not a true time-of-match value. The mid-season drift the
  schema captures is not yet dense enough to give each game its contemporaneous
  CSR; treat the skill term as static-per-season for now.
- **CSR scale (latest snapshot, per game type):** 8-ball 0–138 (n=704), 9-ball
  6–130 (n=707), 10-ball 10–120 (n=707), 10BP 17–113 (n=169). Three players carry
  no `csr_8` (9/10-only "DP LC" divisions); 10BP exists only for the 4-game
  divisions' 169 players — wide enough that the §3 difference bins are well
  populated across the range.

---

## Readiness summary (what this implies for the estimator)

1. **Shrinkage is mandatory, per game type — more so than 13077 alone showed.**
   Raw per-player rack rates are unusable for most players outside 8-ball
   (medians 15/17/12 racks in 9/10/10BP; 77%/74%/84% under 30). Cross-division
   pooling helps only the 32% of players in >1 division; partial pooling toward a
   CSR-based prior is required, not optional.
2. **CSR difference is a strong, available, monotonic predictor** — ~49% at
   parity rising to ~84% per-rack at the extremes, available for 93.4% of games
   (the other 6.6% are exactly the id-less sub games).
3. **A latent-skill / logistic-in-CSR-difference rack model with per-game-type
   structure** fits the evidence: clean curve shape across all four game types,
   thin per-pair data (median 1 meeting) ruling out empirical H2H, slopes too
   close to separate (partial pooling), and a (pending) pairing-history prior.
4. **The handicap balances the whole mid-range and leaks only at the tail** — the
   edge metric ("your P minus matrix-implied P") will be largest in the 46+
   CSR-gap region, where the race matrix under-compensates (68.6% match WR).
5. **Honour the caveats:** exclude the 80 pending matches (mostly 13722/14022
   capture lag), load `pairing_history` only after the deferred harvests, and
   treat CSR as static-per-season until drift snapshots densify.
