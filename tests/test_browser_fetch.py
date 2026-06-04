"""Browser challenge-clearing core tests (no real browser needed)."""

from __future__ import annotations

from src import fetch
from src.browser_fetch import capture_clearing_challenge

CHALLENGE = (
    "<html><head><title>One moment, please...</title>"
    "<script>setTimeout(function(){window.location.reload();},5000)</script>"
    "</head></html>"
)
REAL = "<html><body>real roster grid</body></html>"


def test_clears_after_a_couple_reloads():
    seq = [CHALLENGE, CHALLENGE, REAL]
    i = {"n": 0}
    content, tries = capture_clearing_challenge(
        get_content=lambda: seq[min(i["n"], len(seq) - 1)],
        advance=lambda: i.__setitem__("n", i["n"] + 1),
        attempts=6,
    )
    assert "real" in content and not fetch.is_challenge(content)
    assert tries == 3


def test_gives_up_when_challenge_persists():
    content, tries = capture_clearing_challenge(
        get_content=lambda: CHALLENGE,
        advance=lambda: None,
        attempts=4,
    )
    assert fetch.is_challenge(content)
    assert tries == 4
