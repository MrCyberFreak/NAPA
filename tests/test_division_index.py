"""division_index tests — the discovery catalog store.

Covers row classification (NoCo by slug), shard JSONL round-trip + truncated-tail
resume, merge idempotency + earliest-first_seen preservation, slug-family
grouping (the dupe query), and the _historical.json onboarding inbox.
"""

from __future__ import annotations

import json

import pytest

from src import config
from src import division_index as di
from src.parse.division import DivisionPage


def _dp(did, name, slug, location, resolved):
    return DivisionPage(did=did, name=name, slug=slug, location=location,
                        resolved=resolved)


def test_make_row_classifies_noco_by_slug():
    noco_slug = config.DIVISIONS[config.DID].slug
    hit = di.make_row(config.DID, _dp(config.DID, "n", noco_slug, "Englewood", True),
                      "2026-06-20")
    assert hit["is_noco"] is True
    assert hit["did"] == config.DID and hit["first_seen_date"] == "2026-06-20"

    other = di.make_row(14040, _dp(14040, "n", "tuesday-wrangler-8ball", "Ohio", True),
                        "2026-06-20")
    assert other["is_noco"] is False

    miss = di.make_row(99999, _dp(None, "", "", "", False), "2026-06-20")
    assert miss["is_noco"] is False and miss["resolved"] is False and miss["did"] == 99999


def test_parse_shard_validates():
    assert di.parse_shard("3/4") == (3, 4)
    for bad in ("0/4", "5/4", "x/4", "4"):
        with pytest.raises(ValueError):
            di.parse_shard(bad)


def test_shard_roundtrip_and_truncated_tail(tmp_path):
    sf = tmp_path / "_division_index.shard_1of2.jsonl"
    di.append_shard_row(sf, {"did": 14050, "slug": "a", "resolved": True})
    di.append_shard_row(sf, {"did": 14049, "slug": "", "resolved": False})
    assert set(di.load_shard_rows(sf)) == {"14050", "14049"}
    with sf.open("a", encoding="utf-8") as f:
        f.write('{"did": 14048, "slug"')  # aborted mid-write, no newline
    assert set(di.load_shard_rows(sf)) == {"14050", "14049"}  # partial line skipped


def test_merge_preserves_earliest_first_seen_and_adds_new():
    index = {"14050": {"did": 14050, "slug": "x", "resolved": True,
                       "is_noco": True, "first_seen_date": "2026-06-20"}}
    merged = di.merge_shards(index, [{"did": 14050, "slug": "x", "resolved": True,
                                      "is_noco": True, "first_seen_date": "2026-07-01"}])
    assert merged["14050"]["first_seen_date"] == "2026-06-20"  # earliest kept
    merged2 = di.merge_shards(index, [{"did": 13077, "slug": "x", "resolved": True,
                                       "is_noco": True, "first_seen_date": "2026-06-21"}])
    assert set(merged2) == {"14050", "13077"}


def test_merge_idempotent():
    rows = [{"did": 14050, "slug": "x", "resolved": True, "is_noco": True,
             "first_seen_date": "2026-06-20"}]
    once = di.merge_shards({}, rows)
    assert once == di.merge_shards(once, rows)


def test_slug_families_groups_sessions_and_drops_misses():
    index = {
        "14050": {"did": 14050, "slug": "thursday-x-lc", "resolved": True},
        "13077": {"did": 13077, "slug": "thursday-x-lc", "resolved": True},
        "14040": {"did": 14040, "slug": "tuesday-y-8ball", "resolved": True},
        "99999": {"did": 99999, "slug": "", "resolved": False},  # MISS excluded
    }
    fam = di.slug_families(index)
    assert fam["thursday-x-lc"] == [13077, 14050]
    assert fam["tuesday-y-8ball"] == [14040]
    assert "" not in fam


def test_build_historical_links_successor_and_excludes_curated():
    slug = config.DIVISIONS[config.DID].slug          # a real curated NoCo league
    old_did = min(config.DIVISIONS) - 1               # lower => not curated => historical
    index = {
        str(config.DID): {"did": config.DID, "slug": slug, "resolved": True,
                          "is_noco": True, "first_seen_date": "2026-06-20"},
        str(old_did): {"did": old_did, "slug": slug, "resolved": True,
                       "is_noco": True, "first_seen_date": "2026-06-20"},
    }
    hist = di.build_historical(index)
    assert str(config.DID) not in hist                # curated excluded
    assert str(old_did) in hist                       # historical session surfaced
    succ = max(d for d, dv in config.DIVISIONS.items() if dv.slug == slug)
    assert hist[str(old_did)]["successor"] == succ
    assert hist[str(old_did)]["onboarded"] is False


def test_save_load_roundtrip(tmp_path):
    p = tmp_path / "_division_index.json"
    rows = {"14050": {"did": 14050, "slug": "x", "resolved": True,
                      "is_noco": True, "first_seen_date": "2026-06-20"}}
    di.save_index(rows, path=p, run_date="2026-06-20")
    assert di.load_index(p) == rows
    data = json.loads(p.read_text(encoding="utf-8"))
    assert data["count"] == 1 and data["noco_count"] == 1
    assert di.load_index(tmp_path / "nope.json") == {}   # missing => {}
