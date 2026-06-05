"""NAPA race lookup — CSR pair -> race lengths (the handicap matrix).

Transcribed verbatim from the official calculator's logic (races.napaleagues.com
/js/races.js, "NAPA Races v2.0.0"), captured once and encoded here as a STATIC
table — never fetched live. The calculator computes it by banded rules, not a
flat array, so this mirrors those rules exactly.

Rule structure (confirmed against real game outcomes in the live-scores data):
- The CLASS band is the STRONGER player's CSR:
    0-39 (D/E) | 40-49 (C) | 50-69 (B) | 70-89 (A) | 90+ (M/GM)
- Within a band, the race depends on the DIFF = stronger CSR - weaker CSR.
- The stronger player always races to the higher number.
"""

from __future__ import annotations

# Per band: ordered (diff_max_inclusive, race_stronger, race_weaker). The first
# row whose diff <= diff_max applies. diff == 0 (equal) hits the first row.
_BANDS: list[tuple[int, int, list[tuple[float, int, int]]]] = [
    (0, 39, [(19, 2, 2), (float("inf"), 3, 2)]),
    (40, 49, [(10, 3, 3), (26, 3, 2), (float("inf"), 4, 2)]),
    (50, 69, [(6, 4, 4), (18, 4, 3), (29, 5, 3), (39, 4, 2),
              (48, 5, 2), (float("inf"), 6, 2)]),
    (70, 89, [(5, 5, 5), (14, 5, 4), (21, 6, 4), (28, 5, 3), (36, 6, 3),
              (46, 7, 3), (56, 6, 2), (62, 7, 2), (float("inf"), 8, 2)]),
    (90, 10_000, [(4, 6, 6), (11, 6, 5), (17, 7, 5), (22, 6, 4), (28, 7, 4),
                  (35, 8, 4), (42, 7, 3), (48, 8, 3), (58, 9, 3), (68, 8, 2),
                  (74, 9, 2), (float("inf"), 10, 2)]),
]

# Class label for a CSR (for display / scouting).
_CLASSES = [(39, "D/E"), (49, "C"), (69, "B"), (89, "A"), (10_000, "M/GM")]


def csr_class(csr: int) -> str:
    for hi, label in _CLASSES:
        if csr <= hi:
            return label
    return "M/GM"


def _band_rules(stronger_csr: float) -> list[tuple[float, int, int]]:
    for lo, hi, rules in _BANDS:
        if lo <= stronger_csr <= hi:
            return rules
    return _BANDS[-1][2]


def race(csr_a: int, csr_b: int) -> tuple[int, int]:
    """Return (race_a, race_b): how many games each player must win. The band is
    the stronger player's CSR; the stronger player races to the higher number."""
    a, b = float(csr_a), float(csr_b)
    stronger = max(a, b)
    diff = abs(a - b)
    for diff_max, race_strong, race_weak in _band_rules(stronger):
        if diff <= diff_max:
            break
    else:  # pragma: no cover - inf row guarantees a match
        race_strong, race_weak = race_strong, race_weak
    if a >= b:
        return race_strong, race_weak
    return race_weak, race_strong
