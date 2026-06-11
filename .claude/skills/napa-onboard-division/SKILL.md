---
name: napa-onboard-division
description: Onboard exactly one NAPA division (e.g. 13985) into the multi-division rollout -- scrape-flag flip through backfill, harvest, rebuild, and gates, ending in a STOP for approval. Triggers: onboard division N, start the next division, continue the rollout, run or report the onboarding gates.
---

Walk exactly ONE NoCo division through the onboarding playbook
(MULTIDIVISION_PLAN.md, "Per-division onboarding playbook"), then STOP and
report for explicit user approval. This skill never starts a second division,
never skips the STOP, and never treats its own report as approval.

**Args:** a division id (e.g. `13985`); optionally a resume point ("resume at
gates", "backfill finished overnight"). The playbook spans days — cron and
workflow waits — so resuming mid-playbook is the normal case, not the exception.

## 0. Preflight — refuse early, not late

1. Exactly one did, and it must be in `config.DIVISIONS` (`src/config.py`).
   **13337 is deliberately unregistered** (seen in 3 players' profiles; user
   undecided) — refuse it and ask.
2. Confirm no other division is mid-onboarding: `config.active_dids()` should
   be 13077 + fully-approved divisions only; `gh pr list` shows no open
   flag-flip PR; the previous division's STOP was **explicitly user-approved**
   (check the conversation/handoffs — if unconfirmed, stop and ask).
3. Header-probe check: B1 recon probed only 13985 / 13298 / 13744
   (`data/raw/_recon/VERDICT.md`). For any other division — **13723**
   especially — the roster-grid CSR header was never seen. The header-driven
   parser RAISES on an unexpected shape; that loud failure is by design.
   Warn the user up front; if it fires later, promote the capture to
   `fixtures/` and fix the parser deliberately — never soften it to squeeze a
   grid through. Registry `fmt` is display-only; the grid header is the
   authoritative game set (never assume three games).
4. Budget note: full rollout ≈ 1,000–1,200 Actions min/month against the
   2,000-min private-repo free tier. Include a minutes/headroom note in the
   final report.
5. If resuming: detect the first unmet step (scrape flag in `src/config.py`,
   `data/raw/<did>/` contents, `gh run list` for the three workflows) and pick
   up there. Every step below is idempotent or resumable.

## 1. Flip the scrape flag — own PR

- On a branch, add `scrape=True` to the division's entry in `DIVISIONS` in
  `src/config.py` (mirror the 13077 line), and extend the rollout tripwire
  test `test_active_divisions_match_rollout` in `tests/test_config.py` with
  the new did. Two-line diff; nothing else rides along.
- Direct `git push` to main is blocked by the permission classifier. Use:
  `git push -u origin <branch>` → `gh pr create` → `gh pr merge`.

## 2. Verify the next daily scrape captured it

Crons: 04:00 UTC (league night) and 14:00 UTC daily (`scrape.yml`,
workflow name `scrape-archive`). After one fires:

- `gh run list --workflow=scrape.yml --limit 3` — latest run green.
- `git pull`, then confirm `data/raw/<did>/<date>/` exists (roster_grid.html,
  schedule.html, scratch, division, leaderboard, live_scores).
- `data/raw/_heartbeat.json` lists the did under `divisions` (string-keyed).
- If the run log says "uncleared bot-challenge — aborting": the abort is
  host-wide and by design. NEVER re-dispatch in a loop or hammer the remaining
  divisions — wait for the next cron; investigate only if it repeats.

## 3. Backfill the season's score sheets

```
gh workflow run backfill.yml -f did=<did> -f weeks=auto
gh run watch $(gh run list --workflow=backfill.yml --limit 1 --json databaseId -q '.[0].databaseId')
```

- `auto` walks week 1, 2, 3, … and stops after 2 consecutive EMPTY indexes; a
  nav failure or uncleared challenge ABORTS without counting toward the stop.
  Re-dispatching resumes from disk.
- Seasons are STAGGERED (18/21/27-round examples; non-13077 season key is the
  R1 date, stored in `divisions.season` at schedule load). Never assume 27
  weeks — a near-empty backfill is normal for a just-started season.

## 4. Harvest profiles — tabs-only, ALWAYS via the workflow

```
gh workflow run harvest-profiles.yml -f did=<did> -f drill=0
```

- Never substitute a local `--harvest` run: the local Python `--harvest-drill`
  default is still `"1"` — only the WORKFLOW defaults `drill` to `"0"`.
  Tabs-only is a locked decision (the rivals drill is ~5,200 pages / ~3h45m
  per division and Phase 6 doesn't use the per-game splits). If a local run is
  truly unavoidable, pass `--harvest-drill 0` explicitly.
- Resumable: re-dispatch skips files already on disk; the workflow commits
  partial captures even on timeout (`if: always()`).

## 5. Rebuild and test locally

- `git pull` — the workflows committed the archive (the durable record;
  raw HTML is always archived BEFORE parsing).
- `python -m src.db --rebuild` — pass-ordered: all rosters → schedules →
  sheets → profiles. `data/napa.db` is regenerable and gitignored; never
  commit it.
- `pytest` — full suite green (105 tests at last count, pinned to fixtures/).
- A roster-header RAISE here is preflight item 3 firing: capture → fixture →
  deliberate parser fix → re-run. Never a silent workaround.

## 6. Run the gates

```
python .claude/skills/napa-onboard-division/scripts/run_gates.py --did <did>
```

By default the script re-runs `db.rebuild()` to capture the load report (the
CSR-disagreement warn and unresolved-team counts exist only there);
`--no-rebuild` gates the existing `data/napa.db` and SKIPs those two. Exit 0 =
every hard gate green. Encoded gates (MULTIDIVISION_PLAN.md step 5 +
"Verification"):

- archive: dated roster grids + score sheets under `data/raw/<did>/`
- heartbeat lists the division; "mostly unchanged" steady-state reported
  (PENDING the next cron if the division was just captured — report it as
  pending, never as failed or faked)
- CSR-disagreement warn silent league-wide (a fire means CSR may be
  per-division — schema rethink, do not wave through)
- division schedule: 0 unresolved teams
- master list: every rostered player has a `players` row + ≥1 `skill_snapshot`
- events tagged with the division_id (teams / matches / games)
- 13077 sub-recovery: NULL-id game slots strictly below the 99-slot baseline
  (`--baseline-null-slots`)
- division NULL-slot rate ≤ 20% hard ceiling (`--max-null-rate`) — the real
  test is "plausible sub rate"; eyeball it (13077's is ~7.5%)
- multi-division enumeration refresh (`player_divisions HAVING COUNT(*) > 1`;
  foundation baseline 35)
- the division's own pending-makeups list surfaced (`db.pending_matches` is
  division-scoped, keyed on `divisions.season`)

## 7. STOP — report and ask

Report: did + name; what each step produced (capture dates, weeks backfilled,
profiles harvested); the full gate matrix verbatim; the division's
pending-makeups list (never finalize its standings while these are open); the
Actions-minutes note; any PENDING items (next-cron heartbeat check). Then ask
for explicit approval and STOP.

- Never flip the next division's flag or queue its work "while we wait".
- Never treat this report, a green gate run, or user silence as approval.

## Out of scope

Batch activation (never, under any phrasing); choosing the onboarding order
(recommend the plan's order only if asked: remaining LC divisions, then
DP/8-ball once verified); registering 13337; recomputing PHASE6_READINESS
numbers; approving its own STOP.
