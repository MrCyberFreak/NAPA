# NAPA: one master players list, fed by all 14 NAPA of Northern Colorado divisions

## Goal

**We track PLAYERS and their match data.** The master players list is the league-wide
`players` table keyed by the 8-digit playerID; divisions and teams are routing — a player
funnels into whatever division/team they happen to play in, and everything we know about
them (skill drift, form, lifetime pairings, per-rack results) accrues to the one player row.
The pipeline (repo `MrCyberFreak/NAPA`; local clone to be made at `X:\Claude_Code\Projectes\NAPA`)
currently captures one division — 13077. Expanding to all 14 divisions of **NAPA of Northern
Colorado** (not El Paso "Rockies 2.0", not Mesa) completes the master list for this league and
pools per-player racks across divisions, which is what Phase 6 forecasting needs to fight
9/10-ball sparsity (76% of players have <30 racks in 9-ball within 13077 alone). Some players
play in multiple divisions simultaneously — premise already confirmed in the archive: player
10027703's profile carries `division.php?did=` anchors for both 13077 and 13985.

Division list confirmed from `https://www.napaleagues.com/states.php?location=Colorado`.
User decisions (locked):
- **Full-season score-sheet backfill** for all 13 new divisions.
- **Profile harvest for all new players, TABS-ONLY** (no per-rival drill — drill ≈ 5,200 page
  loads / 3h45m per division and Phase 6 doesn't use the per-game H2H splits; tabs-only
  ≈ 15 min/division, observed 8m49s for 85 players). Rival drill stays available later for
  selectively chosen players.
- Scout grid / standings stay **13077-centric by default**.
- **One division at a time**: after the shared foundation lands, each division is fully
  onboarded (scrape → backfill → harvest → rebuild → gates → report) and then work **STOPS
  for explicit approval** before the next division starts. No batch activation, ever.

## Data model — three layers, players first

- **Identity (league-wide; these tables NEVER gain a division column):** `players`,
  `skill_snapshots`, `player_form`, `pairing_history`. `skill_snapshots` PK stays
  `(player_id, captured_date)` — CSR is a league-wide rating, so a player rostered in two
  divisions loaded the same day hits the same row; add a **verify-and-warn** when two
  divisions' grids disagree on a player's CSR for the same date (last-write-wins, warning
  in the load report). A real disagreement would mean the league computes CSR per division,
  which would force a schema rethink — the warn is the tripwire.
- **Affiliation (how a player funnels into divisions/teams):** rostered membership is
  `team_members` × `teams.division_id` (recurring, from every roster load). New
  `player_divisions(player_id, division_id, first_seen, last_seen)` is **profile-sourced
  only** — it adds membership signal the rosters can't see (divisions outside our scrape
  set; players we only ever meet as subs or rivals). Two provenances, deliberately not
  double-encoded.
- **Events (division-scoped as an attribute, player-keyed as ever):** `teams`/`matches`/
  `games` gain `division_id INTEGER NOT NULL` (+ a `divisions` table seeded from the
  registry). League-wide queries (`player_game_log`, `csr_history`, `pairing_coverage`)
  stay cross-division by design — that IS the Phase 6 pooling.

Key verified facts shaping the design:
- `src/config.py:11` `DID = 13077` is the only true hardcode; `config.url()` already accepts
  a `did` override, but the schedule URL bakes in `weekDay` ("Thursday") — the registry must
  carry per-division weekday. Never assume 27 weeks; discover per division.
- Archive is flat per date (`data/raw/<date>/...`, `data/raw/scores/week_NN/`) — a second
  division collides. Profiles (`data/raw/profiles/<player_id>/`) are player-keyed,
  division-independent — unchanged.
- Schema collisions: `teams UNIQUE(name,season)`, `games UNIQUE(played_date,home_name,away_name)`,
  `_find_match`/mirror-dedup query by date with no division scope. TWO league-wide name→id
  joins exist, not one: `_player_teams` takes `rows[0]` league-wide, and `_resolve_player_id`
  (used by `load_score_sheets`) matches bare name against all of `players`.
