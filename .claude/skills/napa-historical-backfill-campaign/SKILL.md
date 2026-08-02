---
name: napa-historical-backfill-campaign
description: Launch, check, resume, or safely stop the local historical-backfill campaign that recovers past-season NAPA divisions (dids back to 2022) by capturing score sheets, roster_grid, and schedule per historical did, then rebuilding and PRing the raw archive. Runs locally under Scheduled Task NAPA_HistoricalBackfill and NEVER dispatches GitHub Actions. Use for: how many historical dids captured, capture roster/schedule for historical sessions, resume/stop the historical backfill. NOT division-id discovery (napa-discovery-sweep), NOT per-player match-history capture (napa-match-history-campaign), NOT the Actions densification sweep (napa-harvest-sweep), NOT scrape-cron health (napa-scrape-health).
allowed-tools: Bash, Read, Grep, Glob
---

# NAPA historical-backfill campaign

Lifecycle manager for the LOCAL campaign that recovers the discovered HISTORICAL
NoCo divisions (past seasons back to 2022). 14 of 42 historical dids are captured;
the rest remain. Per uncaptured historical did the campaign captures THREE
coupled page-types (resumable, skip-on-disk), then rebuilds the DB and commits the
raw archive via branch+PR:

1. **score sheets** — `data/raw/<did>/scores/*.html` (the slow leg; reuses the
   production `backfill_score_sheets("auto", did=N)` with its own first-goto retry).
2. **roster_grid** — `data/raw/<did>/<date>/roster_grid.html` (historical CSR
   source; clean URL, clears in ~1 req).
3. **schedule** — `data/raw/<did>/<date>/schedule.html` (season-key + match-linking
   source; `print_schedule_v1.php` is VERIFIED-FLAKY — see the run notes).

It runs under the Windows Scheduled Task **`NAPA_HistoricalBackfill`** so it
survives `/clear` and closing Claude Code.

**Why this skill exists, and the HARD SAFETY rule:**

- An EARLIER incident — a detached bash driver loop survived TaskStop and kept
  **dispatching GitHub Actions for ~7.5h** after the user said stop (~11 failed
  runs, real billing). The user is **OVER** their Actions billing limit; all 6
  workflows are currently `disabled_manually`. Therefore this campaign **MUST run
  LOCALLY, MUST NEVER dispatch ANY GitHub Actions workflow, and the driver MUST NOT
  be a detached bash loop.** There is no `gh`/Actions dispatch anywhere in the
  driver.
- Capture is SERIAL, single-browser-context **by rule** (CLAUDE.md host rule: never
  hammer the host; an uncleared bot-challenge aborts host-wide). It is NOT
  parallelizable. It MUST run on the residential IP (a datacenter IP cannot
  cold-start the JS bot-challenge).
- **Stopping is the footgun** — and here it is doubly so. `schtasks /end` and
  TaskStop/background-bash do NOT kill the process tree (orphaned chromium keeps
  capturing), AND the incident was an Actions-dispatch loop. So a safe stop must be
  VERIFIED OVER TIME: on-disk count FROZEN **and** `gh run list` shows no NEW
  `workflow_dispatch` since stop. Never trust a single success message. See **stop**.

**Action verb (the only argument):** `status` (DEFAULT) | `run` | `stop` |
`resume`. Plus an optional explicit did list for `run`. `status` is read-only;
`run` and `stop` MUTATE a long local job — require an explicit verb and confirm
before running.

Paths used throughout (repo root `X:/Claude_Code/Projectes/Billiards/NAPA`):

- Uncaptured-did source of truth: `data/raw/_historical.json` → `["historical"]`
  (42 did→meta) MINUS dids that already have a `data/raw/<did>/scores/` dir.
  Compute it — never hardcode the list.
- Captured pages: `data/raw/<did>/scores/*.html`, `data/raw/<did>/<date>/roster_grid.html`,
  `data/raw/<did>/<date>/schedule.html`.
