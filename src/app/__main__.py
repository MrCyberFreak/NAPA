"""`python -m src.app` — read-only views over data/napa.db (Phases 5–6).

Reads ONLY from the database; never touches the live site.

Examples:
  python -m src.app --depth
  python -m src.app --scout "Pocket Pals #1" "Cheat Code Felt Billiards #6"
  python -m src.app --scout "Pocket Pals #1" "Cheat Code Felt Billiards #6" \
      --cell "Alex Stone" "Sam Cruz"
  # Phase 6 §5 — scout who you play NEXT (auto-expanded from the schedule):
  python -m src.app --division 13985 --upcoming "All gas No breaks Felt Billiards Team #10"
  python -m src.app --division 13985 --upcoming "<team>" --all   # every remaining fixture
  python -m src.app --division 13985 --upcoming "<team>" --round 7
"""

from __future__ import annotations

import argparse
from datetime import date

from .. import config
from ..db import connect, team_depth, upcoming_fixtures
from ..model import Model
from .scout import build_grid, render_cell, render_grid, render_schedule


def _print_depth(conn, season: str, division_id: int) -> None:
    print(f"Bench depth ({season}) — only 5 play league night; deeper = more flexibility")
    for r in team_depth(conn, season, division_id):
        print(f"  {r['roster_size']:>2}  {r['team']}")


def _scout_fixture(conn, my_team, opp_team, season, division_id, model) -> None:
    grid = build_grid(conn, my_team, opp_team, season=season,
                      division_id=division_id, model=model)
    print(render_grid(grid))


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
    parser.add_argument("--upcoming", metavar="MY_TEAM",
                        help="scout your team's upcoming scheduled fixtures (Phase 6 §5)")
    parser.add_argument("--all", action="store_true",
                        help="with --upcoming: expand EVERY remaining fixture (default: the next one)")
    parser.add_argument("--round", type=int,
                        help="with --upcoming: expand only this round's fixture")
    parser.add_argument("--as-of", dest="as_of", default=date.today().isoformat(),
                        help="with --upcoming: reference date (default: today)")
    parser.add_argument("--no-forecast", action="store_true",
                        help="Phase-5 CSR-edge-only grid (skip the Phase-6 win-prob model)")
    args = parser.parse_args()

    conn = connect(args.db)
    # Seasons are staggered per division; when scouting another division with
    # the default season label, use that division's stored season key instead.
    if args.division != config.DID and args.season == config.SEASON:
        from ..db import _stored_season
        args.season = _stored_season(conn, args.division)

    # The forecast model is league-wide; fit once and reuse across all fixtures.
    model = None
    if (args.scout or args.upcoming) and not args.no_forecast:
        model = Model.fit(conn)

    try:
        if args.depth:
            _print_depth(conn, args.season, args.division)
            print()

        if args.scout:
            grid = build_grid(conn, args.scout[0], args.scout[1], season=args.season,
                              division_id=args.division, model=model)
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

        if args.upcoming:
            fixtures = upcoming_fixtures(conn, args.upcoming, args.as_of,
                                         season=args.season, division_id=args.division)
            if not fixtures:
                print(f"No upcoming fixtures for {args.upcoming!r} in {args.season} "
                      f"(division {args.division}) as of {args.as_of}: "
                      f"a finished season has none left to scout.")
            else:
                print(render_schedule(args.upcoming, fixtures))
                if args.round is not None:
                    sel = [f for f in fixtures if f["round"] == args.round]
                    if not sel:
                        print(f"\n(round {args.round} is not an upcoming fixture)")
                elif args.all:
                    sel = fixtures
                else:
                    sel = fixtures[:1]  # the next fixture
                for f in sel:
                    print(f"\n>> R{f['round']} {f['date']} ({f['venue']}) vs {f['opponent']}")
                    _scout_fixture(conn, args.upcoming, f["opponent"],
                                   args.season, args.division, model)

        if not (args.depth or args.scout or args.upcoming):
            parser.print_help()
    finally:
        conn.close()


if __name__ == "__main__":
    main()
