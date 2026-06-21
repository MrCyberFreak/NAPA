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


def _sheet_captured(target: Path) -> bool:
    """True only if `target` is an existing score sheet that actually holds
    games. A pre-season / not-yet-played sheet is a "NO MATCH(ES) PLAYED" shell
    — >500 bytes but ZERO game tables — so a size-only resume check treated it
    as done and never re-fetched the populated sheet once the match was played.
    A shell parses to games==[]; treat it as NOT captured so it is re-fetched
    (observed 14050/14022: a whole season of shells pre-saved at onboarding
    masked every real score sheet)."""
    from .parse.weekly_scores import parse_score_sheet_file

    return target.exists() and bool(parse_score_sheet_file(target).games)


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
    cookie_landed = False  # context has cleared the poolshooters challenge at least once

    def cleared(page, url: str, attempts: int = 1) -> str:
        """Navigate + clear the JS challenge, retrying the WHOLE goto up to
        `attempts` times. The first index fetch on a fresh runner may need
        several tries to land the poolshooters challenge cookie — the goto
        itself can time out while the host slow-walks the interstitial. Without
        this, a single slow nav aborted the entire backfill (observed 2026-06-12,
        13205). Mirrors the harvest first-fetch retry (PR #19)."""
        for _ in range(attempts):
            try:
                page.goto(url, wait_until="domcontentloaded", timeout=45000)
            except Exception as exc:  # noqa: BLE001 — slow challenge / transient nav; retry
                print(f"[backfill] nav {url}: {exc} (retry)")
                continue
            for _ in range(6):
                html = page.content()
                if not fetch.is_challenge(html):
                    return html
                page.wait_for_timeout(6000)
        return ""  # every attempt failed or stayed challenged — caller aborts fail-soft

    with _browser_page(headless) as page:
        def fetch_index(wk: int) -> str:
            # Hard-retry the FIRST fetch (cookie not yet landed) to clear the
            # challenge; once any page clears, the context cookie un-gates the rest.
            nonlocal cookie_landed
            html = cleared(page, config.url("weekly_scores", week=wk, did=did),
                           attempts=8 if not cookie_landed else 1)
            if html and not fetch.is_challenge(html):
                cookie_landed = True
            return html

        for wk, idx_html in _walk_weeks(weeks, fetch_index):
            wkdir = out_root / f"week_{wk:02d}"
            wkdir.mkdir(parents=True, exist_ok=True)
            (wkdir / "_index.html").write_text(idx_html, encoding="utf-8")
            urls = parse_week_index(idx_html)
            print(f"[backfill] week {wk}: {len(urls)} score sheets")
            for url in urls:
                tid = _re.search(r"tid=(\d+)", url)
                target = wkdir / f"{tid.group(1) if tid else 'x'}.html"
                if _sheet_captured(target):
                    continue  # resume — a real, populated capture (not a shell)
                html = cleared(page, url)
                if html and not fetch.is_challenge(html):
                    target.write_text(html, encoding="utf-8")
                    saved.append(str(target))
                page.wait_for_timeout(1200)
    print(f"[backfill] saved {len(saved)} new score sheets")
    return saved


def _discover_cleared(page, url: str, attempts: int = 1) -> str:
    """Navigate + clear the JS challenge, retrying the whole goto up to `attempts`
    times (mirrors backfill_score_sheets.cleared). Returns '' on a hard nav error
    or a challenge that never clears — the caller decides skip-vs-abort. A still-
    challenge result (non-empty but is_challenge) is returned as-is so a sweep can
    tell 'host-wide abort' from 'transient nav skip'."""
    for _ in range(attempts):
        try:
            page.goto(url, wait_until="domcontentloaded", timeout=30000)
        except Exception as exc:  # noqa: BLE001 — slow challenge / transient nav; retry
            print(f"[discover] nav {url}: {exc} (retry)")
            continue
        for _ in range(6):
            html = page.content()
            if not fetch.is_challenge(html):
                return html
            page.wait_for_timeout(6000)
        return html  # stayed challenged through all polls — caller aborts host-wide
    return ""        # every goto attempt errored — fail-soft skip this did


