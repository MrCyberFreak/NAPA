# Finding — the live scoreboard's night-of data is never captured

_Diagnosis only (2026-07-03). No cron/code changed. This is the spec to fix it later._

## Symptom
All 66 archived `data/raw/<did>/<date>/live_scores.html` captures are ~500 B–1 KB
shells that parse to **0 games**. Example (14050, 2026-06-26) holds only the week's
matchup card (`Casey [2] vs. English Majors [10]` …), no players/racks. The parser is
fine — the pinned fixture `fixtures/live_scores.mht` yields **5 games**.

## Root cause — a timing gap, not a parse bug
- The live board endpoint (`scores.playpool.io/getlivescore.php?divID={did}&makeup=`,
  `config.py:281`) is only populated with per-game detail **while play is happening the
  night of the league session**. Afterwards it rolls over to the next week's matchup card.
- `scrape.yml` has a **single daily cron `0 15 * * *` (≈09:00 MT) — the morning AFTER
  league night** (the workflow says so explicitly). Every `live_scores.html` was captured
  in the morning (verified via git author dates: 14050 @ 07:08 MT, 13298/13299 @ 10:18 MT).
- So the only scheduled run fires ~11 h after the board has cleared. The older design had a
  league-night run (~04:00 UTC = ~22:00 MT); it was dropped when the cron went
  day-after-play only.

## What is NOT broken (important)
- The morning cron **does** scrape every active division daily (rosters / standings /
  schedules) and **backfills the score sheets day-after-play** — those are the
  authoritative per-rack finals feeding `games` (23,715 rows). **No final results are lost.**
- The only thing missed is the **live / in-progress board** (rack-by-rack as it happens,
  and any provisional state before the score sheet is finalized).
- `live_scores` is currently **captured but never loaded** into `napa.db` (no loader
  references it — grep: only `fetch.py`, `parse/weekly_scores.py`, `config.py`).

## Note on "pull all current sessions' latest data daily"
That is already satisfied for rosters/standings/schedules (every active division, every
day). Score sheets are **intentionally** day-after-play-per-division-due, because the
full score-sheet walk is the sustained load that escalates the host bot-challenge into
aborts. The genuine gap is specifically the **live board**, not a full daily score walk.

## League nights (from `config.DIVISIONS`)
Divisions play **Sun–Fri** (no Sat):
- Mon: 13881, 13205, 14064 · Tue: 13985, 13986, 13299, 13298 · Wed: 14022, 13937
- Thu: 13077, **14050 (English Majors)** · Fri: 13744, 13723, 13743, 13722 · Sun: 13711

A single nightly run catches whichever divisions played that evening.

## Fix spec (3 pieces)

### 1. League-night workflow
- New `.github/workflows/scrape-live.yml` (or a 2nd cron in `scrape.yml`).
- Schedule ~`30 4 * * *` (04:30 UTC ≈ 22:30 MDT / 21:30 MST — late evening the night of).
  Cron is UTC / not DST-aware; **reckon the due set in America/Denver** so at run time
  "tonight" = the Denver evening date. Comment both MDT/MST locals like `scrape.yml` does.
- Optional: poll a few times (e.g. 03:00 / 04:00 / 05:00 UTC) to capture progression, not
  just the final near-complete board.

### 2. "Playing tonight" selector + capture-only mode
- Add `config.divisions_playing_tonight()` (sibling to `divisions_due()`, which returns
  *yesterday's*): divisions whose `weekday` == the Denver run-time date's weekday.
- Add `python -m src.browser_fetch --live-now`: fetch **only `live_scores`** for tonight's
  divisions via the browser (clears challenge, one shared context), fail-soft, no
  retry-hammer — same discipline as the existing scheduled run.
- **Write to a DISTINCT path** so the morning shell can't overwrite the night-of capture.
  Same-filename write-on-change would let the 09:00 run replace the rich board with the
  shell. Use e.g. `data/raw/<did>/<date>/livescore_snapshots/<utc-ts>.html`.

### 3. Loader (optional — to make it queryable)
- Parse night-of captures with `parse_live_scores` into a **separate** table, e.g.
  `live_score_snapshots (division_id, captured_at, home_player, away_player, sl, racks_won,
  is_race_winner, …)`. **Keep it out of the authoritative `games` pipeline** — the live
  board is provisional; score sheets remain the source of truth. Avoids double-count /
  provisional-vs-final conflicts.

## Verification plan (can't fully test until a league night)
- Pre-checks now: unit-test `divisions_playing_tonight()` (like the existing scheduling
  tests); the parser already passes on the fixture (5 games).
- First real proof: `workflow_dispatch` the new workflow on a **Thursday ~22:00 MT** and
  confirm 14050's capture parses > 0 games (your English Majors match).

## Risk / tradeoffs
- Night-of **live-scores-only** = a single lightweight GET per tonight's divisions
  (typically 1–4/night), far lighter than the score-sheet walk → low bot-challenge risk.
  Keep fail-soft + one shared browser context.
- Do **not** re-add a full night scrape (score sheets) unless intended — that reintroduces
  the exact escalation the day-after design avoids.
- DST + distinct capture path are the two easy-to-miss details.
