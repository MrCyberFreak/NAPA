"""Capture / regenerate the golden dataset for the parse->DB regression harness.

Writes tests/golden/golden.json: the known-good parsed output (match points,
racks, wins/losses/win_pct, hill-hill) for the three golden divisions, captured
from a CLEAN scoped build over the committed raw archive -- the exact same
builder tests/test_golden_harness.py re-runs and diffs against. Run this only to
(re)baseline after an INTENTIONAL, verified change to the pipeline:

    python -m tools.golden_capture            # regenerate golden.json
    python -m tools.golden_capture --check    # build + diff, write nothing (CI-style)

Never touches data/napa.db: everything is built into a throwaway temp DB.
"""

from __future__ import annotations

import argparse
import json
import sys
import tempfile
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
if str(REPO) not in sys.path:
    sys.path.insert(0, str(REPO))

from tests.golden.harness import (  # noqa: E402
    GOLDEN_DIDS, GOLDEN_JSON, MAX_MATCHES, build_division_db, extract_division,
    select_golden_players)


def _select_player_union(tmp: Path) -> list[str]:
    """Build a profile-LESS base DB (rosters/schedules/sheets only) and pick, per
    division, the players whose form+hill-hill are fully non-null -- via the
    file-based probe, so no slow per-player profile load. Returns the player_id-
    sorted union, the exact profile set the test loads."""
    conn = build_division_db(tmp / "select.db", GOLDEN_DIDS, player_ids=[])
    union: list[str] = []
    for did in GOLDEN_DIDS:
        for pid in select_golden_players(conn, did):
            if pid not in union:
                union.append(pid)
    conn.close()
    return sorted(union)


def capture() -> dict:
    with tempfile.TemporaryDirectory() as td:
        tmp = Path(td)
        player_ids = _select_player_union(tmp)
        conn = build_division_db(tmp / "golden.db", GOLDEN_DIDS, player_ids)
        # Freeze a small, stable EARLY slice of match_points (match_limit); the
        # test rebuilds with NO limit and checks the frozen rows as a subset, so
        # a living season's later matches can't shift a still-correct row out of
        # a fixed top-N window and false-flag drift.
        divisions = {str(did): extract_division(conn, did, match_limit=MAX_MATCHES)
                     for did in GOLDEN_DIDS}
        conn.close()
    return {
        "meta": {
            "dids": GOLDEN_DIDS,
            "source": "committed raw archive (data/raw/<did>) via the scoped "
                      "parse->DB builder in tests/golden/harness.py",
            "note": "Regenerate ONLY after an intentional, verified pipeline "
                    "change: python -m tools.golden_capture",
        },
        "player_ids": player_ids,
        "divisions": divisions,
    }


def main() -> int:
    ap = argparse.ArgumentParser(description="capture/regenerate golden.json")
    ap.add_argument("--check", action="store_true",
                    help="build + diff against the committed golden.json; write "
                         "nothing; exit 1 if they differ")
    args = ap.parse_args()

    fresh = capture()
    serialized = json.dumps(fresh, indent=2, sort_keys=True)

    if args.check:
        if not GOLDEN_JSON.exists():
            print("[golden] no golden.json on disk -- run without --check first")
            return 1
        current = json.dumps(json.loads(GOLDEN_JSON.read_text(encoding="utf-8")),
                             indent=2, sort_keys=True)
        if current == serialized:
            print("[golden] OK -- rebuilt golden matches the committed golden.json")
            return 0
        print("[golden] DRIFT -- rebuilt golden differs from golden.json "
              "(a pipeline change moved the known-good values; rebaseline if intended)")
        return 1

    GOLDEN_JSON.write_text(serialized + "\n", encoding="utf-8")
    n = sum(len(d["match_points"]) + len(d["racks"]) + len(d["form"]) + len(d["hill_hill"])
            for d in fresh["divisions"].values())
    print(f"[golden] wrote {GOLDEN_JSON.relative_to(REPO)} "
          f"({len(fresh['divisions'])} divisions, {len(fresh['player_ids'])} players, "
          f"{n} anchor rows)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
