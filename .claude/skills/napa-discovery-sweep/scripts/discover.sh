#!/usr/bin/env bash
# NAPA division-ID discovery sweep - dispatch .github/workflows/discover.yml, find
# the new run id, watch it (sweep: incl. the dependent merge job) to completion,
# then git pull the bot-committed index. DISCOVERY ONLY: never onboards, never
# flips a scrape flag, never rebuilds (that is napa-onboard-division's job).
#
# Discipline (CLAUDE.md hard rules - do NOT soften):
#   * a sweep is heavier than the daily scrape and outward-facing (shards x
#     thousands of requests) - run sparingly, off-hours.
#   * an uncleared bot-challenge aborts ONLY that shard (matrix fail-fast:false),
#     never the whole sweep. Re-dispatch ONCE on a fresh runner; NEVER loop.
#   * workflow_dispatch only fires from the default branch (main) - verified below.
#
# Usage:
#   scripts/discover.sh scout                       # default
#   scripts/discover.sh sweep [high] [low] [shards] # defaults 14050 12000 4
#   scripts/discover.sh check                        # inspect latest run, NO dispatch
set -u

REPO_DIR="X:/Claude_Code/Projectes/Billiards/NAPA"
WF=".github/workflows/discover.yml"
WF_NAME="discover.yml"
cd "$REPO_DIR" || { echo "cannot cd $REPO_DIR" >&2; exit 1; }

MODE="${1:-scout}"
case "$MODE" in
  -h|--help) grep '^#' "$0" | sed 's/^# \{0,1\}//'; exit 0 ;;
  scout) : ;;
  sweep) HIGH="${2:-14050}"; LOW="${3:-12000}"; SHARDS="${4:-4}" ;;
  check|report) MODE="check" ;;
  *) echo "mode must be scout | sweep | check" >&2; exit 2 ;;
esac

# --- check/report: inspect the latest run, NO dispatch -----------------------
if [ "$MODE" = "check" ]; then
  echo "=== latest discover.yml runs ==="
  gh run list --workflow="$WF_NAME" --limit 5 \
    --json databaseId,conclusion,status,event,createdAt,displayTitle \
    -q '.[] | "\(.databaseId)  \(.status)/\(.conclusion)  \(.event)  \(.createdAt)  \(.displayTitle)"' \
    2>/dev/null || echo "(gh run list failed)"
  echo ""
  echo "=== git pull (bot-committed index) ==="
  git pull --ff-only 2>&1 | tail -3
  echo ""
  echo "Now read: data/raw/_historical.json (onboarding inbox)"
  echo "          data/raw/_division_index.json (count / noco_count / gaps)"
  exit 0
fi

# --- default-branch gate: workflow_dispatch only fires from main -------------
if ! git ls-tree main --name-only .github/workflows/ 2>/dev/null | grep -q 'discover.yml'; then
  echo "REFUSING: discover.yml is not on the default branch (main); workflow_dispatch will not fire." >&2
  exit 2
fi

# --- dispatch args -----------------------------------------------------------
if [ "$MODE" = "scout" ]; then
  DISPATCH_ARGS=(-f mode=scout)
  LABEL="scout"
else
  DISPATCH_ARGS=(-f mode=sweep -f high="$HIGH" -f low="$LOW" -f shards="$SHARDS")
  LABEL="sweep $HIGH..$LOW /$SHARDS shards"
fi

log(){ echo "[$(date -u +%FT%TZ)] $*"; }

# Dispatch, find the NEW run id, watch to completion. Echoes the run id on stdout
# (last line); returns the run's exit status.
dispatch_watch(){
  local base rid="" i
  base=$(gh run list --workflow="$WF_NAME" --limit 1 --json databaseId -q '.[0].databaseId' 2>/dev/null)
  gh workflow run "$WF" "${DISPATCH_ARGS[@]}" >/dev/null 2>&1 || { log "dispatch failed"; return 1; }
  log "dispatched: $LABEL"
  for i in $(seq 1 40); do
    rid=$(gh run list --workflow="$WF_NAME" --limit 1 --json databaseId -q '.[0].databaseId' 2>/dev/null)
    [ -n "$rid" ] && [ "$rid" != "$base" ] && break
    sleep 3
  done
  if [ -z "$rid" ] || [ "$rid" = "$base" ]; then log "NO NEW RUN appeared"; return 1; fi
  log "run $rid - watching to completion (sweep: incl. the dependent merge job)"
  if gh run watch "$rid" --exit-status >/dev/null 2>&1; then
    log "run $rid: SUCCESS"; echo "$rid"; return 0
  fi
  log "run $rid: FAILED/ABORTED"; echo "$rid"; return 1
}

log "=== DISCOVER START ($LABEL) ==="
if RID=$(dispatch_watch); then
  RID=$(echo "$RID" | tail -1)
  STATUS="SUCCESS"
else
  RID=$(echo "$RID" | tail -1)
  STATUS="FAILED/ABORTED"
  log "On a SINGLE-shard host-abort, re-dispatch this ONCE on a fresh runner, then STOP. Never loop."
fi

log "=== DISCOVER DONE (run ${RID:-?}: $STATUS) - git pull ==="
git pull --ff-only 2>&1 | tail -3

echo ""
echo "Run ${RID:-?}: $STATUS"
echo "Now read for the report:"
echo "  data/raw/_historical.json    # onboarding inbox: NoCo sessions found, grouped by slug"
echo "  data/raw/_division_index.json # count / noco_count probed; resolved:false = gaps"
echo ""
echo "Then STOP. Onboarding a discovered did is napa-onboard-division (NOT run here)."
[ "$STATUS" = "SUCCESS" ] || exit 1