def discover_scout(high: int | None = None, low: int = 0, headless: bool = True,
                   run_date: str | None = None) -> dict:
    """SCOUT (validation): walk did DOWNWARD from `high` (default the highest
    curated did, 14050), record one index row per division.php, and STOP at the
    first NoCo slug that repeats a NoCo slug already seen this run — proving a
    NoCo league recurs at a lower did (13077 shares 14050's slug → the
    (14050, 13077) pair). Non-NoCo divisions ARE catalogued but do NOT drive the
    stop: the did space is wall-to-wall other-region divisions whose slugs also
    repeat (observed: friday-swmo-rack-royal-lc at 14016/14015 stops a naive
    any-slug scout in ~36 dids, long before the NoCo case). Single runner.
    Updates the master index + _historical.json; returns a proof report.
    Catalog-only: the current divisions it passes are already archived by the
    daily scrape, so it writes no HTML (the full sweep is what archives hits)."""
    from . import division_index as dindex
    from .parse.division import parse_division

    high = high if high is not None else max(config.DIVISIONS)
    run_date = run_date or dt.date.today().isoformat()
    seen: dict[str, int] = {}          # slug -> first (highest) did seen this run
    new_rows: dict[str, dict] = {}
    proof: dict | None = None
    cookie_landed = False
    noco = 0

    with _browser_page(headless) as page:
        for did in range(high, low - 1, -1):
            html = _discover_cleared(page, config.url("division", did=did),
                                     attempts=8 if not cookie_landed else 1)
            if not html:
                print(f"[discover] {did}: nav failed — skipping (fail-soft)")
                continue
            if fetch.is_challenge(html):
                print(f"[discover] {did}: challenge not cleared — aborting (host-wide)")
                break
            cookie_landed = True
            dp = parse_division(html)
            row = dindex.make_row(did, dp, run_date)
            new_rows[str(did)] = row
            noco += int(row["is_noco"])
            page.wait_for_timeout(1500)  # polite
            if not dp.resolved or not row["is_noco"]:
                continue  # non-NoCo: catalogued, but never drives the stop
            if dp.slug in seen:
                proof = {"slug": dp.slug, "first_did": seen[dp.slug], "repeat_did": did}
                print(f"[discover] NoCo REPEAT slug {dp.slug!r}: {seen[dp.slug]} <- {did} "
                      f"— a NoCo league's prior session; stopping scout.")
                break
            seen[dp.slug] = did

    merged = dindex.merge_shards(dindex.load_index(), new_rows.values())
    dindex.save_index(merged, run_date=run_date)
    dindex.save_historical(dindex.build_historical(merged), run_date=run_date)
    floor = min((int(d) for d in new_rows), default=high)
    print(f"[discover] scout catalogued {len(new_rows)} dids ({noco} NoCo) "
          f"from {high} down to {floor}")
    if not proof:
        print("[discover] WARNING: no NoCo slug repeat in range — too shallow, or "
              "curated slugs drifted (14050/13077 were expected to repeat).")
    return {"proof": proof, "catalogued": len(new_rows), "noco": noco, "high": high}


