"""Fetcher — config-driven URL list -> raw HTML archive (Phases 3 + 4).

The fetcher only saves bytes; it never parses, so it rarely breaks. All
fragility lives in the parsers, where it is cheap to fix and replayable against
this archive.

Design (from the build plan):
- Pull pages templated on `did`, write data/raw/<date>/<name>.html.
- Write-on-change: skip writing if identical to the last capture of that page.
- Polite: real UA, spaced + jittered requests, fail-soft (log and STOP on error;
  never retry-hammer).
- Host-AGNOSTIC and config-driven: the same code fetches paper.playpool.io (easy)
  and attempts poolshooters.com (assumed bot-blocked). A connectivity probe logs
  each host's reachability from wherever it runs, so we learn what is actually
  blocked vs assumed.
- Heartbeat: every run writes data/raw/_heartbeat.json so a missed/failed run is
  visible (stale timestamp) even when nothing else changed.
"""

from __future__ import annotations

import argparse
import datetime as dt
import json
import random
import time
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Callable, Iterable

import httpx

from . import config

# A real browser UA — the cooperative host is fine with this; it also keeps us
# honest about identifying as a normal client.
DEFAULT_UA = (
    "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/124.0 Safari/537.36"
)

# Easy tier only (paper.playpool.io). (name, url-kwargs)
EASY_PAGES: list[tuple[str, dict]] = [
    ("roster_grid", {}),
    ("schedule", {}),
    ("scratch", {}),
]

# Host-agnostic archive set. Easy (paper) pages first so they are captured
# before we ever touch the assumed-blocked host; fail-soft stop then preserves
# the easy captures regardless of what poolshooters.com does.
ARCHIVE_PAGES: list[tuple[str, dict]] = EASY_PAGES + [
    ("division", {}),
    ("leaderboard", {}),
    ("live_scores", {}),
]

# One representative real endpoint per host, for the reachability probe.
PROBE_TARGETS: dict[str, str] = {
    "paper.playpool.io": config.url("roster_grid"),
    "scores.playpool.io": config.url("livescores"),
    "poolshooters.com": config.url("division"),
}

ARCHIVE_ROOT = Path("data/raw")


def make_client(timeout: float = 30.0) -> httpx.Client:
    return httpx.Client(
        headers={
            "User-Agent": DEFAULT_UA,
            "Accept": "text/html,application/xhtml+xml",
            "Accept-Language": "en-US,en;q=0.9",
        },
        timeout=timeout,
        follow_redirects=True,
    )


def _polite_sleep(base: float = 3.0, jitter: float = 2.0) -> None:
    time.sleep(base + random.uniform(0, jitter))


def _latest_existing(name: str, root: Path) -> Path | None:
    """Most recent prior archived copy of a page across all date folders."""
    hits = sorted(root.glob(f"*/{name}.html"))
    return hits[-1] if hits else None


def write_on_change(name: str, content: bytes, date: str, root: Path = ARCHIVE_ROOT) -> Path | None:
    """Write content to data/raw/<date>/<name>.html unless it matches the last
    capture of that page. Returns the path written, or None if unchanged."""
    prev = _latest_existing(name, root)
    if prev is not None and prev.read_bytes() == content:
        return None
    out = root / date / f"{name}.html"
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_bytes(content)
    return out


def fetch_pages(
    client: httpx.Client,
    pages: Iterable[tuple[str, dict]] = EASY_PAGES,
    date: str | None = None,
    root: Path = ARCHIVE_ROOT,
    sleep: Callable[[], None] = _polite_sleep,
) -> dict[str, Path | None]:
    """Fetch each page into the archive. Fail-soft: on the first error, log and
    STOP (return what was captured so far) — never retry-hammer the host."""
    date = date or dt.date.today().isoformat()
    written: dict[str, Path | None] = {}
    pages = list(pages)
    for i, (name, kw) in enumerate(pages):
        target = config.url(name, **kw)
        try:
            resp = client.get(target)
            resp.raise_for_status()
        except httpx.HTTPError as exc:
            print(f"[fetch] {name}: request failed ({exc}); stopping (fail-soft).")
            break
        out = write_on_change(name, resp.content, date, root)
        written[name] = out
        status = "wrote" if out else "unchanged"
        print(f"[fetch] {name}: {status}"
              + (f" -> {out}" if out else " (skipped)"))
        if i < len(pages) - 1:
            sleep()  # space requests + jitter
    return written


# --------------------------------------------------------------------------- #
# Connectivity probe (learn what's actually blocked vs assumed)
# --------------------------------------------------------------------------- #

