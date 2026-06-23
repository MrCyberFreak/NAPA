"""Single source of truth for the divisions and their URL patterns.

All 14 NAPA of Northern Colorado divisions (plus 14050 and 14064, the
season-rollovers of 13077 and 13205) live in the DIVISIONS registry; flipping a
division's `scrape` flag is the one-line per-division activation.
`DID = 13077` stays the app-wide default so every existing call site keys on
one config value — retargeting is still a one-line change.
"""

from __future__ import annotations

import datetime as dt
import json
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
    slug: str       # stable LOGICAL-league key (weekday-venue-gameset); survives
                    # did rollovers — a league's session-ids SHARE one slug, so it
                    # also groups the archive (data/raw/<slug>/<did>/). The gameset
                    # token is load-bearing: it's the only thing keeping the three
                    # shared-venue LC/8-ball division pairs from colliding.
    scrape: bool = False


# The 14 NoCo divisions plus 14050 and 14064 (the season-rollovers of 13077 and
# 13205). Rollout is COMPLETE -- every entry is scrape=True; set a division's
# `scrape` flag to activate it (see MULTIDIVISION_PLAN.md rollout).
DIVISIONS: dict[int, Division] = {
    d.did: d
    for d in (
        Division(13077, "Thursday Big Table Felt, No Limit LC", "Thursday", "LC", "thursday-big-table-felt-lc", scrape=True),
        Division(13985, "Felt Laggers", "Tuesday", "LC", "tuesday-felt-laggers-lc", scrape=True),
        Division(14022, "Paradise", "Wednesday", "LC", "wednesday-paradise-lc", scrape=True),
        Division(13986, "Zoosters Laggers", "Tuesday", "LC", "tuesday-zoosters-laggers-lc", scrape=True),
        Division(13937, "Pharaoh's", "Wednesday", "LC", "wednesday-pharaohs-lc", scrape=True),
        Division(13881, "Broomfield Westminster Laggers", "Monday", "LC", "monday-broomfield-westminster-laggers-lc", scrape=True),
        Division(13711, "Wreckroom Sunday", "Sunday", "LC", "sunday-wreckroom-sunday-lc", scrape=True),
        Division(13299, "Piazzas Tuesday", "Tuesday", "LC", "tuesday-piazzas-tuesday-lc", scrape=True),
        Division(13205, "Greeley", "Monday", "LC", "monday-greeley-lc", scrape=True),
        Division(13744, "DP Broomfield Westminster LC", "Friday", "LC", "friday-dp-broomfield-westminster-lc", scrape=True),
        Division(13723, "Piazza Friday DP LC", "Friday", "LC", "friday-piazza-friday-dp-lc", scrape=True),
        Division(13743, "DP Broomfield Westminster 8-ball", "Friday", "8", "friday-dp-broomfield-westminster-8ball", scrape=True),
        Division(13722, "Piazza Friday DP 8-ball", "Friday", "8", "friday-piazza-friday-dp-8ball", scrape=True),
        Division(13298, "Piazzas Tuesday 8-ball", "Tuesday", "8", "tuesday-piazzas-tuesday-8ball", scrape=True),
        # Season-rollover entry: 14050 is the NEW session of 13077 (NAPA mints a
        # new did per session; this is the first rollover the multi-division
        # foundation has hit). KEEP 13077 — it still has an R27 makeup pending
        # 2026-07-09 and holds the 2025-26 season history. Switch the app-default
        # DID (above) from 13077 to 14050 only AFTER 13077 fully closes. R1 = the
        # division's first night, 2026-06-18 (the divisions.season key). It SHARES
        # 13077's slug — same logical league, two session-ids — so both nest under
        # data/raw/thursday-big-table-felt-lc/ once the archive is slug-grouped.
        Division(14050, "Thursday Big Table Felt, No Limit LC (R1 2026-06-18)", "Thursday", "LC", "thursday-big-table-felt-lc", scrape=True),
        # Season-rollover entry: 14064 is the NEW session of 13205 (Greeley
        # Monday LC), discovered 2026-06-22. KEEP 13205 -- it holds the prior
        # session's history (and any pending makeups). 14064 SHARES 13205's slug
        # (monday-greeley-lc) -- same logical league, two session-ids -- so both
        # nest under data/raw/monday-greeley-lc/ once the archive is slug-grouped.
        # R1 = 2026-06-22 (the division's first night; the divisions.season key).
        Division(14064, "Greeley (R1 2026-06-22)", "Monday", "LC", "monday-greeley-lc", scrape=True),
    )
}