def discover_sweep(high: int, low: int, shard: str | None = None,
                   headless: bool = True, run_date: str | None = None) -> dict:
    """FULL SWEEP: walk [high..low] DOWNWARD (this runner's shard residue when
    sharded), record one index row per probed did, and ARCHIVE full HTML only for
    NoCo hits. Resumable: skips dids already in the master index or this shard's
    JSONL. Each runner appends ONLY to its own shard file; a later
    `python -m src.division_index --merge` folds them into the master index and
    derives _historical.json. An uncleared challenge aborts THIS shard (never
    grinds); re-dispatch once on a fresh runner (CLAUDE.md)."""
    from . import division_index as dindex
    from .parse.division import parse_division

    run_date = run_date or dt.date.today().isoformat()
    i = n = None
    if shard:
        i, n = dindex.parse_shard(shard)
        sfile = dindex.shard_path(shard)
    else:
        sfile = dindex.INDEX_PATH.parent / "_division_index.shard_1of1.jsonl"

    already = set(dindex.load_index())            # dids from prior merged runs
    already |= set(dindex.load_shard_rows(sfile))  # this shard's own progress (resume)
    cookie_landed = False
    probed = noco = skipped = 0

    with _browser_page(headless) as page:
        for did in range(high, low - 1, -1):
            if n and (did % n) != (i - 1):         # not this shard's residue
                continue
            if str(did) in already:
                skipped += 1
                continue
            html = _discover_cleared(page, config.url("division", did=did),
                                     attempts=8 if not cookie_landed else 1)
            if not html:
                print(f"[discover] {did}: nav failed — skipping (fail-soft)")
                continue
            if fetch.is_challenge(html):
                print(f"[discover] {did}: challenge not cleared — aborting shard (host-wide)")
                break
            cookie_landed = True
            dp = parse_division(html)
            row = dindex.make_row(did, dp, run_date)
            dindex.append_shard_row(sfile, row)
            probed += 1
            if row["is_noco"] and dp.resolved:
                noco += 1
                fetch.write_on_change("division", html.encode("utf-8"), run_date,
                                      root=config.division_root(did))
            page.wait_for_timeout(1500)            # polite

    print(f"[discover] sweep shard {shard or '1/1'}: probed {probed} "
          f"({noco} NoCo archived), skipped {skipped} already-indexed -> {sfile}")
    return {"probed": probed, "noco": noco, "skipped": skipped, "shard_file": str(sfile)}


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
    With drill_rivals, follows each RIVALS link for the per-game lifetime
    per-opponent record (the "h2h" tab key below is NAPA's hill-hill tab, xTab=12).
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


def harvest_match_history(player_ids: list[str] | None = None,
                          out_root: str | Path = "data/raw/profiles",
                          tabs: tuple[int, ...] = (2, 3, 4), max_pages: int = 200,
                          headless: bool = True, did: int = config.DID) -> int:
    """Harvest per-player career MATCH HISTORY (xTab=2/3/4 = league 8/9/10-ball).

    For each player x tab, walk the &start= pagination (10 matches/page) following
    the NEXT>>> link, archiving each page RAW to
    data/raw/profiles/<id>/match_<tab>_<start>.html BEFORE parsing (hard rule).
    Player-keyed + division-independent, same dir as the other profile tabs.

    Reuses the harvest's challenge discipline (cleared()/cookie_landed/_ChallengeStuck):
    the first goto retries hard to land the challenge cookie, then one cookie un-gates
    the rest; an uncleared challenge ABORTS the run loudly (never grinds). Resumable
    (skips pages already >500B on disk), polite waits, fail-soft per page.

    The next &start is READ from the NEXT>>> link (not blindly +10); the walk stops
    when no NEXT link is present or start fails to strictly increase (loop guard),
    capped at max_pages."""
    from playwright.sync_api import sync_playwright

    from .parse.match_history import next_start_from_html

    out_root = Path(out_root)
    player_ids = player_ids or _roster_player_ids(did)
    base = lambda pid: f"{config.HOST_POOLSHOOTERS}/stats.php?playerSelected=Y&playerID={pid}"
    saved = 0
    cookie_landed = False
    challenged = 0
    streak = 0

    class _ChallengeStuck(Exception):
        """Uncleared bot-challenge — abort the whole run, never grind."""

    def cleared(page, url: str, attempts: int = 1) -> str:
        html = ""
        for _ in range(attempts):
            try:
                page.goto(url, wait_until="domcontentloaded", timeout=30000)
            except Exception as exc:  # noqa: BLE001
                print(f"[match-history] nav {url}: {exc}")
                return ""
            for _ in range(6):
                html = page.content()
                if not fetch.is_challenge(html):
                    return html
                page.wait_for_timeout(6000)
        return html

    with sync_playwright() as p:
        browser = p.chromium.launch(headless=headless)
        context = browser.new_context(user_agent=fetch.DEFAULT_UA, locale="en-US")
        # Throughput trim: abort non-essential resources. The match HTML is
        # server-rendered in the document, so CSS/images/fonts/media are pure
        # overhead. JS is KEPT (the "One moment" bot-challenge needs it to clear);
        # the document and XHR are KEPT. Single-context — no extra host concurrency,
        # so the host-friendly rule still holds.
        context.route("**/*", lambda route: (
            route.abort() if route.request.resource_type in
            ("stylesheet", "image", "font", "media") else route.continue_()))
        page = context.new_page()

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
                page.wait_for_timeout(400)  # polite
            elif html:
                challenged += 1
                streak += 1
                if not cookie_landed or streak >= 8:
                    raise _ChallengeStuck(url)
            return html

        try:
            for pid in player_ids:
                pdir = out_root / pid
                for tab in tabs:
                    start = 0
                    seen_starts: set[int] = set()
                    for _ in range(max_pages):
                        if start in seen_starts:  # loop guard
                            break
                        seen_starts.add(start)
                        url = f"{base(pid)}&xTab={tab}&start={start}"
                        html = get(url, pdir / f"match_{tab}_{start}.html")
                        if not html or fetch.is_challenge(html):
                            break  # nav error / challenge — fail-soft, resume later
                        # Pagination is the same NEXT>>> mechanism on every tab, so
                        # page generically — capture is decoupled from league parsing
                        # (Tournaments/Local-Duels archive raw here, parse later).
                        nxt = next_start_from_html(html)
                        if nxt is None or nxt <= start:  # last page / no progress
                            break
                        start = nxt
        except _ChallengeStuck as exc:
            print(f"[match-history] uncleared bot-challenge — aborting the run ({exc}); "
                  f"re-dispatch resumes from disk")
        finally:
            browser.close()
    print(f"[match-history] saved {saved} new pages ({challenged} challenged skip(s))")
    return saved


def _parse_weeks(spec: str) -> list[int] | str:
    if spec.strip().lower() == "auto":
        return "auto"
    if "-" in spec:
        lo, hi = spec.split("-", 1)
        return list(range(int(lo), int(hi) + 1))
    return [int(x) for x in spec.split(",") if x]


# --------------------------------------------------------------------------- #
# Scheduled (day-after-play) run — the post-rollout cron entry point
# --------------------------------------------------------------------------- #

def _denver_today() -> dt.date:
    """Today's date in the divisions' timezone (America/Denver). The league
    operates in MT; "yesterday's league night" must be reckoned locally, not in
    UTC. Falls back to the UTC date if tz data is unavailable (the cron fires at
    15:00 UTC ≈ 09:00 MT, so the UTC and Denver calendar dates agree anyway)."""
    try:
        from zoneinfo import ZoneInfo
        return dt.datetime.now(ZoneInfo("America/Denver")).date()
    except Exception:  # noqa: BLE001 — no tz database (bare Windows); see docstring
        return dt.datetime.now(dt.timezone.utc).date()


def _pending_for_divisions(dids: Iterable[int], as_of: str) -> dict[int, list[dict]]:
    """Profile-free pending-makeup probe: load each division's newest roster +
    schedule + score sheets into an IN-MEMORY DB and run db.pending_matches.
    Skips the slow league-wide profile pass of a full rebuild — the catch-up
    queue only needs matches-vs-games per division. Never raises (the raw
    archive is the durable record; this only enriches the queue with makeups).
    Rows are materialized to plain dicts so they outlive the connection."""
    from . import db
    from .parse.roster import parse_roster_file
    from .parse.schedule import parse_schedule_file
    from .parse.weekly_scores import parse_score_sheet_file

    pending: dict[int, list[dict]] = {}
    try:
        conn = db.connect(":memory:")
        db.init_db(conn)
        for did in dids:
            root = config.division_root(did)
            grids = sorted(root.glob("*/roster_grid.html"))
            scheds = sorted(root.glob("*/schedule.html"))
            if not grids or not scheds:
                continue
            fixtures = parse_schedule_file(scheds[-1])
            season = db._division_season(did, fixtures)
            db.load_roster(conn, parse_roster_file(grids[-1]),
                           captured_date=grids[-1].parent.name, season=season,
                           division_id=did)
            db.load_schedule(conn, fixtures, season=season, division_id=did)
            sheets = [parse_score_sheet_file(f)
                      for f in sorted(root.glob("scores/week_*/*.html"))
                      if f.name != "_index.html"]
            if sheets:
                db.load_score_sheets(conn, sheets, season=season, division_id=did)
            pending[did] = [dict(r) for r in
                            db.pending_matches(conn, as_of, season=season, division_id=did)]
        conn.close()
    except Exception as exc:  # noqa: BLE001 — best-effort; queue still carries skips
        print(f"[scheduled] pending probe failed ({exc}); queue carries skips only.")
    return pending


# --------------------------------------------------------------------------- #
# Season-rollover discovery (states.php) — runs daily inside scheduled_run
# --------------------------------------------------------------------------- #

_STATES_ROOT = fetch.ARCHIVE_ROOT / "_states"


def fetch_states(date: str | None = None, headless: bool = True, page=None) -> Path | None:
    """Capture the league-discovery page (states.php) into
    data/raw/_states/<date>/states.html via write-on-change — it only commits
    when a rollover / new league actually changes the page. Reuses the shared
    browser `page` when given. Raises BotChallengeError on an uncleared
    challenge; _run_discovery swallows it (discovery is fail-soft)."""
    date = date or dt.date.today().isoformat()
    written = fetch_pages_browser(pages=[("states", {})], date=date, root=_STATES_ROOT,
                                  headless=headless, page=page, raise_on_challenge=True)
    return written.get("states")


def _latest_states_file() -> Path | None:
    """Newest on-disk states.html (today's capture, or the last that changed
    when today's was unchanged by write-on-change)."""
    files = sorted(_STATES_ROOT.glob("*/states.html"))
    return files[-1] if files else None


def _write_states_parsed(date_dir: Path, rows) -> Path:
    """Parsed NoCo rows next to states.html — the diffable record + the source
    for the Actions discovery summary."""
    out = date_dir / "parsed.json"
    out.write_text(json.dumps([r.to_dict() for r in rows], indent=2) + "\n",
                   encoding="utf-8")
    return out


def _run_discovery(date_str: str, run_date_iso: str, page) -> set[int]:
    """Fetch + parse states.php, reconcile rollovers into the registry, and
    return the rollover dids that became active THIS run (to fold into the
    scrape set). Fail-soft: ANY failure — a host challenge, a parse error —
    logs and returns an empty set; discovery NEVER crashes the scheduled run."""
    from . import discovery
    from .parse.states import parse_states_file
    try:
        fetch_states(date=date_str, page=page)
    except Exception as exc:  # noqa: BLE001 — discovery must never crash the run
        print(f"[discovery] states.php capture failed ({exc}); skipping discovery this run.")
        return set()
    latest = _latest_states_file()
    if latest is None:
        print("[discovery] no states.html on disk; skipping reconcile.")
        return set()
    rows = parse_states_file(latest)
    if not rows:
        # A challenge-free page with zero NoCo rows means the group header
        # changed (NAPA renamed "NAPA of Northern Colorado") — ALERT, do NOT
        # silently treat it as "no rollovers".
        print("[discovery] ALERT: 0 NoCo rows on states.php — the league-group "
              "header may have changed; not reconciling this run.")
        return set()
    res = discovery.reconcile_registry(rows, discovery.load_registry(), run_date_iso)
    discovery.save_registry(res.registry, run_date=run_date_iso)
    _write_states_parsed(latest.parent, rows)
    for sdid, e in res.rollovers.items():
        print(f"[discovery] ROLLOVER did={sdid} slug={e['slug']} "
              f"predecessor={e['predecessor']} -> scraping on first appearance")
    for sdid, e in res.unknown.items():
        print(f"[discovery] NEW LEAGUE did={sdid} \"{e['name']}\" slug={e['slug']} "
              "— onboard via napa-onboard-division (report-only, not scraped)")
    return set(res.newly_activated)


def scheduled_run(run_date: dt.date | None = None, headless: bool = True,
                  backfill: bool = True, all_divisions: bool = False) -> dict:
    """Day-after-play scrape + catch-up — replaces the twice-daily
    --all-divisions sweep.

    Pulls the divisions whose league night was yesterday (config.divisions_due)
    PLUS the catch-up queue carryover (src.catchup: divisions skipped by a prior
    abort, or owed a makeup), captures their pages and auto-backfills their new
    score sheets in one pass, then re-derives the queue for next time. So every
    onboarded division is refreshed the morning after it plays, and any piece
    missed for ANY reason — a host abort, a makeup played off-schedule — is
    carried forward and retried on the next run regardless of which division
    that run is otherwise for.

    all_divisions=True SCRAPES every active division daily (so all rosters /
    standings / schedules refresh and every roster/skill/standings change shows
    up in the committed daily diff) while keeping BACKFILL targeted to the
    day-after-play + catch-up set — an all-division score-sheet walk is the
    sustained load that escalates the host bot-challenge into aborts."""
    from . import catchup

    run_date = run_date or _denver_today()
    date_str = run_date.isoformat()
    queue = catchup.load_queue()
    due = config.divisions_due(run_date)
    # Backfill set stays day-after-play (+ catch-up) even when scraping all.
    backfill_dids = set(catchup.run_set(due, queue))

    # Discovery + the page scrape share ONE browser context (challenge cookies
    # amortize). Discovery runs FIRST and DAILY — even when nothing is due — so a
    # season rollover is caught the morning it appears; it is fail-soft (an
    # uncleared states.php challenge skips discovery, never crashes the run) and
    # folds any newly-active rollover did into THIS run's scrape set so its first
    # night is captured even off its weekday.
    with _browser_page(headless) as page:
        newly = _run_discovery(date_str, date_str, page)
        backfill_dids |= newly                       # a new rollover also backfills
        # Scrape set: ALL active divisions daily (all_divisions) so every page
        # refreshes; else just the day-after-play due set. Rollovers always fold in.
        base = config.active_dids() if all_divisions else due
        dids = catchup.run_set(sorted(set(base) | newly), queue)
        carry = sorted(int(d) for d in queue)
        mode = "all-divisions scrape" if all_divisions else "day-after-play"
        print(f"[scheduled] {date_str} ({mode}): due={due or []} + carryover={carry or []}"
              + (f" + rollovers={sorted(newly)}" if newly else "")
              + f" -> scrape {dids or []}")
        if not dids:
            print("[scheduled] nothing to scrape — discovery-only run.")
            return {"due": due, "scraped": [], "results": {}, "queue": {},
                    "discovered": sorted(newly)}
        # Page scrape (the same shared context, so the states.php clear carries).
        results = fetch_divisions_browser(dids, date=date_str, page=page)
    aborted = len(results) < len(dids)  # a host-wide challenge cut the run short

    # Auto-backfill each division actually reached — but not if the host just
    # aborted on us (don't hammer a challenging host; the queue retries it next
    # run). Backfill clears already-on-disk sheets and only fetches new ones,
    # which is how an off-schedule makeup logged under an earlier week gets
    # picked up the morning after it's played.
    if backfill and not aborted:
        for did in dids:
            if str(did) in results and did in backfill_dids:
                backfill_score_sheets("auto", headless=headless, did=did)
    elif aborted:
        print("[scheduled] host aborted page scrape — skipping backfill this run "
              "(carried divisions retry next run).")

    fetch.write_heartbeat(fetch.ARCHIVE_ROOT, {
        "mode": "scheduled-all" if all_divisions else "scheduled",
        "run_date": date_str, "due": due, "carryover": carry,
        "backfilled": sorted(d for d in backfill_dids if str(d) in results),
        "divisions": results,
    })

    pending = _pending_for_divisions([d for d in dids if str(d) in results], date_str)
    new_queue = catchup.reconcile(dids, results, pending, queue, date_str)
    catchup.save_queue(new_queue, run_date=date_str)
    print(f"[scheduled] catch-up queue now: {sorted(int(d) for d in new_queue) or []}")
    return {"due": due, "scraped": dids, "results": results, "queue": new_queue,
            "discovered": sorted(newly)}


def main() -> None:
    parser = argparse.ArgumentParser(description="NAPA browser fetcher (Chromium)")
    parser.add_argument("--date", default=None,
                        help="archive date (YYYY-MM-DD); default today, or the "
                             "Denver-local date under --scheduled")
    parser.add_argument("--did", type=int, default=config.DID,
                        help="division id (default: %(default)s)")
    parser.add_argument("--all-divisions", action="store_true",
                        help="daily scrape: loop every registry division with scrape=True")
    parser.add_argument("--scheduled", action="store_true",
                        help="day-after-play run: scrape + auto-backfill only the "
                             "divisions that played yesterday plus the catch-up "
                             "queue carryover (the post-rollout cron entry point)")
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
    parser.add_argument("--harvest-match-history", action="store_true",
                        help="harvest per-player career match history (xTab 2/3/4 "
                             "= 8/9/10-ball), following &start= pagination")
    parser.add_argument("--match-history-tabs", default="2,3,4",
                        help="comma xTabs for --harvest-match-history (2=8b,3=9b,4=10b)")
    parser.add_argument("--discover-scout", action="store_true",
                        help="discovery: walk did DOWN from the highest curated did to "
                             "the first slug repeat (validates the sweep finds prior sessions)")
    parser.add_argument("--discover-range", nargs=2, type=int, metavar=("HIGH", "LOW"),
                        help="discovery: full sweep of dids [HIGH..LOW] downward "
                             "(index every did, archive HTML for NoCo hits)")
    parser.add_argument("--discover-shard", default=None, metavar="i/N",
                        help="with --discover-range: this runner's shard residue, e.g. 3/4")
    parser.add_argument("--discover-low", type=int, default=0,
                        help="with --discover-scout: stop floor (default 0)")
    args = parser.parse_args()

    if args.discover_scout:
        discover_scout(low=args.discover_low, headless=not args.headed)
        return

    if args.discover_range:
        high, low = args.discover_range
        discover_sweep(high, low, shard=args.discover_shard, headless=not args.headed)
        return

    if args.harvest_match_history:
        tabs = tuple(int(t) if t.isdigit() else t
                     for t in args.match_history_tabs.split(",") if t)
        if args.all_divisions:
            # Union of every active division's roster -> all NoCo players, once each
            # (a player rostered in >1 division is harvested a single time).
            seen: set[str] = set()
            ids: list[str] = []
            for d in config.active_dids():
                for pid in _roster_player_ids(d):
                    if pid not in seen:
                        seen.add(pid)
                        ids.append(pid)
            print(f"[match-history] {len(ids)} players across {len(config.active_dids())} divisions")
            harvest_match_history(player_ids=ids, tabs=tabs, headless=not args.headed)
        else:
            harvest_match_history(tabs=tabs, headless=not args.headed, did=args.did)
        return

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

    if args.scheduled:
        # --date overrides the computed Denver-local date (testing/backfilled runs).
        # --all-divisions: scrape EVERY active division daily (backfill stays
        # day-after-play + catch-up). Without it, scrape is day-after-play too.
        rd = dt.date.fromisoformat(args.date) if args.date else None
        scheduled_run(run_date=rd, headless=not args.headed,
                      all_divisions=args.all_divisions)
        return

    # Daily scrape: the chosen divisions, one shared browser page.
    date_str = args.date or dt.date.today().isoformat()
    dids = config.active_dids() if args.all_divisions else [args.did]
    root_for: Callable[[int], Path] = config.division_root
    if args.root and not args.all_divisions:
        root_for = lambda _did: Path(args.root)  # noqa: E731 — CLI override
    results = fetch_divisions_browser(dids, date=date_str, headless=not args.headed,
                                      root_for=root_for)

    # Heartbeat: ONE write after the loop, at the archive top level,
    # independent of division roots.
    hb = fetch.write_heartbeat(fetch.ARCHIVE_ROOT, {
        "mode": "browser",
        "run_date": date_str,
        "divisions": results,
    })
    print(f"[heartbeat] {hb}")


if __name__ == "__main__":
    main()
