# PHASE6_READINESS.md — empirical groundwork for the forecasting model

> **RECOMPUTED 2026-06-14 against the full multi-division archive, WITH the
> profile pass; §5 H2H + headline counts refreshed 2026-06-15 after the full
> per-rival DRILL; headline counts, §3a slopes, and §5 CSR `n=` trued up
> 2026-06-16 to the 06-15 DB** (the lifetime per-game W-L layer is now complete
> league-wide — see §5). The §1–§3 bin tables and §2/§4 stay from the 2026-06-14
> build: the daily cron added snapshot dates through 06-15 (skill_snapshots
> 1,693 → 2,098), shifting a few as-of CSRs and nudging a few §3 bins by ≤3 games
> (games unchanged at 3,906) and the §3a slopes by ≤0.04 pp — within their CIs,
> no finding changes. Every number
> below pools across the league (13 of the 14
> divisions carry games) instead of division 13077 alone — this supersedes the
> original 13077-only analysis (which held 85 players / 657 games). A **fourth
> game type, 10BP**, enters here (the 4-game divisions 13986/14022, keyed to
> `skill_snapshots.csr_10bp`). One completeness caveat remains, self-healing (see
> §5): **14022's R1 results are not yet posted** (season started 2026-06-10), so
> it carries 0 games. The profile pass is now INCLUDED **and fully drilled** —
> `pairing_history` is loaded at **704/710 players** with **100% of edges carrying
> lifetime per-game W-L** (§5); the 2026-06-15 all-divisions per-rival drill (~40k
> pages) lifted W-L depth from the prior 16% / 85-player (13077-only) coverage to
> complete. The day-after-play cron does not harvest profiles — this was a manual
> densification campaign. The DESIGN decisions in
> PHASE6_DESIGN.md (base+adj,
> shrink-to-prior, per game type) are unaffected — and are reinforced (§1, §3a).

**Scope:** analysis only. No model was built, fit, or trained; no schema changed.
This is the input to the Phase 6 estimator-design decision.

**Source:** `data/napa.db`, rebuilt from the committed raw archive in the DATA.md
pass order (roster grids → schedules → score sheets → profiles), all 14 registry
divisions. Row counts: **710 players, 2,098 skill snapshots, 135 teams, 1,634
matches, 3,906 games** (8 / 9 / 10 / 10BP = 2,142 / 812 / 864 / 88), spanning
**13 divisions** with games. Regenerate deterministically (seeded bootstrap) with
`python tools/phase6_readiness.py`.

Metric definitions (stated so the numbers are unambiguous):
- A **game** row in `games` is one race (handicapped match) between two players
  of a single game type. `home_score`/`away_score` = racks each won.
- A **rack** is one Bernoulli win/loss observation. A player's **racks** in a
  game type = Σ(`home_score`+`away_score`) over the races they played of that
  type — i.e. every rack they contested, won or lost. Total racks contested =
  **24,199** (8 / 9 / 10 / 10BP = 13,674 / 4,839 / 5,086 / 600).
- **As-of CSR** for a game type = the player's most recent NON-NULL
  `skill_snapshots` value for that type. (Multi-division capture means a player
  can have several snapshot dates from different divisions' grids; taking the
  latest non-null per game type avoids spurious gaps when the newest grid is an
  8-ball-only division.) Snapshots span 2026-06-04 … 2026-06-13 — staggered
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
| 8-ball  | 573 | 2 | 31 | 46.0 | 111 | 218 | 221 (39%) | 281 (49%) |
| 9-ball  | 432 | 2 | **15** | 21.7 | 48 | 112 | **256 (59%)** | **334 (77%)** |
| 10-ball | 444 | 2 | 17 | 22.2 | 48 | 102 | 248 (56%) | 329 (74%) |
| 10BP    |  70 | 3 | **12** | 16.9 | 37 |  82 | 53 (76%) | **59 (84%)** |

Pooling across all game types (621 players, median **47** contested racks, mean
75.3, p90 182, max 391; 190 players < 20 racks, 241 < 30) is **worse**, not
better, than 13077 alone was (which had median 103) — because the league-wide
pool is dominated by thin-participation players: **67% of players appear in only
ONE division** and only **33% (215 players) span more than one**, so
cross-division pooling rescues a minority. Most players' evidence is one
division's staggered (18/21/27-week) — and sometimes partial — season. In 9-ball
**77% of players have < 30 racks** and the median player has just 15; 10-ball is
74% under 30; 10BP is 84% under 30 on a 70-player base. Independent races per
player are thinner still (pooled median **8**; per type 8/9/10/10BP medians
6/3/3/2), so racks within a race are correlated and the effective sample is
smaller than the raw rack count.

