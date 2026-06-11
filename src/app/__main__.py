"""`python -m src.app` — read-only views over data/napa.db (Phase 5).

Reads ONLY from the database; never touches the live site.

Examples:
  python -m src.app --depth
  python -m src.app --scout "Pocket Pals #1" "Cheat Code Felt Billiards #6"
  python -m src.app --scout "Pocket Pals #1" "Cheat Code Felt Billiards #6" \
      --cell "Alex Stone" "Sam Cruz"
"""

from __future__ import annotations

import argparse

from .. import config
from ..db import connect, team_depth
from .scout import build_grid, render_cell, render_grid


def _print_depth(conn, season: str, division_id: int) -> None:
    print(f"Bench depth ({season}) — only 5 play league night; deeper = more flexibility")
    for r in team_depth(conn, season, division_id):
        print(f"  {r['roster_size']:>2}  {r['team']}")


def main() -> None:
    parser = argparse.ArgumentParser(description="NAPA views (read-only)")
    parser.add_argument("--db", default=config.DB_PATH, help=f"DB path (default: {config.DB_PATH})")
    parser.add_argument("--season", default=config.SEASON)
    parser.add_argument("--division", type=int, default=config.DID,
                        help=f"division id (default: {config.DID})")
    parser.add_argument("--depth", action="store_true", help="team bench-depth table")
    parser.add_argument("--scout", nargs=2, metavar=("MY_TEAM", "OPP_TEAM"),
                        help="opponent scout grid (your roster x theirs)")
    parser.add_argument("--cell", nargs=2, metavar=("MY_PLAYER", "OPP_PLAYER"),
                        help="drill into one pairing of the --scout grid")
    args = parser.parse_args()

    conn = connect(args.db)
    # Seasons are staggered per division; when scouting another division with
    # the default season label, use that division's stored season key instead.
    if args.division != config.DID and args.season == config.SEASON:
        from ..db import _stored_season
        args.season = _stored_season(conn, args.division)
    try:
        if args.depth:
            _print_depth(conn, args.season, args.division)
            print()
        if args.scout:
            grid = build_grid(conn, args.scout[0], args.scout[1], season=args.season,
                              division_id=args.division)
            print(render_grid(grid))
            if args.cell:
                my_name, opp_name = args.cell
                match = next(
                    (c for row in grid.cells for c in row
                     if c.my_player == my_name and c.opp_player == opp_name),
                    None,
                )
                print()
                print(render_cell(match) if match else
                      f"no cell for {my_name!r} vs {opp_name!r}")
        if not (args.depth or args.scout):
            parser.print_help()
    finally:
        conn.close()


if __name__ == "__main__":
    main()
