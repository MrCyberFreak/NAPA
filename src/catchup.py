"""Catch-up queue — pieces to re-pull on the NEXT scheduled scrape, no matter
which divisions actually played last night.

The day-after-play scrape (config.divisions_due) pulls only the divisions whose
league night was yesterday. Two things slip through that net and must be carried
forward so nothing is silently dropped:

  1. a SKIPPED capture — a host-wide bot-challenge aborts the run and every
     division after the abort is never reached; a nav error leaves one division
     only partially captured;
  2. MISSING results — matches that were scheduled, whose date has passed, but
     which have no loaded games yet: real makeups played on off-schedule dates
     (bye-week placeholders are NOT missing data — they never produce a sheet —
     and are filtered out at the source in db.pending_matches).

Both get recorded here and folded into the next run ON TOP of that day's due set
(see catchup.run_set), so a missed or makeup-bearing division is pulled again
even though it didn't play last night — "include the missing pieces in the next
pull, regardless of division." The queue is a small JSON file committed to the
archive (durable, like _heartbeat.json). Entries clear themselves: a division
leaves the queue once it captures cleanly AND has no outstanding makeups, and a
stale makeup ages out of the window so one never-entered fixture can't pin a
division to a daily re-pull forever.
"""
from __future__ import annotations

import datetime as dt
import json
from pathlib import Path

from . import config, fetch

CATCHUP_PATH = fetch.ARCHIVE_ROOT / "_catchup.json"

# A pending makeup older than this many days is treated as a data phantom (a
# fixture that was never played / never entered), not a real makeup still owed —
# real makeups are played within a few weeks. Past the window it ages out of the
# queue so it can't pin its division to a daily re-pull forever. Generous on
# purpose; widen if a genuinely late makeup is ever missed.
MAKEUP_WINDOW_DAYS = 56


def load_queue(path: Path = CATCHUP_PATH) -> dict[str, dict]:
    """Queued divisions: str(did) -> {"reason", "since", "rounds"?}. A missing
    or unreadable file is an empty queue (the queue is an optimization, never a
    correctness dependency)."""
    if not path.exists():
        return {}
    try:
        return json.loads(path.read_text(encoding="utf-8")).get("divisions", {})
    except (json.JSONDecodeError, OSError):
        return {}


def save_queue(queue: dict[str, dict], path: Path = CATCHUP_PATH,
               run_date: str | None = None) -> Path:
    """Write the queue, did-sorted for a stable diff (it is committed)."""
    path.parent.mkdir(parents=True, exist_ok=True)
    payload = {
        "updated_utc": dt.datetime.now(dt.timezone.utc).isoformat(timespec="seconds"),
        "run_date": run_date,
        "divisions": dict(sorted(queue.items(), key=lambda kv: int(kv[0]))),
    }
    path.write_text(json.dumps(payload, indent=2) + "\n", encoding="utf-8")
    return path


def run_set(due: list[int], queue: dict[str, dict]) -> list[int]:
    """Divisions to scrape this run: today's due set PLUS every queued division
    (carryover), de-duped and returned in registry order so the shared browser
    context visits them deterministically."""
    want = set(due) | {int(d) for d in queue}
    return [did for did in config.DIVISIONS if did in want]


def _expected_pages(did: int) -> set[str]:
    return {name for name, _ in fetch.archive_pages(did)}


def _carry(reason: str, prev: dict[str, dict], key: str, run_date: str) -> dict:
    """A queue entry, preserving the original `since` date across runs so the
    queue shows how long a division has been waiting."""
    return {"reason": reason, "since": prev.get(key, {}).get("since", run_date)}


def _fresh_makeups(pending: list, run_date: str) -> list:
    """Pending makeups still inside the re-pull window (older ones are phantoms).
    `pending` rows are db.pending_matches output (already bye-filtered there)."""
    try:
        cutoff = dt.date.fromisoformat(run_date) - dt.timedelta(days=MAKEUP_WINDOW_DAYS)
    except ValueError:
        return list(pending)
    fresh = []
    for m in pending:
        d = m["date"]
        if not d:
            continue
        try:
            if dt.date.fromisoformat(d) >= cutoff:
                fresh.append(m)
        except (ValueError, TypeError):
            fresh.append(m)  # unparseable date — keep it rather than drop blindly
    return fresh


def reconcile(run_set_dids: list[int], results: dict[str, dict],
              pending_by_did: dict[int, list], prev_queue: dict[str, dict],
              run_date: str) -> dict[str, dict]:
    """The queue after a run. For every division we attempted this run:
      - absent from `results`          -> never reached (upstream abort): re-queue
      - present but pages incomplete   -> partial capture: re-queue
      - present, complete, makeups owed -> re-queue with the owed rounds
      - present, complete, nothing owed -> drop
    `results` is the browser scrape's {str(did): {captured, unchanged}} map;
    `pending_by_did` is db.pending_matches per division AFTER the load."""
    queue: dict[str, dict] = {}
    for did in run_set_dids:
        key = str(did)
        got = results.get(key)
        if got is None:
            queue[key] = _carry("scrape-skipped", prev_queue, key, run_date)
            continue
        captured = set(got.get("captured", [])) | set(got.get("unchanged", []))
        if not _expected_pages(did) <= captured:
            queue[key] = _carry("scrape-incomplete", prev_queue, key, run_date)
            continue
        fresh = _fresh_makeups(pending_by_did.get(did, []), run_date)
        if fresh:
            entry = _carry("pending-makeups", prev_queue, key, run_date)
            entry["rounds"] = sorted({m["round"] for m in fresh})
            queue[key] = entry
    return queue
