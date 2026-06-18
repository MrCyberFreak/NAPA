"""Season-rollover discovery — reconcile states.php against the registry.

NAPA mints a NEW division-id every season. The daily scrape fetches the
league-discovery page (poolshooters.com/states.php), parses the NoCo rows
(src.parse.states), and this module reconciles them against the discovered
overlay (data/raw/_registry.json, the same file config.divisions() reads):

  - a states did already in curated config.DIVISIONS   -> tracked, no action
  - a NON-curated did whose SLUG matches a curated league
        -> ROLLOVER: record it active (folded into the scrape set), link its
           predecessor, and mark the predecessor "rolled" once it drops off the
           page (kept scraped via the catch-up queue while it owes makeups)
  - a NON-curated did with an UNKNOWN slug
        -> NEW LEAGUE: record under "unknown" for a report-only alert; a human
           onboards it one-at-a-time via napa-onboard-division (never auto-merged)

reconcile_registry is a PURE function (states rows + prior registry -> new
registry) so it is fully unit-testable; load/save mirror catchup.load_queue/
save_queue (best-effort JSON, never a correctness dependency).
"""

from __future__ import annotations

import datetime as dt
import json
from dataclasses import dataclass
from pathlib import Path

from . import config

# config owns the path (config.REGISTRY_PATH, the same file config.divisions()
# reads); discovery resolves it at call time so a test redirecting config's path
# steers both readers with one monkeypatch.


@dataclass(frozen=True)
class ReconcileResult:
    registry: dict                    # new payload: {"discovered": {...}, "unknown": {...}}
    newly_activated: tuple[int, ...]  # rollover dids that became active THIS run
    rollovers: dict                   # str(did) -> entry, active rollovers this run
    unknown: dict                     # str(did) -> entry, new leagues this run


def load_registry(path: Path | None = None) -> dict:
    """The full registry payload. A missing/unreadable file is an empty
    registry (the overlay only ever ADDS rollover dids — never a correctness
    dependency for the curated config)."""
    path = path or config.REGISTRY_PATH
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        data = {}
    data.setdefault("discovered", {})
    data.setdefault("unknown", {})
    return data


def save_registry(registry: dict, path: Path | None = None,
                  run_date: str | None = None) -> Path:
    """Write the registry, did-sorted for a stable diff (it is committed)."""
    path = path or config.REGISTRY_PATH
    path.parent.mkdir(parents=True, exist_ok=True)

    def _sorted(block: dict) -> dict:
        return dict(sorted(block.items(), key=lambda kv: int(kv[0])))

    payload = {
        "updated_utc": dt.datetime.now(dt.timezone.utc).isoformat(timespec="seconds"),
        "run_date": run_date,
        "discovered": _sorted(registry.get("discovered", {})),
        "unknown": _sorted(registry.get("unknown", {})),
    }
    path.write_text(json.dumps(payload, indent=2) + "\n", encoding="utf-8")
    return path


def reconcile_registry(rows, prev: dict, run_date: str) -> ReconcileResult:
    """Reconcile the parsed states.php NoCo rows against the prior registry.

    Pure: no I/O. `rows` are src.parse.states.StatesRow; `prev` is load_registry
    output. Idempotent — re-running on the same page yields the same registry
    with `newly_activated` empty and `since`/`first_seen`/`rolled_on` preserved.
    """
    slug_to_curated: dict[str, list[int]] = {}
    for did, d in config.DIVISIONS.items():
        slug_to_curated.setdefault(d.slug, []).append(did)

    prev_disc = prev.get("discovered", {})
    prev_unknown = prev.get("unknown", {})

    # Carry forward lineage history (rolled/closed) so a chain survives.
    discovered: dict[str, dict] = {
        sdid: dict(e) for sdid, e in prev_disc.items()
        if e.get("status") in ("rolled", "closed")
    }
    unknown: dict[str, dict] = {}
    rollovers: dict[str, dict] = {}
    newly: list[int] = []
    states_dids = {r.did for r in rows}

    for r in rows:
        sdid = str(r.did)
        if r.did in config.DIVISIONS:
            continue                                  # already curated/tracked
        if r.slug in slug_to_curated:                 # rollover of a tracked league
            pred = slug_to_curated[r.slug][-1]
            prev_e = prev_disc.get(sdid, {})
            entry = {
                "slug": r.slug,
                "status": "active",
                "weekday": r.weekday or config.DIVISIONS[pred].weekday,
                "name": r.name,
                "predecessor": pred,
                "since": prev_e.get("since", run_date),
            }
            discovered[sdid] = entry
            rollovers[sdid] = entry
            if prev_e.get("status") != "active":
                newly.append(r.did)
        else:                                         # unknown slug -> new league
            unknown[sdid] = {
                "slug": r.slug,
                "name": r.name,
                "first_seen": prev_unknown.get(sdid, {}).get("first_seen", run_date),
            }

    # A rollover's predecessor is "rolled" once it drops off states.php.
    for sdid, e in list(rollovers.items()):
        pred = e["predecessor"]
        if pred in states_dids:
            continue
        pe = prev_disc.get(str(pred), {})
        discovered[str(pred)] = {
            "slug": e["slug"],
            "status": "rolled",
            "weekday": (config.DIVISIONS[pred].weekday
                        if pred in config.DIVISIONS else pe.get("weekday")),
            "successor": int(sdid),
            "rolled_on": pe.get("rolled_on", run_date),
        }

    return ReconcileResult(
        registry={"discovered": discovered, "unknown": unknown},
        newly_activated=tuple(newly),
        rollovers=rollovers,
        unknown=unknown,
    )
