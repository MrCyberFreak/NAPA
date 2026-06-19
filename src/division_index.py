"""Division-ID discovery index — the catalog the did-sweep writes.

NAPA mints a new did every season and exposes no season/year URL param, so the
only lever to find a league's PAST sessions is the did integer itself. The sweep
(src.browser_fetch.discover_scout / discover_sweep) probes division.php?did=N
across a range, parses each NAME -> slug (src.parse.division), and records ONE
index row per probed did here. Grouping rows by slug recovers a league's whole
session lineage (13077 + 14050 share `thursday-big-table-felt-lc`).

Storage model (mirrors discovery.py / catchup.py — committed, human-diffable JSON):
  - master `data/raw/_division_index.json`, str(did) -> row, did-sorted.
  - per-shard JSONL `_division_index.shard_<i>of<N>.jsonl`: a sharded sweep runner
    appends ONLY to its own file (no two runners touch the master), and a merge
    step folds the shards into the master (preserving the earliest first_seen_date)
    and derives `_historical.json` — the report-only onboarding inbox of NoCo
    sessions not yet curated. NoCo membership is decided by SLUG, never location.

A row: {did, echoed_did, name, slug, location, is_noco, resolved, first_seen_date}.
`resolved` distinguishes a real MISS (probed-and-empty) from a hit, so a resume
never re-probes a known gap. `echoed_did` is the did printed on the page; a
mismatch with the probed `did` is a drift signal.
"""

from __future__ import annotations

import argparse
import datetime as dt
import json
from pathlib import Path
from typing import Iterable

from . import config

INDEX_PATH = Path("data/raw") / "_division_index.json"
HISTORICAL_PATH = Path("data/raw") / "_historical.json"


def noco_slugs() -> set[str]:
    """The curated Northern-Colorado league slugs — the NoCo membership test.
    A discovered rollover shares its predecessor's curated slug, and an unknown
    new league isn't NoCo-confirmed until a human onboards it, so the curated set
    is the right gate."""
    return {d.slug for d in config.DIVISIONS.values()}


# ---- row construction ------------------------------------------------------- #

def make_row(probed_did: int, dp, run_date: str) -> dict:
    """Build an index row from a probed did + its parsed DivisionPage."""
    return {
        "did": probed_did,
        "echoed_did": dp.did,          # page's own "Division ID:" (== probed_did on a clean hit)
        "name": dp.name,
        "slug": dp.slug,
        "location": dp.location,
        "is_noco": bool(dp.slug) and dp.slug in noco_slugs(),
        "resolved": dp.resolved,
        "first_seen_date": run_date,
    }


# ---- master index I/O (mirrors discovery.load/save_registry) ---------------- #

def load_index(path: Path | None = None) -> dict[str, dict]:
    """str(did) -> row. Missing/unreadable => {} (the index only ever ADDS rows)."""
    path = path or INDEX_PATH
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return {}
    divs = data.get("divisions", {})
    return divs if isinstance(divs, dict) else {}


def save_index(rows: dict[str, dict], path: Path | None = None,
               run_date: str | None = None) -> Path:
    """Write the master index, did-sorted for a stable committed diff."""
    path = path or INDEX_PATH
    path.parent.mkdir(parents=True, exist_ok=True)
    payload = {
        "updated_utc": dt.datetime.now(dt.timezone.utc).isoformat(timespec="seconds"),
        "run_date": run_date,
        "count": len(rows),
        "noco_count": sum(1 for r in rows.values() if r.get("is_noco")),
        "divisions": dict(sorted(rows.items(), key=lambda kv: int(kv[0]))),
    }
    path.write_text(json.dumps(payload, indent=2) + "\n", encoding="utf-8")
    return path


# ---- per-shard JSONL (no two runners touch the master) ---------------------- #

def parse_shard(shard: str) -> tuple[int, int]:
    """'i/N' -> (i, N) with 1 <= i <= N."""
    try:
        i, n = (int(x) for x in shard.split("/"))
    except ValueError as exc:
        raise ValueError(f"bad --discover-shard {shard!r}: want 'i/N'") from exc
    if not (1 <= i <= n):
        raise ValueError(f"bad --discover-shard {shard!r}: need 1 <= i <= N")
    return i, n


def shard_path(shard: str, root: Path | None = None) -> Path:
    i, n = parse_shard(shard)
    root = root or INDEX_PATH.parent
    return root / f"_division_index.shard_{i}of{n}.jsonl"


def shard_files(root: Path | None = None) -> list[Path]:
    root = root or INDEX_PATH.parent
    return sorted(root.glob("_division_index.shard_*of*.jsonl"))


def append_shard_row(shard_file: Path, row: dict) -> None:
    """Append one row as a JSON line, flushed (crash-safe up to the last line)."""
    shard_file.parent.mkdir(parents=True, exist_ok=True)
    with shard_file.open("a", encoding="utf-8") as f:
        f.write(json.dumps(row) + "\n")
        f.flush()


