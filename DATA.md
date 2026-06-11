# DATA.md — NAPA of Northern Colorado data dictionary

Read this cold to understand what's in the system. All 14 NoCo divisions live in
`config.DIVISIONS`; **13077** ("Thursday Big Table Felt, No Limit LC", season
2025–26, 27 rounds R1 2025‑10‑02 … R27 2026‑06‑04) is the app default and the
only division active so far. Seasons are STAGGERED per division (B1 recon:
18/21/27-round examples); each division's season key is its R1 date (stored in
`divisions.season`); 13077 keeps the "2025-26" label.

## How the data is produced
```
headless Chromium (clears JS challenge) → data/raw/<did>/ (committed) → parsers → SQLite (data/napa.db, regenerable)
```
- `data/raw/<did>/<date>/` — daily scrape per division (roster_grid, schedule, scratch, division, leaderboard, live_scores)
- `data/raw/<did>/scores/week_NN/` — per-game score sheets (the games grain), 1 `_index.html` + per-team `<tid>.html`
- `data/raw/profiles/<8-digit-id>/` — `main/h2h/trends/rivals.html` + `rival_<id>.html` drill-downs (player-keyed, division-independent)
- `data/raw/race_assets/` — races.js provenance for `src/race.py`
- `data/raw/_recon/` — B1 format probes + VERDICT.md (the three grid shapes)
- `fixtures/` — pinned parser test inputs (real captures)

`napa.db` is **not committed** (regenerable from the raw archive). To rebuild:
`python -m src.db --rebuild` — pass-ordered: ALL divisions' roster grids
(chronological; master player list first) → newest schedule per division →
all score sheets → profiles. Loading any division's sheets before all rosters
would miss cross-division id resolutions.

## Tables (row counts: 13077-only rebuild, 2026-06-11; refresh per onboarded division)

Three layers, players first: IDENTITY tables are league-wide and never gain a
division column; EVENTS tables carry `division_id` as an attribute.

| Table | Rows | What it holds | Grain / key |
|---|---|---|---|
| `players` | 85 | Identity + demographics + **career peak CueSpeed** (`peak_csr_8/9/10` + `peak_on_*`). Superset of any single roster. League‑wide master list. | PK `player_id` (8‑digit) |
| `skill_snapshots` | 340 | Dated per‑game CSR (8/9/10) + SM. Append‑only — the **drift record**. League‑wide: same‑day grids MERGE per‑game values; conflicting non‑null CSR warns. NULL = that division's grid doesn't rate the game. | PK (`player_id`, `captured_date`); 4 dates × 85 |
| `divisions` | 14 | Registry rows (name, weekday, format, season key). Seeded from `config.DIVISIONS`. | PK `division_id` |
| `teams` | 10 | Team names per (division, season). | PK `team_id`; UNIQUE (division_id, name, season) |
| `team_members` | 86 | Roster membership (captain flag). 86 slots, 85 distinct players — **Kat Plavnick on 2 teams**. | PK (team_id, player_id, season) |
| `player_divisions` | 85+ | Profile‑sourced "Divisions:" membership — sees divisions outside the scrape set; distinct provenance from rosters. | PK (player_id, division_id) |
| `matches` | 135 | Fixtures. `home_points`/`away_points` from standings record. | PK `match_id`; `division_id`; UNIQUE (season, round, home, away) |
| `games` | 657 | **Per‑game (race) results** — the rack‑level grain. game_type (8/9/10), races, wins, winner. All 657 linked to a match. | PK `game_id`; UNIQUE (division_id, played_date, home_name, away_name) |
| `pairing_history` | 7,731 | **Lifetime aggregate H2H** from profiles: per‑game W‑L + lags. **NOT rack‑level**, lacks opponent‑skill‑at‑time. Pairing‑layer enrichment only. | PK (player_id, rival_id); 6,620 distinct undirected pairs |
| `player_form` | 85 | Dated **form snapshot** (TRENDS): lifetime + last‑10 + 30/60/90‑day records + 10‑match assessment. | PK (player_id, captured_date) |

