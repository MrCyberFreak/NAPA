"""Database (Phase 2) — SQLite schema + loader, designed for HISTORY.

The official site only shows *current* values and overwrites them. This schema
keeps the drift record: skill ratings are stored as append-only dated snapshots,
so re-loading the roster grid on a new date adds history rather than clobbering.

Schema:
  players(player_id, name, gender, home_base, member_since, first_seen, last_seen)
  skill_snapshots(player_id, captured_date, csr_8, csr_9, csr_10, session_matches)
      -> the drift record; PK (player_id, captured_date), append-only by date
  teams(team_id, name, season)
  team_members(team_id, player_id, season, is_captain)
  matches(match_id, season, round, date, home_team_id, away_team_id)
  games(game_id, match_id, home_player_id, away_player_id, game_type, ...)
      -> per-rack grain for forecasting

Rules (from the build plan):
- Snapshots are append-only by captured_date.
- Players are a SUPERSET of the roster (subs play), so player rows can come from
  any source and games.*_player_id is NOT constrained to roster membership.
- The app reads ONLY from this DB.
"""

from __future__ import annotations

import argparse
import datetime as dt
import sqlite3
from pathlib import Path

from . import config
from .parse.profile import Profile
from .parse.roster import RosterPlayer, parse_roster_file
from .parse.schedule import Fixture
from .parse.standings import TeamRecord
from .parse.weekly_scores import Game, ScoreSheet

SCHEMA = """
CREATE TABLE IF NOT EXISTS players (
    player_id    TEXT PRIMARY KEY,
    name         TEXT NOT NULL,
    gender       TEXT,
    home_base    TEXT,
    member_since TEXT,
    first_seen   TEXT,
    last_seen    TEXT
);

-- The drift record: append-only by captured_date.
CREATE TABLE IF NOT EXISTS skill_snapshots (
    player_id       TEXT NOT NULL REFERENCES players(player_id),
    captured_date   TEXT NOT NULL,
    csr_8           INTEGER,
    csr_9           INTEGER,
    csr_10          INTEGER,
    session_matches INTEGER,
    PRIMARY KEY (player_id, captured_date)
);

CREATE TABLE IF NOT EXISTS teams (
    team_id INTEGER PRIMARY KEY,
    name    TEXT NOT NULL,
    season  TEXT NOT NULL,
    UNIQUE (name, season)
);

CREATE TABLE IF NOT EXISTS team_members (
    team_id    INTEGER NOT NULL REFERENCES teams(team_id),
    player_id  TEXT NOT NULL REFERENCES players(player_id),
    season     TEXT NOT NULL,
    is_captain INTEGER NOT NULL DEFAULT 0,
    PRIMARY KEY (team_id, player_id, season)
);

CREATE TABLE IF NOT EXISTS matches (
    match_id     INTEGER PRIMARY KEY,
    season       TEXT NOT NULL,
    round        INTEGER,
    date         TEXT,
    home_team_id INTEGER REFERENCES teams(team_id),
    away_team_id INTEGER REFERENCES teams(team_id),
    home_points  INTEGER,             -- team match points (from standings record)
    away_points  INTEGER
);

-- Per-rack/game grain. NOTE: *_player_id deliberately NOT FK-constrained to
-- roster membership — subs appear in results without being roster members. The
-- player NAME is always recorded (canonical key is the 8-digit id, resolved by
-- name; NULL id = a sub not on the roster).
CREATE TABLE IF NOT EXISTS games (
    game_id          INTEGER PRIMARY KEY,
    match_id         INTEGER REFERENCES matches(match_id),
    played_date      TEXT,
    home_player_id   TEXT,
    away_player_id   TEXT,
    home_player_name TEXT,
    away_player_name TEXT,
    game_type        INTEGER,           -- 8 / 9 / 10 (None from the live board)
    home_race        INTEGER,           -- race target (for censored-count handling)
    away_race        INTEGER,
    home_won         INTEGER,
    home_score       INTEGER,           -- racks won
    away_score       INTEGER
);

CREATE INDEX IF NOT EXISTS idx_snap_date ON skill_snapshots(captured_date);
CREATE INDEX IF NOT EXISTS idx_member_team ON team_members(team_id, season);
CREATE UNIQUE INDEX IF NOT EXISTS idx_match_unique
    ON matches(season, round, home_team_id, away_team_id);
CREATE UNIQUE INDEX IF NOT EXISTS idx_game_unique
    ON games(played_date, home_player_name, away_player_name);
"""


