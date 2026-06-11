# NAPA of Northern Colorado Data System
Personal pipeline: scrape NoCo divisions -> archive raw HTML -> parse -> SQLite -> views.
**We track PLAYERS.** The master list is the league-wide `players` table (8-digit
playerID); divisions and teams are routing — everything known about a player
(skill drift, form, pairings, per-rack results) accrues to one player row.

## Status (as of 2026-06-11)
- Phases 0–5 DONE for division 13077 (full 2025-26 season: 27 weeks of score
  sheets, snapshots, pairing graph, form layers).
- Multi-division FOUNDATION DONE (MULTIDIVISION_PLAN.md): registry of all 14
  NoCo divisions, per-division archive layout, division-scoped events schema,
  header-driven roster parsing, multi-division fetch loop, --rebuild.
- Division rollout: 13077 active. The other 13 onboard ONE AT A TIME (flip the
  registry `scrape` flag -> daily scrape -> backfill `auto` -> harvest tabs-only
  -> rebuild -> gates -> STOP for approval). Never batch-activate.
- Phase 6 (forecasting) NOT started — deliberate. PHASE6_READINESS.md numbers
  are 13077-only and must be recomputed once multi-division data lands.

## Commands
- Fetch all active divisions (browser):  python -m src.browser_fetch --all-divisions   (cron: scrape.yml)
- Fetch one division:  python -m src.browser_fetch --did 13985
- Backfill score sheets:  python -m src.browser_fetch --backfill-weeks auto --did 13985   (auto stops after 2 empty weeks)
- Harvest profiles (tabs-only):  python -m src.browser_fetch --harvest --did 13985 --harvest-drill 0
- Load newest grids:  python -m src.db --load --all-divisions
- Rebuild DB from archive:  python -m src.db --rebuild   (rosters -> schedules -> sheets -> profiles)
- Test:   pytest        (105 tests, pinned to fixtures/)
- Run app / scout grid:  python -m src.app --scout "<team>" "<opp>"  [--division N]   (default 13077)

## Hard rules
- App reads ONLY from data/napa.db. Never fetch from a view.
- Always archive raw HTML to data/raw/<did>/ BEFORE parsing. Raw archive is committed
  (the durable record); napa.db is regenerable and gitignored. Profiles live at
  data/raw/profiles/<player_id>/ (player-keyed, division-independent).
- Parsers must pass against fixtures/ before touching live data.
- Roster grids: segment on `#` team-header rows; NEVER assume team count or size.
  The CSR HEADER declares the division's game set ("CSR8 - 9 - 10" / "CSR" /
  "CSR9 - 10") — values map positionally, absent games are NULL, a count mismatch
  RAISES. Never assume three games (B1 recon: "DP LC" divisions play 9/10 only).
- Players who appear in results/stats are a SUPERSET of the roster (subs exist). Don't FK games.player_id to roster. player_id is NOT unique per roster grid — a player can be rostered on >1 team (real: Kat Plavnick). Key team membership by (team, player_id).
- Canonical player key is the 8-digit playerID. Name->id resolution is DIVISION-FIRST
  with an explicit ambiguity rule (A1): the division's roster, else a UNIQUE
  league-wide match, else NULL + counted in the load report. Subs keep NULL ids,
  never dropped, never guessed.
- skill_snapshots stay LEAGUE-WIDE (PK player_id+captured_date): same-day grids
  MERGE per-game values; a conflicting non-null CSR warns — that warn firing means
  the league computes CSR per division and the schema needs a rethink.
  session_matches is per-division at the source: last-write ambiguous for
  multi-division players (accepted; Phase 6 counts games, not SM).
- Seasons are STAGGERED per division (18/21/27-round examples in B1 recon).
  Never assume 27 weeks; the season key for non-13077 divisions is the R1 date,
  stored in divisions.season. 13077 keeps "2025-26".
- pairing_history is AGGREGATE lifetime W-L (from profile RIVALS/H2H), NOT rack-level —
  keep it separate from `games`. It lacks opponent-skill-at-time.
- ALL hosts (paper.playpool.io, scores.playpool.io, poolshooters.com, playpool.io,
  races.napaleagues.com) serve a "One moment..." JS bot-challenge to plain GETs
  (HTTP 200, not 403). A plain client (even httpx with cookies) CANNOT clear it —
  capture needs a real browser. Headless Chromium (src/browser_fetch.py) on GitHub
  Actions clears it. Datacenter IP is fine once JS runs. The multi-division loop
  reuses ONE browser context (challenge cookies amortize); an UNCLEARED challenge
  aborts the whole run — never hammer the remaining divisions.
- Profile deep tabs (RIVALS/H2H/TRENDS) are JS/AJAX — load via
  stats.php?...&xTab=N (RIVALS=5 drill via &rival=<id>, H2H=12, TRENDS=33). Browser only.
  Profile harvests are TABS-ONLY by default (drill ~5,200 pages/division for
  per-game splits Phase 6 doesn't use; re-enable per player set when needed).
- Current per-game ratings come from each division's roster grid (one fetch per
  division), not per-player profile hits.

## Domain
- LC = Lagger's Choice; skill is per-game (8/9/10). The spread matters, not one number.
- CSR = CueSpeed Rating. Higher = stronger. SM = session matches played.
- Race lengths: src/race.py is the NAPA matrix transcribed from races.js (class = stronger player's CSR band; race from band+diff). Static lookup, never fetched live. League-wide. Provenance: data/raw/race_assets/.
- The 14 NoCo divisions live in config.DIVISIONS (did, weekday, fmt, scrape flag).
  `fmt` is display-only; the authoritative game set comes from the grid header.

## Open data threads
- Pending makeups in 13077 (matches scheduled but not yet played): R25 5 Amigos vs
  Pocket Pals, R26 Doug's Team vs Barbarians, R26 The Furies vs 5 Amigos, R27 Pocket
  Predators vs The Furies. Surfaced by db.pending_matches(as_of) — division-scoped,
  defaults to 13077. Makeups play on OFF-schedule dates, so re-pull score sheets by
  ACTUAL play-date (backfill.yml did=13077); loading drops them off the list.
  Never finalize a division's standings while its makeups are pending.
- Each onboarded division arrives with its own pending set — the onboarding gate
  surfaces it.
- The daily scrape cron (scrape.yml, league-night 04:00 UTC + daily 14:00 UTC)
  loops all ACTIVE divisions: roster/schedule/scratch/division/leaderboard/
  live_scores, write-on-change per division, commits the archive back.
