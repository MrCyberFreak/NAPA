"""Browser fetcher — headless Chromium capture that clears the JS bot-challenge.

Every host answers a plain HTTP GET with a "One moment, please..." JS reload
interstitial that a non-browser client cannot pass (confirmed: even an httpx
cookie-jar reload loop fails). A real browser executes the page's own JavaScript
and reload, which clears the soft challenge, so we capture the RENDERED HTML.

Same discipline as the plain fetcher: write-on-change, fail-soft (an uncleared
challenge or a navigation error logs and STOPS; a challenge interstitial is
NEVER archived), and a heartbeat for visibility.

Playwright is imported lazily so this module (and the unit-testable challenge
core) load without the browser installed.
"""

from __future__ import annotations

import argparse
import datetime as dt
import json
from pathlib import Path
from typing import Callable, Iterable

from . import config
from . import fetch  # reuse is_challenge / write_on_change / heartbeat / UA / page set


def capture_clearing_challenge(
    get_content: Callable[[], str],
    advance: Callable[[], None],
    attempts: int = 6,
) -> tuple[str, int]:
    """Poll rendered content, letting the page advance (its own 5s reload) until
    it is no longer the challenge interstitial or attempts run out. Pure/testable:
    `get_content` returns current HTML, `advance` waits for the next reload."""
    content = get_content()
    tries = 1
    while fetch.is_challenge(content) and tries < attempts:
        advance()
        content = get_content()
        tries += 1
    return content, tries


def fetch_pages_browser(
    pages: Iterable[tuple[str, dict]] | None = None,
    date: str | None = None,
    root: Path = fetch.ARCHIVE_ROOT,
    attempts: int = 6,
    wait_ms: int = 6000,
    headless: bool = True,
) -> dict[str, Path | None]:
    """Capture each page with headless Chromium, clearing the JS challenge.
    Fail-soft: a navigation error or an uncleared challenge logs and STOPS."""
    from playwright.sync_api import sync_playwright

    pages = list(pages if pages is not None else fetch.ARCHIVE_PAGES)
    date = date or dt.date.today().isoformat()
    written: dict[str, Path | None] = {}

    with sync_playwright() as p:
        browser = p.chromium.launch(headless=headless)
        context = browser.new_context(user_agent=fetch.DEFAULT_UA, locale="en-US")
        page = context.new_page()
        try:
            for i, (name, kw) in enumerate(pages):
                url = config.url(name, **kw)
                try:
                    page.goto(url, wait_until="domcontentloaded", timeout=30000)
                except Exception as exc:  # noqa: BLE001 — fail-soft on any nav error
                    print(f"[browser] {name}: navigation failed ({exc}); stopping (fail-soft).")
                    break

                def advance() -> None:
                    page.wait_for_timeout(wait_ms)  # let the page's own reload fire
                    try:
                        page.wait_for_load_state("networkidle", timeout=15000)
                    except Exception:  # noqa: BLE001
                        pass

                content, tries = capture_clearing_challenge(page.content, advance, attempts)
                if fetch.is_challenge(content):
                    print(f"[browser] {name}: bot-challenge not cleared after {tries} "
                          "attempts; stopping (fail-soft).")
                    break

                out = fetch.write_on_change(name, content.encode("utf-8"), date, root)
                written[name] = out
                state = "wrote" if out else "unchanged"
                print(f"[browser] {name}: {state} (cleared in {tries} req)"
                      + (f" -> {out}" if out else ""))
                if i < len(pages) - 1:
                    page.wait_for_timeout(2000)  # polite spacing
        finally:
            browser.close()
    return written


def main() -> None:
    parser = argparse.ArgumentParser(description="NAPA 13077 browser fetcher (Chromium)")
    parser.add_argument("--date", default=dt.date.today().isoformat())
    parser.add_argument("--root", default=str(fetch.ARCHIVE_ROOT))
    parser.add_argument("--headed", action="store_true", help="run with a visible browser")
    args = parser.parse_args()

    root = Path(args.root)
    written = fetch_pages_browser(date=args.date, root=root, headless=not args.headed)

    hb = fetch.write_heartbeat(root, {
        "mode": "browser",
        "run_date": args.date,
        "captured": sorted(n for n, v in written.items() if v is not None),
        "unchanged": sorted(n for n, v in written.items() if v is None),
    })
    print(f"[heartbeat] {hb}")


if __name__ == "__main__":
    main()