def connect(path: str | Path = config.DB_PATH) -> sqlite3.Connection:
    """Open the DB with foreign keys on and dict-like rows."""
    p = Path(path)
    if p.parent and str(p.parent) not in ("", "."):
        p.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(p)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON")
    return conn


def init_db(conn: sqlite3.Connection) -> None:
    conn.executescript(SCHEMA)
    conn.commit()


# --------------------------------------------------------------------------- #
# Loading
# --------------------------------------------------------------------------- #

def _upsert_player(conn: sqlite3.Connection, player_id: str, name: str, seen: str) -> None:
    conn.execute(
        """
        INSERT INTO players (player_id, name, first_seen, last_seen)
        VALUES (?, ?, ?, ?)
        ON CONFLICT(player_id) DO UPDATE SET
            name       = excluded.name,
            first_seen = MIN(players.first_seen, excluded.first_seen),
            last_seen  = MAX(players.last_seen,  excluded.last_seen)
        """,
        (player_id, name, seen, seen),
    )


def _get_or_create_team(conn: sqlite3.Connection, name: str, season: str) -> int:
    conn.execute(
        "INSERT INTO teams (name, season) VALUES (?, ?) ON CONFLICT(name, season) DO NOTHING",
        (name, season),
    )
    row = conn.execute(
        "SELECT team_id FROM teams WHERE name = ? AND season = ?", (name, season)
    ).fetchone()
    return row["team_id"]


def load_roster(
    conn: sqlite3.Connection,
    players: list[RosterPlayer],
    captured_date: str,
    season: str = config.SEASON,
) -> dict:
    """Load a parsed roster grid into the DB.

    - players: upserted (first_seen/last_seen widen with each load)
    - teams / team_members: upserted for the season
    - skill_snapshots: append-only by captured_date (drift record)
    Idempotent: re-loading the same date updates that snapshot; a new date
    appends history.
    """
    init_db(conn)
    for p in players:
        _upsert_player(conn, p.player_id, p.player, captured_date)
        team_id = _get_or_create_team(conn, p.team, season)
        conn.execute(
            """
            INSERT INTO team_members (team_id, player_id, season, is_captain)
            VALUES (?, ?, ?, ?)
            ON CONFLICT(team_id, player_id, season)
                DO UPDATE SET is_captain = excluded.is_captain
            """,
            (team_id, p.player_id, season, int(p.is_captain)),
        )
        conn.execute(
            """
            INSERT INTO skill_snapshots
                (player_id, captured_date, csr_8, csr_9, csr_10, session_matches)
            VALUES (?, ?, ?, ?, ?, ?)
            ON CONFLICT(player_id, captured_date) DO UPDATE SET
                csr_8 = excluded.csr_8, csr_9 = excluded.csr_9,
                csr_10 = excluded.csr_10, session_matches = excluded.session_matches
            """,
            (p.player_id, captured_date, p.csr_8, p.csr_9, p.csr_10, p.session_matches),
        )
    conn.commit()
    return {
        "players": len(players),
        "teams": len({p.team for p in players}),
        "captured_date": captured_date,
        "season": season,
    }


def load_profile(conn: sqlite3.Connection, profile: Profile, captured_date: str | None = None) -> None:
    """Enrich a player with profile demographics (gender / home_base /
    member_since). Existing non-null values are preserved (COALESCE), so a
    profile load never wipes data with a missing field. If the profile carries
    dated current CSRs, record them as a snapshot too (append-only).

    Highest-ever CSRs are available on the parsed Profile for the scout-grid
    drill-down but are not persisted yet (no schema column).
    """
    init_db(conn)
    if not profile.player_id:
        return
    seen = captured_date or profile.as_of or dt.date.today().isoformat()
    conn.execute(
        """
        INSERT INTO players (player_id, name, gender, home_base, member_since, first_seen, last_seen)
        VALUES (?, ?, ?, ?, ?, ?, ?)
        ON CONFLICT(player_id) DO UPDATE SET
            name         = COALESCE(excluded.name, players.name),
            gender       = COALESCE(excluded.gender, players.gender),
            home_base    = COALESCE(excluded.home_base, players.home_base),
            member_since = COALESCE(excluded.member_since, players.member_since),
            first_seen   = MIN(players.first_seen, excluded.first_seen),
            last_seen    = MAX(players.last_seen,  excluded.last_seen)
        """,
        (profile.player_id, profile.name, profile.gender, profile.home_base,
         profile.member_since, seen, seen),
    )
    if profile.current_csr and profile.as_of:
        c = profile.current_csr
        conn.execute(
            """
            INSERT INTO skill_snapshots
                (player_id, captured_date, csr_8, csr_9, csr_10, session_matches)
            VALUES (?, ?, ?, ?, ?, NULL)
            ON CONFLICT(player_id, captured_date) DO UPDATE SET
                csr_8 = COALESCE(excluded.csr_8, skill_snapshots.csr_8),
                csr_9 = COALESCE(excluded.csr_9, skill_snapshots.csr_9),
                csr_10 = COALESCE(excluded.csr_10, skill_snapshots.csr_10)
            """,
            (profile.player_id, profile.as_of, c.get(8), c.get(9), c.get(10)),
        )
    conn.commit()