# --------------------------------------------------------------------------- #
# Two-source registry: curated DIVISIONS (above) MERGED at runtime with the
# discovered-rollover overlay below. NAPA mints a new did per season; the daily
# states.php discovery job records rollovers into _registry.json, and
# divisions() folds the active ones in WITHOUT a config edit. Curated always
# wins (it is the tested, graduated truth); the overlay only ADDS rollover dids.
# --------------------------------------------------------------------------- #

# Discovered-rollover overlay, written by the discovery job (like _catchup.json).
REGISTRY_PATH = pathlib.Path("data/raw") / "_registry.json"


def _load_registry_overlay() -> dict[str, dict]:
    """The overlay's "discovered" block (str(did) -> entry). Missing or
    unreadable => empty: the overlay only ADDS rollover dids, never a
    correctness dependency — curated DIVISIONS stands alone."""
    try:
        data = json.loads(REGISTRY_PATH.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return {}
    disc = data.get("discovered", {})
    return disc if isinstance(disc, dict) else {}


# Discovered-historical inbox: older sessions recovered by the division-ID sweep
# (src/division_index.py -> data/raw/_historical.json). Report-only for onboarding,
# but folded into divisions() as scrape=False so (a) the rebuild can LOAD a captured
# historical session's archive and (b) url() builds correct, weekday-bearing URLs
# for it. NEVER scraped by the cron (active_dids filters scrape=True).
HISTORICAL_PATH = pathlib.Path("data/raw") / "_historical.json"

_WEEKDAYS = ("Monday", "Tuesday", "Wednesday", "Thursday", "Friday", "Saturday", "Sunday")


def _weekday_from_slug(slug: str) -> str:
    """A slug is '<weekday>-<venue>-<gameset>'; the first token is the league
    night. Falls back to WEEK_DAY when the head isn't a weekday."""
    head = slug.split("-", 1)[0].capitalize() if slug else ""
    return head if head in _WEEKDAYS else WEEK_DAY


def _fmt_from_slug(slug: str) -> str:
    """Display-only format from the slug's gameset suffix. The roster-grid header
    is the AUTHORITATIVE game set (see roster.py); this is cosmetic only."""
    if slug.endswith("-8ball"):
        return "8"
    if slug.endswith("-9ball"):
        return "9"
    return "LC"


def _load_historical() -> dict[str, dict]:
    """The historical inbox's per-did entries (str(did) -> entry). Missing or
    unreadable => empty: historical loading is best-effort, never a correctness
    dependency."""
    try:
        data = json.loads(HISTORICAL_PATH.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return {}
    hist = data.get("historical", {})
    return hist if isinstance(hist, dict) else {}


def divisions() -> dict[int, Division]:
    """Curated DIVISIONS merged with the discovered-rollover overlay — THE
    accessor every active-set reader routes through.

    Curated entries always win. A discovered overlay did that is NOT curated is
    synthesized from its recorded slug/weekday: status "active" => scrape=True
    (it joins the daily weekday sweep); any other status (e.g. a "rolled"
    predecessor still owed makeups) => scrape=False — present, so
    catchup.run_set can still carry it, but excluded from the sweep. A slugless
    overlay entry is malformed and skipped."""
    merged = dict(DIVISIONS)
    for did_str, e in _load_registry_overlay().items():
        try:
            did = int(did_str)
        except (TypeError, ValueError):
            continue
        if did in merged or not e.get("slug"):
            continue  # curated wins (graduated); slugless => malformed
        merged[did] = Division(
            did=did,
            name=e.get("name", f"discovered-{did}"),
            weekday=e.get("weekday", WEEK_DAY),
            fmt=e.get("fmt", "LC"),
            slug=e["slug"],
            scrape=(e.get("status") == "active"),
        )
    # Fold the discovered-historical inbox last (curated + active overlay win):
    # older sessions, NEVER scraped (scrape=False), weekday/fmt derived from slug.
    for did_str, e in _load_historical().items():
        try:
            did = int(did_str)
        except (TypeError, ValueError):
            continue
        slug = e.get("slug")
        if did in merged or not slug:
            continue
        merged[did] = Division(
            did=did,
            name=e.get("name", f"historical-{did}"),
            weekday=_weekday_from_slug(slug),
            fmt=_fmt_from_slug(slug),
            slug=slug,
            scrape=False,
        )
    return merged


def active_dids() -> list[int]:
    """Dids flagged scrape=True (curated + any discovered-active rollover), in
    registry order."""
    return [did for did, d in divisions().items() if d.scrape]


# League nights run Sun–Fri across the NoCo divisions (no division plays
# Saturday). `weekday` strings match datetime.strftime("%A") verbatim, which is
# what divisions_due() keys on — keep them spelled "Monday".."Sunday".
def divisions_playing_on(weekday: str, active_only: bool = True) -> list[int]:
    """Dids whose league night is `weekday` ("Monday".."Sunday"), registry
    order. active_only restricts to scrape=True (the daily run never touches a
    not-yet-onboarded division)."""
    return [did for did, d in divisions().items()
            if d.weekday == weekday and (not active_only or d.scrape)]


def divisions_due(run_date: dt.date, active_only: bool = True) -> list[int]:
    """Day-after-play capture set: the divisions whose league night was the day
    BEFORE run_date — their results have just posted. The scheduled scrape runs
    once each morning (America/Denver) and pulls only these, instead of
    re-sweeping all 14 divisions twice a day. `run_date` is the LOCAL date of
    the run; caller is responsible for passing the Denver-local date (see
    browser_fetch scheduled mode). Carryover from the catch-up queue is added
    ON TOP of this set, so a missed or makeup-bearing division is still pulled
    even when it didn't play last night (see src/catchup.py)."""
    yesterday = (run_date - dt.timedelta(days=1)).strftime("%A")
    return divisions_playing_on(yesterday, active_only=active_only)


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
    # Weekday for the schedule URL: curated first (the common, cheap path), then
    # the merged overlay for a discovered rollover did, else the module default.
    if "week_day" in kw:
        week_day = kw["week_day"]
    elif did in DIVISIONS:
        week_day = DIVISIONS[did].weekday
    else:
        _divs = divisions()
        week_day = _divs[did].weekday if did in _divs else WEEK_DAY

    templates = {
        # Easy tier (paper.playpool.io)
        "roster_grid": f"{HOST_PAPER}/roster_grid.php?did={did}&lcF8=N",
        "schedule": (
            f"{HOST_PAPER}/print_schedule_v1.php?did={did}&divID={did}"
            f"&weekNumber={week_number}&weekDay={week_day}"
        ),
        "scratch": f"{HOST_PAPER}/scratch.php?division={did}&mastersDivision=N&mastersRace=",
        # Medium tier (poolshooters.com static)
        # League-discovery page (did-independent): lists every active division
        # grouped by franchise — how we notice a season rollover / new league.
        "states": f"{HOST_POOLSHOOTERS}/states.php?location=Colorado",
        "division": f"{HOST_POOLSHOOTERS}/division.php?did={did}",
        "leaderboard": f"{HOST_POOLSHOOTERS}/division.php?did={did}&view=leader&ver=detailed",
        "achievements": f"{HOST_POOLSHOOTERS}/division.php?did={did}&view=ach",
        # Individual point standings (the division race) — updates weekly and the
        # host OVERWRITES it (no historical-flex URL), so capture starts the drift
        # record only from now on. write_on_change drift-logs it for free.
        "flex": f"{HOST_POOLSHOOTERS}/division.php?did={did}&view=flex",
        "weekly_scores": f"{HOST_POOLSHOOTERS}/standings_weekly_scores.php?did={did}&week={week}",
        # Live per-game scoring data endpoint (the games grain).
        "live_scores": f"{HOST_SCORES}/getlivescore.php?divID={did}&makeup=",
        # Hard tier (poolshooters.com profile deep tabs) — JS/AJAX loaded, Phase 6
        "profile": f"{HOST_POOLSHOOTERS}/stats.php?playerID={player_id}",
        # Live scoreboard (not needed for read-only)
        "livescores": f"{HOST_SCORES}/livescores.php?divID={did}",
    }
    return templates[name]
