"""Fetcher (Phase 3) — config-driven URL list -> raw HTML archive.

The fetcher only saves bytes; it never parses, so it rarely breaks. All
fragility lives in the parsers, where it is cheap to fix and replayable against
this archive.

Design (from the build plan):
- Pull pages templated on `did`, write data/raw/<date>/<name>.html.
- Write-on-change: skip writing if identical to the last capture of that page.
- Polite: real UA, spaced + jittered requests, fail-soft (log and STOP on error;
  never retry-hammer).
- Only paper.playpool.io (the cooperative host) is fetched here. poolshooters.com
  is bot-blocked and handled separately (Phase 4).
"""

from __future__ import annotations

import argparse
import datetime as dt
import random
import time
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


def main() -> None:
    parser = argparse.ArgumentParser(description="NAPA 13077 fetcher (paper.playpool.io)")
    parser.add_argument("--date", default=dt.date.today().isoformat(),
                        help="archive date folder (YYYY-MM-DD, default: today)")
    parser.add_argument("--root", default=str(ARCHIVE_ROOT),
                        help=f"archive root (default: {ARCHIVE_ROOT})")
    parser.add_argument("--load", action="store_true",
                        help="after fetching, load the roster grid into the DB")
    parser.add_argument("--db", default=config.DB_PATH, help=f"DB path (default: {config.DB_PATH})")
    args = parser.parse_args()

    root = Path(args.root)
    with make_client() as client:
        written = fetch_pages(client, date=args.date, root=root)

    if args.load:
        # Load whatever roster grid we have (new capture, else the latest prior).
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