def _resolve_team_id(conn: sqlite3.Connection, short_name: str, season: str) -> int | None:
    """Schedule uses SHORT team names ('The Furies'); rosters carry the full
    'The Furies Felt Billiards Team #2'. Resolve by prefix (exact first)."""
    row = conn.execute(
        "SELECT team_id FROM teams WHERE season = ? AND name = ?",
        (season, short_name),
    ).fetchone()
    if row:
        return row["team_id"]
    rows = conn.execute(
        "SELECT team_id FROM teams WHERE season = ? AND name LIKE ? || '%'",
        (season, short_name),
    ).fetchall()
    return rows[0]["team_id"] if len(rows) == 1 else None


def load_schedule(
    conn: sqlite3.Connection,
    fixtures: list[Fixture],
    season: str = config.SEASON,
) -> dict:
    """Load fixtures into matches, resolving short team names to team_ids.
    Idempotent on (season, round, home, away). Unresolved teams are skipped
    (counted), so a name mismatch is visible rather than silently corrupting."""
    init_db(conn)
    loaded = unresolved = 0
    for f in fixtures:
        home_id = _resolve_team_id(conn, f.home, season)
        away_id = _resolve_team_id(conn, f.away, season)
        if home_id is None or away_id is None:
            unresolved += 1
            continue
        conn.execute(
            """
            INSERT INTO matches (season, round, date, home_team_id, away_team_id)
            VALUES (?, ?, ?, ?, ?)
            ON CONFLICT(season, round, home_team_id, away_team_id)
                DO UPDATE SET date = excluded.date
            """,
            (season, f.round, f.date, home_id, away_id),
        )
        loaded += 1
    conn.commit()
    return {"loaded": loaded, "unresolved": unresolved, "fixtures": len(fixtures)}


def _player_teams(conn: sqlite3.Connection, name: str, season: str) -> tuple[str | None, set[str]]:
    """Resolve a results NAME to (canonical 8-digit id, set of teams). Canonical
    key is the 8-digit id (results/live-scores give only names). A sub not on the
    roster resolves to (None, set())."""
    rows = conn.execute(
        """
        SELECT p.player_id AS pid, t.name AS team
        FROM players p
        LEFT JOIN team_members tm ON tm.player_id = p.player_id AND tm.season = ?
        LEFT JOIN teams t ON t.team_id = tm.team_id
        WHERE p.name = ?
        """,
        (season, name),
    ).fetchall()
    if not rows:
        return None, set()
    return rows[0]["pid"], {r["team"] for r in rows if r["team"]}


def _find_match(conn, date, teams_a, teams_b, season) -> int | None:
    """Find the match on `date` for these players' teams (orientation-agnostic —
    the schedule's home/away may differ from the game's). Prefer a match whose
    BOTH teams are known; otherwise a single known team uniquely identifies the
    match (each team plays once per round), which also links a sub's game."""
    known = teams_a | teams_b
    if not date or not known:
        return None
    rows = conn.execute(
        """
        SELECT m.match_id, h.name AS home, a.name AS away
        FROM matches m
        JOIN teams h ON h.team_id = m.home_team_id
        JOIN teams a ON a.team_id = m.away_team_id
        WHERE m.season = ? AND m.date = ?
        """,
        (season, date),
    ).fetchall()
    both = [m for m in rows if {m["home"], m["away"]} <= known]
    if len(both) == 1:
        return both[0]["match_id"]
    touching = [m for m in rows if {m["home"], m["away"]} & known]
    return touching[0]["match_id"] if len(touching) == 1 else None


