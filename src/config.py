"""Single source of truth for the divisions and their URL patterns.

All 14 NAPA of Northern Colorado divisions live in the DIVISIONS registry;
flipping a division's `scrape` flag is the one-line per-division activation.
`DID = 13077` stays the app-wide default so every existing call site keys on
one config value — retargeting is still a one-line change.
"""

from __future__ import annotations

import pathlib
from dataclasses import dataclass

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


@dataclass(frozen=True)
class Division:
    """One NoCo division. `weekday` must match print_schedule_v1.php's
    weekDay values verbatim ("Monday".."Sunday"). `fmt` ("LC" or "8") is
    DISPLAY-ONLY — the authoritative game set comes from the roster grid's
    CSR header at parse time (B1 recon: the "DP ... LC" divisions actually
    play 9/10-ball only; see data/raw/_recon/VERDICT.md)."""

    did: int
    name: str
    weekday: str
    fmt: str
    scrape: bool = False


# The 14 NoCo divisions. Only 13077 starts scrape=True — set a division's
# `scrape` flag to activate it (see MULTIDIVISION_PLAN.md rollout).
DIVISIONS: dict[int, Division] = {
    d.did: d
    for d in (
        Division(13077, "Thursday Big Table Felt, No Limit LC", "Thursday", "LC", scrape=True),
        Division(13985, "Felt Laggers", "Tuesday", "LC", scrape=True),
        Division(14022, "Paradise", "Wednesday", "LC", scrape=True),
        Division(13986, "Zoosters Laggers", "Tuesday", "LC", scrape=True),
        Division(13937, "Pharaoh's", "Wednesday", "LC", scrape=True),
        Division(13881, "Broomfield Westminster Laggers", "Monday", "LC", scrape=True),
        Division(13711, "Wreckroom Sunday", "Sunday", "LC", scrape=True),
        Division(13299, "Piazzas Tuesday", "Tuesday", "LC", scrape=True),
        Division(13205, "Greeley", "Monday", "LC", scrape=True),
        Division(13744, "DP Broomfield Westminster LC", "Friday", "LC", scrape=True),
        Division(13723, "Piazza Friday DP LC", "Friday", "LC", scrape=True),
        Division(13743, "DP Broomfield Westminster 8-ball", "Friday", "8", scrape=True),
        Division(13722, "Piazza Friday DP 8-ball", "Friday", "8"),
        Division(13298, "Piazzas Tuesday 8-ball", "Tuesday", "8", scrape=True),
    )
}


def active_dids() -> list[int]:
    """Dids flagged scrape=True, in registry order."""
    return [did for did, d in DIVISIONS.items() if d.scrape]


def division_root(did: int) -> pathlib.Path:
    """Per-division raw-archive root: data/raw/<did>."""
    return pathlib.Path("data/raw") / str(did)


def url(name: str, **kw) -> str:
    """Build a known URL for the configured division.

    `did` defaults to the configured DID; pass overrides as kwargs
    (e.g. week=5) for the templated endpoints. `week_day` defaults to
    the registry weekday for known dids (WEEK_DAY for unknown ones).
    """
    did = kw.get("did", DID)
    week = kw.get("week")
    week_number = kw.get("week_number", SEASON_WEEKS)
    player_id = kw.get("player_id")
    week_day = kw.get("week_day", DIVISIONS[did].weekday if did in DIVISIONS else WEEK_DAY)

    templates = {
        # Easy tier (paper.playpool.io)
        "roster_grid": f"{HOST_PAPER}/roster_grid.php?did={did}&lcF8=N",
        "schedule": (
            f"{HOST_PAPER}/print_schedule_v1.php?did={did}&divID={did}"
            f"&weekNumber={week_number}&weekDay={week_day}"
        ),
        "scratch": f"{HOST_PAPER}/scratch.php?division={did}&mastersDivision=N&mastersRace=",
        # Medium tier (poolshooters.com static)
        "division": f"{HOST_POOLSHOOTERS}/division.php?did={did}",
        "leaderboard": f"{HOST_POOLSHOOTERS}/division.php?did={did}&view=leader&ver=detailed",
        "achievements": f"{HOST_POOLSHOOTERS}/division.php?did={did}&view=ach",
        "weekly_scores": f"{HOST_POOLSHOOTERS}/standings_weekly_scores.php?did={did}&week={week}",
        # Live per-game scoring data endpoint (the games grain).
        "live_scores": f"{HOST_SCORES}/getlivescore.php?divID={did}&makeup=",
        # Hard tier (poolshooters.com profile deep tabs) — JS/AJAX loaded, Phase 6
        "profile": f"{HOST_POOLSHOOTERS}/stats.php?playerID={player_id}",
        # Live scoreboard (not needed for read-only)
        "livescores": f"{HOST_SCORES}/livescores.php?divID={did}",
    }
    return templates[name]
