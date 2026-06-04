"""Phase 3 fetcher tests — against a mocked transport (no live network).

Verifies the archive path, write-on-change behavior, and fail-soft stop.
"""

from __future__ import annotations

import json

import httpx
import pytest

from src import fetch

NO_SLEEP = lambda: None  # noqa: E731 — keep tests fast, no real spacing


def _client(handler):
    return httpx.Client(transport=httpx.MockTransport(handler))


def test_fetches_pages_into_dated_archive(tmp_path):
    def handler(request):
        return httpx.Response(200, content=b"<html>" + request.url.path.encode() + b"</html>")

    with _client(handler) as client:
        written = fetch.fetch_pages(client, date="2026-06-04", root=tmp_path, sleep=NO_SLEEP)

    assert set(written) == {"roster_grid", "schedule", "scratch"}
    for name in written:
        p = tmp_path / "2026-06-04" / f"{name}.html"
        assert p.exists() and written[name] == p


def test_write_on_change_skips_identical_capture(tmp_path):
    body = b"<html>same</html>"
    handler = lambda req: httpx.Response(200, content=body)  # noqa: E731

    with _client(handler) as client:
        first = fetch.fetch_pages(client, date="2026-06-04", root=tmp_path, sleep=NO_SLEEP)
        # A later date, identical bytes -> nothing new written.
        second = fetch.fetch_pages(client, date="2026-06-05", root=tmp_path, sleep=NO_SLEEP)

    assert all(v is not None for v in first.values())
    assert all(v is None for v in second.values())  # unchanged -> skipped
    assert not (tmp_path / "2026-06-05").exists()


def test_write_on_change_writes_when_content_differs(tmp_path):
    name, content = "roster_grid", b"v1"
    assert fetch.write_on_change(name, content, "2026-06-04", root=tmp_path) is not None
    # Same content, new date -> skipped.
    assert fetch.write_on_change(name, content, "2026-06-05", root=tmp_path) is None
    # Changed content -> written under the new date.
    out = fetch.write_on_change(name, b"v2", "2026-06-05", root=tmp_path)
    assert out == tmp_path / "2026-06-05" / "roster_grid.html"
    assert out.read_bytes() == b"v2"


def test_fail_soft_stops_without_raising(tmp_path):
    calls = {"n": 0}

    def handler(request):
        calls["n"] += 1
        if calls["n"] == 1:
            return httpx.Response(200, content=b"<html>ok</html>")
        return httpx.Response(503)  # host trouble on the 2nd page

    with _client(handler) as client:
        written = fetch.fetch_pages(client, date="2026-06-04", root=tmp_path, sleep=NO_SLEEP)

    # First page captured; run stopped at the failure (no retry-hammer).
    assert "roster_grid" in written
    assert "scratch" not in written
    assert calls["n"] == 2


def test_probe_classifies_ok_blocked_and_unreachable():
    def handler(request):
        host = request.url.host
        if "paper" in host:
            return httpx.Response(200, content=b"<html>roster grid</html>")
        if "scores" in host:
            return httpx.Response(403, content=b"Forbidden")
        raise httpx.ConnectError("no route to host")  # poolshooters

    with _client(handler) as client:
        results = {p.host: p for p in fetch.probe_hosts(client)}

    paper = results["paper.playpool.io"]
    assert paper.reachable and not paper.blocked and paper.status == 200
    scores = results["scores.playpool.io"]
    assert scores.reachable and scores.blocked and scores.status == 403
    pool = results["poolshooters.com"]
    assert not pool.reachable and pool.status is None


def test_heartbeat_is_written_with_timestamp(tmp_path):
    out = fetch.write_heartbeat(tmp_path, {"run_date": "2026-06-04", "captured": []})
    data = json.loads(out.read_text())
    assert out.name == "_heartbeat.json"
    assert data["run_date"] == "2026-06-04"
    assert "updated_utc" in data


_CHALLENGE_HTML = (
    "<html><head><title>One moment, please...</title>"
    "<script>(function(){setTimeout(function(){window.location.reload();},5000)}())</script>"
    "</head><body>spinner</body></html>"
)


def test_is_challenge_detects_reload_interstitial():
    assert fetch.is_challenge(_CHALLENGE_HTML)
    assert not fetch.is_challenge("<html><body>real roster grid</body></html>")


def test_fetch_clears_reload_challenge(tmp_path):
    seen: dict[str, int] = {}

    def handler(request):
        path = request.url.path
        seen[path] = seen.get(path, 0) + 1
        # roster_grid challenges once, then serves real content on the reload.
        if "roster_grid" in path and seen[path] == 1:
            return httpx.Response(200, text=_CHALLENGE_HTML)
        return httpx.Response(200, text=f"<html>real {path}</html>")

    with _client(handler) as client:
        written = fetch.fetch_pages(
            client, pages=[("roster_grid", {})], date="2026-06-04",
            root=tmp_path, sleep=NO_SLEEP, challenge_sleep=NO_SLEEP,
        )

    assert written["roster_grid"] is not None
    body = (tmp_path / "2026-06-04" / "roster_grid.html").read_bytes()
    assert b"real" in body and b"One moment" not in body
    assert seen["/roster_grid.php"] == 2  # cleared on the reload


def test_fetch_stops_and_archives_nothing_when_challenge_persists(tmp_path):
    handler = lambda req: httpx.Response(200, text=_CHALLENGE_HTML)  # noqa: E731

    with _client(handler) as client:
        written = fetch.fetch_pages(
            client, pages=[("roster_grid", {}), ("schedule", {})],
            date="2026-06-04", root=tmp_path, sleep=NO_SLEEP, challenge_sleep=NO_SLEEP,
        )

    assert "roster_grid" not in written  # not archived (no challenge interstitials)
    assert "schedule" not in written     # stopped (fail-soft)
    assert not (tmp_path / "2026-06-04").exists()


def test_probe_reports_challenge_verdict():
    handler = lambda req: httpx.Response(200, text=_CHALLENGE_HTML)  # noqa: E731
    with _client(handler) as client:
        results = fetch.probe_hosts(client, challenge_sleep=NO_SLEEP)
    assert all(r.verdict == "CHALLENGE" for r in results)
    assert all(r.reachable and r.challenge and not r.blocked for r in results)
