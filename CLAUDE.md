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
- Roster: 10 teams, 82 players, sizes 7–11. Segment on `#` team-header rows; NEVER assume 8/team.
- Players who appear in results/stats are a SUPERSET of the roster (subs exist). Don't FK games.player_id to roster.
- Two hosts: paper.playpool.io = ok to fetch; poolshooters.com = blocks bots (see Phase 4).
- Player-profile match history is JS-tab-loaded — a plain GET only gets the summary. Needs a browser.
- Current per-game ratings come from the roster grid (one fetch), not 82 profile hits.

## Domain
- LC = Lagger's Choice; skill is per-game (8/9/10). The spread matters, not one number.
- CSR = CueSpeed Rating. Higher = stronger. SM = session matches played.
