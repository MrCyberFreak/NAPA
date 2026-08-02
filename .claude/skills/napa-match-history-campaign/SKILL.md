---
name: napa-match-history-campaign
description: Launch, check, resume, or safely stop/kill the local detached NAPA match-history capture campaign (the veterans-first per-player profile capture under Scheduled Task NAPA_MatchHistoryCapture, veterans_first.log). Use for: is the capture still running, how many players done, stop/kill it without orphaning chromium, relaunch the veterans-first capture as a detached task, did it finish. NOT the GitHub-Actions division harvest sweep (napa-harvest-sweep) or the daily scrape-cron health check (napa-scrape-health).
allowed-tools: Bash, Read, Grep, Glob
---

# NAPA match-history campaign

Lifecycle manager for the LOCAL, detached, per-player career match-history capture:
all 708 rostered players × 11 NAPA profile `xTab` tabs
(`2,3,4,10BP,777,17,9BP,RR9,RR10,24,25`), **veterans-first** (richest career
history first), running under the Windows Scheduled Task
**`NAPA_MatchHistoryCapture`** so it survives `/clear` and closing Claude Code.

Why this skill exists, and why it is NOT a workflow fan-out:

- The capture is SERIAL, single-browser-context **by rule** (CLAUDE.md host rule:
  never hammer the host; an uncleared bot-challenge aborts host-wide). It cannot be
  parallelized — one browser context clears the challenge at a time.
- It MUST run LOCALLY on the residential IP. A datacenter IP cannot cold-start the
  JS bot-challenge.
- **Stopping is the footgun.** `schtasks /end` and the background-bash / TaskStop
  mechanism do NOT kill the process tree — they orphan bash + python + chromium,
  which keep capturing in roster order and inflate the page count (~3 incidents in
  one session). A safe stop REQUIRES the PowerShell tree-kill AND a frozen
  page-count verify. That is the core value of this skill — see action **stop**.

**Action verb (the only argument):** `status` (DEFAULT) | `launch` | `stop` |
`resume`. Plus an optional VET threshold for `launch` (default 200).
`status` is read-only. `launch` and `stop` MUTATE a long local job — require an
explicit verb and confirm before running.

Paths used throughout (repo root `X:/Claude_Code/Projectes/Billiards/NAPA`):

- Pages: `data/raw/profiles/<player_id>/match_*.html`
- Log: `handoffs/veterans_first.log` (the `COMPLETE: ... no new pages` line = done)
- Scripts (promoted into this skill): `.claude/skills/napa-match-history-campaign/scripts/`
  — `run_capture.bat`, `capture_veterans_first.sh`, `capture_veterans_first.py`, `stop.ps1`

---

## status (DEFAULT — read-only)

Never mutates anything. Run all of these from the repo root and report ONE
one-screen verdict:

1. **Task state:** `schtasks /query /tn NAPA_MatchHistoryCapture` → `Running` or
   `Ready`. (`ERROR: ... cannot find` = the task was deleted / never registered =
   not currently a campaign.)
2. **Pages on disk:** count `data/raw/profiles/*/match_*.html`
   (`ls data/raw/profiles/*/match_*.html | wc -l`).
3. **Players done / 708:** count DISTINCT player dirs that have at least one LEAGUE
   match page (tabs `match_2/3/4*`), e.g.
   `ls -d data/raw/profiles/*/ | while read d; do ls "$d"match_2_*.html "$d"match_3_*.html "$d"match_4_*.html >/dev/null 2>&1 && basename "$d"; done | wc -l`.
   Report `<n>/708`.
4. **Live? (still writing):** count pages written in the last 5 min —
   `find data/raw/profiles -name 'match_*.html' -mmin -5 | wc -l`. `>0` = capturing
   right now; `0` while task is `Running` = stalled / between resume attempts.
5. **Complete?** `tail -5 handoffs/veterans_first.log` — look for
   `COMPLETE: ... no new pages`. That line (two consecutive runs with no new pages)
   is the authoritative done signal, NOT the task state.

