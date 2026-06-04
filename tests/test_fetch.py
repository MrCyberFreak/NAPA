"""Phase 3 fetcher tests — against a mocked transport (no live network).

Verifies the archive path, write-on-change behavior, and fail-soft stop.
"""

from __future__ import annotations

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