`matches/games` deliberately do **NOT** FK `*_player_id` to roster membership (subs).
Sources that give only names (live scores, score sheets) are name‑joined to the
8‑digit id DIVISION-FIRST (A1: division roster, else unique league‑wide, else
NULL + counted); subs keep `player_id = NULL` and are never dropped.
League‑wide queries (`player_game_log`, `csr_history`, `pairing_coverage`) pool
across divisions by design — that IS the Phase 6 pooling.

## Key distributions measured

**Per‑game data (`games`)**
- 657 games · **~4,100 racks** played · all linked to a match.
- 8/9/10‑ball split: **340 / 140 / 177**  (≈ 52% / 21% / 27%) — 8‑ball dominates (LC).
- Racks per player: **median 74**, mean ~80, p90 ~160, max ~228; right‑skewed
  (≈30 regulars >120 racks; ≈18 thin‑tail players <20 → need shrinkage to roster CSR).
- Single‑session head‑to‑head pairings: **592**, median **1** game/pairing
  (empirical H2H statistically meaningless single‑session).

**Densification (`pairing_history`)**
- **6,620 distinct lifetime pairings** vs **592** single‑session ≈ **10.5× denser**;
  every id‑resolved in‑division pairing now has lifetime per‑game history.
- 7,731 directed rival edges; rivals per player median 61, mean 91, max 386.
- 1,553 distinct opponents (1,468 off the current roster = subs/past, superset rule).
- Still thin per pair (lifetime mean ~2 meetings) → a **pooled latent‑skill model**
  with these counts as priors is the right shape; not direct empirical H2H.

**Skill drift / form**
- **45 of 85** players' CSRs recomputed Jun 4 → Jun 5 (end‑of‑session recompute) —
  captured as dated `skill_snapshots` (4 capture dates now archived).
- Career peak per game in `players.peak_csr_*` (e.g. one player 8‑ball 17 now / 50 peak)
  — exposes long‑run decline; current ratings corroborate the roster‑grid snapshots.
- `player_form`: 85 form snapshots (e.g. 18 players "recommended" in their last‑10).

## Race lengths
`src/race.py` — the official NAPA matrix transcribed verbatim from `races.js`
(class = stronger player's CSR band 0‑39/40‑49/50‑69/70‑89/90+; race from band+diff;
stronger races to the higher number). Static lookup, never fetched live.
Cross‑validated against real game outcomes (e.g. CSR 106 vs 38 → race 8‑2).

## Open data threads
- **Pending makeups** (scheduled, not yet played — `db.pending_matches(as_of)`):
  R25 5 Amigos vs Pocket Pals · R26 Doug's Team vs Barbarians ·
  R26 The Furies vs 5 Amigos · R27 Pocket Predators vs The Furies.
  Makeups play on **off‑schedule dates**, so re‑pull their score sheets by ACTUAL
  play‑date; loading drops them off the list. **Do not finalize standings** while pending.
- **Standings** (`matches.*_points`) are loaded only from the one committed
  `comp_sheet_season.mht` (Ed's Balls' record) — complete for that team, partial for
  others. Harvest all 10 teams' `standings_teams_record.php` for full standings.
- **Daily scrape cron** (`scrape.yml`) keeps running over all ACTIVE divisions
  (league‑night 04:00 UTC + daily 14:00 UTC): write‑on‑change per division,
  commits the archive back. `backfill.yml` (per‑division, `weeks=auto`) /
  `harvest-profiles.yml` (per‑division, tabs‑only default) are manual + resumable.
- **Division onboarding** is one at a time with stop gates — see
  MULTIDIVISION_PLAN.md "Per-division onboarding playbook".

## Phase 6 (forecasting) — NOT started
Per‑game win probability P(A beats B in one rack); project as even race and the
actual handicapped race; edge = your P minus the matrix‑implied P. Method TBD with
the volumes above in hand. Handle censored counts (race ends when someone hits their number).