Subs (NULL id, not on a roster) contributed racks too — 8 / 9 / 10 / 10BP =
997 / 303 / 317 / 14 racks across 152 / 56 / 53 / 2 games — but they carry no CSR
and are excluded from the per-player tables (see §2).

**Implication:** a raw per-player, per-game empirical win-rate is unusable for
the majority of players in every game type but 8-ball. The estimator needs
partial pooling / shrinkage toward a CSR-derived prior (and CSR is the natural
prior — see §3). Pooling across divisions does NOT remove the need; it deepens it.

---

## 2. CSR-at-match coverage — is the skill-difference signal available?

A game is "covered" when **both** players have a usable as-of CSR for that game
type. The **263 uncovered games (6.7%) are EXACTLY the 263 games with a sub on
one side** (8 / 9 / 10 / 10BP sub games = 152 / 56 / 53 / 2) — coverage never
fails for a missing rating, only for an unrostered player who has none. Every
resolved player who played a game type carries that type's CSR.

| Game | covered / total | coverage |
|------|----------------:|---------:|
| 8-ball  | 1,990 / 2,142 | 92.9% |
| 9-ball  |   756 / 812 | 93.1% |
| 10-ball |   811 / 864 | 93.9% |
| 10BP    |    86 / 88 | 97.7% |
| **All** | **3,643 / 3,906** | **93.3%** |

Coverage is markedly higher than the 13077-only 85.5% — across the league subs
are a smaller fraction of games. The skill-difference signal is reliably
available, and where it's missing it's missing because the player is unrostered
(no CSR exists), not because of data gaps. Modeling can train on the 3,643
two-CSR games and treat sub games as held-out / id-less.

---

## 3. The key relationship — per-rack win-rate vs CSR difference

Games binned by (stronger CSR − weaker CSR), using each game's own type's CSR;
the **stronger** player's pooled **per-rack** win-rate (the modeling target) and
**per-match/race** win-rate (the handicapped outcome) per bin, with counts.

### Pooled (all game types) — cleanest shape

| CSR diff | games | racks | rack WR (strong) | match WR (strong) |
|----------|------:|------:|-----------------:|------------------:|
| 0–2   | 264 | 1,543 | 49.4% | 47.3% |
| 3–5   | 331 | 1,931 | 51.5% | 49.5% |
| 6–10  | 517 | 2,916 | 55.8% | 52.2% |
| 11–15 | 456 | 2,562 | 59.0% | 55.9% |
| 16–20 | 395 | 2,391 | 62.3% | 57.0% |
| 21–30 | 681 | 4,170 | 64.4% | 53.6% |
| 31–45 | 549 | 3,568 | 71.0% | 57.9% |
| 46+   | 450 | 3,487 | **83.8%** | 68.2% |

**Two findings, both central to the model design:**

1. **The per-rack curve is monotonic and steep.** At CSR parity the stronger
   side wins ~49% of racks (coin flip — CSR difference ≈ 0 → no edge, which
   validates CSR as *the* signal). The per-rack win-rate then climbs smoothly to
   ~84% at the largest gaps. This is a clean, well-behaved skill→probability
   curve — the right shape for a latent-skill / logistic-in-CSR-difference link.

2. **The handicap holds *matches* near 50–58% across the whole mid-range and
   leaks only at the tail.** Match (race) win-rate stays compressed at ~50–58%
   from the 3–5 bin through 31–45 even as the per-rack edge climbs from 52% to
   71% — the race length absorbs it. Only at the extreme (46+ CSR) does the race
   matrix **under-compensate**: the stronger player still takes 68.2% of matches.
   (The 13077-only data showed a mid-range *inversion* at 21–30 — stronger losing
   matches more often — that was small-sample noise; with 13 divisions the
   mid-range is flat-near-even.) So the handicap balances typical mismatches but
   leaks edge at the tail — precisely the region where "your P minus the
   matrix-implied P" (the Phase 6 edge metric) is largest.

### Per game type (same binning; small bins are noisy)

**8-ball**

