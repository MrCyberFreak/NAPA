---
name: napa-scrape-health
description: Verify NAPA daily scrape cron health — check scrape.yml run status, write-on-change commit diff, and heartbeat coverage of the divisions due that day. Use when asked whether the scrape ran green, to verify the cron, or to check capture health.
allowed-tools: Bash, Read, Grep, Glob
---

# NAPA scrape health check

Give a per-division health verdict on the latest `scrape.yml` run (workflow name
`scrape-archive`, repo `MrCyberFreak/NAPA`). This skill is READ-ONLY: never
re-run or dispatch a workflow, never run `src.browser_fetch`/`src.fetch`, never
write to `data/raw/` or the DB. The remedy for a challenge-abort is waiting for
the next cron — never re-hammer the hosts.

Optional argument: a date (`YYYY-MM-DD`) or a run id. Default: the latest run.

## Semantics to apply (verified against the repo — do not re-derive)

- **Write-on-change**: a page is archived to `data/raw/<did>/<date>/<page>.html`
  only if its bytes differ from the last capture; unchanged pages write nothing.
- **Green ≠ full capture.** The fetch loop is two-level fail-soft and exits 0
  either way:
  - Uncleared bot-challenge is HOST-WIDE: it aborts the WHOLE run (remaining
    divisions skipped, by design — every host serves a "One moment, please..."
    JS interstitial to plain GETs as HTTP 200, and only the headless-Chromium
    fetcher clears it; the loop reuses ONE browser context so challenge cookies
    amortize). Log line: `uncleared bot-challenge — aborting the run`.
  - A navigation error is DIVISION-LOCAL: it skips the rest of that division's
    pages (log: `stopping (fail-soft).`) and the loop continues.
  - A `failure` conclusion is therefore infra-level only: pip/Playwright
    install, checkout, the 60-min job timeout, or the push after 5 rebase
    retries. The DB-load step is `continue-on-error` and cannot fail the run.
- **A capturing run commits.** `data/raw/_heartbeat.json` (archive top level,
  league-wide, rewritten each run that captures) carries `updated_utc`, so
  `git add -A data/raw` always stages at least the heartbeat. The commit is by
  `napa-archive-bot`, message `chore(archive): scrape <date> [skip ci]`, pushed
  to `main`. On a day with something due, NO bot commit is an ANOMALY (push
  race), not a quiet-healthy signal. "Mostly unchanged" = the commit touches
  only `_heartbeat.json` plus a handful of pages.
- **A no-op day is healthy and makes NO commit.** Day-after-play means a run
  whose due set is empty AND whose carry-over queue is empty returns early
  BEFORE writing the heartbeat or queue (log: `nothing due and queue empty —
  no-op.`), so it stages nothing and pushes nothing. The heartbeat's
  `run_date`/`updated_utc` then stay on the previous capturing run. This is the
  normal Sunday case (no division plays Saturday → `divisions_due(Sun) == []`).
  Only flag a missing commit when something WAS due that day.
- **Cron**: a SINGLE `0 15 * * *` UTC run (~09:00 MT) calling
  `python -m src.browser_fetch --scheduled` — day-after-play, NOT the retired
  twice-daily `--all-divisions` sweep. It scrapes + auto-backfills only the
  divisions whose league night was YESTERDAY (`config.divisions_due`, reckoned
  America/Denver) plus the catch-up carry-over. At 15:00 UTC the UTC date equals
  the Denver date year-round. GitHub cron drifts (observed +38 to +97 min) and
  can SKIP a slot outright. Flag only if NO scheduled run landed in the past
  ~24 h.

## Procedure

1. **Expected divisions for THIS run (ground truth).** A day-after-play run does
   NOT target all 14 active divisions — only the set due that morning. The
   heartbeat records that set directly: expected coverage = its `due` array
   (divisions whose league night was yesterday) ∪ its `carryover` array
   (catch-up queue). The `scrape=True` registry in `src/config.py` is the
   universe a division must belong to, NOT the per-run expectation — a division
   absent from a run because it didn't play and isn't carried over is correct,
   not a miss. To cross-check `due` independently, `config.divisions_due` keys on
   the weekday before the run date. The local checkout can be stale — if
   `src/config.py` is missing locally or the working tree is behind, read it from
   `main`: `gh api repos/MrCyberFreak/NAPA/contents/src/config.py --jq .content | base64 -d`