**Verdict line:** Running/Ready · `<pages>` pages · `<n>/708` players · live? `yes/no`
· complete? `yes/no`. If complete, point the user at the post-capture tail (merge
PR #50 → `python -m src.db --rebuild` → QA) but DO NOT run it — that is out of scope
(below).

---

## stop (SAFE — the whole reason this skill exists)

Confirm with the user first (this halts a long local job). Then run the bundled
`stop.ps1`, which does all three required steps and ASSERTS the result:

```
powershell -NoProfile -ExecutionPolicy Bypass \
  -File .claude/skills/napa-match-history-campaign/scripts/stop.ps1
```

It performs, in order:

1. `schtasks /end /tn NAPA_MatchHistoryCapture` (necessary, NOT sufficient — does
   not kill the tree).
2. The PowerShell process-tree-kill (the exact handoff filter):
   ```
   Get-CimInstance Win32_Process | ? { ($_.CommandLine -match 'capture_veterans|browser_fetch' -and $_.Name -ne 'pwsh.exe') -or $_.Name -eq 'chrome-headless-shell.exe' } | % { Stop-Process -Id $_.ProcessId -Force }
   ```
3. **Frozen-page-count verify:** sample the page count, wait ~30s, sample again.
   If it MOVED, an orphan is still capturing — the script exits non-zero and you
   MUST NOT report "stopped". Re-run `stop.ps1` until the count is frozen.

**Refuse to declare "stopped" while the page count is still moving.** A moving
count means an orphaned chromium/python is still alive and will spawn a competing
roster-order capture. `stop.ps1` exit 0 = frozen = safe; exit 2 = still moving =
re-run it. Never use TaskStop / background-bash kill alone as the stop.

When the WHOLE job is finished (status shows complete and you no longer need the
task), remove it: `schtasks /delete /tn NAPA_MatchHistoryCapture /f`.

---

## launch

Confirm with the user first. Optional arg: VET threshold (lifetime_played cutoff
for the veterans tier; default 200 ≈ 152 players).

1. **Assert nothing is already live.** Run the **status** checks. If the task is
   `Running` OR pages were written in the last 5 min, STOP — a campaign is already
   in flight; launching a second one creates the exact competing-capture problem
   this skill guards against. Do not launch.
2. **Assert the driver scripts exist** under
   `.claude/skills/napa-match-history-campaign/scripts/`: `run_capture.bat`,
   `capture_veterans_first.sh`, `capture_veterans_first.py`. Also confirm
   `data/napa.db` exists (the driver reads `player_form.lifetime_played` to rank).
3. **Register + run the Scheduled Task** pointing at the promoted `.bat`:
   ```
   schtasks /create /tn NAPA_MatchHistoryCapture /sc ONCE /st 00:00 /f \
     /tr "X:\Claude_Code\Projectes\Billiards\NAPA\.claude\skills\napa-match-history-campaign\scripts\run_capture.bat <VET>"
   schtasks /run /tn NAPA_MatchHistoryCapture
   ```
   (Omit `<VET>` to use the default 200.) The `.bat` → `capture_veterans_first.sh`
   resume-loop → `capture_veterans_first.py` driver. Verify with **status** that
   the task is `Running` and pages start landing.

---

## resume (after a logoff/reboot stopped it)

The task survives logon but a logoff/reboot stops it. The harvester skips on-disk
pages, so it picks up from disk — just re-run the task:

```
schtasks /run /tn NAPA_MatchHistoryCapture
```

Then confirm with **status** that pages resume (live? = yes). If the task itself is
gone (`schtasks /query` errors), the job needs **launch**, not resume.

---

## Out of scope (do NOT do these from this skill)

- The GitHub-Actions division profile-harvest sweep → **napa-harvest-sweep**.
- The daily scrape-cron health verdict → **napa-scrape-health**.
- Flipping `scrape` flags / onboarding a division → **napa-onboard-division**.
- `python -m src.db --rebuild` or recomputing PHASE6_READINESS numbers. The rebuild
  is the post-capture tail; mention it, never run it here.
- The storage decision (raw-HTML vs data-only-JSON) — an OPEN design question for
  the user, not automation.
