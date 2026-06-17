"""Match-history capture driver: VETERANS FIRST, then division by division.

Promoted from handoffs/capture_veterans_first.py (was untracked session scratch,
re-derived 4+ times). Behavior is unchanged — only the repo-root resolution was
made location-independent so the script runs from the skill's scripts/ dir.

Ordering (the harvester is single-context + resumable, so re-runs skip done pages):
  Phase 1 - veterans league-wide: players with lifetime_played >= VET, richest
            first (most career matches = most history = most value for Phase 6).
  Phase 2 - the rest, division by division (registry order), richest-first within
            each division, until every rostered player is covered.

lifetime_played comes from player_form (career matches) — the right proxy for how
much match history a player has (SM is only the current season, max ~31).

VET threshold (default 200) can be overridden via argv[1] or env CAPTURE_VET, e.g.:
  python capture_veterans_first.py 150
  CAPTURE_VET=150 python capture_veterans_first.py
The capture is SERIAL single-browser-context BY RULE (CLAUDE.md host rule: never
hammer the host; an uncleared challenge aborts host-wide) and must run locally on
the residential IP. Never fan this out into parallel agents/contexts.
"""
import os
import sqlite3
import sys

# The repo root is this file's grandparent-of-grandparent:
#   <repo>/.claude/skills/napa-match-history-campaign/scripts/capture_veterans_first.py
# Resolve it explicitly (so `import src` works) and run relative paths from it.
_HERE = os.path.dirname(os.path.abspath(__file__))
REPO_ROOT = os.path.abspath(os.path.join(_HERE, "..", "..", "..", ".."))
sys.path.insert(0, REPO_ROOT)
os.chdir(REPO_ROOT)

from src import config
from src.browser_fetch import _roster_player_ids, harvest_match_history

# lifetime career matches => "veteran" / data-rich tier (~152 players at 200).
VET = int(os.environ.get("CAPTURE_VET") or (sys.argv[1] if len(sys.argv) > 1 else 200))

conn = sqlite3.connect("data/napa.db")
life = dict(conn.execute(
    "SELECT player_id, MAX(COALESCE(lifetime_played, 0)) FROM player_form GROUP BY player_id"))
conn.close()


def rank(pid: str) -> int:
    return life.get(pid, 0)


# roster membership per division, from the committed roster grids (capture-layer
# source — no dependency on the regenerable DB for the player SET, only for ranking)
div_players = {d: _roster_player_ids(d) for d in config.active_dids()}

ordered: list[str] = []
seen: set[str] = set()

# Phase 1 — veterans league-wide, richest first
for pid in sorted({p for ps in div_players.values() for p in ps}, key=rank, reverse=True):
    if pid not in seen and rank(pid) >= VET:
        seen.add(pid)
        ordered.append(pid)
n_vets = len(ordered)

# Phase 2 — division by division (registry order), richest-first within each
for d in config.active_dids():
    for pid in sorted(div_players[d], key=rank, reverse=True):
        if pid not in seen:
            seen.add(pid)
            ordered.append(pid)

# ALL tabs: league game types (same parser) + Tournaments + Local Duels (archived
# raw now, parsed by their own loader later). Pagination is generic per tab.
ALL_TABS = (2, 3, 4, "10BP", 777, 17, "9BP", "RR9", "RR10", 24, 25)

print(f"[veterans-first] {n_vets} veterans (lifetime>={VET}) then "
      f"{len(ordered) - n_vets} more by division = {len(ordered)} players ordered; "
      f"tabs={ALL_TABS}", flush=True)
harvest_match_history(player_ids=ordered, tabs=ALL_TABS, headless=True)