| diff | games | racks | rack WR | match WR |
|------|------:|------:|--------:|---------:|
| 0–2   | 127 |   763 | 50.2% | 48.8% |
| 3–5   | 163 |   978 | 51.1% | 48.5% |
| 6–10  | 247 | 1,438 | 54.3% | 49.4% |
| 11–18 | 347 | 2,051 | 59.9% | 58.2% |
| 19–30 | 470 | 2,859 | 64.6% | 55.5% |
| 31+   | 636 | 4,588 | 78.3% | 63.2% |

**9-ball**

| diff | games | racks | rack WR | match WR |
|------|------:|------:|--------:|---------:|
| 0–2   |  57 |   340 | 52.4% | 54.4% |
| 3–5   |  76 |   425 | 51.1% | 47.4% |
| 6–10  | 128 |   739 | 55.8% | 54.7% |
| 11–18 | 146 |   816 | 57.8% | 50.0% |
| 19–30 | 172 | 1,060 | 64.2% | 52.9% |
| 31+   | 177 | 1,156 | 75.3% | 59.3% |

**10-ball**

| diff | games | racks | rack WR | match WR |
|------|------:|------:|--------:|---------:|
| 0–2   |  74 |   398 | 46.0% | 40.5% |
| 3–5   |  88 |   500 | 53.0% | 54.5% |
| 6–10  | 130 |   665 | 58.9% | 55.4% |
| 11–18 | 183 | 1,014 | 60.9% | 57.4% |
| 19–30 | 177 | 1,088 | 63.6% | 52.0% |
| 31+   | 159 | 1,104 | 75.2% | 60.4% |

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
| 8-ball  | 52.2% (3,179) | 73.4% (7,219) | **+21.1 pp** |
| 9-ball  | 53.7% (1,502) | 70.1% (2,175) | **+16.4 pp** |
| 10-ball | 53.9% (1,572) | 69.8% (2,103) | **+15.8 pp** |
| 10BP    | 52.1% (144)   | 74.4% (324)   | **+22.3 pp** |

