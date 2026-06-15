---
name: napa-readiness-recompute
description: Recompute PHASE6_READINESS.md from the current data/napa.db and open a doc-update PR. Runs tools/phase6_readiness.py, flags stale figures (header + §1-§5 + summary) via a stale-scan, edits the doc, branches to avoid archive-bot races. Use after a densification rebuild (harvest/drill/backfill) when the readiness numbers may have moved -- NOT for harvesting profiles or building the Phase 6 forecast model.
allowed-tools: Bash, Read, Edit, Grep, Glob
---

# NAPA readiness recompute

Bring `PHASE6_READINESS.md` back in sync with the current `data/napa.db` and open
a branch+PR for the change. This is the deterministic-compute → doc tail that runs
after a rebuild (e.g. a profile harvest/drill or a score-sheet backfill landed new
data). It recomputes `tools/phase6_readiness.py`, diffs its figures against the
doc, edits the stale ones, and STOPS at an open PR. It does NOT harvest, drill,
backfill, or build the Phase 6 model.

**Args:** optional `--rebuild` (run `python -m src.db --rebuild` first, ~30 min;
default assumes the DB is already rebuilt); optional `--no-pr` (edit + report the
diff, open no PR).

## 0. Preflight

1. **Working tree.** A doc PR must start clean. The only acceptable noise is
   untracked `handoffs/` and the gitignored `data/napa.db`. If `git status
   --short` shows other staged/modified files, STOP and surface them — don't fold
   unrelated changes into the readiness PR.
2. **DB present + current.** Assert `data/napa.db` exists. If `--rebuild`, run
   `python -m src.db --rebuild` now and confirm `csr_conflicts: 0` league-wide and
   `profiles … failed: 0` in the tail. Without `--rebuild`, trust that the caller
   rebuilt — but if the readiness numbers look wildly off, the DB is stale; rebuild.
3. This skill is for the **13077-superset multi-division** doc. It assumes the doc
   already exists (it's a refresh, not a first authoring).

## 1. Scan for stale figures

```
python .claude/skills/napa-readiness-recompute/scripts/stale_scan.py
```

It runs `tools/phase6_readiness.py` (the deterministic, seeded compute) and prints
an OK / STALE table for ~25 high-value scalars the doc cites in prose: header
totals (players, skill_snapshots, teams, matches, games), §2 CSR coverage, §3a
slopes, the whole §5 `pairing_history` block (edges, subjects, pairings,
reciprocal %, W-L count/%, game-pair overlap, historical-only, pending total), and
§5 caveats (CSR `n=` per type, latest snapshot date). Exit 0 = doc current
(nothing to do — report and STOP); exit 1 = at least one STALE row.

The scan is a FLAGGING AID, not the editor. A STALE row means the current value
isn't in the doc verbatim — go look. It does NOT cover the §1/§3 bin tables or any
prose *wording* (rankings, verdicts); judge those by reading the full
`python tools/phase6_readiness.py` dump against the doc (see §2).

## 2. Decide scope, then edit the doc

For every STALE scalar, update its number wherever it appears — in §-body prose,
the intro banner, AND the "Readiness summary" (numbers are repeated across all
three; `grep -n` the old value to catch every copy). Then check the parts the scan
can't:

- **Derived wording.** §3a states a flatness *ranking* ("8-ball flattest, 10-ball
  steepest") and a verdict. If the slopes moved, re-read whether the ranking still
  holds and rewrite the prose to match — a prior session shipped a stale ranking
  here. Same for any "median X racks", "84% of pairings once", etc.
- **§1/§3 bin tables.** The scan doesn't track these. Eyeball them against the
  dump. **Scope judgement:** if the only mover was a same-day scrape nudging a few
  §3 CSR bins by ≤a-few games / slopes by <0.1 pp (within their CIs, no
  conclusion change), DON'T hand-churn ~50 bin cells — that's the error-prone
  transcription this skill exists to bound. Instead leave §1-§4 and add ONE banner
  line scoping the refresh (e.g. "§5 + headline counts refreshed <date>; §1-§4
  from the prior build, negligible drift, no finding changes"). If a real data
  load (new games) moved the bins materially, update the tables.
- **Dates.** Bump the recompute date in the banner; update "as of <date>" on the
  pending line and the snapshot-span text if the snapshot dates changed.

Re-run `stale_scan.py` after editing — it should reach the scope you intended (0
STALE, or only the §1-§4 cells you consciously deferred per the banner note).

## 3. Branch + PR (unless `--no-pr`)

Doc changes go via **branch + PR**, never a direct push to `main` — the archive
bot pushes `[skip ci]` commits to `main` and a direct push races it.

```
rm -f .git/index.lock                      # recurs from the IDE git integration
git checkout -b docs/phase6-readiness-<short-reason>
git add PHASE6_READINESS.md
git commit -m "docs(phase6): <what moved and why>"   # end with the Co-Authored-By trailer
git push -u origin HEAD
gh pr create --base main --title "…" --body "…"      # table the before→after of the stale figures
```

STOP at the open PR. Report the PR link + the stale-scan before/after. Do NOT
merge — leave that to the operator (the project convention is
`gh pr merge --squash --delete-branch`, but it's their call).

## Out of scope

- Harvesting / drilling profiles, or running a sweep → `napa-harvest-sweep`.
- Backfilling score sheets / onboarding a division → `napa-onboard-division`.
- Scrape-cron health verdicts → `napa-scrape-health`.
- Designing, fitting, or training the Phase 6 forecast model (that's the actual
  model work; this skill only keeps the readiness *analysis* current).
- Authoring the doc from scratch — this refreshes an existing PHASE6_READINESS.md.
