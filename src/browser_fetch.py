"""Browser fetcher — headless Chromium capture that clears the JS bot-challenge.

Every host answers a plain HTTP GET with a "One moment, please..." JS reload
interstitial that a non-browser client cannot pass (confirmed: even an httpx
cookie-jar reload loop fails). A real browser executes the page's own JavaScript
and reload, which clears the soft challenge, so we capture the RENDERED HTML.

Same discipline as the plain fetcher: write-on-change, fail-soft (a challenge
interstitial is NEVER archived), and a heartbeat for visibility. The daily
scrape loops the active divisions reusing ONE browser page (challenge cookies
persist per host, so divisions after the first skip the 6s clears) with
two-level fail-soft: a navigation error stops the CURRENT division's remaining
pages and continues to the next division; an uncleared bot-challenge is a
HOST-WIDE condition and aborts the whole run.

Playwright is imported lazily so this module (and the unit-testable challenge
core) load without the browser installed.
"""

from __future__ import annotations

import argparse
import datetime as dt
import itertools
import json
from contextlib import contextmanager
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


class BotChallengeError(RuntimeError):
    """An uncleared JS bot-challenge — a host-wide condition, not a per-page
    one, so multi-division callers abort the whole run instead of hammering
    the remaining divisions. Carries the pages written before the abort so
    the heartbeat can still report them."""

    def __init__(self, message: str, written: dict[str, Path | None] | None = None):
        super().__init__(message)
        self.written: dict[str, Path | None] = written or {}


@contextmanager
def _browser_page(headless: bool = True):
    """One Chromium page in a fresh context (UA + locale set), closed on exit.
    Callers that loop divisions share a single page so challenge cookies
    persist across them."""
    from playwright.sync_api import sync_playwright

    with sync_playwright() as p:
        browser = p.chromium.launch(headless=headless)
        context = browser.new_context(user_agent=fetch.DEFAULT_UA, locale="en-US")
        try:
            yield context.new_page()
        finally:
            browser.close()


def fetch_pages_browser(
    pages: Iterable[tuple[str, dict]] | None = None,
    date: str | None = None,
    root: Path = fetch.ARCHIVE_ROOT,
    attempts: int = 6,
    wait_ms: int = 6000,
    headless: bool = True,
    page=None,
    raise_on_challenge: bool = False,
) -> dict[str, Path | None]:
    """Capture each page with headless Chromium, clearing the JS challenge.
    Fail-soft: a navigation error logs and STOPS. An uncleared challenge stops
    too — or raises BotChallengeError (carrying the partial result) when
    `raise_on_challenge`, so a multi-division loop can abort the whole run.
    Pass an existing Playwright `page` to reuse one browser/context (challenge
    cookies persist per host); standalone, a browser is created and closed."""
    if page is None:
        with _browser_page(headless) as own_page:
            return fetch_pages_browser(pages=pages, date=date, root=root,
                                       attempts=attempts, wait_ms=wait_ms, page=own_page,
                                       raise_on_challenge=raise_on_challenge)

    pages = list(pages if pages is not None else fetch.ARCHIVE_PAGES)
    date = date or dt.date.today().isoformat()
    written: dict[str, Path | None] = {}

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
            msg = f"[browser] {name}: bot-challenge not cleared after {tries} attempts"
            if raise_on_challenge:
                print(msg + "; aborting (host-wide).")
                raise BotChallengeError(msg, written)
            print(msg + "; stopping (fail-soft).")
            break

        out = fetch.write_on_change(name, content.encode("utf-8"), date, root)
        written[name] = out
        state = "wrote" if out else "unchanged"
        print(f"[browser] {name}: {state} (cleared in {tries} req)"
              + (f" -> {out}" if out else ""))
        if i < len(pages) - 1:
            page.wait_for_timeout(2000)  # polite spacing
    return written