- Score-sheet links inside the archived `week_NN/_index.html` already embed `did` — only the
  index URL and output dir need parameterizing.
- The profile main page renders a `Divisions:` field with `division.php?did=N` anchors — not
  yet parsed; `fixtures/profile_main.html` ALREADY contains it, so no fixture refresh is needed.
- DB is regenerable from the raw archive — schema changes mean rebuild, no ALTER migration.
- Current per-game ratings come from each division's roster grid (one fetch/division), not
  per-player profile hits.

## Division registry (the 14)

| did | weekday | format | note |
|---|---|---|---|
| 13077 | Thu | LC | current; app default |
| 13985 | Tue | LC | Felt Laggers — **first new division onboarded** |
| 14022 | Wed | LC | Paradise |
| 13986 | Tue | LC | Zoosters Laggers |
| 13937 | Wed | LC | Pharaoh's |
| 13881 | Mon | LC | Broomfield-Westminster Laggers |
| 13711 | Sun | LC | Wreckroom |
| 13299 | Tue | LC | Piazzas |
| 13205 | Mon | LC | Greeley |
| 13744 | Fri | LC | **DP** — verify sheet format in recon |
| 13723 | Fri | LC | **DP** Piazza |
| 13743 | Fri | 8-ball | **DP + 8-ball-only** |
| 13722 | Fri | 8-ball | **DP + 8-ball-only** |
| 13298 | Tue | 8-ball | 8-ball-only |

Registry = `Division` frozen dataclass (did, name, weekday, fmt "LC"|"8",
`scrape: bool = False`) + `DIVISIONS` dict in `src/config.py`. Weekday strings must match
`print_schedule_v1.php`'s `weekDay` values exactly ("Monday"…"Sunday"). Only 13077 starts
`scrape=True` — the flag is the one-line per-division activation. `DID = 13077` stays the
default everywhere; add `active_dids()` and `division_root(did) -> data/raw/<did>`.

## Track A — player identity (the point of the expansion)

- **A1 — name→id resolution becomes division-preferring, with an explicit ambiguity rule.**
  Applies to BOTH joins (`_player_teams` AND `_resolve_player_id`): filter name candidates
  to the division's roster (`team_members` × `teams.division_id`, season); if 0 hits, accept
  a UNIQUE league-wide match (this is how a 13077 "sub" who is rostered in another NoCo
  division finally gets their id); if >1 candidates remain, resolve to NULL and COUNT it in
  the load report — never an arbitrary `rows[0]`. Subs stay NULL-id, never dropped.
- **A2 — parse the profile `Divisions:` field.** `src/parse/profile.py` extracts
  `division.php?did=(\d+)` anchors → `Profile.divisions`; `load_profile()` upserts
  `player_divisions` (MIN/MAX first/last_seen). Test against the existing
  `fixtures/profile_main.html` (it already carries the field).
  **Gate:** rebuild populates `player_divisions` from the 85 archived profiles;
  `HAVING COUNT(*) > 1` empirically enumerates the multi-division players before any
  new-division work lands.
- **A3 — `python -m src.db --rebuild`, pass-ordered so the master list exists first:**
  pass 1 ALL active divisions' roster grids (every archived date — master list + snapshot
  history + affiliations), pass 2 all schedules, pass 3 all score sheets, pass 4 profiles.
  Loading any division's sheets before all rosters would miss cross-division id resolutions.
  `--did N` / `--all-divisions` flags; loaders/queries gain `division_id: int = config.DID`
  so every existing call site and test is unchanged.
- **A4 — profile harvests, tabs-only, one division at a time (locked).** One
  `harvest-profiles.yml` dispatch per division with `did` set, `drill=0`
  (≈ 15 min/division). `harvest_profiles(..., did)` reads roster ids per division;
  per-file resume dedup skips shared players for free. Loses only per-game W/L splits in
  `pairing_history` for new players — Phase 6 pools through latent skill and doesn't use them.

**Player gates (checked at every rollout stop):**
- *Master-list completeness:* every rostered player in every active division has a `players`
  row + ≥1 `skill_snapshot`; `players` count ≈ union of active rosters + subs (superset rule
  intact).
