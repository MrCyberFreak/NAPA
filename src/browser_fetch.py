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


def capture_assets(url: str, out_dir: str | Path, headless: bool = True) -> list[str]:
    """One-off: load `url` in Chromium and save every JS asset it requests (plus
    the rendered HTML). Used to recover a page's dynamic logic/data (e.g. the
    race calculator's CSR->race lookup) that a static MHTML save drops."""
    import re as _re
    from playwright.sync_api import sync_playwright

    out = Path(out_dir)
    out.mkdir(parents=True, exist_ok=True)
    saved: list[str] = []

    with sync_playwright() as p:
        browser = p.chromium.launch(headless=headless)
        page = browser.new_context(user_agent=fetch.DEFAULT_UA, locale="en-US").new_page()

        def on_response(resp) -> None:
            try:
                ct = resp.headers.get("content-type", "")
                if resp.url.split("?")[0].endswith(".js") or "javascript" in ct:
                    name = _re.sub(r"[^A-Za-z0-9._-]", "_", resp.url.split("//", 1)[-1])[:120]
                    (out / name).write_bytes(resp.body())
                    saved.append(name)
            except Exception:  # noqa: BLE001
                pass

        page.on("response", on_response)
        try:
            page.goto(url, wait_until="networkidle", timeout=45000)
        except Exception as exc:  # noqa: BLE001
            print(f"[capture] {url}: {exc}")
        for _ in range(6):
            if not fetch.is_challenge(page.content()):
                break
            page.wait_for_timeout(6000)
        (out / "_rendered.html").write_text(page.content(), encoding="utf-8")
        browser.close()
    print(f"[capture] saved {len(saved)} JS assets + _rendered.html to {out}")
    return saved


def backfill_score_sheets(weeks, out_root: str | Path = "data/raw/scores",
                          headless: bool = True) -> list[str]:
    """Walk standings_weekly_scores.php?week=N for each week, follow every
    'view score sheet' (scores.php) link, and save the rendered HTML. Resumable:
    skips sheets already on disk. The raw archive is the durable backfill record."""
    import re as _re
    from playwright.sync_api import sync_playwright

    from .parse.weekly_scores import parse_week_index

    out_root = Path(out_root)
    saved: list[str] = []

    def cleared(page, url: str) -> str:
        try:
            page.goto(url, wait_until="domcontentloaded", timeout=30000)
        except Exception as exc:  # noqa: BLE001
            print(f"[backfill] nav failed {url}: {exc}")
            return ""
        for _ in range(6):
            if not fetch.is_challenge(page.content()):
                break
            page.wait_for_timeout(6000)
        return page.content()

    with sync_playwright() as p:
        browser = p.chromium.launch(headless=headless)
        page = browser.new_context(user_agent=fetch.DEFAULT_UA, locale="en-US").new_page()
        try:
            for wk in weeks:
                wkdir = out_root / f"week_{wk:02d}"
                wkdir.mkdir(parents=True, exist_ok=True)
                idx_html = cleared(page, config.url("weekly_scores", week=wk))
                (wkdir / "_index.html").write_text(idx_html, encoding="utf-8")
                urls = parse_week_index(idx_html)
                print(f"[backfill] week {wk}: {len(urls)} score sheets")
                for url in urls:
                    tid = _re.search(r"tid=(\d+)", url)
                    target = wkdir / f"{tid.group(1) if tid else 'x'}.html"
                    if target.exists() and target.stat().st_size > 500:
                        continue  # resume
                    html = cleared(page, url)
                    if html and not fetch.is_challenge(html):
                        target.write_text(html, encoding="utf-8")
                        saved.append(str(target))
                    page.wait_for_timeout(1200)
        finally:
            browser.close()
    print(f"[backfill] saved {len(saved)} new score sheets")
    return saved


def explore_profile(player_id: str, out_dir: str | Path, headless: bool = True) -> list[str]:
    """One-off: open a player profile, click each deep tab, and save the rendered
    HTML + every XHR/JSON/HTML response the tabs trigger — to learn how RIVALS /
    H2H / TRENDS load before building the harvester."""
    import re as _re
    from playwright.sync_api import sync_playwright

    out = Path(out_dir)
    out.mkdir(parents=True, exist_ok=True)
    responses: list[tuple[str, str, bytes]] = []

    with sync_playwright() as p:
        browser = p.chromium.launch(headless=headless)
        page = browser.new_context(user_agent=fetch.DEFAULT_UA, locale="en-US").new_page()

        def on_resp(r) -> None:
            try:
                ct = r.headers.get("content-type", "")
                if any(t in ct for t in ("json", "html", "javascript")):
                    responses.append((r.url, ct, r.body()))
            except Exception:  # noqa: BLE001
                pass

        page.on("response", on_resp)
        url = config.url("profile", player_id=player_id)
        try:
            page.goto(url, wait_until="networkidle", timeout=45000)
        except Exception as exc:  # noqa: BLE001
            print(f"[explore] nav: {exc}")
        for _ in range(6):
            if not fetch.is_challenge(page.content()):
                break
            page.wait_for_timeout(6000)
        (out / "profile_main.html").write_text(page.content(), encoding="utf-8")

        for label in ("RIVALS", "H2H", "TRENDS", "SEASONS", "MATCHES", "MATCH HISTORY"):
            try:
                page.get_by_text(label, exact=False).first.click(timeout=4000)
                page.wait_for_timeout(3500)
                (out / f"tab_{label.replace(' ', '_')}.html").write_text(
                    page.content(), encoding="utf-8")
            except Exception as exc:  # noqa: BLE001
                print(f"[explore] tab {label}: {type(exc).__name__}")

        for i, (u, ct, body) in enumerate(responses):
            name = _re.sub(r"[^A-Za-z0-9._-]", "_", u.split("//", 1)[-1])[:70]
            ext = ".json" if "json" in ct else (".js" if "javascript" in ct else ".html")
            (out / f"resp_{i:03d}_{name}{ext}").write_bytes(body)
        browser.close()
    print(f"[explore] saved profile + {len(responses)} responses to {out}")
    return [str(out)]


def _parse_weeks(spec: str) -> list[int]:
    if "-" in spec:
        lo, hi = spec.split("-", 1)
        return list(range(int(lo), int(hi) + 1))
    return [int(x) for x in spec.split(",") if x]


def main() -> None:
    parser = argparse.ArgumentParser(description="NAPA 13077 browser fetcher (Chromium)")
    parser.add_argument("--date", default=dt.date.today().isoformat())
    parser.add_argument("--root", default=str(fetch.ARCHIVE_ROOT))
    parser.add_argument("--headed", action="store_true", help="run with a visible browser")
    parser.add_argument("--capture-url", help="one-off: capture a page's JS assets + HTML")
    parser.add_argument("--out", help="output dir for --capture-url")
    parser.add_argument("--backfill-weeks", help="e.g. 1-27 : backfill score sheets")
    parser.add_argument("--explore-profile", help="player_id : capture profile tabs + XHR")
    args = parser.parse_args()

    if args.capture_url:
        capture_assets(args.capture_url, args.out or "data/raw/_assets", headless=not args.headed)
        return

    if args.explore_profile:
        explore_profile(args.explore_profile, args.out or "data/raw/profile_explore",
                        headless=not args.headed)
        return

    if args.backfill_weeks:
        backfill_score_sheets(_parse_weeks(args.backfill_weeks), headless=not args.headed)
        return

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
