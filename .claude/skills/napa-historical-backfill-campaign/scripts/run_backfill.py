"""Historical-backfill capture driver: LOCAL, SERIAL, single browser context.

Loops the UNCAPTURED discovered-historical NoCo divisions (dids) and captures
THREE page-types per did, resumably (skips anything already on disk):

  1. SCORE SHEETS  -> data/raw/<did>/scores/*.html
       via src.browser_fetch.backfill_score_sheets("auto", did=N, headless=True).
       Already resumable + has its own first-goto hard-retry (browser_fetch.py).
  2. roster_grid   -> data/raw/<did>/<date>/roster_grid.html   (historical CSR source)
       clean URL, clears in ~1 req.
  3. schedule      -> data/raw/<did>/<date>/schedule.html       (season-key / match link)
       print_schedule_v1.php is VERIFIED-FLAKY: the print endpoint slow-walks and the
       goto TIMES OUT on cold first hits (probe: landed on attempt 5 of 8). We mirror
       the backfill cleared() hard-retry (wait_until="commit"/"domcontentloaded",
       ~45s timeout, up to 8 attempts) AFTER warming the host with the roster_grid
       goto in the SAME context (challenge cookie persists), and bound week_number so
       we never assume 27 weeks (the page returns the full schedule regardless).

SAFETY — why this script exists and what it must NEVER do:
  - This campaign runs LOCALLY on the residential IP (a datacenter IP cannot cold-start
    the JS bot-challenge). It is SERIAL, single-browser-context BY RULE (CLAUDE.md host
    rule: never hammer the host; an uncleared challenge aborts host-wide).
  - It MUST NEVER dispatch ANY GitHub Actions workflow and MUST NOT be a detached bash
    loop. An earlier incident — a detached bash driver that survived TaskStop and kept
    dispatching Actions for ~7.5h (~11 failed runs, real billing) past a stop — is the
    whole reason for the no-Actions rule. There is NO gh / Actions call anywhere here.

Usage (run by the Scheduled Task via run_backfill.bat, or directly):
  python run_backfill.py                 # default = computed uncaptured set
  python run_backfill.py 11396 11441     # explicit did list
"""
import datetime as dt
import json
import os
import sys
from pathlib import Path

# Repo root is this file's great-great-grandparent:
#   <repo>/.claude/skills/napa-historical-backfill-campaign/scripts/run_backfill.py
_HERE = os.path.dirname(os.path.abspath(__file__))
REPO_ROOT = os.path.abspath(os.path.join(_HERE, "..", "..", "..", ".."))
sys.path.insert(0, REPO_ROOT)
os.chdir(REPO_ROOT)

from src import config, fetch
from src.browser_fetch import _browser_page, backfill_score_sheets

HISTORICAL_JSON = Path("data/raw/_historical.json")
# print_schedule_v1.php returns the FULL schedule regardless of a modest weekNumber;
# the probe used 18 and got all 27 rounds. Bounded so we never assume 27 weeks.
SCHEDULE_WEEK_NUMBER = 18
SCHED_ATTEMPTS = 8       # the print endpoint slow-walks: hard-retry the whole goto
SCHED_TIMEOUT_MS = 45000


def historical_dids() -> list[str]:
    """All discovered-historical dids (keys of _historical.json -> 'historical')."""
    data = json.loads(HISTORICAL_JSON.read_text(encoding="utf-8"))
    return list(data["historical"].keys())


def is_captured(did: str) -> bool:
    """A did is 'captured' only when ALL THREE page-types are on disk: score
    sheets AND roster_grid AND schedule. Keying on the score dir alone would
    EXCLUDE the dids captured by the score-sheet-only campaign (they have
    scores/ but no roster_grid/schedule yet) — exactly the dids this coupled
    pass exists to backfill. Mirrors status.sh's all-3 definition. Each leg is
    itself resumable (skip-on-disk), so a did drops out once fully captured."""
    root = config.division_root(int(did))
    has_scores = (root / "scores").is_dir() and any((root / "scores").glob("*.html"))
    has_roster = any(root.glob("*/roster_grid.html"))
    has_schedule = any(root.glob("*/schedule.html"))
    return has_scores and has_roster and has_schedule


def uncaptured_dids() -> list[str]:
    return [d for d in historical_dids() if not is_captured(d)]


