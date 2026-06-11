# B1 recon verdict — format classes across NoCo divisions

Captured 2026-06-10 (local headless Chromium, residential IP; all challenges cleared).
Probes: 13985 (normal LC), 13298 (8-ball-only), 13744 (DP "LC"). Five pages each:
roster_grid, division, schedule (weekNumber=30), weekly_scores week=1, one linked
score sheet. Existing parsers were run against every capture.

## Roster grid: THREE header shapes, one parser — B6 is mandatory

The grid header column declares the division's game set; the current parser
hardcodes the 13077 shape and must become header-driven.

| class | header | example | current parser behavior |
|---|---|---|---|
| 3-game LC (13077, 13985) | `CSR8 - 9 - 10` | `95 - 79 - 81`, SM | OK — parses correctly (13985: 76 players / 10 teams) |
| 8-ball-only (13298) | `CSR` | `90`, SM | **fails loudly** — 0 players (`_CSR_TRIPLE_RE` no match) |
| 2-game DP (13744) | `CSR9 - 10` | `77 - 58`, SM | **SILENT MISPARSE** — maps 9-ball CSR→csr_8, 10-ball→csr_9, and EATS the SM column as csr_10 |

13744 is NOT a 3-game division: it plays 9/10-ball only (its sampled score sheet
was 5×10-ball). The silent misparse is the dangerous case — B6 must parse the
header, map dash-separated values to the declared game types (absent games →
None), and RAISE on a value-count/header mismatch. No non-triple division may be
loaded before that lands.

Knock-on for B4 (schema): `skill_snapshots.csr_8/9/10` must be NULLABLE, and the
same-day upsert must MERGE per-game values (a player seen via 13298's grid brings
only csr_8; last-write-wins would null out the other two captured the same day by
13077's grid). Verify-and-warn applies per game type on conflicting NON-NULL values.

## Score sheets: identical markup everywhere — no parser change

All three classes parse with `parse_score_sheet` unchanged (13985: 8/9/10 mix;
13298: all type 8; 13744: all type 10). Sheet host is playpool.io/scores.php with
`did` embedded in the index links, as expected.

## Schedule + season structure: staggered, never 27

`print_schedule_v1.php?...&weekNumber=30&weekDay=<registry day>` returns the FULL
season regardless of elapsed weeks; `parse_schedule` handles all of it unchanged.

| did | rounds | R1 date | last date | division page "Session Weeks" |
|---|---|---|---|---|
| 13985 | 18 | 2026-06-02 | 2026-09-29 | 18 |
| 13298 | 27 | 2025-12-16 | 2026-06-30 | 27 |
| 13744 | 21 | 2026-04-03 | 2026-08-21 | 21 |

Seasons are per-division (13985's NEW season started 2026-06-08 week; 13298 ends
this month). `SEASON = "2025-26"` cannot be shared. Recommendation for B4: derive
each division's season key from its schedule's R1 date (self-describing, unique,
no registry hardcode); 13077 keeps its existing label for continuity.

Backfill note: 13298 (R1 2025-12-16, 27 rounds) and 13744 (R1 2026-04-03) are
mid-season — "auto" week discovery is required, and their archives will keep
growing weekly after backfill. 13985 has only ~1 played week so far: its
"backfill" is nearly free, and almost the whole season will accrue via the
daily scrape.

## Misc

- `lcF8=N` worked for all three grid classes — no flag change needed.
- `weekDay` must match the division's day (registry value) or the print page is
  wrong — confirmed working for Tuesday/Friday.
- Registry `fmt` for 13744 (and presumably 13723) is really "9/10", not LC-3-game;
  treat `fmt` as display-only — the AUTHORITATIVE game set comes from the grid
  header at parse time. Verify 13723's header at its onboarding gate.

## Fixtures to promote (B6)

- `roster_grid_13985.html` (3-game regression), `roster_grid_8ball_13298.html`
  (single CSR), `roster_grid_2game_13744.html` (CSR9-10 + the SM-swallow trap),
  `score_sheet_10ball_13744.html`, `weekly_index_13985.html`.

**Gate result: PASS with required work scoped.** Score sheets/schedules/indexes
need zero parser changes; roster parsing needs the header-driven B6 fix before
any non-triple division loads; B4 schema needs nullable+merge skill snapshots
and per-division season keys.
