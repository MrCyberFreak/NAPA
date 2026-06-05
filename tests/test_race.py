"""Race lookup tests — values read directly from the official races.js rules,
and cross-checked against real live-scores outcomes."""

from __future__ import annotations

from src.race import csr_class, race


def test_equal_csr_per_band():
    assert race(30, 30) == (2, 2)      # 0-39 D/E
    assert race(45, 45) == (3, 3)      # 40-49 C
    assert race(60, 60) == (4, 4)      # 50-69 B
    assert race(80, 80) == (5, 5)      # 70-89 A
    assert race(95, 95) == (6, 6)      # 90+  M/GM


def test_known_band_and_diff_cells():
    # stronger band = stronger player's CSR; stronger races to the higher number.
    assert race(95, 80) == (7, 5)      # 90+, diff 15 -> 12-17 row
    assert race(72, 30) == (7, 3)      # 70-89, diff 42 -> 37-46 row
    assert race(60, 20) == (5, 2)      # 50-69, diff 40 -> 40-48 row
    assert race(49, 22) == (4, 2)      # 40-49, diff 27 -> 27+ row
    assert race(30, 11) == (2, 2)      # 0-39, diff 19 -> <=19 row
    assert race(30, 5) == (3, 2)       # 0-39, diff 25 -> 20+ row


def test_orientation_is_symmetric():
    assert race(80, 95) == (5, 7)      # weaker listed first -> mirror of (95,80)
    assert race(38, 106) == (2, 8)


def test_cross_check_against_real_games():
    # From live_scores.mht (these races match the observed rack outcomes):
    assert race(106, 38) == (8, 2)     # Scotty(106) raced to 8, won 8
    assert race(95, 61) == (8, 4)      # Hector(95) vs Anna(61)
    assert race(102, 36) == (8, 2)     # Gustaf(102) vs Shannon(36)


def test_csr_class():
    assert csr_class(20) == "D/E"
    assert csr_class(45) == "C"
    assert csr_class(60) == "B"
    assert csr_class(80) == "A"
    assert csr_class(120) == "M/GM"
