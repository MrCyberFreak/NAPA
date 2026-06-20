---
name: napa-discovery-sweep
description: Run or check a NAPA division-ID discovery sweep -- dispatch discover.yml (scout or sharded sweep over a did range), watch the run + merge to green, and report the historical NoCo sessions in _historical.json ready to onboard. NOT the profile-harvest/backfill densification sweep and NOT onboarding a division.
allowed-tools: Bash, Read, Grep, Glob
---

# NAPA division discovery sweep

Dispatch `.github/workflows/discover.yml` to recover a NoCo league's PAST sessions
by probing the division-ID integer (NAPA mints a new `did` per season and exposes
no season/year URL param, so the `did` range is the only lever), monitor the run
(and for a sweep its dependent `merge` job) to green, then read the merged index
and report the historical NoCo sessions ready to onboard. Then STOP.

This skill is DISCOVERY-ONLY. It NEVER flips a `config.DIVISIONS` scrape flag,
NEVER onboards a discovered did, and NEVER runs the rebuild — those are
`napa-onboard-division`'s job. It is also NOT the profile-harvest / score-sheet
densification sweep over already-onboarded dids — that is `napa-harvest-sweep`.

**Args / inputs:**
- `mode` — `scout` (default) or `sweep`.
- For `sweep`: `high` / `low` / `shards` (defaults `14050` / `12000` / `4`).
- `check` / `report` — inspect the LATEST discover run and the merged index
  WITHOUT dispatching anything.

## 0. Preflight — confirm before dispatching

1. **Check vs run.** If the user asked to "check"/"report"/"did it finish/what's
   in _historical.json", do NOT dispatch — jump to §3 (read latest run) then §4–5.
2. **Confirm intent + range** with the user before a `sweep`. A sweep is HEAVIER
   than the daily scrape and outward-facing: `shards x thousands` of
   `division.php?did=N` requests against the host. Run it sparingly, OFF-HOURS.
3. **Host-abort discipline (CLAUDE.md hard rule).** An uncleared bot-challenge
   aborts ONLY that shard (the matrix is `fail-fast: false`), never the whole
   sweep. Re-dispatch ONCE on a fresh runner; NEVER loop or hammer the host.
4. **Default-branch gate.** `workflow_dispatch` only fires from the default branch
   — verify `discover.yml` is on `main` before dispatching:
   `git ls-tree main --name-only .github/workflows/ | grep discover`.

## 1. Dispatch discover.yml

Use the helper (it captures the run id and encodes the discipline) — do NOT
hand-roll a parallel dispatch:

```
.claude/skills/napa-discovery-sweep/scripts/discover.sh scout
.claude/skills/napa-discovery-sweep/scripts/discover.sh sweep [high] [low] [shards]
.claude/skills/napa-discovery-sweep/scripts/discover.sh check     # no dispatch
```

The exact `gh workflow run` inputs (verified against `discover.yml`):
- `gh workflow run .github/workflows/discover.yml -f mode=scout`
- `gh workflow run .github/workflows/discover.yml -f mode=sweep -f high=<high> -f low=<low> -f shards=<shards>`

Input names are `mode` / `high` / `low` / `shards` (all strings; `low` is the
scout stop-floor and the sweep low bound). Underneath, the workflow calls
`python -m src.browser_fetch --discover-scout --discover-low <low>` (scout) or
`--discover-range <high> <low> --discover-shard i/N` per shard (sweep), then the
`merge` job runs `python -m src.division_index --merge --shards <shards>`.

## 2. Monitor to green

The helper finds the new run id and `gh run watch --exit-status`es it.

- **scout** — one `scout` job; watch it to completion.
- **sweep** — the run fans out `prep` -> `sweep` (shard matrix) -> `merge`. Watch
  the WHOLE run; the `merge` job (`if: always()`) folds the shard JSONLs into the
  master index and `_historical.json`, so the report is only valid AFTER `merge`
  finishes. A single shard aborting on a host-challenge is EXPECTED fail-soft (the
  matrix is `fail-fast: false`); the other shards and the merge still complete.
- **One retry, then stop.** On a single-shard host-abort, re-dispatch ONCE on a
  fresh runner (new IP usually clears the challenge), then move on. NEVER loop.

## 3. Pull the bot-committed result

The scout / each shard / the merge commit to `main` as `napa-archive-bot`
(`chore(discover): ... [skip ci]`). Sync the local checkout:

```
git pull --ff-only
```

For a `check`/`report` (no dispatch), find the latest run first:
`gh run list --repo MrCyberFreak/NAPA --workflow=discover.yml --limit 10 --json databaseId,conclusion,event,createdAt,updatedAt,displayTitle`,
note its conclusion, then `git pull --ff-only` and read the committed JSON below.

## 4. Read the index + the onboarding inbox

- `data/raw/_historical.json` — the ONBOARDING INBOX (report-only). Shape:
  `{"updated_utc", "run_date", "count", "historical": {"<did>": {"slug", "name",
  "location", "successor", "first_seen_date", "onboarded": false}}}`. Each entry
  is a NoCo session the sweep resolved that is NOT already curated in
  `config.DIVISIONS`; `successor` is the highest curated did sharing the slug (the
  live session). These are NEVER auto-scraped — a human onboards them.
- `data/raw/_division_index.json` — every probed did. Shape: `{"updated_utc",
  "run_date", "count", "noco_count", "divisions": {"<did>": {"did", "name",
  "slug", "location", "is_noco", "resolved", "first_seen_date"}}}`. Use it for the
  totals (`count` probed, `noco_count` NoCo) and unresolved gaps (`resolved:false`
  / empty `slug` = a did that returned no parseable division — a gap, not a hit).

## 5. Report — then STOP

Report and hand off:

- New historical NoCo sessions found, GROUPED BY SLUG (a slug with >1 did is a
  multi-session league lineage — the whole point of the sweep): did, name,
  location, `first_seen_date`, and `successor` (the live curated session).
- Coverage: `count` probed, `noco_count`, and any unresolved-gap dids worth a
  re-probe at a tighter range.
- The run id / conclusion, and whether any shard aborted on the host-challenge
  (and was retried once).

Then STOP for the user to decide onboarding. Do NOT flip a `scrape` flag, do NOT
onboard, do NOT rebuild. Recommend the hand-off:

```
# Onboard a discovered did (separate skill — NOT run here):
#   napa-onboard-division  <did>
```

## Out of scope

- Onboarding a discovered did, editing `config.DIVISIONS`, flipping a `scrape`
  flag → `napa-onboard-division`.
- Running `python -m src.db --rebuild`.
- The profile-harvest / score-sheet backfill densification sweep over
  already-onboarded dids → `napa-harvest-sweep`.
- Scrape-cron health verdicts → `napa-scrape-health`.
- URL-tree Phases 2–4.
