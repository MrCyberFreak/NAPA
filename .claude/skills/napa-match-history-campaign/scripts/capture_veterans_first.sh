#!/usr/bin/env bash
# Veterans-first match-history campaign wrapper.
# Promoted from handoffs/capture_veterans_first.sh (untracked scratch). Behavior
# unchanged; it now invokes the driver that lives beside it in scripts/.
#
# The harvester is single-context, resumable (skips pages >500B on disk), and
# returns even after a mid-run challenge-abort — so completion is gated on TWO
# consecutive runs that add no new pages (rides out a transient cold-start stall),
# NOT on exit code. The log line "COMPLETE: ... no new pages" is the done signal.
#
# Optional arg: VET threshold (lifetime_played cutoff for the veterans tier),
# forwarded to the driver; default 200.
set -u

HERE="$(cd "$(dirname "$0")" && pwd)"
REPO_ROOT="$(cd "$HERE/../../../.." && pwd)"   # <repo>/.claude/skills/<name>/scripts -> <repo>
cd "$REPO_ROOT"

VET="${1:-200}"
DRIVER="$HERE/capture_veterans_first.py"
LOG=handoffs/veterans_first.log
mkdir -p handoffs

count() { ls data/raw/profiles/*/match_*.html 2>/dev/null | wc -l; }
echo "=== veterans-first campaign START $(date -u) (VET=$VET) ===" | tee -a "$LOG"
dry=0
for attempt in $(seq 1 30); do
  before=$(count)
  echo "--- attempt $attempt: $before pages on disk $(date -u) ---" | tee -a "$LOG"
  rm -f .git/index.lock 2>/dev/null
  CAPTURE_VET="$VET" python "$DRIVER" >>"$LOG" 2>&1; rc=$?
  after=$(count)
  echo "    -> $after pages (+$((after-before))), driver rc=$rc" | tee -a "$LOG"
  if [ "$rc" -ne 0 ]; then
    echo "    driver crashed (rc=$rc) — NOT complete; retry" | tee -a "$LOG"; dry=0
  elif [ "$after" -le "$before" ]; then
    dry=$((dry+1))
    [ "$dry" -ge 2 ] && { echo "=== COMPLETE: clean run, no new pages x2 ($after pages) $(date -u) ===" | tee -a "$LOG"; exit 0; }
  else
    dry=0
  fi
  sleep 30
done
echo "=== exhausted attempts ($(count) pages) $(date -u) ===" | tee -a "$LOG"
