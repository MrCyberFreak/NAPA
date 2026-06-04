"""Weekly-scores parser -> per-game player-vs-player results (the `games` grain).

Stub — implemented after the roster parser. NOTE: the exact page shape is not
yet confirmed (no per-game page captured). Capture one
`standings_weekly_scores.php?...&week=N` page first, then pin this parser to it.
Players seen here are a SUPERSET of the roster (subs play), so do not constrain
output to roster membership.
"""

from __future__ import annotations


def parse_weekly_scores(html: str):
    raise NotImplementedError("weekly-scores parser pending a confirmed fixture")