# Markers that suggest a bot-block / challenge rather than real content.
_BLOCK_MARKERS = ("cf-chl", "captcha", "access denied", "are you a robot",
                  "request blocked", "attention required")


def _looks_blocked(status: int, body: str) -> bool:
    if status in (401, 403, 429, 503):
        return True
    low = body[:4000].lower()
    return any(m in low for m in _BLOCK_MARKERS)


@dataclass
class ProbeResult:
    host: str
    url: str
    reachable: bool          # got any HTTP response (network path works)
    status: int | None
    blocked: bool            # reachable but bot-blocked (403/429/challenge)
    latency_ms: int | None
    note: str

    def summary(self) -> str:
        if not self.reachable:
            return f"{self.host:<22} UNREACHABLE   {self.note}"
        verdict = "BLOCKED" if self.blocked else "OK"
        return (f"{self.host:<22} {verdict:<11} HTTP {self.status} "
                f"{self.latency_ms}ms  {self.note}".rstrip())


def probe_hosts(client: httpx.Client, targets: dict[str, str] = PROBE_TARGETS) -> list[ProbeResult]:
    """GET one representative endpoint per host and classify the outcome:
    UNREACHABLE (no HTTP response = network/DNS blocked) vs BLOCKED (HTTP
    403/429/challenge = bot-block) vs OK (real response). Read-only, one hit each."""
    results: list[ProbeResult] = []
    for host, url in targets.items():
        t0 = time.perf_counter()
        try:
            resp = client.get(url)
            ms = int((time.perf_counter() - t0) * 1000)
            blocked = _looks_blocked(resp.status_code, resp.text)
            note = f"{len(resp.content)}B" + (" (block markers)" if blocked and resp.status_code < 400 else "")
            results.append(ProbeResult(host, url, True, resp.status_code, blocked, ms, note))
        except httpx.HTTPError as exc:
            results.append(ProbeResult(host, url, False, None, False, None, type(exc).__name__ + f": {exc}"))
    return results


def write_heartbeat(root: Path, payload: dict) -> Path:
    """Durable run record so a missed/failed scrape is visible (stale timestamp)."""
    root.mkdir(parents=True, exist_ok=True)
    out = root / "_heartbeat.json"
    payload = {"updated_utc": dt.datetime.now(dt.timezone.utc).isoformat(timespec="seconds"), **payload}
    out.write_text(json.dumps(payload, indent=2) + "\n", encoding="utf-8")
    return out


def main() -> None:
    parser = argparse.ArgumentParser(description="NAPA 13077 fetcher (host-agnostic)")
    parser.add_argument("--date", default=dt.date.today().isoformat(),
                        help="archive date folder (YYYY-MM-DD, default: today)")
    parser.add_argument("--root", default=str(ARCHIVE_ROOT),
                        help=f"archive root (default: {ARCHIVE_ROOT})")
    parser.add_argument("--probe-only", action="store_true",
                        help="run the connectivity probe + heartbeat, skip fetching")
    parser.add_argument("--load", action="store_true",
                        help="after fetching, load the roster grid into the DB")
    parser.add_argument("--db", default=config.DB_PATH, help=f"DB path (default: {config.DB_PATH})")
    args = parser.parse_args()

    root = Path(args.root)
    with make_client(timeout=20.0) as client:
        print("[probe] host reachability:")
        probes = probe_hosts(client)
        for p in probes:
            print("  " + p.summary())

        written: dict[str, Path | None] = {}
        if not args.probe_only:
            written = fetch_pages(client, pages=ARCHIVE_PAGES, date=args.date, root=root)

    hb = write_heartbeat(root, {
        "run_date": args.date,
        "probe": [asdict(p) for p in probes],
        "captured": sorted(n for n, v in written.items() if v is not None),
        "unchanged": sorted(n for n, v in written.items() if v is None),
    })
    print(f"[heartbeat] {hb}")

    if args.load and not args.probe_only:
        from .db import connect, load_roster
        from .parse.roster import parse_roster_file

        roster = written.get("roster_grid") or _latest_existing("roster_grid", root)
        if roster is None:
            print("[fetch] no roster grid available to load.")
            return
        conn = connect(args.db)
        result = load_roster(conn, parse_roster_file(roster), captured_date=args.date)
        conn.close()
        print(f"[fetch] loaded {result['players']} players / {result['teams']} teams "
              f"@ {args.date} into {args.db}")


if __name__ == "__main__":
    main()