def _split_written(written: dict[str, Path | None]) -> dict[str, list[str]]:
    """Heartbeat shape for one division's results: written-path -> captured,
    None (write-on-change skip) -> unchanged."""
    return {"captured": sorted(n for n, v in written.items() if v is not None),
            "unchanged": sorted(n for n, v in written.items() if v is None)}


def fetch_divisions_browser(
    dids: Iterable[int],
    date: str | None = None,
    headless: bool = True,
    attempts: int = 6,
    wait_ms: int = 6000,
    page=None,
    root_for: Callable[[int], Path] = config.division_root,
) -> dict[str, dict[str, list[str]]]:
    """Daily scrape across divisions, reusing ONE browser page (challenge
    cookies persist per host, so divisions after the first skip the 6s clears).
    Two-level fail-soft: a navigation error stops the CURRENT division's
    remaining pages (fetch_pages_browser returns partial) and the loop moves on
    to the next division; an uncleared bot-challenge is host-wide and aborts
    the WHOLE run. Returns {did: {"captured": [...], "unchanged": [...]}} for
    the heartbeat — including the aborted division's partial results."""
    if page is None:
        with _browser_page(headless) as own_page:
            return fetch_divisions_browser(dids, date=date, attempts=attempts,
                                           wait_ms=wait_ms, page=own_page, root_for=root_for)

    results: dict[str, dict[str, list[str]]] = {}
    for did in dids:
        print(f"[browser] division {did}:")
        try:
            written = fetch_pages_browser(pages=fetch.archive_pages(did), date=date,
                                          root=root_for(did), attempts=attempts,
                                          wait_ms=wait_ms, page=page,
                                          raise_on_challenge=True)
        except BotChallengeError as exc:
            results[str(did)] = _split_written(exc.written)
            print(f"[browser] division {did}: uncleared bot-challenge — aborting the run "
                  "(host-wide condition; remaining divisions skipped).")
            break
        results[str(did)] = _split_written(written)
    return results


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


def classify_index(html: str) -> str:
    """Pure stop/abort decision for one weekly-scores index capture:
    - "abort": failed nav ("" content) or an uncleared challenge — host-wide
      trouble that must NEVER count toward the auto stop (a mid-run challenge
      must not silently truncate a backfill);
    - "empty": a successfully cleared page with zero score-sheet (scores.php)
      links — past the division's played weeks;
    - "ok":    a cleared page with at least one score-sheet link."""
    from .parse.weekly_scores import parse_week_index

    if not html or fetch.is_challenge(html):
        return "abort"
    return "ok" if parse_week_index(html) else "empty"


def _walk_weeks(weeks, fetch_index: Callable[[int], str]):
    """Yield (week, index_html) for each OK week. `weeks` is a list of ints or
    "auto": auto walks week 1,2,3,... and STOPS after 2 CONSECUTIVE empty
    indexes (season end discovered); an "abort" classification ends the walk
    immediately in EITHER mode (fail-soft — a re-run resumes from disk)."""
    auto = weeks == "auto"
    empties = 0
    for wk in itertools.count(1) if auto else weeks:
        html = fetch_index(wk)
        verdict = classify_index(html)
        if verdict == "abort":
            print(f"[backfill] week {wk}: nav failed or challenge uncleared — "
                  "aborting the backfill (fail-soft).")
            return
        if verdict == "empty":
            empties += 1
            print(f"[backfill] week {wk}: empty index ({empties} consecutive).")
            if auto and empties >= 2:
                print("[backfill] 2 consecutive empty weeks — season end; stopping.")
                return
            continue
        empties = 0
        yield wk, html


def backfill_score_sheets(weeks, out_root: str | Path | None = None,
                          headless: bool = True, did: int = config.DID) -> list[str]:
    """Walk standings_weekly_scores.php?week=N for each week (`weeks` is a list,
    or "auto" to discover the division's played weeks — see _walk_weeks), follow
    every 'view score sheet' (scores.php) link, and save the rendered HTML.
    Resumable: skips sheets already on disk. The raw archive is the durable
    backfill record."""
    import re as _re

    from .parse.weekly_scores import parse_week_index

    out_root = Path(out_root) if out_root is not None else config.division_root(did) / "scores"
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

    with _browser_page(headless) as page:
        def fetch_index(wk: int) -> str:
            return cleared(page, config.url("weekly_scores", week=wk, did=did))

        for wk, idx_html in _walk_weeks(weeks, fetch_index):
            wkdir = out_root / f"week_{wk:02d}"
            wkdir.mkdir(parents=True, exist_ok=True)
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


