# NAPA 13077 Data System
Personal pipeline: scrape division 13077 -> archive raw HTML -> parse -> SQLite -> views.

## Status (as of 2026-06-05, end of season R27)
- Phases 0–5 DONE: scaffold, parsers (roster/schedule/score-sheet/profile/standings),
  SQLite schema + loaders, browser fetcher + GitHub Actions automation, scout grid
  with REAL NAPA race lengths.
- Full-season data captured: all 27 weeks of per-game score sheets, end-of-session
  roster snapshots, the densified lifetime pairing graph, and the drift/form layers.
- Phase 6 (forecasting) NOT started — deliberate. See DATA.md for the volumes that
  inform the model choice.
- See DATA.md for the data dictionary (every table, row counts, key distributions).

## Commands
- Fetch (browser, clears challenge):  python -m src.browser_fetch   (cron: scrape.yml)
- Backfill score sheets:  python -m src.browser_fetch --backfill-weeks 1-27
- Harvest profiles:  python -m src.browser_fetch --harvest
- Parse+load (roster):  python -m src.db --load
- Test:   pytest        (59 tests, pinned to fixtures/)
- Run app / scout grid:  python -m src.app --scout "<team>" "<opp>"

## Hard rules
- App reads ONLY from data/napa.db. Never fetch from a view.
- Always archive raw HTML to data/raw/ BEFORE parsing. Raw archive is committed
  (the durable record); napa.db is regenerable and gitignored.
- Parsers must pass against fixtures/ before touching live data.
- Roster: 10 teams, ~86 roster slots (grows with subs), sizes 7–11. Segment on `#` team-header rows; NEVER assume 8/team. CSR is dash-separated (`95 - 80 - 81`).
- Players who appear in results/stats are a SUPERSET of the roster (subs exist). Don't FK games.player_id to roster. player_id is NOT unique per roster grid — a player can be rostered on >1 team (real: Kat Plavnick). Key team membership by (team, player_id).
- Canonical player key is the 8-digit playerID. Sources that give only a name
  (live scores, score sheets) are name-joined to it; subs keep a NULL id, never dropped.
- pairing_history is AGGREGATE lifetime W-L (from profile RIVALS/H2H), NOT rack-level —
  keep it separate from `games`. It lacks opponent-skill-at-time.
- ALL hosts (paper.playpool.io, scores.playpool.io, poolshooters.com, playpool.io,
  races.napaleagues.com) serve a "One moment..." JS bot-challenge to plain GETs
  (HTTP 200, not 403). A plain client (even httpx with cookies) CANNOT clear it —
  capture needs a real browser. Phase 4 uses headless Chromium (src/browser_fetch.py)
  on GitHub Actions, which clears it. Datacenter IP is fine once JS runs.
- Profile deep tabs (RIVALS/H2H/TRENDS) are JS/AJAX — load via
  stats.php?...&xTab=N (RIVALS=5 drill via &rival=<id>, H2H=12, TRENDS=33). Browser only.
- Current per-game ratings come from the roster grid (one fetch), not 85 profile hits.

## Domain
- LC = Lagger's Choice; skill is per-game (8/9/10). The spread matters, not one number.
- CSR = CueSpeed Rating. Higher = stronger. SM = session matches played.
- Race lengths: src/race.py is the NAPA matrix transcribed from races.js (class = stronger player's CSR band; race from band+diff). Static lookup, never fetched live. Provenance: data/raw/race_assets/.

## Open data threads
- Pending makeups (matches scheduled but not yet played): R25 5 Amigos vs Pocket Pals,
  R26 Doug's Team vs Barbarians, R26 The Furies vs 5 Amigos, R27 Pocket Predators vs
  The Furies. Surfaced by db.pending_matches(as_of). Makeups play on OFF-schedule dates,
  so re-pull their score sheets by ACTUAL play-date; loading drops them off the list.
  Never finalize standings while any are pending.
- The daily scrape cron (scrape.yml) keeps running: roster/schedule/scratch/division/
  leaderboard/live_scores, write-on-change, commits the archive back.

