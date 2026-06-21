#!/usr/bin/env bash
# NAPA harvest/backfill sweep - dispatch a GitHub Actions workflow across several
# ALREADY-ONBOARDED divisions STRICTLY one run at a time, host-friendly.
# Productionized from the session-scratch handoffs/sweep_driver.sh.
#
# Discipline (CLAUDE.md hard rules - do NOT soften):
#   * one run at a time. The workflows' concurrency groups (cancel-in-progress:
#     false) queue/cancel mass dispatches, and only one browser context should be
#     clearing the host bot-challenge at a time.
#   * validation gate: the FIRST division gates the sweep. If its run fails,
#     ABORT the whole sweep - never burn the rest on an escalated host.
#   * exactly ONE re-dispatch per division on a failed run, then move on. No loop.
#   * never mix harvest + backfill in one sweep (both hit poolshooters.com).
#
# Usage:
#   scripts/sweep.sh [--workflow harvest|backfill] [--drill 1] <did> [<did> ...]
#     --workflow  harvest (default) -> harvest-profiles.yml  -f did -f drill=<drill>
#                 backfill          -> backfill.yml          -f did -f weeks=auto
#     --drill     harvest only; 1 (default) = full per-rival record drill (the
#                 standard for densification); 0 = tabs-only. Must be 0 or 1.
set -u

REPO_DIR="X:/Claude_Code/Projectes/NAPA"
cd "$REPO_DIR" || { echo "cannot cd $REPO_DIR" >&2; exit 1; }

WORKFLOW="harvest"; DRILL="1"; DIDS=()
while [ $# -gt 0 ]; do
  case "$1" in
    --workflow) WORKFLOW="${2:-}"; shift 2 ;;
    --drill)    DRILL="${2:-}";    shift 2 ;;
    -h|--help)  grep '^#' "$0" | sed 's/^# \{0,1\}//'; exit 0 ;;
    --*)        echo "unknown flag: $1" >&2; exit 2 ;;
    *)          DIDS+=("$1");      shift ;;
  esac
done

[ "${#DIDS[@]}" -gt 0 ] || { echo "no division ids given" >&2; exit 2; }
case "$WORKFLOW" in
  harvest)  WF="harvest-profiles.yml" ;;
  backfill) WF="backfill.yml" ;;
  *) echo "--workflow must be harvest|backfill" >&2; exit 2 ;;
esac
if [ "$WORKFLOW" = "harvest" ] && [ "$DRILL" != "0" ] && [ "$DRILL" != "1" ]; then
  echo "REFUSING --drill=$DRILL: must be 1 (full per-rival drill, the standard) or 0 (tabs-only)." >&2
  exit 2
fi

# --- Preflight: every did must be onboarded (config.active_dids) -------------
# Onboarding a not-yet-active division is napa-onboard-division's job, not ours.
python - "${DIDS[@]}" <<'PY' || exit 2
import sys
from src import config
active = {str(d) for d in config.active_dids()}
bad = [d for d in sys.argv[1:] if d not in active]
if bad:
    sys.stderr.write(
        "REFUSING - not onboarded (not in config.active_dids; absent or "
        "scrape=False): " + ", ".join(bad) + "\n"
        "Onboard a new division with napa-onboard-division first.\n")
    raise SystemExit(1)
print("preflight ok - all onboarded:", ", ".join(sys.argv[1:]))
PY

LOG="handoffs/sweep.log"
mkdir -p handoffs
: > "$LOG"
log(){ echo "[$(date -u +%FT%TZ)] $*" | tee -a "$LOG"; }

# Workflow-specific dispatch args for one did.
wf_args(){
  if [ "$WORKFLOW" = "harvest" ]; then echo "-f did=$1 -f drill=$DRILL";
  else echo "-f did=$1 -f weeks=auto"; fi
}

# Dispatch the workflow for a did, find the new run id, watch to completion.
# Returns the run's exit status (0 = success).
dispatch_watch(){
  local did="$1" label="$2" base rid="" i
  base=$(gh run list --workflow="$WF" --limit 1 --json databaseId -q '.[0].databaseId' 2>/dev/null)
  # shellcheck disable=SC2046
  gh workflow run "$WF" $(wf_args "$did") >/dev/null 2>&1
  log "dispatched $label ($WF did=$did)"
  for i in $(seq 1 40); do
    rid=$(gh run list --workflow="$WF" --limit 1 --json databaseId -q '.[0].databaseId' 2>/dev/null)
    [ -n "$rid" ] && [ "$rid" != "$base" ] && break
    sleep 3
  done
  if [ -z "$rid" ] || [ "$rid" = "$base" ]; then log "$label: NO NEW RUN appeared"; return 1; fi
  log "$label: run $rid - watching"
  if gh run watch "$rid" --exit-status >/dev/null 2>&1; then log "$label: SUCCESS (run $rid)"; return 0; fi
  log "$label: FAILED/ABORTED (run $rid)"; return 1
}

declare -A RESULT
log "=== SWEEP START ($WORKFLOW; ${#DIDS[@]} division(s): ${DIDS[*]}) ==="

# Validation gate: the FIRST division. A failure here kills the whole sweep.
first="${DIDS[0]}"
if dispatch_watch "$first" "$WORKFLOW-$first"; then
  RESULT[$first]="SUCCESS"
else
  RESULT[$first]="ABORT(gate)"
  log "validation: FAILED on $first - aborting sweep (host likely escalated/auth)."
  log "=== SWEEP ABORTED ==="
  printf '  %-7s %s\n' "$first" "${RESULT[$first]}"
  exit 1
fi

# Remaining divisions, one at a time, exactly one retry each.
for did in "${DIDS[@]:1}"; do
  if dispatch_watch "$did" "$WORKFLOW-$did"; then
    RESULT[$did]="SUCCESS"
  else
    log "$WORKFLOW-$did: retrying ONCE on a fresh runner"
    if dispatch_watch "$did" "$WORKFLOW-$did-retry"; then
      RESULT[$did]="SUCCESS(retry)"
    else
      RESULT[$did]="ABORT - leave for cron/manual"
    fi
  fi
done

log "=== SWEEP COMPLETE - git pull ==="
git pull --ff-only 2>&1 | tail -3 | tee -a "$LOG"

echo ""
echo "=== sweep result ==="
for did in "${DIDS[@]}"; do printf '  %-7s %s\n' "$did" "${RESULT[$did]:-UNKNOWN}"; done
echo ""
echo "Next - coverage check, then the owed rebuild (NOT run here):"
echo "  python .claude/skills/napa-harvest-sweep/scripts/coverage_gap.py ${DIDS[*]}"
echo "  python -m src.db --rebuild   # ~25 min; loads new profiles into pairing_history"
