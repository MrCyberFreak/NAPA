---
name: napa-harvest-sweep
description: Run a NAPA profile-harvest/backfill sweep across several already-onboarded divisions one at a time (host-friendly, gated, one retry per challenge abort). Use for Phase-6 densification or filling profile-coverage gaps -- NOT for onboarding a new division.
allowed-tools: Bash, Read, Grep, Glob
---

# NAPA harvest sweep

Dispatch the profile-harvest (or score-sheet backfill) workflow across several
ALREADY-ONBOARDED NoCo divisions, STRICTLY one run at a time, then STOP with a
coverage report. This is the densification / gap-fill pass — e.g. topping up
`pairing_history` after a rollout, or filling profile-coverage gaps. It does NOT
onboard a division, never flips a `scrape` flag, never runs the rebuild.

**Args:** a list of division ids (e.g. `13722 13723 13743 13744`); optional
`--workflow harvest|backfill` (default `harvest`); optional `--drill` (harvest
only, default `1` = full per-rival drill, the densification standard; `0` =
tabs-only).

## 0. Preflight — refuse early

1. Every did must already be in `config.DIVISIONS` with `scrape=True`
   (`config.active_dids()`). A not-yet-onboarded did is REFUSED — onboarding
   (flag flip → first scrape → backfill → gates → STOP) is the
   `napa-onboard-division` skill's job, not this one. (The sweep script's Python
   preflight enforces this and exits non-zero on any unknown did.)
2. Never sweep a harvest and a backfill together: both hit poolshooters.com and a
   concurrent pair starves each into 30s nav timeouts (onboard skill §4). Pick
   ONE workflow per sweep.
3. `--drill` defaults to `1` (full per-rival record drill) — the standard for the
   densification sweep, so `pairing_history` lands per-game lifetime splits for
   every division. The drill is ~5,200 pages / ~3h45m per division, which is why
   it runs STRICTLY one division per dispatch (the workflow's 350-min timeout
   covers one). Pass `--drill 0` for a fast tabs-only top-up; anything other than
   0 or 1 is REFUSED.
4. Confirm nothing is already in flight for these dids
   (`gh run list --workflow=harvest-profiles.yml --limit 5`, or `--workflow=backfill.yml`)
   — the workflows' `concurrency` groups (`cancel-in-progress: false`) queue, they
   do not parallelize.

## 1. Run the sweep — one at a time, gated

```
.claude/skills/napa-harvest-sweep/scripts/sweep.sh \
    [--workflow harvest|backfill] [--drill 1] <did> [<did> ...]
```

The script encodes the host-friendly discipline (CLAUDE.md hard rules) — do NOT
hand-roll a parallel dispatch:

- **Validation gate.** The FIRST division is the gate: dispatch, poll for the new
  run id, `gh run watch --exit-status` to completion. If that run fails, the WHOLE
  sweep aborts — do not burn the remaining divisions on a host that escalated.
- **Sequential.** Each remaining did: dispatch → poll for the new run id → watch
  to completion before the next. Never dispatch ahead (the concurrency group would
  queue/cancel anyway, and only one browser context should clear the host
  bot-challenge at a time).
- **One retry.** On a failed run, re-dispatch that did ONCE on a fresh runner (a
  new IP usually clears the challenge), then move on. NEVER loop or hammer.
- A harvest **challenge-abort is a GREEN run** (fail-soft; `if: always()` commits
  partial captures), so `gh run watch --exit-status` returns success even when
  capture stalled. The real signal is the §2 coverage gap: a division that stays
  far short after a SUCCESS aborted on the challenge — re-dispatch it once more,
  or read its `[harvest]` log line (onboard skill §4), never loop.

## 2. STOP — pull, report coverage, fold profiles in (incremental ingest)

The script ends with `git pull` (the workflows commit the archive / profiles to
`main`) and a per-division SUCCESS / ABORT block. Then:

- Run the profile-coverage check and report the gap per division:
  ```
  python .claude/skills/napa-harvest-sweep/scripts/coverage_gap.py <did> [<did> ...]
  ```
  It counts rostered players (`team_members ⋈ teams` on `division_id`, distinct
  non-null `player_id`) with no `data/raw/profiles/<id>/` dir yet.
- Fold the new profiles into `napa.db` with the INCREMENTAL ingest (seconds, no
  rebuild) — for each swept division:
  ```
  python -m src.db --ingest-profiles --did <did>
  ```
  It loads only the profile dirs whose files changed since last ingest (idempotent
  upserts; no wipe, no profile-pass), so `pairing_history` / `player_form` pick up
  the harvest without the old ~5-7h rebuild. A full `python -m src.db --rebuild` is
  needed ONLY for a schema change / integrity reset — do NOT run it from this skill.
  STOP.

## Out of scope

- Flipping a `scrape` flag / onboarding a not-yet-active division →
  `napa-onboard-division`.
- Onboarding decisions; the rebuild; flipping `scrape` flags (the drill itself
  now runs by default — `--drill 1`).
- Running `python -m src.db --rebuild`, or recomputing PHASE6_READINESS numbers.
- Scrape-cron health verdicts → `napa-scrape-health`.