- *Cross-division sub recovery:* the count of NULL-id player slots in 13077's games strictly
  DECREASES vs the pre-expansion baseline as more rosters land; report the NULL rate per
  division.
- *CSR coherence:* the cross-division CSR-disagreement warn stays silent (fires only on real
  disagreement).

## Track B — division plumbing (in service of Track A)

- **B1 — format recon (no `src/` changes).** Capture for 13985 (normal LC), 13298
  (8-ball-only), 13744 (DP): roster_grid, division page, schedule,
  `standings_weekly_scores.php?week=1`, one linked score sheet. Commit under
  `data/raw/_recon/<did>/`. Tooling: add an `out` input to `capture-races.yml` (default
  `data/raw/race_assets`; commit path widens to `data/raw`) — or run `--capture-url` locally
  with a headed browser.
  **Verify:** roster CSR shape for 8-ball-only grids (triple vs single — `_CSR_TRIPLE_RE`
  requires a triple today), the `lcF8` flag, DP score-sheet markup vs the label-driven
  parser, per-division season label + elapsed weeks, and `weekNumber` semantics for ≠27-week
  divisions. All NoCo divisions are assumed to share `SEASON = "2025-26"`; if recon shows
  otherwise, the registry gains an optional season override (flag only — don't build until
  seen). Promote the best captures into `fixtures/`.
  **Gate:** written per-division-class verdict (same markup or not) before schema lock.
- **B2 — config registry** (see table above): `url()` takes weekday from the registry when
  `did` is passed; new unit tests build every registry URL; full pytest green.
- **B3 — archive migration (one atomic `[skip ci]` PR).** `git mv` ALL dated dirs
  (`data/raw/20*`) → `data/raw/13077/<date>/`, `data/raw/scores` → `data/raw/13077/scores/`.
  No legacy-path grandfathering. Unchanged: `profiles/`, `profile_explore/`, `race_assets/`,
  `_heartbeat.json`. The SAME commit updates every path-coupled spot:
  `fetch.archive_pages(did)` (replaces static `ARCHIVE_PAGES` use),
  `db._discover_roster_source(did)`, `browser_fetch._roster_player_ids(did)`,
  `backfill_score_sheets(..., did)` default out_root.
  **Cron-race discipline:** the daily scrape keeps writing old-layout dirs while this PR is
  open — disable scrape.yml's schedule before branching, rebase-merge promptly, re-enable
  after. **Gate:** pytest green; `python -m src.db --load` discovers the migrated newest grid
  (85 players / 10 teams); `git log --follow` shows archive history preserved. (The full-DB
  counts gate waits for `--rebuild` in A3/B4 — no rebuild CLI exists yet.)
