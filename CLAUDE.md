# NAPA 13077 Data System
Personal pipeline: scrape division 13077 -> archive raw HTML -> parse -> SQLite -> views.

## Commands
- Fetch:  python -m src.fetch
- Parse+load: python -m src.db --load
- Test:   pytest
- Run app: python -m src.app

## Hard rules
- App reads ONLY from data/napa.db. Never fetch from a view.
- Always archive raw HTML to data/raw/<date>/ BEFORE parsing.
- Parsers must pass against fixtures/ before touching live data.
- Roster: 10 teams, ~86 roster slots (grows with subs), sizes 7–11. Segment on `#` team-header rows; NEVER assume 8/team. CSR is dash-separated (`95 - 80 - 81`).
- Players who appear in results/stats are a SUPERSET of the roster (subs exist). Don't FK games.player_id to roster. player_id is NOT unique per roster grid — a player can be rostered on >1 team (real: Kat Plavnick). Key team membership by (team, player_id).
- ALL hosts (paper.playpool.io, scores.playpool.io, poolshooters.com) serve a "One moment..." JS bot-challenge to plain GETs (HTTP 200, not 403). A plain client (even httpx with cookies) CANNOT clear it — capture needs a real browser. Phase 4 uses headless Chromium (src/browser_fetch.py) on GitHub Actions, which clears it.
- Player-profile match history is JS-tab-loaded — a plain GET only gets the summary. Needs a browser.
- Current per-game ratings come from the roster grid (one fetch), not 82 profile hits.

## Domain
- LC = Lagger's Choice; skill is per-game (8/9/10). The spread matters, not one number.
- CSR = CueSpeed Rating. Higher = stronger. SM = session matches played.
