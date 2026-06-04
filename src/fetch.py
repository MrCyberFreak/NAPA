"""Fetcher (Phase 3) — config-driven URL list -> raw HTML archive.

Stub. When implemented: pull pages templated on `did`, write
`data/raw/<date>/<name>.html`, write-on-change (skip if identical to last
capture), polite (real UA, spaced + jittered requests, fail-soft). Only
paper.playpool.io is fetchable here; poolshooters.com is bot-blocked (Phase 4).

The fetcher only saves bytes — it never parses — so it rarely breaks.
"""

from __future__ import annotations


def main() -> None:
    raise NotImplementedError("fetcher is Phase 3")


if __name__ == "__main__":
    main()