2. **Find the run.**
   `gh run list --repo MrCyberFreak/NAPA --workflow=scrape.yml --limit 10 --json databaseId,conclusion,event,createdAt,updatedAt`
   Pick the latest run, or the one matching the date/run-id argument. Note
   `event` (schedule vs workflow_dispatch), drift from the nearest cron slot,
   and duration (`updatedAt - createdAt`).

3. **If `failure`:** `gh run view <id> --repo MrCyberFreak/NAPA --log-failed`.
   Classify as infra (install / checkout / timeout / push). Challenge-aborts do
   NOT land here — they are green; detect them in step 4.

4. **Heartbeat (the per-division truth).** Read the committed
   `data/raw/_heartbeat.json` from `main` (local copy only if current).
   Expected scheduled-run shape:
   `{"updated_utc", "mode": "scheduled", "run_date", "due": [...], "carryover": [...], "divisions": {"<did>": {"captured": [...], "unchanged": [...]}}}`
   - `mode` should be `"scheduled"` for a cron run. A `probe` key with no
     `divisions` means the probe step's heartbeat survived: the browser step
     never completed. Needs attention.
   - **Expected coverage = `due` ∪ `carryover` (read from the heartbeat
     itself).** `divisions` must contain a key for every did in that union.
     Missing trailing dids = challenge-abort; confirm via the run log
     (`gh run view <id> --repo MrCyberFreak/NAPA --log`, search
     `uncleared bot-challenge`). Report it as expected fail-soft behavior whose
     remedy is the next cron — never a manual re-run. A division NOT in `due`
     and NOT in `carryover` is correctly absent (it didn't play) — never flag it.
   - If `due` and `carryover` are both empty, this was a no-op day: the heartbeat
     wasn't rewritten this run (its `run_date` is the prior capturing run) and
     there is no commit. Healthy — confirm the log shows `nothing due and queue
     empty — no-op.`
   - Per division, `captured` + `unchanged` should be the 6 daily pages:
     `division, leaderboard, live_scores, roster_grid, schedule, scratch`.
     A short set = navigation fail-soft for that division — find
     `stopping (fail-soft)` in the log. (Score-sheet backfill pages are fetched
     separately and do not appear in this per-division page set.)
   - `updated_utc` should sit within the drift window of the `0 15 * * *` slot.

5. **Archive commit.** Find the bot commit for the run date and list its files:
   `gh api "repos/MrCyberFreak/NAPA/commits?per_page=10" --jq '.[] | .sha + "  " + .commit.message'`
   (match `chore(archive): scrape <date>`), then
   `gh api repos/MrCyberFreak/NAPA/commits/<sha> --jq '.files[].filename'`.
   Only `_heartbeat.json` (and possibly `_catchup.json`, which the scheduled run
   re-saves each capturing run) changed = an all-unchanged capture day (healthy).
   Page files appear as `data/raw/<did>/<date>/<page>.html`. A green scheduled run
   with something due but no bot commit = anomaly — say so; a no-op day (nothing
   due, empty queue) correctly has NO commit (see Semantics) — not an anomaly.

6. **Timing.** ~1m30s is normal when mostly unchanged. Double-digit minutes
   means heavy capture (fine if the heartbeat is complete); approaching the
   60-min timeout warrants attention.

7. **Report.** One verdict line per EXPECTED division (the run's `due` ∪
   `carryover`), not all 14 — and call out a no-op day as such:
   - `healthy` — covered by the heartbeat, full page set, commit consistent.
   - `needs-attention` — expected (in `due`/`carryover`) but missing from the
     heartbeat (say whether it is a challenge-abort), partial page set
     (navigation fail-soft), probe-only heartbeat, infra-failed run, or no
     scheduled run in ~24 h.
   Include: run id, conclusion, event, start time vs cron slot (drift),
   duration vs typical, and a changed-vs-unchanged summary per division.
   Recommend only "wait for the next cron" or "read the logs" — never offer to
   re-run, dispatch, or backfill from this skill.

## Out of scope

- Re-running or fixing scrapes; dispatching backfills or harvests; anything
  that writes to `data/raw/` or the DB.
- Division onboarding gates — that is the `napa-onboard-division` skill.