def load_games(conn: sqlite3.Connection, games: list[Game], season: str = config.SEASON) -> dict:
    """Load per-game results into `games`. Resolves player names -> 8-digit ids
    (NULL for subs), links each game to its match by the team pair + date.
    Idempotent on (played_date, home_name, away_name)."""
    init_db(conn)
    loaded = linked = unresolved_players = 0
    for g in games:
        hid, hteams = _player_teams(conn, g.home.player, season)
        aid, ateams = _player_teams(conn, g.away.player, season)
        unresolved_players += (hid is None) + (aid is None)
        match_id = _find_match(conn, g.date, hteams, ateams, season)
        linked += match_id is not None
        conn.execute(
            """
            INSERT INTO games (match_id, played_date, home_player_id, away_player_id,
                               home_player_name, away_player_name, game_type,
                               home_won, home_score, away_score)
            VALUES (?, ?, ?, ?, ?, ?, NULL, ?, ?, ?)
            ON CONFLICT(played_date, home_player_name, away_player_name) DO UPDATE SET
                match_id = excluded.match_id,
                home_won = excluded.home_won,
                home_score = excluded.home_score,
                away_score = excluded.away_score
            """,
            (match_id, g.date, hid, aid, g.home.player, g.away.player,
             int(g.home_won), g.home.racks_won, g.away.racks_won),
        )
        loaded += 1
    conn.commit()
    return {"games": len(games), "loaded": loaded, "linked_to_match": linked,
            "unresolved_player_slots": unresolved_players}


def _resolve_player_id(conn: sqlite3.Connection, name: str) -> str | None:
    row = conn.execute("SELECT player_id FROM players WHERE name = ?", (name,)).fetchone()
    return row["player_id"] if row else None


def load_score_sheets(conn: sqlite3.Connection, sheets: list[ScoreSheet],
                      season: str = config.SEASON) -> dict:
    """Load score-sheet games (the authoritative per-game grain, WITH game type +
    race targets) into `games`. Resolves names -> 8-digit ids (subs kept, NULL).
    Links the match by the two teams + date. Dedupes mirrored rows so fetching
    both teams' sheets for a match doesn't double-count games."""
    init_db(conn)
    loaded = skipped = unresolved = 0
    for sh in sheets:
        # All games on a sheet share the match; resolve it once from the matchup.
        hteam_id = _resolve_team_id(conn, sh.home_team, season)
        ateam_id = _resolve_team_id(conn, sh.away_team, season)
        match_row = conn.execute(
            """SELECT match_id FROM matches WHERE season = ? AND date = ?
               AND ((home_team_id = ? AND away_team_id = ?)
                 OR (home_team_id = ? AND away_team_id = ?))""",
            (season, sh.date, hteam_id, ateam_id, ateam_id, hteam_id),
        ).fetchone() if (hteam_id and ateam_id and sh.date) else None
        match_id = match_row["match_id"] if match_row else None
        for g in sh.games:
            # mirror check: same game from the opponent's sheet (home/away flipped)
            dup = conn.execute(
                """SELECT 1 FROM games WHERE played_date = ? AND game_type = ?
                   AND ((home_player_name = ? AND away_player_name = ?)
                     OR (home_player_name = ? AND away_player_name = ?))""",
                (sh.date, g.game_type, g.home_player, g.away_player,
                 g.away_player, g.home_player),
            ).fetchone()
            if dup:
                skipped += 1
                continue
            hid = _resolve_player_id(conn, g.home_player)
            aid = _resolve_player_id(conn, g.away_player)
            unresolved += (hid is None) + (aid is None)
            won = g.home_won
            conn.execute(
                """
                INSERT INTO games (match_id, played_date, home_player_id, away_player_id,
                                   home_player_name, away_player_name, game_type,
                                   home_race, away_race, home_won, home_score, away_score)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT(played_date, home_player_name, away_player_name) DO UPDATE SET
                    match_id=excluded.match_id, game_type=excluded.game_type,
                    home_race=excluded.home_race, away_race=excluded.away_race,
                    home_won=excluded.home_won, home_score=excluded.home_score,
                    away_score=excluded.away_score
                """,
                (match_id, sh.date, hid, aid, g.home_player, g.away_player, g.game_type,
                 g.home_race, g.away_race, None if won is None else int(won),
                 g.home_wins, g.away_wins),
            )
            loaded += 1
    conn.commit()
    return {"sheets": len(sheets), "loaded": loaded, "deduped": skipped,
            "unresolved_player_slots": unresolved}


