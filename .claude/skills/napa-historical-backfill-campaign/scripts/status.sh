#!/usr/bin/env bash
# status.sh -- READ-ONLY status of the NAPA historical-backfill campaign.
#
# Reports, per discovered-historical did: scores/ + roster_grid + schedule captured?
# captured-vs-remaining (n/42), live? (files written in last 5 min), and the
# CRITICAL safety line: NO GitHub Actions exposure (all 6 workflows still
# disabled_manually AND no recent workflow_dispatch). Never mutates anything.
#
# Usage (from anywhere): bash .claude/skills/napa-historical-backfill-campaign/scripts/status.sh
set -u
HERE="$(cd "$(dirname "$0")" && pwd)"
REPO_ROOT="$(cd "$HERE/../../../.." && pwd)"   # <repo>/.claude/skills/<name>/scripts -> <repo>
cd "$REPO_ROOT"

HIST=data/raw/_historical.json
echo "=== NAPA historical-backfill status $(date -u) ==="

# --- Per-did capture matrix -------------------------------------------------
dids=$(python -c "import json;print(' '.join(json.load(open('$HIST'))['historical']))" 2>/dev/null)
total=0; full=0; remaining=""
for did in $dids; do
  total=$((total+1))
  s=0; r=0; c=0
  [ -d "data/raw/$did/scores" ] && [ -n "$(ls data/raw/$did/scores 2>/dev/null)" ] && s=1
  ls data/raw/$did/*/roster_grid.html >/dev/null 2>&1 && r=1
  ls data/raw/$did/*/schedule.html    >/dev/null 2>&1 && c=1
  if [ "$s$r$c" = "111" ]; then
    full=$((full+1))
  else
    remaining="$remaining $did"
    printf "  did %-7s scores=%s roster=%s schedule=%s\n" "$did" "$s" "$r" "$c"
  fi
done
echo "captured (all 3): $full/$total dids"
echo "remaining (queue):$remaining"

# --- Scheduled task state ---------------------------------------------------
echo "--- task NAPA_HistoricalBackfill ---"
schtasks /query /tn NAPA_HistoricalBackfill 2>/dev/null | tail -1 || \
  echo "  (task not registered -- not currently a campaign)"

# --- Live? (still writing in the last 5 min) --------------------------------
live=$(find data/raw -mmin -5 \( -name 'score_*.html' -o -name 'roster_grid.html' \
        -o -name 'schedule.html' -o -path '*/scores/*.html' \) 2>/dev/null | wc -l)
echo "live? (files written in last 5 min): $live"

# --- CRITICAL SAFETY: no GitHub Actions exposure ----------------------------
echo "--- SAFETY: GitHub Actions exposure ---"
if command -v gh >/dev/null 2>&1; then
  # Exclude GitHub's built-in "Dependency Graph" workflow: it is legitimately
  # `active`, is NOT one of our 6 NAPA workflows, and consumes no Actions minutes.
  # Counting it tripped a FALSE "ACTIONS EXPOSURE" alarm on every status check.
  enabled=$(gh workflow list --all 2>/dev/null | grep -iv 'Dependency Graph' | grep -ciE '\bactive\b' || true)
  disabled=$(gh workflow list --all 2>/dev/null | grep -ci 'disabled_manually' || true)
  echo "  workflows: $disabled disabled_manually, $enabled active (expect 0 active / 6 disabled)"
  recent=$(gh run list --limit 10 --json event,createdAt,workflowName 2>/dev/null \
            | python -c "import sys,json,datetime as dt; rows=json.load(sys.stdin); cut=dt.datetime.now(dt.timezone.utc)-dt.timedelta(minutes=15); n=[r for r in rows if r['event']=='workflow_dispatch' and dt.datetime.fromisoformat(r['createdAt'].replace('Z','+00:00'))>cut]; print(len(n))" 2>/dev/null || echo "?")
  echo "  new workflow_dispatch in last 15 min: $recent (expect 0)"
  if [ "$enabled" != "0" ] || [ "$recent" != "0" ]; then
    echo "  !!! ACTIONS EXPOSURE -- a workflow is enabled or a dispatch fired. This campaign must NEVER coincide with Actions."
  else
    echo "  OK: no Actions exposure."
  fi
else
  echo "  WARNING: gh not found -- cannot confirm no Actions exposure."
fi

# --- Verdict ----------------------------------------------------------------
[ "$live" -gt 0 ] && lv=yes || lv=no
echo "VERDICT: $full/$total captured | remaining$remaining | live? $lv"