- Scripts: `.claude/skills/napa-historical-backfill-campaign/scripts/` —
  `run_backfill.bat`, `run_backfill.py`, `stop.ps1`, `status.sh`.

---

## ⚠ PREREQUISITE TO FLAG ON EVERY `run` (not fixed here)

The 2022-era `roster_grid` header is **`CSR 8 - 9 - 10 - SM`** — an extra trailing
`SM` column the current roster parser RAISES on (per the CLAUDE.md grid rule: an
unknown game token raises). **Until that parser fix lands, the rebuild's roster
pass will RAISE on historical roster_grid files.** This skill does NOT fix it (that
is a separate `src/` change the user is doing right after this skill is built).
The `run` step's rebuild MUST surface / warn about this and must not report a clean
rebuild if the roster pass raised on a historical `- SM` grid.

---

## status (DEFAULT — read-only)

Never mutates anything. Run the bundled `status.sh` from the repo root and report
ONE one-screen verdict:

```
bash .claude/skills/napa-historical-backfill-campaign/scripts/status.sh
```

It reports:

1. **Per-did capture matrix** — for each historical did, whether `scores/` +
   `roster_grid` + `schedule` are captured. Lists the not-yet-complete dids.
2. **Captured vs remaining** — `<n>/42 dids fully captured` and the remaining queue
   (computed from `_historical.json`, never hardcoded).
3. **Task state** — `schtasks /query /tn NAPA_HistoricalBackfill` → `Running` /
   `Ready` / not registered.
4. **Live?** — files written in the last 5 min (`>0` = capturing now; `0` while
   `Running` = stalled / between dids).
5. **CRITICAL safety line** — confirm NO Actions exposure: all 6 workflows still
   `disabled_manually` (`gh workflow list --all`) AND `gh run list --limit 10` shows
   no new `workflow_dispatch`. If a workflow is enabled or a dispatch fired, say so
   loudly — this campaign must NEVER coincide with Actions.

**Verdict line:** `<n>/42` captured · remaining `<queue>` · task Running/Ready ·
live? `yes/no` · Actions exposure? `none` (or LOUD if not).

---

## stop (SAFE — the incident guard)

Confirm with the user first (this halts a long local job). Then run the bundled
`stop.ps1`, which does all FOUR required steps and ASSERTS the result:

```
powershell -NoProfile -ExecutionPolicy Bypass \
  -File .claude/skills/napa-historical-backfill-campaign/scripts/stop.ps1
```

It performs, in order:

1. `schtasks /end /tn NAPA_HistoricalBackfill` (necessary, NOT sufficient — does
   not kill the tree).
2. PowerShell process-tree-kill, filtered to THIS driver:
   ```
   ($_.CommandLine -match 'run_backfill|browser_fetch' -and $_.Name -ne 'pwsh.exe') -or $_.Name -eq 'chrome-headless-shell.exe'
   ```
3. **Frozen on-disk verify:** count `scores/*.html` + `roster_grid` + `schedule`
   across all historical dids, two samples ~30s apart. If it MOVED, a local orphan
   is still capturing — the script exits `2` and you MUST NOT report "stopped".
4. **No-Actions verify (the new assertion):** `gh run list` shows NO new
   `workflow_dispatch` since stop AND `gh workflow list --all` shows all 6 still
   `disabled_manually`. If a workflow is enabled or a dispatch appeared, the script
   exits `3` — this is the incident pattern.

**Refuse to declare "stopped" unless the on-disk count is FROZEN (exit not 2) AND
there is no new gh dispatch (exit not 3).** Exit `0` = both verified = safe. A
moving count or a new dispatch means re-run / investigate; never trust a single
success message.

When the WHOLE campaign is done, remove the task:
`schtasks /delete /tn NAPA_HistoricalBackfill /f`.

---

## run

Confirm with the user first. Optional arg: an explicit space-separated did list
(default = the computed uncaptured-historical set).