- **B4 — division-scoped events schema + loaders (`src/db.py`).** DDL: `divisions` table
  (seeded from registry); `division_id NOT NULL` on `teams`/`matches`/`games`; `teams`
  UNIQUE → `(division_id, name, season)`; `idx_game_unique` →
  `(division_id, played_date, home_name, away_name)`. The ON CONFLICT targets must track the
  new indexes exactly: the upserts in `load_games` and `load_score_sheets` name the new
  column set; the mirror-dedup SELECT gains `AND division_id = ?`; `_get_or_create_team`'s
  conflict target becomes `(division_id, name, season)`. `_find_match` and `_resolve_team_id`
  gain division scope (two Friday divisions share dates). Division-scoped query surface:
  `load_roster`, `load_schedule`, `load_team_record`, `pending_matches`, `standings`,
  `matches_for_round`, `team_depth`, `team_roster_latest` — all defaulting to `config.DID`.
  Scout call sites (`build_grid` → `team_roster_latest`/`team_depth` in `src/app/scout.py`)
  inherit the 13077 default, so the grid is unchanged by default but immune to
  cross-division team-name collisions.
  **Gate:** new collision tests (same team name in 2 divisions; same pairing same date in
  2 divisions; CSR-disagreement warn; division-preferring + ambiguity-NULL name resolution);
  13077 `--rebuild` matches DATA.md as an **explainable delta** — players=85, teams=10,
  matches=135 exact; games=657 plus any post-2026-06-05 makeup sheets; skill_snapshots ≥170
  (one row per player per changed-grid date — the archive already has roster captures newer
  than DATA.md's as-of). Any UNexplained delta fails the gate.
- **B5 — multi-division fetch + workflows.** `browser_fetch.main()` gains `--did N` /
  `--all-divisions`: loop `active_dids()` reusing ONE browser context (challenge cookies
  persist per host → divisions after the first skip the 6s clears; daily run ≈ 10–20 min,
  not 14× full cost). Each division writes under its own root (`fetch_pages_browser` already
  takes `root` — pass `division_root(did)`) so write-on-change compares within a division,
  never across. Fail-soft: a nav error skips to the next division; an uncleared bot-challenge
  aborts the whole run. Heartbeat: accumulate `{"divisions": {did: {captured, unchanged}}}`
  across the loop, write ONCE to `data/raw/_heartbeat.json` after all divisions (the writer
  overwrites the file). `backfill_score_sheets(weeks|"auto", did)`: "auto" walks weeks and
  stops after 2 consecutive EMPTY indexes — where empty means a cleared page with zero
  score-sheet links; a failed nav or uncleared challenge ("" content) ABORTS fail-soft and
  never counts toward the stop, so a mid-run challenge can't silently truncate a backfill.
  Workflows: `scrape.yml` league-night cron `0 4 * * 5` → `0 4 * * *` (every weekday now has
  a league night; the separate `0 14 * * *` daily pass already exists and stays), browser
  step + db load → `--all-divisions` (keep `continue-on-error`), add `timeout-minutes: 60`,
  keep `[skip ci]` + pull-rebase commit discipline (`git add -A data/raw` already covers the
  new layout). `backfill.yml`: inputs `did` (default 13077) + `weeks` (default "auto");
  commit path `data/raw/scores` → `data/raw` (the old path misses `data/raw/<did>/scores/`);
  keep the serial concurrency group. `harvest-profiles.yml`: input `did`; **default `drill=0`
  (tabs-only)** per the locked decision; keep `if: always()` commit. Unchanged:
  `explore-profile.yml`; `capture-races.yml` only gains the B1 `out` input.
  **Gate:** unit tests for `archive_pages(did)` + the auto-week stop/abort distinction; a
  13077-only dispatch run produces the identical (migrated) layout.
- **B6 — parser tolerance for odd formats (scoped strictly by B1 recon).** Only if recon
  demands: `roster.py` accepts single-CSR rows (`csr_9/csr_10 → int | None`, `spread` guards
  None); `weekly_scores.py` adjusts for DP sheets (label-driven, likely no change);
  `scout.py` tolerates NULL csr_9/10 (defensive — app default is 13077). New fixtures +
  tests: roster 13985, roster 8-ball-only, DP score sheet, 13985 week index.
  **Gate:** pytest green; the 13298 + 13744 recon captures load with zero unresolved-team
  anomalies beyond expected subs.

## Rollout — foundation once, then ONE division at a time

> **ROLLOUT COMPLETE (2026-06-12): all 14 NoCo divisions are active (scrape=True).**
> Onboarded one at a time per the playbook below. Post-rollout the twice-daily
> all-division scrape was replaced by a DAY-AFTER-PLAY cron + catch-up queue
> (config.divisions_due, src/catchup.py, scrape.yml). Remaining tails, all
> self-healing via that cron: 13722 score sheets (host challenge escalated mid-
> rollout), 14022 R1 results (not yet posted), and profile harvests for the 6
> new divisions (deferred Phase-6 densification). PHASE6_READINESS.md numbers
> must now be recomputed (still 13077-only).

**Foundation (once):** B1 recon → B2 registry → B3 archive migration → B4 schema/loaders +
A1 resolution + A2 `player_divisions` + A3 `--rebuild` + B5 fetch/workflows → 13077
regression gate (pytest 59+new green; rebuild explainable-delta vs DATA.md; two consecutive
daily scrape runs, second mostly "unchanged"; scout grid for two 13077 teams identical to
pre-change) → **STOP — report, ask to continue.**

**Per-division onboarding playbook** (repeat for exactly ONE division; recommended order
13985 → remaining LC divisions → DP/8-ball-only divisions once B6 is in):
1. Flip the division's registry `scrape` flag (one-line config change, own commit).
2. Next daily scrape captures it — check `data/raw/<did>/<date>/` dirs + heartbeat lists it.
3. Backfill its full season: `backfill.yml` dispatch `did=N weeks=auto` (est. 30–60 min).
4. Harvest its profiles tabs-only: `harvest-profiles.yml` dispatch `did=N drill=0` (≈15 min).
5. Rebuild; run the gates — division: load report 0 unresolved teams, unresolved players ≈
   sub rate, its pending-makeup list surfaced; player: master-list completeness, sub-recovery
   delta, multi-division enumeration updated, CSR warn silent; next-day scrape mostly
   "unchanged".
6. **STOP — report the gate results and ask before starting the next division.**

Docs update after the foundation and refresh as divisions complete:
- `CLAUDE.md`: the player-first three-layer invariant; new archive layout; registry;
  app-default-13077; division-scoped pending-makeup rule; new hard rules (skill snapshots
  league-wide w/ verify-and-warn; name→id resolution division-first with ambiguity→NULL;
  one-division-at-a-time rollout with stops).
- `DATA.md`: layout, `--rebuild` pass order, `division_id`/`divisions`/`player_divisions` in
  the dictionary, refreshed row counts per completed division.
- `PHASE6_READINESS.md`: header note that per-player rack counts are stale and must be
  recomputed once multi-division data lands (**flag only — don't redo the analysis**).

## Tracked impacts

- **4 pending 13077 makeups (R25/R26/R27):** process unchanged; `pending_matches()` now
  division-scoped (default 13077); re-pull by actual play date via `backfill.yml did=13077`;
  never finalize 13077 standings while pending. Each onboarded division arrives with its own
  pending set (playbook step 5 surfaces it).
- **Actions budget:** ongoing daily scrapes ~1,000–1,200 min/month (2 runs/day × 15–20 min)
  + one-time backfills ~600 min total (spread across the one-at-a-time stops) + tabs-only
  harvests ~200 min total. Near the 2,000-min/month private-repo free tier — watch the first
  full month; the per-division stops naturally pace the spend.

## NOT changing

`src/race.py` race matrix + `capture-races.yml` capture logic; parser content logic where
recon confirms identical markup; profiles archive layout + harvest mechanics; the identity
tables' schemas (`players`/`skill_snapshots`/`pairing_history`/`player_form`) and
`team_members`; app default division + scout-grid logic; challenge-clearing core,
write-on-change, `[skip ci]`/pull-rebase discipline.

## Verification (end-to-end, player gates first)

1. **Master list:** every rostered player in every active division has a `players` row + ≥1
   snapshot; `player_divisions HAVING COUNT(*) > 1` lists the multi-division players;
   cross-division rack pool per player per game type strictly ≥ the 13077-only numbers.
2. **Sub recovery:** NULL-id game slots in 13077's games strictly below the pre-expansion
   baseline; per-division NULL rates reported and ≈ true sub rate.
3. **Foundation regression:** pytest green (59 existing + new tests); 13077 `--rebuild`
   matches DATA.md as an explainable delta (exact on players/teams/matches; games/snapshots
   deltas accounted for by post-2026-06-05 captures); scout grid for two 13077 teams
   identical to pre-change.
4. **Per division (at each stop):** `data/raw/<did>/<date>/` dirs present; heartbeat lists
   all active divisions; second consecutive daily run mostly "unchanged"; every division has
   teams/matches/games rows tagged with its `division_id`; load report anomalies zero beyond
   expected subs.

First implementation action: clone the repo to `X:\Claude_Code\Projectes\NAPA` (folder
contains only `.claude/` — clone into it via `git clone <url> tmp` + move, or `git init` +
remote + pull) and work on a feature branch, PR like Phases 0–5.