_PROFILE_TABS = {"main": "", "h2h": "&xTab=12", "trends": "&xTab=33", "rivals": "&xTab=5"}


def _roster_player_ids(did: int = config.DID) -> list[str]:
    from .parse.roster import parse_roster_file
    grids = sorted(config.division_root(did).glob("*/roster_grid.html"))
    if not grids:
        return []
    return sorted({p.player_id for p in parse_roster_file(grids[-1])})


def harvest_profiles(player_ids: list[str] | None = None, out_root: str | Path = "data/raw/profiles",
                     tabs=("rivals", "h2h", "trends", "main"), drill_rivals: bool = True,
                     headless: bool = True, did: int = config.DID) -> int:
    """Harvest player profiles into data/raw/profiles/<id>/ (player-keyed,
    division-independent; `did` only selects whose roster grid supplies the
    default player_ids). Resumable (skips files already on disk), spaced,
    fail-soft PER PAGE for nav errors (logs and continues — a re-run resumes).
    With drill_rivals, follows each RIVALS link for per-game lifetime H2H.
    Rate-limit-friendly: slow + bounded.

    Challenge handling (2026-06-11 14022 harvests): the poolshooters.com
    challenge clears on a fresh goto — sometimes not for ~40 min on a given
    runner — and once ONE page clears, the context's cookie un-gates the rest.
    So the first fetch retries goto hard (~5 min); an uncleared challenge then
    ABORTS the run loudly instead of silently grinding 36s on every page
    (observed: 58 min / 0 pages, exit 0). Re-dispatch resumes from disk."""
    from playwright.sync_api import sync_playwright

    from .parse.profile import parse_profile_rivals

    out_root = Path(out_root)
    player_ids = player_ids or _roster_player_ids(did)
    base = lambda pid: f"{config.HOST_POOLSHOOTERS}/stats.php?playerSelected=Y&playerID={pid}"
    saved = 0
    cookie_landed = False  # context has cleared the challenge at least once
    challenged = 0
    streak = 0  # consecutive challenged pages

    class _ChallengeStuck(Exception):
        """Uncleared bot-challenge — abort the whole run, never grind."""

    def cleared(page, url: str, attempts: int = 1) -> str:
        html = ""
        for _ in range(attempts):
            try:
                page.goto(url, wait_until="domcontentloaded", timeout=30000)
            except Exception as exc:  # noqa: BLE001
                print(f"[harvest] nav {url}: {exc}")
                return ""
            for _ in range(6):
                html = page.content()
                if not fetch.is_challenge(html):
                    return html
                page.wait_for_timeout(6000)
        return html

    with sync_playwright() as p:
        browser = p.chromium.launch(headless=headless)
        page = browser.new_context(user_agent=fetch.DEFAULT_UA, locale="en-US").new_page()

        def get(url: str, path: Path) -> str:
            nonlocal saved, cookie_landed, challenged, streak
            if path.exists() and path.stat().st_size > 500:
                return path.read_text(encoding="utf-8", errors="replace")
            html = cleared(page, url, attempts=8 if not cookie_landed else 1)
            if html and not fetch.is_challenge(html):
                cookie_landed = True
                streak = 0
                path.parent.mkdir(parents=True, exist_ok=True)
                path.write_text(html, encoding="utf-8")
                saved += 1
                page.wait_for_timeout(1500)  # polite
            elif html:  # still the challenge page ("" = nav error, fail-soft)
                challenged += 1
                streak += 1
                if not cookie_landed or streak >= 8:
                    raise _ChallengeStuck(url)
            return html

        try:
            for pid in player_ids:
                pdir = out_root / pid
                for name in tabs:
                    get(base(pid) + _PROFILE_TABS[name], pdir / f"{name}.html")
                if drill_rivals:
                    rfile = pdir / "rivals.html"
                    if rfile.exists():
                        _, rivals = parse_profile_rivals(rfile.read_text(encoding="utf-8", errors="replace"))
                        for r in rivals:
                            get(base(pid) + f"&xTab=5&rival={r.rival_id}",
                                pdir / f"rival_{r.rival_id}.html")
        except _ChallengeStuck as exc:
            print(f"[harvest] uncleared bot-challenge — aborting the run ({exc}); "
                  f"re-dispatch resumes from disk")
        finally:
            browser.close()
    print(f"[harvest] saved {saved} new profile pages ({challenged} challenged skip(s))")
    return saved


