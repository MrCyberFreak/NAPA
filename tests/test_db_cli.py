"""CLI arg-scoping for `src.db`.

Regression guard for the footgun where a bare `python -m src.db --ingest`
silently scoped to config.DID (13077) only -- so every OTHER division's freshly
scraped data looked missing until someone remembered to add --all-divisions.
The daily ingest path is multi-division, so a bare `--ingest` must fold in
EVERY active division; `--did N` is the explicit opt-in to a single one.
"""

from __future__ import annotations

from src import config
from src.db import build_parser, _ingest_dids


def test_bare_ingest_scopes_to_all_active_divisions():
    args = build_parser().parse_args(["--ingest"])
    assert args.did is None  # no silent single-division default
    dids = _ingest_dids(args)
    assert dids == config.active_dids()
    assert len(dids) > 1  # a multi-division system, never just config.DID


def test_ingest_did_scopes_to_one_division():
    args = build_parser().parse_args(["--ingest", "--did", "14050"])
    assert _ingest_dids(args) == [14050]


def test_ingest_all_divisions_flag_is_explicit_synonym_for_all():
    args = build_parser().parse_args(["--ingest", "--all-divisions"])
    assert _ingest_dids(args) == config.active_dids()
