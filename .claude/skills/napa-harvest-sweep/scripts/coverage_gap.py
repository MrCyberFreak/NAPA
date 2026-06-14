#!/usr/bin/env python3
"""Profile-coverage gap for one or more NAPA divisions.

For each division: how many rostered players have no data/raw/profiles/<id>/ dir
yet (the harvest target). Rostered = team_members JOIN teams on division_id,
distinct non-null player_id. Read-only; no DB writes, no fetch.

Usage:  python scripts/coverage_gap.py <did> [<did> ...]
"""
from __future__ import annotations

import os
import sqlite3
import sys

DB = "data/napa.db"
PROFILES = "data/raw/profiles"


def main() -> int:
    dids = sys.argv[1:]
    if not dids:
        print("usage: coverage_gap.py <did> [<did> ...]", file=sys.stderr)
        return 2

    have = ({d for d in os.listdir(PROFILES) if d.isdigit()}
            if os.path.isdir(PROFILES) else set())
    con = sqlite3.connect(DB)
    con.row_factory = sqlite3.Row

    total_missing = 0
    for did in dids:
        rows = con.execute(
            "SELECT DISTINCT tm.player_id "
            "FROM team_members tm JOIN teams t ON tm.team_id = t.team_id "
            "WHERE t.division_id = ? AND tm.player_id IS NOT NULL",
            (int(did),),
        ).fetchall()
        rostered = {str(r["player_id"]) for r in rows}
        missing = sorted(rostered - have, key=int)
        have_n = len(rostered) - len(missing)
        total_missing += len(missing)
        pct = 100 * have_n / len(rostered) if rostered else 0.0
        tail = ""
        if missing:
            shown = ", ".join(missing[:12])
            tail = f" -> {shown}" + (" ..." if len(missing) > 12 else "")
        print(f"{did}: {len(rostered)} rostered, {have_n} with profile "
              f"({pct:.0f}%), {len(missing)} MISSING{tail}")
    print(f"TOTAL missing across {len(dids)} division(s): {total_missing}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
