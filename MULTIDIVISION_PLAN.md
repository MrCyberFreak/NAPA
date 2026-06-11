# NAPA: expand from division 13077 to all 14 NAPA of Northern Colorado divisions

## Context

The NAPA pipeline (repo `MrCyberFreak/NAPA`; local clone to be made at `X:\Claude_Code\Projectes\NAPA`) currently scrapes one division — 13077 — into a raw-HTML git archive, parses it into SQLite, and serves a scout grid. The owner wants all 14 divisions of **NAPA of Northern Colorado** (not El Paso "Rockies 2.0", not Mesa) because some players play in multiple divisions simultaneously, and Phase 6 forecasting needs pooled per-player racks across divisions to fight 9/10-ball sparsity (76% of players have <30 racks in 9-ball within 13077 alone).

Division list confirmed from `https://www.napaleagues.com/states.php?location=Colorado`. User decisions (locked):
- **Full-season score-sheet backfill** for all 13 new divisions.
- **Profile harvest for all new players, one division at a time, TABS-ONLY** (no per-rival drill — drill ≈ 5,200 page loads / 3h45m per division and Phase 6 doesn't use the per-game H2H splits; tabs-only ≈ 15 min/division). Rival drill stays available later for selectively chosen players.
- Scout grid / standings stay **13077-centric by default**.

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

Key verified facts shaping the design:
- `src/config.py:11` `DID = 13077` is the only true hardcode; `config.url()` already accepts a `did` override, but the schedule URL bakes in `weekDay` ("Thursday") — registry must carry per-division weekday. Never assume 27 weeks; discover per division.
- Archive is flat per date (`data/raw/<date>/...`, `data/raw/scores/week_NN/`) — a second division collides. Profiles (`data/raw/profiles/<player_id>/`) are player-keyed, division-independent — unchanged.
- Schema collisions: `teams UNIQUE(name,season)`, `games UNIQUE(played_date,home_name,away_name)`, `_find_match`/mirror-dedup query by date with no division scope, `_player_teams` name resolution takes `rows[0]` league-wide.
- Score-sheet links inside the archived `week_NN/_index.html` already embed `did` — only the index URL and output dir need parameterizing.
- Profile main page renders a `Divisions:` field with `division.php?did=N` anchors — not yet parsed; cheap multi-division-membership signal.
- DB is regenerable from the raw archive — schema changes mean rebuild, no ALTER migration.

## Step 0 — Format recon (no code changes)

Capture with existing `--capture-url` tooling for 13985 (normal LC), 13298 (8-ball-only), 13744 (DP): roster_grid, division page, schedule, `standings_weekly_scores.php?week=1`, one linked score sheet. Commit under `data/raw/_recon/<did>/`.
**Verify:** roster CSR shape for 8-ball-only grids (triple vs single — `_CSR_TRIPLE_RE` requires a triple today), the `lcF8` flag, DP score-sheet markup vs the label-driven parser, per-division season label and elapsed weeks. Promote the best captures into `fixtures/`.
**Gate:** written per-division-class verdict (same markup or not) before schema lock.

## Step 1 — `src/config.py`: DIVISIONS registry

`Division` frozen dataclass (did, name, weekday, fmt "LC"|"8", `scrape: bool = False`) + `DIVISIONS` dict of all 14 (only 13077 starts `scrape=True` — flag stages rollout). Keep `DID = 13077` as default everywhere. `url()` takes weekday from the registry. Add `active_dids()` and `division_root(did) -> data/raw/<did>`.
**Gate:** new unit tests build every registry URL; full pytest green.

## Step 2 — Archive migration (one `[skip ci]` commit)

`git mv` the 6 dated dirs → `data/raw/13077/<date>/`, `data/raw/scores` → `data/raw/13077/scores/`. No legacy-path grandfathering. Unchanged: `profiles/`, `profile_explore/`, `race_assets/`, `_heartbeat.json`. Same change updates path-coupled spots: `fetch.archive_pages(did)` (replaces static `ARCHIVE_PAGES` use), `db._discover_roster_source(did)`, `browser_fetch._roster_player_ids(did)`, `backfill_score_sheets(..., did)` default out_root.
**Gate:** pytest green; rebuild from migrated archive reproduces DATA.md counts (85 players / 10 teams / 135 matches / 657 games).

## Step 3 — Schema + loaders (`src/db.py`)

DDL: new `divisions` table (seeded from registry); `teams`/`matches`/`games` gain `division_id INTEGER NOT NULL`; `teams` UNIQUE → `(division_id, name, season)`; `games` UNIQUE → `(division_id, played_date, home_name, away_name)`; new `player_divisions(player_id, division_id, first_seen, last_seen)`. Unchanged: `players`, `skill_snapshots` (PK stays league-wide `(player_id, captured_date)` — CSR is league-wide; add verify-and-warn on cross-division CSR disagreement, last-write-wins), `team_members`, `pairing_history`, `player_form`.

Loaders/queries gain `division_id: int = config.DID` (existing call sites/tests unchanged): `load_roster`, `_get_or_create_team`, `_resolve_team_id`, `load_schedule`, `load_games`, `load_score_sheets` (+ division-scoped mirror-dedup and `_find_match` — two Friday divisions share dates), `load_team_record`, `pending_matches`, `standings`, `matches_for_round`, `team_depth`, `team_roster_latest`. `_player_teams` name→id resolution becomes **division-preferring** (fixes the latent league-wide `rows[0]` hazard). League-wide queries (`player_game_log`, `csr_history`, `pairing_coverage`) stay cross-division by design — that's the Phase 6 pooling. New `python -m src.db --rebuild` (per division: roster grids → schedule → score sheets; then profiles) + `--did`/`--all-divisions` flags.
**Gate:** new collision tests (same team name 2 divisions; same pairing same date 2 divisions; CSR-disagreement warn; division-scoped name resolution); 13077 rebuild matches DATA.md exactly.

## Step 4 — Parse the profile `Divisions:` field

`src/parse/profile.py`: extract `division.php?did=(\d+)` anchors → `Profile.divisions`. `load_profile()` upserts `player_divisions` (MIN/MAX first/last_seen). Refresh `fixtures/profile_main.html` if it predates the field.
**Gate:** rebuild populates `player_divisions` from the 85 archived profiles; `HAVING COUNT(*) > 1` count empirically confirms the multi-division premise before new-division work lands.

## Step 5 — Multi-division fetch (`src/browser_fetch.py`, `src/fetch.py`)

`main()` gains `--did N` / `--all-divisions`: loop `active_dids()` reusing ONE browser context (challenge cookies persist per host → divisions after the first skip the 6s clears; daily run ≈ 10-20 min, not 14× full cost). Fail-soft: nav error skips to next division; uncleared bot-challenge aborts the whole run. Heartbeat becomes per-division: `{"divisions": {did: {captured, unchanged}}}`. `backfill_score_sheets(weeks|"auto", did)`: "auto" walks weeks and stops after 2 consecutive empty indexes (mid-season divisions, unknown counts). `harvest_profiles(..., did)` reads roster ids per division; resumability dedups shared players for free.
**Gate:** unit tests for `archive_pages(did)` + auto-week stop; a 13077-only dispatch run produces the identical (migrated) layout.

## Step 6 — Workflows + staged activation

- `scrape.yml`: cron `0 4 * * 5` → `0 4 * * *` (every weekday now has a league night); browser step → `--all-divisions`; db load → `--all-divisions` (keep `continue-on-error`); add `timeout-minutes: 60`; keep `[skip ci]` + pull-rebase commit discipline.
- `backfill.yml`: inputs `did` (default 13077) + `weeks` (default "auto"); keep the serial concurrency group.
- `harvest-profiles.yml`: input `did`; **default `drill=0` (tabs-only)** per user decision; keep `if: always()` commit.
- Unchanged: `capture-races.yml`, `explore-profile.yml`.

Staged activation via the registry `scrape` flag (one-line config change per stage): (1) 13077 only — regression; (2) +13985; (3) +odd formats (13298, 13744, 13743, 13722) after Step 7; (4) all 14.
**Gate per stage:** dispatch run green; `data/raw/<did>/<date>/` dirs present; heartbeat lists all active divisions; next-day run mostly "unchanged".

## Step 7 — Parser tolerance for odd formats (scoped by recon)

Only if recon demands: `roster.py` accepts single-CSR rows (`csr_9/csr_10 → int | None`, `spread` guards None); `weekly_scores.py` adjusts for DP sheets (label-driven, likely no change); `scout.py` tolerates NULL csr_9/10 (defensive — app default is 13077). New fixtures + tests: roster 13985, roster 8-ball-only, DP score sheet, 13985 week index.
**Gate:** pytest green; 13298 + 13744 recon captures load with zero unresolved-team anomalies beyond expected subs.

## Step 8 — Backfill all 13 new divisions (one dispatch each)

Order: 13985 → odd formats → remaining seven. After each: rebuild + check load report (unresolved teams must be 0; unresolved players ≈ sub rate). Est. 30-60 min/division; **~8-13 h Actions total, one-time**.

## Step 9 — Profile harvests, tabs-only, one division at a time

One `harvest-profiles.yml` dispatch per division with `did` set, `drill=0`. ≈ **15 min/division** (observed 8m49s for 85 players tabs-only); shared players skipped. Per-game rival drill stays available later for selectively chosen players (e.g. upcoming opponents). Loses only per-game W/L splits in `pairing_history` for new players — Phase 6 pools through latent skill and doesn't use them.

## Step 10 — Docs

- `CLAUDE.md`: new archive layout, registry, app-default-13077, division-scoped pending-makeup rule, new hard rules (skill snapshots league-wide w/ verify-and-warn; name→id resolution division-first).
- `DATA.md`: layout, `--rebuild` order, `division_id`/`divisions`/`player_divisions` in the dictionary, refreshed row counts after backfills.
- `PHASE6_READINESS.md`: header note that per-player rack counts are stale and must be recomputed once multi-division data lands (**flag only — don't redo the analysis**).

## Tracked impacts

- **4 pending 13077 makeups (R25/R26/R27):** process unchanged; `pending_matches()` now division-scoped (default 13077); re-pull by actual play date via `backfill.yml did=13077`; never finalize 13077 standings while pending. New divisions arrive with their own pending sets (Step 8 load report surfaces them).
- **Actions budget:** ongoing daily scrapes ~1,000-1,200 min/month (2 runs/day × 15-20 min) + one-time backfills ~600 min. With tabs-only harvests (~200 min total) this stays near the 2,000-min/month private-repo free tier; watch the first full month.

## NOT changing

`src/race.py` race matrix + `capture-races.yml`; parser content logic where recon confirms identical markup; profiles archive layout + harvest mechanics; `players`/`skill_snapshots`/`pairing_history`/`player_form`/`team_members` schemas; app default division + scout-grid logic; challenge-clearing core, write-on-change, `[skip ci]`/pull-rebase discipline.

## Verification (end-to-end)

1. After Step 3: `pytest` green (59 existing + new collision tests); `python -m src.db --rebuild` on 13077 reproduces DATA.md counts exactly.
2. After Step 6 stage 2: two consecutive daily scrape runs for {13077, 13985}; second run mostly "unchanged"; heartbeat shows both.
3. After Step 8: rebuild; sanity SQL — every division has teams/matches/games rows tagged with its `division_id`; `player_divisions HAVING COUNT(*)>1` lists the multi-division players; cross-division rack pool per player per game type strictly ≥ the 13077-only numbers.
4. Scout grid regression: `python -m src.app --scout "<team>" "<opp>"` for two 13077 teams produces the same grid as pre-change.

First implementation action: clone the repo to `X:\Claude_Code\Projectes\NAPA` (folder contains only `.claude/` — clone into it via `git clone <url> tmp` + move, or `git init` + remote + pull) and work on a feature branch, PR like Phases 0-5.