def load_shard_rows(shard_file: Path) -> dict[str, dict]:
    """str(did) -> row already written to this shard (intra-shard resume).
    Tolerates a truncated final line from an aborted run."""
    rows: dict[str, dict] = {}
    if not shard_file.exists():
        return rows
    for line in shard_file.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line:
            continue
        try:
            r = json.loads(line)
        except json.JSONDecodeError:
            continue  # truncated tail line — skip, the did just gets re-probed
        rows[str(r["did"])] = r
    return rows


# ---- merge + derived views -------------------------------------------------- #

def merge_shards(index: dict[str, dict], shard_rows: Iterable[dict]) -> dict[str, dict]:
    """Fold shard rows into the master index. A later probe of a did overwrites
    its row but PRESERVES the earliest first_seen_date (idempotent re-runs never
    bump it)."""
    merged = {k: dict(v) for k, v in index.items()}
    for r in shard_rows:
        did = str(r["did"])
        prev = merged.get(did)
        if prev and prev.get("first_seen_date"):
            earliest = min(filter(None, (prev["first_seen_date"],
                                         r.get("first_seen_date"))))
            r = {**r, "first_seen_date": earliest}
        merged[did] = r
    return merged


def slug_families(index: dict[str, dict]) -> dict[str, list[int]]:
    """slug -> sorted dids carrying it. Any slug with >1 did is a multi-session
    league — the whole point of the sweep."""
    fam: dict[str, list[int]] = {}
    for r in index.values():
        if r.get("resolved") and r.get("slug"):
            fam.setdefault(r["slug"], []).append(int(r["did"]))
    return {s: sorted(d) for s, d in fam.items()}


def build_historical(index: dict[str, dict]) -> dict[str, dict]:
    """The onboarding inbox: NoCo sessions the sweep found that are NOT already
    curated. Report-only — a human onboards via napa-onboard-division; these are
    NEVER auto-scraped (unlike _registry.json's discovered-active rollovers).
    `successor` = the highest curated did sharing the slug (the live session)."""
    curated = set(config.DIVISIONS)
    curated_by_slug: dict[str, list[int]] = {}
    for did, d in config.DIVISIONS.items():
        curated_by_slug.setdefault(d.slug, []).append(did)

    hist: dict[str, dict] = {}
    for did_str, r in index.items():
        if not (r.get("is_noco") and r.get("resolved")):
            continue
        did = int(did_str)
        if did in curated:
            continue  # already tracked
        succ = max(curated_by_slug.get(r["slug"], [did]))
        hist[did_str] = {
            "slug": r["slug"],
            "name": r.get("name", ""),
            "location": r.get("location", ""),
            "successor": succ if succ != did else None,
            "first_seen_date": r.get("first_seen_date"),
            "onboarded": False,
        }
    return hist


def save_historical(hist: dict[str, dict], path: Path | None = None,
                    run_date: str | None = None) -> Path:
    path = path or HISTORICAL_PATH
    path.parent.mkdir(parents=True, exist_ok=True)
    payload = {
        "updated_utc": dt.datetime.now(dt.timezone.utc).isoformat(timespec="seconds"),
        "run_date": run_date,
        "count": len(hist),
        "historical": dict(sorted(hist.items(), key=lambda kv: int(kv[0]))),
    }
    path.write_text(json.dumps(payload, indent=2) + "\n", encoding="utf-8")
    return path


# ---- CLI: merge shards -> master index + historical inbox ------------------- #

def main() -> None:
    ap = argparse.ArgumentParser(description="division discovery index tools")
    ap.add_argument("--merge", action="store_true",
                    help="fold shard JSONLs into the master index + derive _historical.json")
    ap.add_argument("--shards", type=int, default=None,
                    help="expected shard count (informational; all shard files are merged)")
    ap.add_argument("--run-date", default=None)
    ap.add_argument("--keep-shards", action="store_true",
                    help="do not delete shard files after merging")
    args = ap.parse_args()

    if not args.merge:
        ap.error("nothing to do (pass --merge)")

    run_date = args.run_date or dt.date.today().isoformat()
    index = load_index()
    files = shard_files()
    rows: list[dict] = []
    for sf in files:
        rows.extend(load_shard_rows(sf).values())

    merged = merge_shards(index, rows)
    save_index(merged, run_date=run_date)
    hist = build_historical(merged)
    save_historical(hist, run_date=run_date)

    multi = {s: d for s, d in slug_families(merged).items() if len(d) > 1}
    noco = sum(1 for r in merged.values() if r.get("is_noco"))
    print(f"[index] merged {len(rows)} rows from {len(files)} shard(s) -> "
          f"{len(merged)} divisions ({noco} NoCo); {len(multi)} multi-session slugs; "
          f"{len(hist)} historical NoCo session(s) for onboarding")
    for slug, dids in sorted(multi.items()):
        print(f"[index]   {slug}: {dids}")

    if not args.keep_shards:
        for sf in files:
            sf.unlink(missing_ok=True)


if __name__ == "__main__":
    main()
