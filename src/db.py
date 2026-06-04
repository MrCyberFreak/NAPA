"""Database (Phase 2) — SQLite schema + loader.

Stub. Schema is designed for HISTORY, not just current state:
  players(player_id, name, gender, home_base, member_since, ...)
  skill_snapshots(player_id, captured_date, csr_8, csr_9, csr_10, session_matches)
  teams, team_members(team_id, player_id, season)
  matches(round, date, home_team, away_team, ...)
  games(match_id, home_player_id, away_player_id, game_type, home_won, ...)

Rules: snapshots are append-only by date; do NOT FK games.player_id to roster
membership (subs exist). The app reads ONLY from this DB.
"""

from __future__ import annotations

import argparse


def main() -> None:
    parser = argparse.ArgumentParser(description="NAPA 13077 database loader")
    parser.add_argument("--load", action="store_true", help="parse fixtures/archive and load the DB")
    parser.parse_args()
    raise NotImplementedError("database schema + loader is Phase 2")


if __name__ == "__main__":
    main()
