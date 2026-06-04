"""Player-profile parser (summary view only).

Stub — implemented after the roster parser. IMPORTANT: a plain GET of
`stats.php?playerID=` only yields the summary header + current/highest CSRs.
The deep data (match history, H2H, rivals) is JS-tab-loaded and needs a real
browser — that is Phase 6, not here. This parser targets the summary only.
"""

from __future__ import annotations


def parse_profile(html: str):
    raise NotImplementedError("profile (summary) parser pending a captured fixture")
