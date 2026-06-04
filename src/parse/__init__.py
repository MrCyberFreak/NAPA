"""Parsers: raw HTML (captured fixtures or live archive) -> structured records.

All fragility lives here, where it is cheap to fix and replayable against the
raw archive. Each parser is pinned to a fixture so it cannot silently regress.
"""
