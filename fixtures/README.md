# fixtures/

Captured raw pages used as **parser test inputs** (committed separately).
These are the immutable "store raw HTML before parsing" inputs for Phase 1.

Expected captures (file names are flexible; tests glob for them):
- `roster_grid*.mht` / `.html`   — roster grid (paper.playpool.io) — Phase 1 anchor
- `schedule*.mht`                — full schedule
- `profile*.mht`                 — one player profile (summary view)
- `leaderboard*.mht`             — a leaderboard view
- `division*.mht`                — division portal (the URL map)
- `weekly_scores*.mht`           — a weekly per-game page (shape TBD)

The roster-grid test asserts **10 teams / 82 players / sizes 7–11** against the
real capture once present; a synthetic fixture under `tests/data/` exercises the
parser logic in the meantime.