def load_team_record(conn: sqlite3.Connection, record: TeamRecord, season: str = config.SEASON) -> dict:
    """Load a team's season match results (team-level points) into matches,
    aligning each week's points to that match's home/away orientation. Played
    weeks only. Summing across all teams' records yields full standings."""
    init_db(conn)
    loaded = unresolved = 0
    for r in record.results:
        if r.home_points is None or r.away_points is None:
            continue
        points = {r.home: r.home_points, r.away: r.away_points}
        teams = {_resolve_team_id(conn, r.home, season): r.home,
                 _resolve_team_id(conn, r.away, season): r.away}
        if None in teams:
            unresolved += 1
            continue
        row = conn.execute(
            """
            SELECT match_id, home_team_id, away_team_id FROM matches
            WHERE season = ? AND round = ?
              AND home_team_id IN (?, ?) AND away_team_id IN (?, ?)
            """,
            (season, r.week, *teams.keys(), *teams.keys()),
        ).fetchone()
        if not row:
            unresolved += 1
            continue
        conn.execute(
            "UPDATE matches SET home_points = ?, away_points = ? WHERE match_id = ?",
            (points[teams[row["home_team_id"]]], points[teams[row["away_team_id"]]],
             row["match_id"]),
        )
        loaded += 1
    conn.commit()
    return {"results": len(record.results), "loaded": loaded, "unresolved": unresolved}


# --------------------------------------------------------------------------- #
# Queries (demonstrate the history the official site can't show)
# --------------------------------------------------------------------------- #

def player_game_log(conn: sqlite3.Connection, player_id: str) -> list[sqlite3.Row]:
    """Every recorded game a player appears in (either side), most recent first."""
    return conn.execute(
        """
        SELECT played_date, home_player_name, away_player_name,
               home_score, away_score, home_won,
               CASE WHEN home_player_id = ?1 THEN home_won
                    ELSE NOT home_won END AS player_won
        FROM games
        WHERE home_player_id = ?1 OR away_player_id = ?1
        ORDER BY played_date DESC
        """,
        (player_id,),
    ).fetchall()


def pending_matches(conn: sqlite3.Connection, as_of: str, season: str = config.SEASON) -> list[sqlite3.Row]:
    """Scheduled matches whose date has passed (<= as_of) but have NO loaded
    games — i.e. not-yet-played makeups. Structured for re-pull: the match row
    (teams + round + date) persists; re-fetching its score sheet later fills it
    in and it drops off this list. Missing games are PENDING, never an error."""
    return conn.execute(
        """
        SELECT m.round, m.date, h.name AS home_team, a.name AS away_team
        FROM matches m
        JOIN teams h ON h.team_id = m.home_team_id
        JOIN teams a ON a.team_id = m.away_team_id
        WHERE m.season = ? AND m.date <= ?
          AND NOT EXISTS (SELECT 1 FROM games g WHERE g.match_id = m.match_id)
        ORDER BY m.round, home_team
        """,
        (season, as_of),
    ).fetchall()


def standings(conn: sqlite3.Connection, season: str = config.SEASON) -> list[sqlite3.Row]:
    """Team standings = total match points across played weeks, by team. Complete
    only for teams whose season records have been loaded (each page = one team)."""
    return conn.execute(
        """
        SELECT t.name AS team,
               SUM(pts) AS points,
               COUNT(*) AS matches_played
        FROM (
            SELECT home_team_id AS team_id, home_points AS pts FROM matches
            WHERE season = ?1 AND home_points IS NOT NULL
            UNION ALL
            SELECT away_team_id, away_points FROM matches
            WHERE season = ?1 AND away_points IS NOT NULL
        ) r
        JOIN teams t ON t.team_id = r.team_id
        GROUP BY r.team_id
        ORDER BY points DESC, team
        """,
        (season,),
    ).fetchall()