def _parse_weeks(spec: str) -> list[int] | str:
    if spec.strip().lower() == "auto":
        return "auto"
    if "-" in spec:
        lo, hi = spec.split("-", 1)
        return list(range(int(lo), int(hi) + 1))
    return [int(x) for x in spec.split(",") if x]


def main() -> None:
    parser = argparse.ArgumentParser(description="NAPA browser fetcher (Chromium)")
    parser.add_argument("--date", default=dt.date.today().isoformat())
    parser.add_argument("--did", type=int, default=config.DID,
                        help="division id (default: %(default)s)")
    parser.add_argument("--all-divisions", action="store_true",
                        help="daily scrape: loop every registry division with scrape=True")
    parser.add_argument("--root", default=None,
                        help="override archive root (single-division daily scrape only; "
                             "default: data/raw/<did>)")
    parser.add_argument("--headed", action="store_true", help="run with a visible browser")
    parser.add_argument("--capture-url", help="one-off: capture a page's JS assets + HTML")
    parser.add_argument("--out", help="output dir for --capture-url")
    parser.add_argument("--backfill-weeks",
                        help='e.g. 1-27, 5,6 or "auto" : backfill score sheets')
    parser.add_argument("--explore-profile", help="player_id : capture profile tabs + XHR")
    parser.add_argument("--harvest", action="store_true", help="harvest roster profiles")
    parser.add_argument("--harvest-tabs", default="rivals,h2h,trends,main",
                        help="comma tabs to harvest")
    parser.add_argument("--harvest-drill", default="1", help="1=drill rivals, 0=tabs only")
    args = parser.parse_args()

    if args.harvest:
        harvest_profiles(tabs=tuple(args.harvest_tabs.split(",")),
                         drill_rivals=args.harvest_drill == "1", headless=not args.headed,
                         did=args.did)
        return

    if args.capture_url:
        capture_assets(args.capture_url, args.out or "data/raw/_assets", headless=not args.headed)
        return

    if args.explore_profile:
        explore_profile(args.explore_profile, args.out or "data/raw/profile_explore",
                        headless=not args.headed)
        return

    if args.backfill_weeks:
        backfill_score_sheets(_parse_weeks(args.backfill_weeks), headless=not args.headed,
                              did=args.did)
        return

    # Daily scrape: the chosen divisions, one shared browser page.
    dids = config.active_dids() if args.all_divisions else [args.did]
    root_for: Callable[[int], Path] = config.division_root
    if args.root and not args.all_divisions:
        root_for = lambda _did: Path(args.root)  # noqa: E731 — CLI override
    results = fetch_divisions_browser(dids, date=args.date, headless=not args.headed,
                                      root_for=root_for)

    # Heartbeat: ONE write after the loop, at the archive top level,
    # independent of division roots.
    hb = fetch.write_heartbeat(fetch.ARCHIVE_ROOT, {
        "mode": "browser",
        "run_date": args.date,
        "divisions": results,
    })
    print(f"[heartbeat] {hb}")


if __name__ == "__main__":
    main()
