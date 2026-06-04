"""Single source of truth for the division and its URL patterns.

Open decision #1 from the build plan: we don't yet know whether `did=13077`
persists across seasons. Keep it as ONE config value the whole system keys on,
so retargeting a new season is a one-line change.
"""

from __future__ import annotations

# The division everything keys on. Change this (and only this) to retarget.
DID = 13077

# Season runs ~27 weekly rounds (R1 = 2025-10-02, R27 = 2026-06-04).
SEASON = "2025-26"
SEASON_WEEKS = 27
WEEK_DAY = "Thursday"

# Default on-disk database (the app reads ONLY from here).
DB_PATH = "data/napa.db"

# Two hosts, different behavior (see plan "Ground truth").
HOST_PAPER = "https://paper.playpool.io"        # cooperative — plain fetch works
HOST_POOLSHOOTERS = "https://poolshooters.com"  # bot-blocked — needs residential IP
HOST_SCORES = "https://scores.playpool.io"      # scoring login — not needed read-only


def url(name: str, **kw) -> str:
    """Build a known URL for the configured division.

    `did` defaults to the configured DID; pass overrides as kwargs
    (e.g. week=5) for the templated endpoints.
    """
    did = kw.get("did", DID)
    week = kw.get("week")
    week_number = kw.get("week_number", SEASON_WEEKS)
    player_id = kw.get("player_id")

    templates = {
        # Easy tier (paper.playpool.io)
        "roster_grid": f"{HOST_PAPER}/roster_grid.php?did={did}&lcF8=N",
        "schedule": (
            f"{HOST_PAPER}/print_schedule_v1.php?did={did}&divID={did}"
            f"&weekNumber={week_number}&weekDay={WEEK_DAY}"
        ),
        "scratch": f"{HOST_PAPER}/scratch.php?division={did}&mastersDivision=N&mastersRace=",
        # Medium tier (poolshooters.com static)
        "division": f"{HOST_POOLSHOOTERS}/division.php?did={did}",
        "leaderboard": f"{HOST_POOLSHOOTERS}/division.php?did={did}&view=leader&ver=detailed",
        "achievements": f"{HOST_POOLSHOOTERS}/division.php?did={did}&view=ach",
        "weekly_scores": f"{HOST_POOLSHOOTERS}/standings_weekly_scores.php?did={did}&week={week}",
        # Hard tier (poolshooters.com profile deep tabs) — JS/AJAX loaded, Phase 6
        "profile": f"{HOST_POOLSHOOTERS}/stats.php?playerID={player_id}",
        # Live scoreboard (not needed for read-only)
        "livescores": f"{HOST_SCORES}/livescores.php?divID={did}",
    }
    return templates[name]