def matches_for_round(conn: sqlite3.Connection, round_: int, season: str = config.SEASON):
    """This-round fixtures with resolved team names (scout-grid entry point)."""
    return conn.execute(
        """
        SELECT m.round, m.date, h.name AS home_team, a.name AS away_team
        FROM matches m
        JOIN teams h ON h.team_id = m.home_team_id
        JOIN teams a ON a.team_id = m.away_team_id
        WHERE m.season = ? AND m.round = ?
        ORDER BY m.date, home_team
        """,
        (season, round_),
    ).fetchall()

def csr_history(conn: sqlite3.Connection, player_id: str) -> list[sqlite3.Row]:
    """A player's per-game CSR over time — the drift the live site overwrites."""
    return conn.execute(
        """
        SELECT captured_date, csr_8, csr_9, csr_10, session_matches
        FROM skill_snapshots WHERE player_id = ? ORDER BY captured_date
        """,
        (player_id,),
    ).fetchall()


def team_depth(conn: sqlite3.Connection, season: str = config.SEASON) -> list[sqlite3.Row]:
    """Roster size per team — bench depth is an exploitable scouting signal
    (only 5 play on league night; a deep team can hold back a counter)."""
    return conn.execute(
        """
        SELECT t.name AS team, COUNT(*) AS roster_size,
               SUM(tm.is_captain) AS captains
        FROM team_members tm JOIN teams t ON t.team_id = tm.team_id
        WHERE tm.season = ?
        GROUP BY t.team_id ORDER BY roster_size DESC, t.name
        """,
        (season,),
    ).fetchall()


def team_roster_latest(
    conn: sqlite3.Connection, team: str, season: str = config.SEASON
) -> list[sqlite3.Row]:
    """A team's players with their most-recent CSR snapshot (scout-grid input)."""
    return conn.execute(
        """
        SELECT p.player_id, p.name, tm.is_captain,
               s.csr_8, s.csr_9, s.csr_10, s.session_matches, s.captured_date
        FROM team_members tm
        JOIN teams t   ON t.team_id = tm.team_id
        JOIN players p ON p.player_id = tm.player_id
        JOIN skill_snapshots s ON s.player_id = p.player_id
        WHERE t.name = ? AND tm.season = ?
          AND s.captured_date = (
              SELECT MAX(captured_date) FROM skill_snapshots
              WHERE player_id = p.player_id)
        ORDER BY tm.is_captain DESC, p.name
        """,
        (team, season),
    ).fetchall()


# --------------------------------------------------------------------------- #
# CLI
# --------------------------------------------------------------------------- #

def _discover_roster_source() -> Path | None:
    """Prefer the newest archived roster grid; fall back to a fixtures capture."""
    raw = Path("data/raw")
    if raw.is_dir():
        archived = sorted(raw.glob("*/roster_grid.*"), reverse=True)
        if archived:
            return archived[0]
    fx = Path("fixtures")
    if fx.is_dir():
        for pat in ("roster*grid*.mht", "roster*grid*.mhtml", "roster*grid*.html"):
            hits = sorted(fx.glob(pat))
            if hits:
                return hits[0]
    return None


def main() -> None:
    parser = argparse.ArgumentParser(description="NAPA 13077 database loader")
    parser.add_argument("--load", action="store_true",
                        help="parse a roster grid and load it into the DB")
    parser.add_argument("--roster", type=str, default=None,
                        help="path to a roster-grid file (default: newest archive, "
                             "else a fixtures/ capture)")
    parser.add_argument("--date", type=str, default=dt.date.today().isoformat(),
                        help="captured_date for the snapshot (YYYY-MM-DD, default: today)")
    parser.add_argument("--db", type=str, default=config.DB_PATH,
                        help=f"database path (default: {config.DB_PATH})")
    args = parser.parse_args()

    if not args.load:
        parser.print_help()
        return

    source = Path(args.roster) if args.roster else _discover_roster_source()
    if source is None or not source.exists():
        raise SystemExit(
            "No roster grid found. Fetch one to data/raw/<date>/roster_grid.html, "
            "commit a capture to fixtures/, or pass --roster PATH."
        )

    players = parse_roster_file(source)
    conn = connect(args.db)
    result = load_roster(conn, players, captured_date=args.date)
    print(f"Loaded {result['players']} players / {result['teams']} teams "
          f"from {source} @ {result['captured_date']} into {args.db}")
    for row in team_depth(conn):
        print(f"  {row['roster_size']:>2}  {row['team']}")
    conn.close()


if __name__ == "__main__":
    main()