def _cleared(page, url: str, attempts: int, timeout_ms: int) -> str:
    """Navigate + clear the JS challenge, hard-retrying the WHOLE goto up to
    `attempts` times. Mirrors browser_fetch.backfill_score_sheets.cleared() — the
    print_schedule endpoint can TIME OUT on a cold goto while the host slow-walks
    the interstitial; retrying the goto (not just polling content) is what lands it."""
    for attempt in range(1, attempts + 1):
        try:
            page.goto(url, wait_until="domcontentloaded", timeout=timeout_ms)
        except Exception as exc:  # noqa: BLE001 — slow challenge / transient nav; retry
            print(f"    nav {url}: {exc} (retry {attempt}/{attempts})", flush=True)
            continue
        for _ in range(6):
            html = page.content()
            if not fetch.is_challenge(html):
                return html
            page.wait_for_timeout(6000)
    return ""  # every attempt failed or stayed challenged


def _capture_page(page, name: str, did: int, date: str, **url_kw) -> bool:
    """Capture one clean page (roster_grid / schedule) into data/raw/<did>/<date>/.
    Skip-on-disk (resumable). Returns True if a (non-empty, non-challenge) file is
    present on disk after the call."""
    out = config.division_root(did) / date / f"{name}.html"
    # Resume: a prior dated capture for this did already on disk counts as done.
    existing = sorted(config.division_root(did).glob(f"*/{name}.html"))
    if existing:
        print(f"    {name}: already on disk ({existing[-1]}) — skip", flush=True)
        return True
    attempts = SCHED_ATTEMPTS if name == "schedule" else 4
    timeout = SCHED_TIMEOUT_MS if name == "schedule" else 30000
    html = _cleared(page, config.url(name, did=did, **url_kw), attempts, timeout)
    if not html or fetch.is_challenge(html):
        print(f"    {name}: NOT captured (uncleared/empty) — leaving for resume", flush=True)
        return False
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(html, encoding="utf-8")
    print(f"    {name}: wrote {out} ({len(html)} bytes)", flush=True)
    return True


def capture_did(did: str, headless: bool = True) -> None:
    """Capture all 3 page-types for one historical did in ONE browser context.
    roster_grid first (warms the host / lands the challenge cookie), then the
    flaky schedule print page, then the score-sheet backfill (own retry loop)."""
    n = int(did)
    date = dt.date.today().isoformat()
    print(f"=== did {did}: capture (roster_grid, schedule, score sheets) ===", flush=True)

    # 1+2: roster_grid then schedule, sharing one context so the challenge cookie
    #      persists (roster_grid warms the host for the slow schedule print page).
    with _browser_page(headless) as page:
        _capture_page(page, "roster_grid", n, date)
        _capture_page(page, "schedule", n, date, week_number=SCHEDULE_WEEK_NUMBER)

    # 3: score sheets — reuse the production backfill (auto-stops after 2 empty
    #    weeks; resumable; has its own first-goto hard-retry).
    sheets = backfill_score_sheets("auto", did=n, headless=headless)
    print(f"    score sheets: {len(sheets)} new sheet(s) for did {did}", flush=True)


def main(argv: list[str]) -> int:
    requested = argv[1:]
    if requested:
        dids = requested
        print(f"[historical-backfill] explicit dids: {' '.join(dids)}", flush=True)
    else:
        dids = uncaptured_dids()
        total = len(historical_dids())
        print(f"[historical-backfill] {total - len(dids)}/{total} dids already captured; "
              f"{len(dids)} remaining: {' '.join(dids)}", flush=True)

    if not dids:
        print("[historical-backfill] nothing to capture — all historical dids done.",
              flush=True)
        return 0

    failed: list[str] = []
    for did in dids:
        try:
            capture_did(did)
        except Exception as exc:  # noqa: BLE001 — one bad did must not abort the rest
            print(f"!!! did {did}: capture FAILED ({type(exc).__name__}: {exc}) — "
                  f"continuing with the next did", flush=True)
            failed.append(did)
    if failed:
        print(f"[historical-backfill] done with {len(failed)} did(s) failed "
              f"(left for resume): {' '.join(failed)}", flush=True)
    else:
        print("[historical-backfill] capture loop complete (no per-did failures).",
              flush=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv))