1. **HARD-REFUSE if there is ANY Actions exposure.** Run the **status** safety line
   first. If ANY `gh workflow` is enabled OR a recent `workflow_dispatch` exists,
   STOP and do not run — this campaign must NEVER coincide with Actions (the ~7.5h
   incident). This refusal is non-negotiable.
2. **Assert nothing is already live.** Run the **status** checks. If the task is
   `Running` OR files were written in the last 5 min, STOP — a campaign is already
   in flight; a second one creates the competing-capture problem.
3. **Assert the driver scripts exist** under
   `.claude/skills/napa-historical-backfill-campaign/scripts/`: `run_backfill.bat`,
   `run_backfill.py`. Confirm `data/raw/_historical.json` exists (the uncaptured-set
   source).
4. **Register + run the Scheduled Task** pointing at the `.bat`:
   ```
   schtasks /create /tn NAPA_HistoricalBackfill /sc ONCE /st 00:00 /f \
     /tr "X:\Claude_Code\Projectes\Billiards\NAPA\.claude\skills\napa-historical-backfill-campaign\scripts\run_backfill.bat"
   schtasks /run /tn NAPA_HistoricalBackfill
   ```
   (Append a did list to the `.bat` path to scope it.) The driver loops the
   uncaptured dids SERIALLY in ONE browser context: per did it captures
   `roster_grid` (warms the host), then the flaky `schedule` print page with an
   up-to-8× goto hard-retry (mirrors the backfill `cleared()` pattern — the print
   endpoint slow-walks and times out on cold hits; bounded `week_number=18` returns
   the full schedule, so never assume 27 weeks), then the score-sheet backfill.
   Per-did `try/except` means one bad did doesn't abort the rest. Verify with
   **status** that the task is `Running` and files start landing. **NO `gh`, NO
   Actions, NO detached bash dispatch loop.**
5. **After the capture loop — rebuild:** `python -m src.db --rebuild --no-profiles`
   (loads rosters → schedules → sheets; `--no-profiles` skips the slow ~4h profile
   pass; historical dids fold into `config.divisions()` as scrape=False and
   `db._archived_dids()` iterates them, PR #71). **Surface the `- SM` prerequisite:
   if the roster pass RAISES on a historical `CSR 8 - 9 - 10 - SM` grid, report it
   and do NOT call the rebuild clean** — the parser fix is a separate `src/` change.
   Report load deltas (games / matches / season-key population).
6. **Commit the archive via branch+PR.** Direct push to main is classifier-BLOCKED.
   Commit `data/raw` on a branch → `gh pr create` → merge, message
   `chore(archive): historical roster/schedule + sheets [skip ci]`. The `[skip ci]`
   is mandatory (moot while workflows are disabled, but keep it). This is the ONLY
   `gh` use in the skill, and it is a PR — NOT a workflow dispatch.

---

## resume (after a logoff/reboot, or to pick up a partial run)

The task survives logon but a logoff/reboot stops it. The driver skips on-disk
captures (resumable), so it picks up from disk — just re-run the task:

```
schtasks /run /tn NAPA_HistoricalBackfill
```

Then confirm with **status** that captures resume (live? = yes). If the task itself
is gone (`schtasks /query` errors), the campaign needs **run**, not resume.

---

## Out of scope (do NOT do these from this skill)

- **Dispatching ANY GitHub Actions workflow — BANNED.** The driver is local-only;
  the only `gh` use is the archive PR (step 6), never a `workflow run`/dispatch.
- The `- SM` roster-parser fix — a separate `src/` change the user does right after
  this skill is built. This skill FLAGS it, never fixes it.
- Division-ID discovery (finding new dids) → **napa-discovery-sweep**.
- Per-player profile match-history capture → **napa-match-history-campaign**.
- The GitHub-Actions profile/backfill densification sweep → **napa-harvest-sweep**.
- The daily scrape-cron health verdict → **napa-scrape-health**.
- The `profiles=True` ~4h full rebuild and PHASE6_READINESS recompute.
- Re-enabling workflows / the Actions-billing decision — the user's call, not
  automation.