**(b) Slope of a rack-weighted linear-probability fit** (pp of rack-WR per +10
CSR points), with a **game-clustered bootstrap 95% CI** (3,000 reps, resampling
whole races so correlated racks-within-a-race don't inflate precision):

| Game | slope (pp / +10 CSR) | 95% CI | races | racks |
|------|---------------------:|:------:|------:|------:|
| 8-ball  | +5.10 | [4.77, 5.42] | 1,990 | 12,677 |
| 9-ball  | +5.11 | [4.37, 5.88] |   756 |  4,536 |
| 10-ball | +5.18 | [4.46, 5.92] |   811 |  4,769 |
| 10BP    | +7.04 | [5.27, 9.10] |    86 |    586 |

Pairwise (independent bootstrap): P(slope₈ > slope₉) = **0.49**, P(slope₉ >
slope₁₀) = **0.45** (both coin flips), P(slope₈ > slope₁₀) = 0.42. 10BP looks steepest
(P(·>10BP) ≈ 0.02–0.03) but rests on 86 races with a huge CI [5.27, 9.10].

**Verdict: no — 9-ball is NOT flatter.** Its slope point estimate (5.11) sits in
the *middle* of the three core games (8-ball 5.10, 10-ball 5.18), not at the
bottom — and the differences are not significant: P(slope₈ > slope₉) = 0.49 and
P(slope₉ > slope₁₀) = 0.45 are both coin flips. **The 8/9/10 CIs overlap heavily
(all within ~4.4–6.0); the per-rack slopes are statistically indistinguishable
(~5.1–5.2 pp / +10 CSR).** If anything the *flattest* point estimate is 8-ball
(5.10) — the opposite of the hypothesis singling out 9-ball. The called-9 slop
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
| 1 | 2,775 | 84% |
| 2 |   460 | 14% |
| 3 |    48 | 1%  |
| 4 |    13 | 0%  |
| 5 |     3 | 0%  |

- **3,299 distinct pairings** (by name), **median 1**, mean 1.18, max 5 meetings.
- Id-resolved pairs only (both sides rostered): 3,067 pairs, same median 1.

**84% of pairings were played exactly once.** A single-meeting empirical H2H
record is statistically meaningless, and pooling across the league did not create
depth (the max is 5 meetings, the mean barely above 1). The model cannot key on
observed pairwise matchups; it must pool through latent player skill, with the
pairing graph used only as a prior — confirming the architecture DATA.md
anticipated.

---

## 5. Data caveats that affect modeling

- **Pending matches: 32 across the league as of 2026-06-15 — now almost all
  genuine makeups, not capture lag.** Surfaced by `db.pending_matches(as_of)`
  (bye-filtered, division-scoped). 13722's full slate is **no longer pending** —
  its score sheets loaded in the 2026-06-14 backfill (it now contributes games),
  leaving just 2 genuine makeups. The rest splits two ways:
  - **14022 (2)** — R1 results not yet posted on the site (season started
    2026-06-10); the only true capture lag left.
  - **~30 genuine off-schedule makeups** across 13723 (7), 13744 (5), 13743 (5),
    13077 (4), 13937 (3), 13711 (2), 13722 (2), plus the shared 13298/13299
    Dec-R1 phantom (1 each).

  These are not missing data to impute — they are unplayed or not-yet-captured.
  Any train/test split or as-of evaluation must treat them as absent; a re-pull
  by actual play-date adds their score sheets later (and drops 14022 in).
- **`pairing_history` IS loaded AND fully drilled — the lifetime H2H layer is now complete.**
  The profile pass + the all-divisions per-rival drill landed for all 14 divisions:
  **48,076 directed RIVALS edges** over **704 of 710 players** (the 6 without a
  RIVALS row are new players with no lifetime H2H), collapsing to **36,022 distinct
  unordered pairings** (33% reciprocal). This is a lifetime aggregate W-L / RIVALS
  layer — a prior on pairings, never rack-level, never in `games`. Its value as a
  prior is the overlap: it **covers 3,066 of this rebuild's 3,067 id-resolved game
  pairs (100%)** — essentially every matchup the model will see carries a lifetime
  prior — with a further **32,956 pairings** seen historically but not this season.
  **Direction depth is now complete: 100% of edges (48,076) carry W-L totals AND
  per-game 8/9/10 splits**, up from the prior 16% / 85-player (13077-only) coverage
  — the 2026-06-15 all-divisions per-rival drill (~40k pages, 0 challenge aborts)
  realized the full layer. No densification lever remains.
- **Snapshots span eight dates (2026-06-04 … 06-15), not one** — staggered
  season-ends across divisions. As-of CSR is effectively each division's
  end-of-season rating, not a true time-of-match value. The mid-season drift the
  schema captures is not yet dense enough to give each game its contemporaneous
  CSR; treat the skill term as static-per-season for now.
- **CSR scale (latest snapshot, per game type):** 8-ball 0–138 (n=707), 9-ball
  6–130 (n=710), 10-ball 10–120 (n=710), 10BP 17–113 (n=169). Three players carry
  no `csr_8` (9/10-only "DP LC" divisions); 10BP exists only for the 4-game
  divisions' 169 players — wide enough that the §3 difference bins are well
  populated across the range.

---

## Readiness summary (what this implies for the estimator)

1. **Shrinkage is mandatory, per game type — more so than 13077 alone showed.**
   Raw per-player rack rates are unusable for most players outside 8-ball
   (medians 15/17/12 racks in 9/10/10BP; 77%/74%/84% under 30). Cross-division
   pooling helps only the 33% of players in >1 division; partial pooling toward a
   CSR-based prior is required, not optional.
2. **CSR difference is a strong, available, monotonic predictor** — ~49% at
   parity rising to ~84% per-rack at the extremes, available for 93.3% of games
   (the other 6.7% are exactly the id-less sub games).
3. **A latent-skill / logistic-in-CSR-difference rack model with per-game-type
   structure** fits the evidence: clean curve shape across all four game types,
   thin per-pair data (median 1 meeting) ruling out empirical H2H, slopes too
   close to separate (partial pooling), and a now-complete pairing-history prior
   (100% of game pairs covered, 704/710 players, fully drilled to lifetime per-game W-L).
4. **The handicap balances the whole mid-range and leaks only at the tail** — the
   edge metric ("your P minus matrix-implied P") will be largest in the 46+
   CSR-gap region, where the race matrix under-compensates (68.2% match WR).
5. **Honour the caveats:** exclude the 32 pending matches (now mostly genuine
   makeups; only 14022's R1 is capture lag), use `pairing_history` as a prior now
   (loaded at 704/710-player coverage, fully drilled to lifetime per-game W-L), and
   treat CSR as static-per-season until drift snapshots densify.
