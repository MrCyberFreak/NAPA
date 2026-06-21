"""Database (Phase 2) — SQLite schema + loader, designed for HISTORY.

The official site only shows *current* values and overwrites them. This schema
keeps the drift record: skill ratings are stored as append-only dated snapshots,
so re-loading the roster grid on a new date adds history rather than clobbering.

Three layers, players first (see MULTIDIVISION_PLAN.md):
  IDENTITY (league-wide, never division-scoped):
    players(player_id, name, gender, home_base, member_since, first_seen, last_seen)
    skill_snapshots(player_id, captured_date, csr_8, csr_9, csr_10, csr_10bp, csr_f8, csr_7b, session_matches)
        -> the drift record; PK (player_id, captured_date), append-only by date;
           per-game values MERGE across divisions' grids (an 8-ball-only grid
           brings only csr_8); conflicting non-null values warn (CSR is league-
           wide — a real disagreement is a tripwire, not an expected state)
    player_form, pairing_history (lifetime, profile-sourced)
  AFFILIATION:
    teams(team_id, division_id, name, season), team_members(team_id, player_id, ...)
    player_divisions(player_id, division_id, ...) -> profile-sourced "Divisions:"
  EVENTS (division-scoped as an attribute, player-keyed as ever):
    divisions(division_id, name, weekday, format, season)
    matches(match_id, division_id, season, round, date, home/away_team_id, ...)
    games(game_id, division_id, match_id, home/away_player_id, game_type, ...)
        -> per-rack grain for forecasting; league-wide queries pool across
           divisions by design (that IS the Phase 6 pooling)

Rules (from the build plan):
- Snapshots are append-only by captured_date.
- Players are a SUPERSET of the roster (subs play), so player rows can come from
  any source and games.*_player_id is NOT constrained to roster membership.
- Name -> id resolution is division-preferring with an explicit ambiguity rule
  (A1): in-division roster first; else a UNIQUE league-wide match; else NULL,
  counted — never an arbitrary pick.
- The app reads ONLY from this DB.
"""

from __future__ import annotations

import argparse
import datetime as dt
import json
import sqlite3
from pathlib import Path

from . import config
from .parse.profile import CueSpeed, Profile, TrendForm
from .parse.roster import RosterPlayer, parse_roster_file
from .parse.schedule import Fixture
from .parse.standings import TeamRecord
from .parse.weekly_scores import Game, ScoreSheet

SCHEMA = """
-- Division registry rows (seeded from config.DIVISIONS; season is set per
-- division when its schedule loads — seasons are STAGGERED, see B1 recon).
CREATE TABLE IF NOT EXISTS divisions (
    division_id   INTEGER PRIMARY KEY,
    name          TEXT,
    weekday       TEXT,
    format        TEXT,
    season        TEXT,
    slug          TEXT,       -- stable logical-league key (weekday-venue-gameset)
    status        TEXT,       -- 'active' | 'rolled' (a newer session-id exists)
    successor_did INTEGER     -- next session-id when this division has rolled
);

CREATE TABLE IF NOT EXISTS players (
    player_id    TEXT PRIMARY KEY,
    name         TEXT NOT NULL,
    gender       TEXT,
    home_base    TEXT,
    member_since TEXT,
    first_seen   TEXT,
    last_seen    TEXT,
    peak_csr_8   INTEGER, peak_csr_9 INTEGER, peak_csr_10 INTEGER,   -- career peaks (profile)
    peak_on_8    TEXT, peak_on_9 TEXT, peak_on_10 TEXT               -- date each peak set
);

-- Player form snapshot (TRENDS tab): lifetime + last-10 + 30/60/90-day windows.
-- Snapshot layer (dated) — the "form term" for forecasting.
CREATE TABLE IF NOT EXISTS player_form (
    player_id        TEXT NOT NULL,
    captured_date    TEXT NOT NULL,
    lifetime_played  INTEGER, lifetime_w INTEGER, lifetime_l INTEGER,
    lifetime_win_pct INTEGER, avg_ppm REAL,
    last10_w INTEGER, last10_l INTEGER, last10_win_pct INTEGER, last10_assessment TEXT,
    d30_played INTEGER, d30_w INTEGER, d30_l INTEGER,
    d60_played INTEGER, d60_w INTEGER, d60_l INTEGER,
    d90_played INTEGER, d90_w INTEGER, d90_l INTEGER,
    PRIMARY KEY (player_id, captured_date)
);

-- The drift record: append-only by captured_date. League-wide PK — a player in
-- two divisions the same day hits ONE row; per-game values merge (COALESCE) and
-- conflicting non-null values warn at load. session_matches is per-division on
-- the source grids, so for multi-division players it is last-write ambiguous —
-- Phase 6 counts games, not SM, so this is accepted and documented.
CREATE TABLE IF NOT EXISTS skill_snapshots (
    player_id       TEXT NOT NULL REFERENCES players(player_id),
    captured_date   TEXT NOT NULL,
    csr_8           INTEGER,
    csr_9           INTEGER,
    csr_10          INTEGER,
    csr_10bp        INTEGER,  -- 10BP variant, 4-game grids only (14022)
    csr_f8          INTEGER,  -- F8 (Felt-8-ball) variant, LC+F8 grids (10874/10993)
    csr_7b          INTEGER,  -- 7B (7-ball) variant, Piazza Tuesday grid (11297)
    session_matches INTEGER,
    PRIMARY KEY (player_id, captured_date)
);

-- Individual point standings (the division's FLEX race), one row per player per
-- captured_date — a weekly drift record (the host overwrites the live page, so
-- history accrues only from when we start capturing). player_id is the resolved
-- name->id (A1), NULL for subs/ambiguous; ratings kept raw (game set NOT assumed
-- here — it is division-specific; see roster.py). AP/MP and the forfeit-adjusted
-- ADJ.* feed AVG PPM, the ranking key.
CREATE TABLE IF NOT EXISTS flex_standings (
    division_id   INTEGER NOT NULL REFERENCES divisions(division_id),
    captured_date TEXT NOT NULL,
    rank          INTEGER,
    player_id     TEXT,            -- resolved name->id; NULL for subs/ambiguous
    player_name   TEXT NOT NULL,
    ratings_raw   TEXT,            -- "(77, 54, 49)" verbatim; not split to 8/9/10
    ap            INTEGER,         -- actual points
    mp            INTEGER,         -- matches played
    ff_20         INTEGER,         -- forfeit credit @ race-to-20
    ff_14         INTEGER,         -- forfeit credit @ race-to-14
    adj_ap        INTEGER,         -- forfeit-adjusted actual points
    adj_mp        INTEGER,         -- forfeit-adjusted matches played
    avg_ppm       REAL,            -- adj_ap / adj_mp — the rank key
    PRIMARY KEY (division_id, captured_date, player_name)
);

CREATE TABLE IF NOT EXISTS teams (
    team_id     INTEGER PRIMARY KEY,
    division_id INTEGER NOT NULL REFERENCES divisions(division_id),
    name        TEXT NOT NULL,
    season      TEXT NOT NULL,
    UNIQUE (division_id, name, season)
);

-- Profile-sourced division membership (the "Divisions:" field) — deliberately
-- separate provenance from rostered membership (team_members x teams): it sees
-- divisions outside our scrape set and players we only meet as subs or rivals.
CREATE TABLE IF NOT EXISTS player_divisions (
    player_id   TEXT NOT NULL,
    division_id INTEGER NOT NULL,
    first_seen  TEXT,
    last_seen   TEXT,
    PRIMARY KEY (player_id, division_id)
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
    division_id  INTEGER NOT NULL REFERENCES divisions(division_id),
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
    division_id      INTEGER NOT NULL REFERENCES divisions(division_id),
    match_id         INTEGER REFERENCES matches(match_id),
    played_date      TEXT,
    home_player_id   TEXT,
    away_player_id   TEXT,
    home_player_name TEXT,
    away_player_name TEXT,
    game_type        INTEGER,           -- 8 / 9 / 10 ints; '10BP' text for the BP
                                        -- variant (None from the live board)
    home_race        INTEGER,           -- race target (for censored-count handling)
    away_race        INTEGER,
    home_won         INTEGER,
    home_score       INTEGER,           -- racks won
    away_score       INTEGER
);

-- Lifetime pairing history from player profiles (RIVALS drill-downs -- per-opponent
-- head-to-head; NOT the hill-hill "H2H" tab, which is a deciding-game stat).
-- DISTINCT from `games`: these are aggregate W-L counts, not rack-level results,
-- and lack opponent-skill-at-time. Enrichment of the pairing layer only.
-- Keyed by 8-digit ids; rivals are a SUPERSET of the roster (subs appear).
CREATE TABLE IF NOT EXISTS pairing_history (
    player_id     TEXT NOT NULL,
    rival_id      TEXT NOT NULL,
    rival_name    TEXT,
    total_matches INTEGER,
    wins INTEGER, losses INTEGER, win_pct INTEGER,
    g8_w INTEGER, g8_l INTEGER, g9_w INTEGER, g9_l INTEGER, g10_w INTEGER, g10_l INTEGER,
    lags_won INTEGER,
    captured_date TEXT,
    PRIMARY KEY (player_id, rival_id)
);

-- Per-player career MATCH HISTORY (profile tab xTab=2/3/4: league 8/9/10-ball).
-- RICHER than `games` (this-season, score-sheet grain): it carries the subject's
-- CSR-at-match-time, the makeup flag, venue, and spans a player's WHOLE career
-- across divisions (incl. prior-season / non-NoCo dids the scrape set never sees).
-- Distinct provenance + grain from `games`, so it is its OWN table (like
-- pairing_history is kept separate from games). Player ids are NOT FK'd: the
-- subject is the profile owner (always known); the opponent is a raw NAME that
-- may be a sub / out-of-scope player with no row in `players`. Names are stored
-- raw; id-resolution is OPTIONAL (subject_player_id is the only id v1 needs).
CREATE TABLE IF NOT EXISTS match_history (
    subject_player_id TEXT NOT NULL,        -- profile owner = the 8-digit id in the URL
    game_type         INTEGER NOT NULL,     -- 8 / 9 / 10  (tab 2/3/4); INTs like games.game_type
    played_date       TEXT NOT NULL,        -- ISO yyyy-mm-dd, parsed from "Apr. 30 '26"
    division_id       INTEGER,              -- leading int of the DIVISION row (may be off-scrape, e.g. 12399); NULL if unparseable
    division_name     TEXT,                 -- remainder of the DIVISION row
    result            TEXT,                 -- 'W' / 'L' from the SUBJECT's perspective (row0)
    subject_csr       INTEGER,              -- subject's CSR at match time ("CSR: 95")
    venue             TEXT,                 -- VENUE row
    subject_side      TEXT,                 -- 'home'/'away'; NULL when the owner name matches neither side (name variant / sub) — the match is still kept, not dropped
    home_player_name  TEXT,                 -- MATCH row, raw "First Last" (left col)
    away_player_name  TEXT,                 -- MATCH row, raw (right col)
    home_race         INTEGER,              -- RACE row
    away_race         INTEGER,
    home_wins         INTEGER,              -- "# WINS" row = racks won
    away_wins         INTEGER,
    home_score        INTEGER,              -- SCORE row = match points
    away_score        INTEGER,
    is_makeup         INTEGER NOT NULL DEFAULT 0,  -- 1 when MATCH label carries "(mm)"
    source_tab        INTEGER,              -- provenance: xTab the row came from (2/3/4)
    source_start      INTEGER,              -- provenance: pagination &start of the page it was harvested on
    page_index        INTEGER,              -- provenance: 0-based position of the match table WITHIN that page
    captured_date     TEXT,                 -- harvest date (provenance)
    -- Keyed on the natural match identity, MIRRORING `games`
    -- (ON CONFLICT(division_id, played_date, home_player_name, away_player_name)).
    -- The source exposes NO stable per-match id, and the page lists matches
    -- newest-first, so a newly-played match shifts every (source_start,page_index)
    -- — a stream-position key would DUPLICATE every prior match on the next
    -- harvest. The content key is stable, so re-harvesting (paginating
    -- start=0,10,20… AND re-runs after new matches) upserts in place — idempotent
    -- and correctly incremental. game_type is in the key because tabs 2/3/4
    -- paginate independently. KNOWN LIMITATION (identical to `games`): two matches
    -- vs the SAME opponent on the SAME date with the SAME home/away orientation
    -- collapse to one row — the source gives nothing to disambiguate them. Rare (a
    -- same-night makeup doubleheader); the daily score-sheet `games` table is the
    -- authoritative rack-level record for the current season regardless.
    PRIMARY KEY (subject_player_id, game_type, played_date, home_player_name, away_player_name)
);

CREATE INDEX IF NOT EXISTS idx_snap_date ON skill_snapshots(captured_date);
CREATE INDEX IF NOT EXISTS idx_flex_date ON flex_standings(division_id, captured_date);
CREATE INDEX IF NOT EXISTS idx_member_team ON team_members(team_id, season);
CREATE UNIQUE INDEX IF NOT EXISTS idx_match_unique
    ON matches(season, round, home_team_id, away_team_id);
CREATE UNIQUE INDEX IF NOT EXISTS idx_game_unique
    ON games(division_id, played_date, home_player_name, away_player_name);
CREATE INDEX IF NOT EXISTS idx_mh_subject   ON match_history(subject_player_id);
CREATE INDEX IF NOT EXISTS idx_mh_division  ON match_history(division_id);
CREATE INDEX IF NOT EXISTS idx_mh_opponent  ON match_history(home_player_name, away_player_name);

-- Per-player career TOURNAMENT MATCHES (profile tab xTab=24, "Tournaments >
-- View All"). A DIFFERENT structure from the league match_history tabs (2/3/4)
-- and from `games` (this-season score-sheet grain): tournament bracket matches,
-- league-wide, spanning a player's WHOLE career across NAPA national/regional
-- events (many off-NoCo, never seen by the division scrape), carrying hometowns +
-- tournament_name/event the league grain lacks and lacking division_id/venue/
-- CSR-at-time. Its OWN table, like match_history / pairing_history. The SUBJECT
-- is the profile owner (the playerID anchor / <h2> name); it may be the LEFT or
-- the RIGHT side — match the owner name to a side like match_history does, never
-- assume left=subject. result/scores/race are stored from the SUBJECT's
-- perspective. Player ids are NOT FK'd: subject is the only known id; the
-- opponent is a raw NAME (an out-of-scope tournament player with no `players`
-- row). subject_player_id + the natural-key columns are the only NOT NULL fields;
-- every other column is NULLABLE so a name-variant / partial row is KEPT.
CREATE TABLE IF NOT EXISTS tournament_matches (
    subject_player_id TEXT NOT NULL,        -- profile owner = the 8-digit playerID on the page
    played_date       TEXT NOT NULL,        -- ISO yyyy-mm-dd, from "Played: Saturday, Aug 09, 2025"
    tournament_name   TEXT NOT NULL,        -- row0, e.g. "2025 NAPA CUESPEED MILE HIGH TRIFECTA"
    opponent_name     TEXT NOT NULL,        -- the NON-subject side's name (key column)
    event_name        TEXT NOT NULL DEFAULT '',  -- row1 lead, e.g. "OPEN 8-BALL CHAMPIONSHIP"; '' (not NULL) so it keys cleanly
    game_type         TEXT,                 -- 8/9/10/7 or "Fast8"/"LC" parsed from the event text
    subject_name      TEXT,                 -- subject side display name (row2)
    subject_location  TEXT,                 -- subject side "City, State" (<small>)
    opponent_location TEXT,                 -- opponent side "City, State" (<small>)
    subject_side      TEXT,                 -- 'home'(left)/'away'(right); NULL when owner matches neither
    result            TEXT,                 -- 'W'/'L' from the SUBJECT's perspective (red=lost/green=won)
    subject_race      INTEGER,              -- RACE row, subject side
    opp_race          INTEGER,              -- RACE row, opponent side
    subject_score     INTEGER,              -- SCORE row, subject side
    opp_score         INTEGER,              -- SCORE row, opponent side
    source_tab        INTEGER,              -- provenance: xTab the row came from (24)
    source_start      INTEGER,              -- provenance: pagination &start of the harvested page
    page_index        INTEGER,              -- provenance: 0-based position of the match table WITHIN the page
    captured_date     TEXT,                 -- harvest date (provenance)
    -- NATURAL CONTENT KEY (NOT stream position). The source lists newest-first
    -- with NO per-match id, so a newly-played match PREPENDS and shifts every
    -- (source_start, page_index) — a stream-position key would DUPLICATE every
    -- prior match on re-harvest (the league match_history regression we must not
    -- repeat). The content key upserts in place: idempotent + correctly
    -- incremental. event_name is IN the key (coalesced to '' when unread) so a
    -- single tournament+date holding matches in different events (8/9/10-ball) vs
    -- the same opponent does not collapse. KNOWN, ACCEPTED limitation (same as
    -- match_history/games): two identical-natural-key matches collapse to one row
    -- — rare, and the source gives nothing to disambiguate them.
    PRIMARY KEY (subject_player_id, played_date, tournament_name, opponent_name, event_name)
);
CREATE INDEX IF NOT EXISTS idx_tm_subject    ON tournament_matches(subject_player_id);
CREATE INDEX IF NOT EXISTS idx_tm_tournament ON tournament_matches(tournament_name, played_date);
CREATE INDEX IF NOT EXISTS idx_tm_opponent   ON tournament_matches(opponent_name);
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


def _rollover_status(divs: dict) -> tuple[dict, dict]:
    """Derive (status, successor_did) per did from slug grouping: within a
    logical league (shared slug), the highest did is the current 'active'
    session and any older session-id is 'rolled' with successor = the next did
    up. Recovers the 13077 -> 14050 rollover with no hardcode."""
    by_slug: dict[str, list[int]] = {}
    for did, d in divs.items():
        by_slug.setdefault(d.slug, []).append(did)
    status: dict[int, str] = {}
    succ: dict[int, int | None] = {}
    for dids in by_slug.values():
        order = sorted(dids)
        for i, did in enumerate(order):
            rolled = i < len(order) - 1
            status[did] = "rolled" if rolled else "active"
            succ[did] = order[i + 1] if rolled else None
    return status, succ


def init_db(conn: sqlite3.Connection) -> None:
    conn.executescript(SCHEMA)
    # Column-tolerant: write slug/status/successor only if the columns exist, so
    # init_db on a pre-rebuild (old-schema) DB during a daily db --load never
    # breaks (a schema change otherwise implies a rebuild — project rule, no ALTER).
    cols = {r[1] for r in conn.execute("PRAGMA table_info(divisions)")}
    extra = [c for c in ("slug", "status", "successor_did") if c in cols]
    divs = config.divisions()                     # curated + any discovered rollover
    status, succ = _rollover_status(divs)
    for d in divs.values():
        names = ["division_id", "name", "weekday", "format"]
        vals = [d.did, d.name, d.weekday, d.fmt]
        avail = {"slug": d.slug, "status": status.get(d.did),
                 "successor_did": succ.get(d.did)}
        names += extra
        vals += [avail[c] for c in extra]
        setters = ", ".join(f"{c} = excluded.{c}" for c in names if c != "division_id")
        conn.execute(
            f"INSERT INTO divisions ({', '.join(names)}) "
            f"VALUES ({', '.join('?' for _ in names)}) "
            f"ON CONFLICT(division_id) DO UPDATE SET {setters}",
            vals,
        )
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


def _get_or_create_team(conn: sqlite3.Connection, name: str, season: str,
                        division_id: int = config.DID) -> int:
    conn.execute(
        """INSERT INTO teams (division_id, name, season) VALUES (?, ?, ?)
           ON CONFLICT(division_id, name, season) DO NOTHING""",
        (division_id, name, season),
    )
    row = conn.execute(
        "SELECT team_id FROM teams WHERE division_id = ? AND name = ? AND season = ?",
        (division_id, name, season),
    ).fetchone()
    return row["team_id"]


def load_roster(
    conn: sqlite3.Connection,
    players: list[RosterPlayer],
    captured_date: str,
    season: str = config.SEASON,
    division_id: int = config.DID,
) -> dict:
    """Load a parsed roster grid into the DB.

    - players: upserted (first_seen/last_seen widen with each load)
    - teams / team_members: upserted for the (division, season)
    - skill_snapshots: append-only by captured_date (drift record); per-game
      values MERGE across same-day grids (an 8-ball-only grid brings only
      csr_8) and a conflicting non-null value warns — CSR is league-wide, so a
      real disagreement is the tripwire that the league computes it per
      division, which would force a schema rethink.
    Idempotent: re-loading the same date updates that snapshot; a new date
    appends history.
    """
    init_db(conn)
    csr_conflicts = 0
    for p in players:
        _upsert_player(conn, p.player_id, p.player, captured_date)
        team_id = _get_or_create_team(conn, p.team, season, division_id)
        conn.execute(
            """
            INSERT INTO team_members (team_id, player_id, season, is_captain)
            VALUES (?, ?, ?, ?)
            ON CONFLICT(team_id, player_id, season)
                DO UPDATE SET is_captain = excluded.is_captain
            """,
            (team_id, p.player_id, season, int(p.is_captain)),
        )
        existing = conn.execute(
            "SELECT csr_8, csr_9, csr_10, csr_10bp, csr_f8, csr_7b FROM skill_snapshots "
            "WHERE player_id = ? AND captured_date = ?",
            (p.player_id, captured_date),
        ).fetchone()
        if existing:
            for col, new in (("csr_8", p.csr_8), ("csr_9", p.csr_9),
                             ("csr_10", p.csr_10), ("csr_10bp", p.csr_10bp),
                             ("csr_f8", p.csr_f8), ("csr_7b", p.csr_7b)):
                if existing[col] is not None and new is not None and existing[col] != new:
                    csr_conflicts += 1
                    print(f"[load] CSR DISAGREEMENT {p.player} ({p.player_id}) {col}: "
                          f"{existing[col]} != {new} @ {captured_date} "
                          f"(loading division {division_id})")
        conn.execute(
            """
            INSERT INTO skill_snapshots
                (player_id, captured_date, csr_8, csr_9, csr_10, csr_10bp, csr_f8,
                 csr_7b, session_matches)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
            ON CONFLICT(player_id, captured_date) DO UPDATE SET
                csr_8 = COALESCE(excluded.csr_8, skill_snapshots.csr_8),
                csr_9 = COALESCE(excluded.csr_9, skill_snapshots.csr_9),
                csr_10 = COALESCE(excluded.csr_10, skill_snapshots.csr_10),
                csr_10bp = COALESCE(excluded.csr_10bp, skill_snapshots.csr_10bp),
                csr_f8 = COALESCE(excluded.csr_f8, skill_snapshots.csr_f8),
                csr_7b = COALESCE(excluded.csr_7b, skill_snapshots.csr_7b),
                session_matches = COALESCE(excluded.session_matches,
                                           skill_snapshots.session_matches)
            """,
            (p.player_id, captured_date, p.csr_8, p.csr_9, p.csr_10, p.csr_10bp,
             p.csr_f8, p.csr_7b, p.session_matches),
        )
    conn.commit()
    return {
        "players": len(players),
        "teams": len({p.team for p in players}),
        "captured_date": captured_date,
        "season": season,
        "division_id": division_id,
        "csr_conflicts": csr_conflicts,
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
    # Profile-sourced division membership (A2's "Divisions:" field). getattr:
    # the parse layer grows the field on its own branch — absent means no data.
    for did in getattr(profile, "divisions", []) or []:
        conn.execute(
            """INSERT INTO player_divisions (player_id, division_id, first_seen, last_seen)
               VALUES (?, ?, ?, ?)
               ON CONFLICT(player_id, division_id) DO UPDATE SET
                   first_seen = MIN(player_divisions.first_seen, excluded.first_seen),
                   last_seen  = MAX(player_divisions.last_seen,  excluded.last_seen)""",
            (profile.player_id, did, seen, seen),
        )
    conn.commit()


def _resolve_team_id(conn: sqlite3.Connection, short_name: str, season: str,
                     division_id: int = config.DID) -> int | None:
    """Schedule uses SHORT team names ('The Furies'); rosters carry the full
    'The Furies Felt Billiards Team #2'. Resolve by prefix (exact first),
    scoped to the division — team names recur across divisions."""
    row = conn.execute(
        "SELECT team_id FROM teams WHERE division_id = ? AND season = ? AND name = ?",
        (division_id, season, short_name),
    ).fetchone()
    if row:
        return row["team_id"]
    rows = conn.execute(
        "SELECT team_id FROM teams WHERE division_id = ? AND season = ? AND name LIKE ? || '%'",
        (division_id, season, short_name),
    ).fetchall()
    return rows[0]["team_id"] if len(rows) == 1 else None


def load_schedule(
    conn: sqlite3.Connection,
    fixtures: list[Fixture],
    season: str = config.SEASON,
    division_id: int = config.DID,
) -> dict:
    """Load fixtures into matches, resolving short team names to team_ids.
    Idempotent on (season, round, home, away). Unresolved teams are skipped
    (counted), so a name mismatch is visible rather than silently corrupting."""
    init_db(conn)
    loaded = unresolved = 0
    for f in fixtures:
        home_id = _resolve_team_id(conn, f.home, season, division_id)
        away_id = _resolve_team_id(conn, f.away, season, division_id)
        if home_id is None or away_id is None:
            unresolved += 1
            continue
        conn.execute(
            """
            INSERT INTO matches (division_id, season, round, date, home_team_id, away_team_id)
            VALUES (?, ?, ?, ?, ?, ?)
            ON CONFLICT(season, round, home_team_id, away_team_id)
                DO UPDATE SET date = excluded.date
            """,
            (division_id, season, f.round, f.date, home_id, away_id),
        )
        loaded += 1
    conn.commit()
    return {"loaded": loaded, "unresolved": unresolved, "fixtures": len(fixtures)}


def _player_teams(conn: sqlite3.Connection, name: str, season: str,
                  division_id: int = config.DID) -> tuple[str | None, set[str], bool]:
    """Resolve a results NAME to (canonical 8-digit id, in-division teams,
    ambiguous). Division-preferring with an explicit ambiguity rule (A1):
    1. exactly one player of that name rostered in THIS division -> them;
    2. none in-division -> a UNIQUE league-wide name match (this is how a sub
       who is rostered in another NoCo division finally gets their id);
    3. more than one candidate either way -> (None, set(), True), counted by
       the caller — never an arbitrary pick.
    A sub not in `players` at all resolves to (None, set(), False)."""
    rows = conn.execute(
        """
        SELECT p.player_id AS pid, t.name AS team
        FROM players p
        JOIN team_members tm ON tm.player_id = p.player_id AND tm.season = ?
        JOIN teams t ON t.team_id = tm.team_id AND t.division_id = ?
        WHERE p.name = ?
        """,
        (season, division_id, name),
    ).fetchall()
    pids = {r["pid"] for r in rows}
    if len(pids) == 1:
        return rows[0]["pid"], {r["team"] for r in rows}, False
    if len(pids) > 1:
        return None, set(), True
    league = conn.execute(
        "SELECT player_id FROM players WHERE name = ?", (name,)
    ).fetchall()
    if len(league) == 1:
        return league[0]["player_id"], set(), False
    return None, set(), len(league) > 1


def _find_match(conn, date, teams_a, teams_b, season,
                division_id: int = config.DID) -> int | None:
    """Find the match on `date` for these players' teams (orientation-agnostic —
    the schedule's home/away may differ from the game's). Prefer a match whose
    BOTH teams are known; otherwise a single known team uniquely identifies the
    match (each team plays once per round), which also links a sub's game.
    Division-scoped: two Friday divisions share play dates."""
    known = teams_a | teams_b
    if not date or not known:
        return None
    rows = conn.execute(
        """
        SELECT m.match_id, h.name AS home, a.name AS away
        FROM matches m
        JOIN teams h ON h.team_id = m.home_team_id
        JOIN teams a ON a.team_id = m.away_team_id
        WHERE m.division_id = ? AND m.season = ? AND m.date = ?
        """,
        (division_id, season, date),
    ).fetchall()
    both = [m for m in rows if {m["home"], m["away"]} <= known]
    if len(both) == 1:
        return both[0]["match_id"]
    touching = [m for m in rows if {m["home"], m["away"]} & known]
    return touching[0]["match_id"] if len(touching) == 1 else None


def load_games(conn: sqlite3.Connection, games: list[Game], season: str = config.SEASON,
               division_id: int = config.DID) -> dict:
    """Load per-game results into `games`. Resolves player names -> 8-digit ids
    (NULL for subs; ambiguous names NULL and counted), links each game to its
    match by the team pair + date. Idempotent on (division, date, home, away)."""
    init_db(conn)
    loaded = linked = unresolved_players = ambiguous_names = 0
    for g in games:
        hid, hteams, hamb = _player_teams(conn, g.home.player, season, division_id)
        aid, ateams, aamb = _player_teams(conn, g.away.player, season, division_id)
        unresolved_players += (hid is None) + (aid is None)
        ambiguous_names += hamb + aamb
        match_id = _find_match(conn, g.date, hteams, ateams, season, division_id)
        linked += match_id is not None
        conn.execute(
            """
            INSERT INTO games (division_id, match_id, played_date,
                               home_player_id, away_player_id,
                               home_player_name, away_player_name, game_type,
                               home_won, home_score, away_score)
            VALUES (?, ?, ?, ?, ?, ?, ?, NULL, ?, ?, ?)
            ON CONFLICT(division_id, played_date, home_player_name, away_player_name)
            DO UPDATE SET
                match_id = excluded.match_id,
                home_won = excluded.home_won,
                home_score = excluded.home_score,
                away_score = excluded.away_score
            """,
            (division_id, match_id, g.date, hid, aid, g.home.player, g.away.player,
             int(g.home_won), g.home.racks_won, g.away.racks_won),
        )
        loaded += 1
    conn.commit()
    return {"games": len(games), "loaded": loaded, "linked_to_match": linked,
            "unresolved_player_slots": unresolved_players,
            "ambiguous_names": ambiguous_names}


def _resolve_player_id(conn: sqlite3.Connection, name: str, season: str = config.SEASON,
                       division_id: int = config.DID) -> tuple[str | None, bool]:
    """Name -> id under the same A1 rule as _player_teams (one rule, one place).
    Returns (player_id, ambiguous)."""
    pid, _teams, ambiguous = _player_teams(conn, name, season, division_id)
    return pid, ambiguous


def load_score_sheets(conn: sqlite3.Connection, sheets: list[ScoreSheet],
                      season: str = config.SEASON, division_id: int = config.DID) -> dict:
    """Load score-sheet games (the authoritative per-game grain, WITH game type +
    race targets) into `games`. Resolves names -> 8-digit ids (subs kept, NULL;
    ambiguous names NULL and counted). Links the match by the two teams + date.
    Dedupes mirrored rows so fetching both teams' sheets for a match doesn't
    double-count games. Division-scoped throughout."""
    init_db(conn)
    loaded = skipped = unresolved = ambiguous_names = 0
    for sh in sheets:
        # All games on a sheet share the match; resolve it once from the matchup.
        hteam_id = _resolve_team_id(conn, sh.home_team, season, division_id)
        ateam_id = _resolve_team_id(conn, sh.away_team, season, division_id)
        match_row = conn.execute(
            """SELECT match_id FROM matches WHERE division_id = ? AND season = ? AND date = ?
               AND ((home_team_id = ? AND away_team_id = ?)
                 OR (home_team_id = ? AND away_team_id = ?))""",
            (division_id, season, sh.date, hteam_id, ateam_id, ateam_id, hteam_id),
        ).fetchone() if (hteam_id and ateam_id and sh.date) else None
        match_id = match_row["match_id"] if match_row else None
        for g in sh.games:
            # mirror check: same game from the opponent's sheet (home/away flipped)
            dup = conn.execute(
                """SELECT 1 FROM games WHERE division_id = ? AND played_date = ?
                   AND game_type = ?
                   AND ((home_player_name = ? AND away_player_name = ?)
                     OR (home_player_name = ? AND away_player_name = ?))""",
                (division_id, sh.date, g.game_type, g.home_player, g.away_player,
                 g.away_player, g.home_player),
            ).fetchone()
            if dup:
                skipped += 1
                continue
            hid, hamb = _resolve_player_id(conn, g.home_player, season, division_id)
            aid, aamb = _resolve_player_id(conn, g.away_player, season, division_id)
            unresolved += (hid is None) + (aid is None)
            ambiguous_names += hamb + aamb
            won = g.home_won
            conn.execute(
                """
                INSERT INTO games (division_id, match_id, played_date,
                                   home_player_id, away_player_id,
                                   home_player_name, away_player_name, game_type,
                                   home_race, away_race, home_won, home_score, away_score)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT(division_id, played_date, home_player_name, away_player_name)
                DO UPDATE SET
                    match_id=excluded.match_id, game_type=excluded.game_type,
                    home_race=excluded.home_race, away_race=excluded.away_race,
                    home_won=excluded.home_won, home_score=excluded.home_score,
                    away_score=excluded.away_score
                """,
                (division_id, match_id, sh.date, hid, aid, g.home_player, g.away_player,
                 g.game_type, g.home_race, g.away_race, None if won is None else int(won),
                 g.home_wins, g.away_wins),
            )
            loaded += 1
    conn.commit()
    return {"sheets": len(sheets), "loaded": loaded, "deduped": skipped,
            "unresolved_player_slots": unresolved, "ambiguous_names": ambiguous_names}


def load_flex(conn: sqlite3.Connection, standings, captured_date: str,
              season: str = config.SEASON, division_id: int = config.DID) -> dict:
    """Load one FLEX individual-point-standings snapshot into `flex_standings`.
    Resolves player names -> 8-digit ids (division-first A1; NULL for subs /
    ambiguous, counted). Keyed by (division, captured_date, player_name) so a
    re-load of the same day upserts and distinct days accrue as a drift record."""
    init_db(conn)
    loaded = unresolved = ambiguous = 0
    for r in standings.rows:
        pid, amb = _resolve_player_id(conn, r.player, season, division_id)
        unresolved += pid is None
        ambiguous += amb
        conn.execute(
            """
            INSERT INTO flex_standings
                (division_id, captured_date, rank, player_id, player_name,
                 ratings_raw, ap, mp, ff_20, ff_14, adj_ap, adj_mp, avg_ppm)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            ON CONFLICT(division_id, captured_date, player_name) DO UPDATE SET
                rank=excluded.rank, player_id=excluded.player_id,
                ratings_raw=excluded.ratings_raw, ap=excluded.ap, mp=excluded.mp,
                ff_20=excluded.ff_20, ff_14=excluded.ff_14, adj_ap=excluded.adj_ap,
                adj_mp=excluded.adj_mp, avg_ppm=excluded.avg_ppm
            """,
            (division_id, captured_date, r.rank, pid, r.player, r.ratings_raw,
             r.ap, r.mp, r.ff_20, r.ff_14, r.adj_ap, r.adj_mp, r.avg_ppm),
        )
        loaded += 1
    conn.commit()
    return {"rows": len(standings.rows), "loaded": loaded,
            "unresolved_players": unresolved, "ambiguous_names": ambiguous}


def load_team_record(conn: sqlite3.Connection, record: TeamRecord, season: str = config.SEASON,
                     division_id: int = config.DID) -> dict:
    """Load a team's season match results (team-level points) into matches,
    aligning each week's points to that match's home/away orientation. Played
    weeks only. Summing across all teams' records yields full standings."""
    init_db(conn)
    loaded = unresolved = 0
    for r in record.results:
        if r.home_points is None or r.away_points is None:
            continue
        points = {r.home: r.home_points, r.away: r.away_points}
        teams = {_resolve_team_id(conn, r.home, season, division_id): r.home,
                 _resolve_team_id(conn, r.away, season, division_id): r.away}
        if None in teams:
            unresolved += 1
            continue
        row = conn.execute(
            """
            SELECT match_id, home_team_id, away_team_id FROM matches
            WHERE division_id = ? AND season = ? AND round = ?
              AND home_team_id IN (?, ?) AND away_team_id IN (?, ?)
            """,
            (division_id, season, r.week, *teams.keys(), *teams.keys()),
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


def load_match_results(conn: sqlite3.Connection, results, season: str = config.SEASON,
                       division_id: int = config.DID) -> dict:
    """Load the official match-POINT totals parsed off a weekly-scores INDEX
    (parse.weekly_scores.parse_week_results) into matches.home/away_points,
    aligning each pair to the match's home/away orientation. This is the result
    layer mined from the page we already archive for sheet URLs — independent of
    whether the per-rack score sheet has been published yet.

    A 0-0 pair is a NOT-YET-PLAYED match (NAPA always distributes ~80-96 points
    across a played team match); it is skipped so a pending fixture is never
    recorded as a 0-0 result. Unresolved team names / missing fixtures are
    counted (visible), never guessed. Mirrors load_team_record's per-result
    alignment; kept separate while the team-record page stays a later add."""
    init_db(conn)
    loaded = unresolved = skipped = 0
    for r in results:
        if not r.home_points and not r.away_points:
            skipped += 1                          # 0-0 (or null) = not played yet
            continue
        points = {r.home: r.home_points, r.away: r.away_points}
        teams = {_resolve_team_id(conn, r.home, season, division_id): r.home,
                 _resolve_team_id(conn, r.away, season, division_id): r.away}
        if None in teams:
            unresolved += 1
            continue
        row = conn.execute(
            """
            SELECT match_id, home_team_id, away_team_id FROM matches
            WHERE division_id = ? AND season = ? AND round = ?
              AND home_team_id IN (?, ?) AND away_team_id IN (?, ?)
            """,
            (division_id, season, r.week, *teams.keys(), *teams.keys()),
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
    return {"results": len(results), "loaded": loaded,
            "unresolved": unresolved, "skipped": skipped}


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


def load_rivals(conn: sqlite3.Connection, subject_id: str, rivals, captured_date: str | None = None) -> int:
    """Record lifetime pairing existence/identity from a RIVALS list. Idempotent
    on (player_id, rival_id); per-game counts are filled later by drill-downs."""
    init_db(conn)
    if not subject_id:
        return 0
    n = 0
    for r in rivals:
        conn.execute(
            """INSERT INTO pairing_history (player_id, rival_id, rival_name, captured_date)
               VALUES (?, ?, ?, ?)
               ON CONFLICT(player_id, rival_id) DO UPDATE SET
                   rival_name = COALESCE(excluded.rival_name, pairing_history.rival_name)""",
            (subject_id, r.rival_id, r.name, captured_date),
        )
        n += 1
    conn.commit()
    return n


def load_cuespeed(conn: sqlite3.Connection, player_id: str, cs: CueSpeed) -> None:
    """Fold career-peak CueSpeed (per game + date) into the players row. Current
    dated ratings corroborate the roster-grid snapshots and aren't re-stored."""
    init_db(conn)
    pk = cs.peak
    conn.execute(
        """INSERT INTO players (player_id, name, peak_csr_8, peak_csr_9, peak_csr_10,
                                peak_on_8, peak_on_9, peak_on_10)
           VALUES (?, ?, ?, ?, ?, ?, ?, ?)
           ON CONFLICT(player_id) DO UPDATE SET
               peak_csr_8=excluded.peak_csr_8, peak_csr_9=excluded.peak_csr_9,
               peak_csr_10=excluded.peak_csr_10, peak_on_8=excluded.peak_on_8,
               peak_on_9=excluded.peak_on_9, peak_on_10=excluded.peak_on_10""",
        (player_id, player_id,
         pk.get(8, (None, None))[0], pk.get(9, (None, None))[0], pk.get(10, (None, None))[0],
         pk.get(8, (None, None))[1], pk.get(9, (None, None))[1], pk.get(10, (None, None))[1]),
    )
    conn.commit()


def load_trends(conn: sqlite3.Connection, player_id: str, form: TrendForm, captured_date: str) -> None:
    """Record a dated form snapshot (lifetime + last-10 + 30/60/90-day)."""
    init_db(conn)
    d30 = form.d30 or (None, None, None)
    d60 = form.d60 or (None, None, None)
    d90 = form.d90 or (None, None, None)
    conn.execute(
        """INSERT OR REPLACE INTO player_form
           (player_id, captured_date, lifetime_played, lifetime_w, lifetime_l,
            lifetime_win_pct, avg_ppm, last10_w, last10_l, last10_win_pct, last10_assessment,
            d30_played, d30_w, d30_l, d60_played, d60_w, d60_l, d90_played, d90_w, d90_l)
           VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)""",
        (player_id, captured_date, form.lifetime_played, form.lifetime_w, form.lifetime_l,
         form.lifetime_win_pct, form.avg_ppm, form.last10_w, form.last10_l, form.last10_win_pct,
         form.last10_assessment, d30[0], d30[1], d30[2], d60[0], d60[1], d60[2],
         d90[0], d90[1], d90[2]),
    )
    conn.commit()


def update_pairing_record(conn: sqlite3.Connection, player_id: str, rival_id: str,
                          per_game: dict, rival_name: str | None = None) -> None:
    """Fold a rival drill-down's per-game (played, lags, wins, losses) into the
    pairing row (per-opponent lifetime record). Aggregate counts only — never
    rack-level, never into `games`."""
    init_db(conn)
    g = {k: per_game.get(k, (0, 0, 0, 0)) for k in (8, 9, 10)}
    total = sum(v[0] for v in g.values())
    lags = sum(v[1] for v in g.values())
    wins = sum(v[2] for v in g.values())
    losses = sum(v[3] for v in g.values())
    conn.execute(
        """INSERT INTO pairing_history
               (player_id, rival_id, rival_name, total_matches, wins, losses, lags_won,
                g8_w, g8_l, g9_w, g9_l, g10_w, g10_l)
           VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?)
           ON CONFLICT(player_id, rival_id) DO UPDATE SET
               rival_name=COALESCE(pairing_history.rival_name, excluded.rival_name),
               total_matches=excluded.total_matches, wins=excluded.wins,
               losses=excluded.losses, lags_won=excluded.lags_won,
               g8_w=excluded.g8_w, g8_l=excluded.g8_l, g9_w=excluded.g9_w,
               g9_l=excluded.g9_l, g10_w=excluded.g10_w, g10_l=excluded.g10_l""",
        (player_id, rival_id, rival_name, total, wins, losses, lags,
         g[8][2], g[8][3], g[9][2], g[9][3], g[10][2], g[10][3]),
    )


def load_match_history(conn: sqlite3.Connection, subject_id: str, game_type: int,
                       rows, captured_date: str | None = None) -> dict:
    """Load one harvested match-history page's rows for ONE subject + game_type.

    Idempotent on the natural match key (subject_player_id, game_type,
    played_date, home_player_name, away_player_name) — mirroring how `games` keys
    a match. Re-harvesting (paginating start=0,10,20… AND re-runs after new matches
    have been played) upserts in place: the content key is stable even though the
    source lists matches newest-first and a new match shifts every page position.
    A stream-position key would instead duplicate every prior match on the next
    harvest. KNOWN LIMITATION (identical to `games`): two matches vs the same
    opponent on the same date with the same home/away orientation collapse to one
    row (the source exposes no per-match id to tell them apart) — rare, and `games`
    is authoritative at rack level for the current season regardless.

    Distinct provenance + grain from `games` — never folded into it. Opponent ids
    are NOT resolved here (names may be subs / out-of-scope players); the subject
    id is the profile owner, passed in. Rows missing a key column (played_date /
    either name) are skipped + counted, never guessed; a name-variant subject_side
    or an unparseable division_id is kept (those columns are nullable). Returns a
    load-report dict for the rebuild/gate consumers."""
    init_db(conn)
    loaded = skipped = 0
    if not subject_id:
        return {"loaded": 0, "skipped": 0, "subject": subject_id}
    for r in rows:
        # The row-level key columns must be present (subject_id + game_type are args).
        if not r.played_date or not r.home_player_name or not r.away_player_name:
            skipped += 1
            continue
        conn.execute(
            """INSERT INTO match_history
                   (subject_player_id, game_type, played_date, division_id,
                    division_name, result, subject_csr, venue, subject_side,
                    home_player_name, away_player_name, home_race, away_race,
                    home_wins, away_wins, home_score, away_score, is_makeup,
                    source_tab, source_start, page_index, captured_date)
               VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)
               ON CONFLICT(subject_player_id, game_type, played_date,
                           home_player_name, away_player_name)
                   DO UPDATE SET
                   division_id   = COALESCE(excluded.division_id, match_history.division_id),
                   division_name = COALESCE(excluded.division_name, match_history.division_name),
                   result        = COALESCE(excluded.result, match_history.result),
                   subject_csr   = COALESCE(excluded.subject_csr, match_history.subject_csr),
                   venue         = COALESCE(excluded.venue, match_history.venue),
                   subject_side  = COALESCE(excluded.subject_side, match_history.subject_side),
                   home_race     = COALESCE(excluded.home_race, match_history.home_race),
                   away_race     = COALESCE(excluded.away_race, match_history.away_race),
                   home_wins     = COALESCE(excluded.home_wins, match_history.home_wins),
                   away_wins     = COALESCE(excluded.away_wins, match_history.away_wins),
                   home_score    = COALESCE(excluded.home_score, match_history.home_score),
                   away_score    = COALESCE(excluded.away_score, match_history.away_score),
                   is_makeup     = excluded.is_makeup,
                   source_tab    = excluded.source_tab,
                   source_start  = excluded.source_start,
                   page_index    = excluded.page_index,
                   captured_date = COALESCE(excluded.captured_date, match_history.captured_date)""",
            (subject_id, game_type, r.played_date, r.division_id, r.division_name,
             r.result, r.subject_csr, r.venue, r.subject_side,
             r.home_player_name, r.away_player_name, r.home_race, r.away_race,
             r.home_wins, r.away_wins, r.home_score, r.away_score,
             1 if r.is_makeup else 0, r.source_tab, r.source_start, r.page_index,
             captured_date),
        )
        loaded += 1
    conn.commit()
    return {"loaded": loaded, "skipped": skipped, "subject": subject_id}


def load_tournament_matches(conn: sqlite3.Connection, subject_id: str, rows,
                            captured_date: str | None = None) -> dict:
    """Load one harvested tournaments (xTab=24) page's rows for ONE subject.

    Idempotent on the natural content key (subject_player_id, played_date,
    tournament_name, opponent_name, event_name) — MIRRORING how match_history /
    `games` key a match. Re-harvesting (paginating start=0,10,20… AND re-runs
    after new tournament matches have been played) upserts in place: the content
    key is stable even though the source lists matches newest-first and a new
    match shifts every page position. A stream-position key would instead
    duplicate every prior match on the next harvest (the league match_history
    regression we must not repeat). KNOWN LIMITATION (identical to
    match_history/games): two matches with the same natural key collapse to one
    row (the source exposes no per-match id) — rare.

    Distinct provenance + grain from match_history (tournament bracket matches,
    league-wide career, no division/venue/CSR-at-time) — never folded into it.
    Opponent ids are NOT resolved here (out-of-scope tournament players with no
    `players` row); the subject id is the profile owner, passed in. Rows missing a
    key column (played_date / tournament_name / opponent_name) are skipped +
    counted, never guessed; event_name is coalesced to '' so it keys cleanly. A
    name-variant subject_side (NULL) is kept. Returns a load-report dict."""
    init_db(conn)
    loaded = skipped = 0
    if not subject_id:
        return {"loaded": 0, "skipped": 0, "subject": subject_id}
    for r in rows:
        # The row-level key columns must be present (subject_id is the arg).
        if not r.played_date or not r.tournament_name or not r.opponent_name:
            skipped += 1
            continue
        event_name = r.event_name or ""  # '' (not NULL) so it participates in the key
        game_type = None if r.game_type is None else str(r.game_type)
        conn.execute(
            """INSERT INTO tournament_matches
                   (subject_player_id, played_date, tournament_name, opponent_name,
                    event_name, game_type, subject_name, subject_location,
                    opponent_location, subject_side, result, subject_race, opp_race,
                    subject_score, opp_score, source_tab, source_start, page_index,
                    captured_date)
               VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)
               ON CONFLICT(subject_player_id, played_date, tournament_name,
                           opponent_name, event_name)
                   DO UPDATE SET
                   game_type         = COALESCE(excluded.game_type, tournament_matches.game_type),
                   subject_name      = COALESCE(excluded.subject_name, tournament_matches.subject_name),
                   subject_location  = COALESCE(excluded.subject_location, tournament_matches.subject_location),
                   opponent_location = COALESCE(excluded.opponent_location, tournament_matches.opponent_location),
                   subject_side      = COALESCE(excluded.subject_side, tournament_matches.subject_side),
                   result            = COALESCE(excluded.result, tournament_matches.result),
                   subject_race      = COALESCE(excluded.subject_race, tournament_matches.subject_race),
                   opp_race          = COALESCE(excluded.opp_race, tournament_matches.opp_race),
                   subject_score     = COALESCE(excluded.subject_score, tournament_matches.subject_score),
                   opp_score         = COALESCE(excluded.opp_score, tournament_matches.opp_score),
                   source_tab        = excluded.source_tab,
                   source_start      = excluded.source_start,
                   page_index        = excluded.page_index,
                   captured_date     = COALESCE(excluded.captured_date, tournament_matches.captured_date)""",
            (subject_id, r.played_date, r.tournament_name, r.opponent_name,
             event_name, game_type, r.subject_name, r.subject_location,
             r.opponent_location, r.subject_side, r.result, r.subject_race,
             r.opp_race, r.subject_score, r.opp_score, r.source_tab,
             r.source_start, r.page_index, captured_date),
        )
        loaded += 1
    conn.commit()
    return {"loaded": loaded, "skipped": skipped, "subject": subject_id}


def pairing_coverage(conn: sqlite3.Connection) -> dict:
    """Densification metric: distinct UNORDERED player pairs with lifetime history
    (from pairing_history) — to compare against the single-session game pairings."""
    pairs = {frozenset((a, b)) for a, b in
             conn.execute("SELECT player_id, rival_id FROM pairing_history")}
    return {"directed_edges": conn.execute("SELECT COUNT(*) FROM pairing_history").fetchone()[0],
            "distinct_pairings": len(pairs),
            "subjects": conn.execute("SELECT COUNT(DISTINCT player_id) FROM pairing_history").fetchone()[0]}


def pending_matches(conn: sqlite3.Connection, as_of: str, season: str = config.SEASON,
                    division_id: int = config.DID) -> list[sqlite3.Row]:
    """Scheduled matches whose date has passed (<= as_of) but have NO loaded
    games — i.e. not-yet-played makeups. Structured for re-pull: the match row
    (teams + round + date) persists; re-fetching its score sheet later fills it
    in and it drops off this list. Missing games are PENDING, never an error.

    BYE rounds are excluded: the site schedules an odd team out against a
    placeholder "Bye" team. Its stored name is the full roster form ("Bye" plus
    the division suffix, e.g. "Bye Zoosters Team #6"), so it is matched as the
    leading word — it has no roster and never produces a real score sheet, so it
    would otherwise sit here as an eternal phantom and (post-redesign) pin its
    division to a daily catch-up re-pull. A bye is not missing data; it is the
    absence of a match."""
    return conn.execute(
        """
        SELECT m.round, m.date, h.name AS home_team, a.name AS away_team
        FROM matches m
        JOIN teams h ON h.team_id = m.home_team_id
        JOIN teams a ON a.team_id = m.away_team_id
        WHERE m.division_id = ? AND m.season = ? AND m.date <= ?
          AND LOWER(h.name) != 'bye' AND LOWER(h.name) NOT LIKE 'bye %'
          AND LOWER(a.name) != 'bye' AND LOWER(a.name) NOT LIKE 'bye %'
          AND NOT EXISTS (SELECT 1 FROM games g WHERE g.match_id = m.match_id)
        ORDER BY m.round, home_team
        """,
        (division_id, season, as_of),
    ).fetchall()


def standings(conn: sqlite3.Connection, season: str = config.SEASON,
              division_id: int = config.DID) -> list[sqlite3.Row]:
    """Team standings = total match points across played weeks, by team. Complete
    only for teams whose season records have been loaded (each page = one team)."""
    return conn.execute(
        """
        SELECT t.name AS team,
               SUM(pts) AS points,
               COUNT(*) AS matches_played
        FROM (
            SELECT home_team_id AS team_id, home_points AS pts FROM matches
            WHERE division_id = ?2 AND season = ?1 AND home_points IS NOT NULL
            UNION ALL
            SELECT away_team_id, away_points FROM matches
            WHERE division_id = ?2 AND season = ?1 AND away_points IS NOT NULL
        ) r
        JOIN teams t ON t.team_id = r.team_id
        GROUP BY r.team_id
        ORDER BY points DESC, team
        """,
        (season, division_id),
    ).fetchall()


def matches_for_round(conn: sqlite3.Connection, round_: int, season: str = config.SEASON,
                      division_id: int = config.DID):
    """This-round fixtures with resolved team names (scout-grid entry point)."""
    return conn.execute(
        """
        SELECT m.round, m.date, h.name AS home_team, a.name AS away_team
        FROM matches m
        JOIN teams h ON h.team_id = m.home_team_id
        JOIN teams a ON a.team_id = m.away_team_id
        WHERE m.division_id = ? AND m.season = ? AND m.round = ?
        ORDER BY m.date, home_team
        """,
        (division_id, season, round_),
    ).fetchall()


def upcoming_fixtures(conn: sqlite3.Connection, team: str, as_of: str,
                      season: str = config.SEASON, division_id: int = config.DID):
    """A team's NOT-YET-PLAYED fixtures (date >= as_of), opponent resolved, in
    chronological order — the entry point for the Phase-6 §5 "scout who you play
    next" forecast. Match-level points are not stored (NULL across the board), so
    the date is the discriminator: a finished season has none, a mid-season one
    carries its whole forward schedule (verified: 13985 has its full slate to
    2026-09-29). Rows: round, date, opponent (the OTHER team), venue ('home'/
    'away'). BYE fixtures are excluded — a bye is the absence of a match, not an
    opponent to scout (same placeholder-name rule as pending_matches)."""
    return conn.execute(
        """
        SELECT m.round, m.date,
               CASE WHEN h.name = ?3 THEN a.name ELSE h.name END AS opponent,
               CASE WHEN h.name = ?3 THEN 'home' ELSE 'away' END AS venue
        FROM matches m
        JOIN teams h ON h.team_id = m.home_team_id
        JOIN teams a ON a.team_id = m.away_team_id
        WHERE m.division_id = ?1 AND m.season = ?2
          AND (h.name = ?3 OR a.name = ?3)
          AND m.date >= ?4
          AND LOWER(h.name) != 'bye' AND LOWER(h.name) NOT LIKE 'bye %'
          AND LOWER(a.name) != 'bye' AND LOWER(a.name) NOT LIKE 'bye %'
        ORDER BY m.date, m.round
        """,
        (division_id, season, team, as_of),
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


def team_depth(conn: sqlite3.Connection, season: str = config.SEASON,
               division_id: int = config.DID) -> list[sqlite3.Row]:
    """Roster size per team — bench depth is an exploitable scouting signal
    (only 5 play on league night; a deep team can hold back a counter)."""
    return conn.execute(
        """
        SELECT t.name AS team, COUNT(*) AS roster_size,
               SUM(tm.is_captain) AS captains
        FROM team_members tm JOIN teams t ON t.team_id = tm.team_id
        WHERE tm.season = ? AND t.division_id = ?
        GROUP BY t.team_id ORDER BY roster_size DESC, t.name
        """,
        (season, division_id),
    ).fetchall()


def team_roster_latest(
    conn: sqlite3.Connection, team: str, season: str = config.SEASON,
    division_id: int = config.DID,
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
        WHERE t.name = ? AND t.division_id = ? AND tm.season = ?
          AND s.captured_date = (
              SELECT MAX(captured_date) FROM skill_snapshots
              WHERE player_id = p.player_id)
        ORDER BY tm.is_captain DESC, p.name
        """,
        (team, division_id, season),
    ).fetchall()


# --------------------------------------------------------------------------- #
# Rebuild (A3) — the DB is regenerable from the committed raw archive
# --------------------------------------------------------------------------- #

def _division_season(did: int, fixtures: list[Fixture]) -> str:
    """Per-division season key. 13077 keeps its historic label for continuity;
    other divisions are keyed by their season's R1 date (self-describing,
    unique, no registry hardcode — seasons are STAGGERED, see B1 recon)."""
    if did == config.DID:
        return config.SEASON
    dates = sorted(f.date for f in fixtures if f.date)
    return dates[0] if dates else "unknown"


def _archived_dids() -> list[int]:
    """Every registered division (curated + discovered rollover + historical
    inbox) that actually has an archive dir, registry order."""
    return [d for d in config.divisions() if config.division_root(d).is_dir()]


def _profiles_root() -> Path:
    """Player-keyed profile archive root: data/raw/profiles/ (division-independent)."""
    return Path("data/raw/profiles")


def load_profile_dir(conn: sqlite3.Connection, pdir: Path,
                     *, captured_default: str | None = None) -> tuple[bool, str | None]:
    """Load ONE data/raw/profiles/<id>/ directory into the DB via the idempotent
    profile loaders (demographics, CSR peaks, rivals, per-rival record drill-downs,
    trends, career match history, tournaments). Shared by rebuild()'s pass 4 and
    the incremental ingest_profiles(), so the per-profile logic lives in one place.

    Returns (loaded, error): (True, None) on a successful load, (False, None) when
    skipped (no main.html / no player_id), (False, msg) on a captured exception.
    Never raises — one bad capture must not kill the caller. The caller owns
    conn.commit() (update_pairing_record does not self-commit)."""
    from .parse.match_history import TAB_GAME_TYPE, parse_match_history_file
    from .parse.profile import (parse_cuespeed, parse_profile_file,
                                parse_profile_rivals, parse_rival_record, parse_trends)
    from .parse.tournament import parse_tournament_file

    main_f = pdir / "main.html"
    if not main_f.exists():
        return (False, None)
    try:
        prof = parse_profile_file(main_f)
        if not prof.player_id:
            return (False, None)
        load_profile(conn, prof)
        captured = prof.as_of or captured_default or dt.date.today().isoformat()
        html = main_f.read_text(encoding="utf-8", errors="replace")
        load_cuespeed(conn, prof.player_id, parse_cuespeed(html))
        rivals_f = pdir / "rivals.html"
        if rivals_f.exists():
            _, rivals = parse_profile_rivals(
                rivals_f.read_text(encoding="utf-8", errors="replace"))
            load_rivals(conn, prof.player_id, rivals, captured)
        for rf in sorted(pdir.glob("rival_*.html")):
            per_game = parse_rival_record(rf.read_text(encoding="utf-8", errors="replace"))
            update_pairing_record(conn, prof.player_id, rf.stem.split("_", 1)[1], per_game)
        trends_f = pdir / "trends.html"
        if trends_f.exists():
            form = parse_trends(trends_f.read_text(encoding="utf-8", errors="replace"))
            load_trends(conn, prof.player_id, form, captured)
        # Career match history: any archived match_<tab>_<start>.html (no-op when
        # none). Tab/start are recovered from the filename; game_type from the tab.
        for mf in sorted(pdir.glob("match_*.html")):
            tok = mf.stem.split("_")[1]
            tab = int(tok) if tok.isdigit() else tok
            if tab == 24:  # Tournaments — own parser + table (xTab=24)
                sid, tpage = parse_tournament_file(mf)
                load_tournament_matches(conn, sid or prof.player_id,
                                        tpage.matches, captured)
                continue
            if tab not in TAB_GAME_TYPE:
                continue  # Local-Duels (25): archived raw, parsed elsewhere
            sid, page = parse_match_history_file(mf)
            load_match_history(conn, sid or prof.player_id, page.game_type,
                               page.matches, captured)
        return (True, None)
    except Exception as exc:  # noqa: BLE001 — one bad capture must not kill the caller
        return (False, str(exc))


def rebuild(db_path: str | Path = config.DB_PATH, dids: list[int] | None = None,
            profiles: bool = True) -> dict:
    """Rebuild the DB from the raw archive, pass-ordered so the master player
    list exists before any score sheet resolves names (loading one division's
    sheets before all rosters would miss cross-division id resolutions):
      pass 1: every archived roster grid, ALL divisions, chronological
      pass 2: newest schedule per division (also sets divisions.season)
      pass 3: every score sheet, per division
      pass 4: profiles (league-wide: demographics, divisions, peaks, rivals,
              drill-downs, trends)
    Returns a per-pass report keyed for the load-report gates.

    profiles=False skips pass 4 — by far the slowest pass (thousands of
    per-player HTML files, I/O-bound on a slow disk). Every PASS/FAIL onboarding
    gate is sourced from passes 1–3; only the profile-sourced multi-division
    ENUMERATION (player_divisions) is informational, so onboarding can gate fast
    and leave the full profile load for the final verification rebuild."""
    from .parse.schedule import parse_schedule_file
    from .parse.weekly_scores import parse_score_sheet_file, parse_week_results_file
    from .parse.flex import parse_flex_file

    path = Path(db_path)
    if path.exists():
        path.unlink()
    conn = connect(path)
    init_db(conn)
    dids = dids or _archived_dids()
    report: dict = {"divisions": {}, "profiles": {}}

    # Season keys first (teams/matches key on them), then the ordered passes.
    seasons: dict[int, str] = {}
    fixtures_by_did: dict[int, list[Fixture]] = {}
    for did in dids:
        scheds = sorted(config.division_root(did).glob("*/schedule.html"))
        fixtures_by_did[did] = parse_schedule_file(scheds[-1]) if scheds else []
        seasons[did] = _division_season(did, fixtures_by_did[did])
        conn.execute("UPDATE divisions SET season = ? WHERE division_id = ?",
                     (seasons[did], did))
    conn.commit()

    for did in dids:  # pass 1: rosters (master list + snapshots + affiliations)
        rep = {"roster_loads": 0, "csr_conflicts": 0}
        for grid in sorted(config.division_root(did).glob("*/roster_grid.html")):
            r = load_roster(conn, parse_roster_file(grid), captured_date=grid.parent.name,
                            season=seasons[did], division_id=did)
            rep["roster_loads"] += 1
            rep["csr_conflicts"] += r["csr_conflicts"]
        report["divisions"][did] = rep

    for did in dids:  # pass 2: schedules
        if fixtures_by_did[did]:
            report["divisions"][did]["schedule"] = load_schedule(
                conn, fixtures_by_did[did], season=seasons[did], division_id=did)

    for did in dids:  # pass 3: score sheets (per-game grain) + match-point results
        sheet_files = [f for f in sorted(config.division_root(did).glob("scores/week_*/*.html"))
                       if f.name != "_index.html"]
        if sheet_files:
            sheets = [parse_score_sheet_file(f) for f in sheet_files]
            report["divisions"][did]["sheets"] = load_score_sheets(
                conn, sheets, season=seasons[did], division_id=did)
        # The official outcome layer: match POINTS off each week's index (the
        # page already archived for sheet URLs). Lands results/standings even
        # when the per-rack sheet has not been published yet.
        results = [r for idx in sorted(config.division_root(did).glob("scores/week_*/_index.html"))
                   for r in parse_week_results_file(idx)]
        if results:
            report["divisions"][did]["results"] = load_match_results(
                conn, results, season=seasons[did], division_id=did)

    for did in dids:  # pass 3b: FLEX individual point standings (dated drift snapshots)
        flex_files = sorted(config.division_root(did).glob("*/flex.html"))
        if not flex_files:
            continue
        rep = {"flex_loads": 0, "flex_rows": 0, "flex_failed": 0}
        for ff in flex_files:
            try:
                fs = parse_flex_file(ff)
                res = load_flex(conn, fs, captured_date=ff.parent.name,
                                season=seasons[did], division_id=did)
                rep["flex_loads"] += 1
                rep["flex_rows"] += res["loaded"]
            except Exception as exc:  # noqa: BLE001 — one bad capture must not kill a rebuild
                rep["flex_failed"] += 1
                print(f"[rebuild] flex {ff} failed: {exc}")
        report["divisions"][did]["flex"] = rep

    # pass 4: profiles — league-wide, after every roster so ids all exist.
    # Skipped when profiles=False (the slow, I/O-bound pass; not needed for the
    # PASS/FAIL onboarding gates — see rebuild() docstring).
    profiles_root = _profiles_root()
    loaded = failed = 0
    if profiles and profiles_root.is_dir():
        for pdir in sorted(profiles_root.iterdir()):
            ok, err = load_profile_dir(conn, pdir)
            if ok:
                loaded += 1
            elif err is not None:
                failed += 1
                print(f"[rebuild] profile {pdir.name} failed: {err}")
    conn.commit()
    report["profiles"] = {"loaded": loaded, "failed": failed, "skipped": not profiles}

    counts = {t: conn.execute(f"SELECT COUNT(*) FROM {t}").fetchone()[0]
              for t in ("players", "skill_snapshots", "teams", "matches", "games",
                        "pairing_history", "player_form", "player_divisions",
                        "tournament_matches", "flex_standings")}
    report["counts"] = counts
    conn.close()
    return report


# --------------------------------------------------------------------------- #
# CLI
# --------------------------------------------------------------------------- #

def _discover_roster_source(did: int = config.DID) -> Path | None:
    """Prefer the newest archived roster grid; fall back to a fixtures capture."""
    raw = config.division_root(did)
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


def _stored_season(conn: sqlite3.Connection, did: int) -> str:
    """Division's season key: stored value first, else derived from the newest
    archived schedule, else the configured default (13077's label)."""
    row = conn.execute("SELECT season FROM divisions WHERE division_id = ?", (did,)).fetchone()
    if row and row["season"]:
        return row["season"]
    scheds = sorted(config.division_root(did).glob("*/schedule.html"))
    if scheds:
        from .parse.schedule import parse_schedule_file
        season = _division_season(did, parse_schedule_file(scheds[-1]))
        conn.execute("UPDATE divisions SET season = ? WHERE division_id = ?", (season, did))
        conn.commit()
        return season
    return config.SEASON


def _load_one(conn: sqlite3.Connection, did: int, date: str, roster: str | None = None) -> None:
    source = Path(roster) if roster else _discover_roster_source(did)
    if source is None or not source.exists():
        print(f"[load] division {did}: no roster grid found — skipped.")
        return
    players = parse_roster_file(source)
    result = load_roster(conn, players, captured_date=date,
                         season=_stored_season(conn, did), division_id=did)
    print(f"Loaded {result['players']} players / {result['teams']} teams "
          f"from {source} @ {result['captured_date']} (division {did})")
    for row in team_depth(conn, season=_stored_season(conn, did), division_id=did):
        print(f"  {row['roster_size']:>2}  {row['team']}")


def ingest(db_path: str = config.DB_PATH, dids: list[int] | None = None) -> dict:
    """INCREMENTAL load: fold new/changed score sheets (plus schedules, official
    match-point results, FLEX, and the newest roster grid for name resolution)
    for the given divisions into an EXISTING `napa.db`, via the idempotent upsert
    loaders. This is the daily path -- it does NOT delete the DB and does NOT run
    the slow profile pass, so it leaves `pairing_history`/`player_form` and every
    other division untouched. Use `--rebuild` only for a from-scratch
    regeneration (schema change / integrity reset). Default dids = every active
    (scrape=True) division; pass a subset (e.g. the divisions that just played).

    Re-ingesting a division is safe: every loader keys on a natural unique tuple
    and upserts (games on (division, date, home_name, away_name); matches on
    (season, round, teams); snapshots append per captured_date), so a second run
    over the same archive changes nothing -- proven by the loader idempotency
    tests and by re-running this command."""
    from .parse.schedule import parse_schedule_file
    from .parse.weekly_scores import parse_score_sheet_file, parse_week_results_file
    from .parse.flex import parse_flex_file

    path = Path(db_path)
    if not path.exists():
        raise FileNotFoundError(
            f"{db_path} does not exist -- run `python -m src.db --rebuild` first; "
            "--ingest folds new data into an EXISTING database.")
    conn = connect(path)
    init_db(conn)  # create-if-not-exists only; never wipes
    dids = dids or config.active_dids()
    report: dict = {"divisions": {}}
    for did in dids:
        root = config.division_root(did)
        season = _stored_season(conn, did)
        rep: dict = {}
        grids = sorted(root.glob("*/roster_grid.html"))
        if grids:
            r = load_roster(conn, parse_roster_file(grids[-1]),
                            captured_date=grids[-1].parent.name, season=season,
                            division_id=did)
            rep["roster"] = {"loads": 1, "csr_conflicts": r["csr_conflicts"]}
        scheds = sorted(root.glob("*/schedule.html"))
        if scheds:
            rep["schedule"] = load_schedule(conn, parse_schedule_file(scheds[-1]),
                                            season=season, division_id=did)
        sheet_files = [f for f in sorted(root.glob("scores/week_*/*.html"))
                       if f.name != "_index.html"]
        if sheet_files:
            sheets = [parse_score_sheet_file(f) for f in sheet_files]
            rep["sheets"] = load_score_sheets(conn, sheets, season=season,
                                              division_id=did)
        results = [r for idx in sorted(root.glob("scores/week_*/_index.html"))
                   for r in parse_week_results_file(idx)]
        if results:
            rep["results"] = load_match_results(conn, results, season=season,
                                                division_id=did)
        flex_files = sorted(root.glob("*/flex.html"))
        if flex_files:
            try:
                fs = parse_flex_file(flex_files[-1])
                rep["flex"] = load_flex(conn, fs, captured_date=flex_files[-1].parent.name,
                                        season=season, division_id=did)
            except Exception as exc:  # noqa: BLE001 — one bad capture must not kill the run
                rep["flex"] = {"error": str(exc)}
        report["divisions"][did] = rep
    counts = {t: conn.execute(f"SELECT COUNT(*) FROM {t}").fetchone()[0]
              for t in ("players", "skill_snapshots", "teams", "matches", "games",
                        "flex_standings")}
    report["counts"] = counts
    conn.close()
    return report


def _profiles_state_path(db_path: str | Path) -> Path:
    """Change-detection state for ingest_profiles, kept beside the DB (regenerable,
    gitignored). Tying it to the DB dir keeps tests on a tmp DB fully isolated."""
    return Path(db_path).resolve().parent / "profiles_ingest_state.json"


def _dir_signature(pdir: Path) -> str:
    """Stat-only signature of a profile dir: sorted `name:size` of its *.html files.
    Cheap (no reads) and sufficient because harvest only ADDS files and never
    rewrites an existing page >500B — so a changed file set means new data landed."""
    return ";".join(f"{p.name}:{p.stat().st_size}"
                    for p in sorted(pdir.glob("*.html")))


def _read_profiles_state(path: Path) -> dict:
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {"version": 1, "dirs": {}}


def _write_profiles_state(path: Path, state: dict) -> None:
    path.write_text(json.dumps(state, indent=0), encoding="utf-8")


def ingest_profiles(db_path: str | Path = config.DB_PATH, *,
                    dids: list[int] | None = None,
                    player_ids: list[str] | None = None,
                    all_dirs: bool = False, force: bool = False,
                    profiles_root: str | Path | None = None) -> dict:
    """INCREMENTAL profile load: fold harvested data/raw/profiles/<id>/ dirs into
    the EXISTING napa.db via the idempotent profile loaders (load_profile_dir) --
    NO wipe, NO full re-walk. The post-HARVEST counterpart to ingest() (the daily,
    profile-free path). Profiles are player-keyed, so scope is by player:
      - player_ids=[...] -> exactly those players
      - dids=[...]       -> every player on those divisions' newest roster grids
      - all_dirs=True    -> every profile dir on disk (the rebuild-equivalent set)
    Default scope (none of the above) = active divisions' rosters. Change detection
    (default): a gitignored state file beside the DB records each dir's stat-only
    signature; only dirs whose signature changed since last ingest are loaded.
    force=True bypasses the filter. Re-ingest is a no-op (idempotent loaders); use
    --rebuild only for schema / integrity resets."""
    from .browser_fetch import _roster_player_ids

    path = Path(db_path)
    if not path.exists():
        raise FileNotFoundError(
            f"{db_path} does not exist -- run `python -m src.db --rebuild` first; "
            "--ingest-profiles folds harvested profiles into an EXISTING database.")
    root = Path(profiles_root) if profiles_root else _profiles_root()
    conn = connect(path)
    init_db(conn)  # create-if-not-exists only; never wipes

    # resolve scope -> candidate player ids that actually have a dir on disk
    if player_ids:
        candidates = [str(p) for p in player_ids]
    elif all_dirs:
        candidates = ([d.name for d in sorted(root.iterdir()) if d.is_dir()]
                      if root.is_dir() else [])
    else:
        ids: set[str] = set()
        for did in (dids or config.active_dids()):
            ids.update(_roster_player_ids(did))
        candidates = sorted(ids)
    candidates = [pid for pid in candidates if (root / pid).is_dir()]

    # change-detection filter (skip dirs whose signature is unchanged) unless force
    state_path = _profiles_state_path(path)
    state = _read_profiles_state(state_path)
    dirs_state = state.setdefault("dirs", {})
    to_load: list[tuple[str, str]] = []
    skipped = 0
    for pid in candidates:
        sig = _dir_signature(root / pid)
        if force or dirs_state.get(pid, {}).get("sig") != sig:
            to_load.append((pid, sig))
        else:
            skipped += 1

    loaded = failed = 0
    today = dt.date.today().isoformat()
    for pid, sig in to_load:
        ok, err = load_profile_dir(conn, root / pid)
        if err is not None:
            failed += 1
            print(f"[ingest-profiles] profile {pid} failed: {err}")
            continue
        if ok:
            loaded += 1
        # record signature whether loaded or cleanly skipped (no main.html), so a
        # genuinely-empty dir isn't retried every run; only errors stay unrecorded.
        dirs_state[pid] = {"sig": sig, "loaded_at": today}
    conn.commit()
    _write_profiles_state(state_path, state)

    counts = {t: conn.execute(f"SELECT COUNT(*) FROM {t}").fetchone()[0]
              for t in ("players", "skill_snapshots", "pairing_history",
                        "player_form", "match_history", "tournament_matches",
                        "player_divisions")}
    conn.close()
    scope = "players" if player_ids else "all_dirs" if all_dirs else "divisions"
    return {"scope": scope, "considered": len(candidates), "loaded": loaded,
            "failed": failed, "skipped_unchanged": skipped, "counts": counts}


def main() -> None:
    parser = argparse.ArgumentParser(description="NAPA database loader")
    parser.add_argument("--load", action="store_true",
                        help="parse roster grid(s) and load into the DB")
    parser.add_argument("--rebuild", action="store_true",
                        help="rebuild the DB from the raw archive (all archived divisions)")
    parser.add_argument("--ingest", action="store_true",
                        help="INCREMENTAL: fold new score sheets (+ schedules, "
                             "match-point results, flex, newest roster) into the "
                             "EXISTING DB via idempotent upserts -- no wipe, no "
                             "profile pass. The daily path; use --did / "
                             "--all-divisions to scope. (cf. --rebuild = from scratch)")
    parser.add_argument("--no-profiles", action="store_true",
                        help="with --rebuild: skip the slow profile pass (pass 4) for a "
                             "fast iteration rebuild; passes 1-3 (rosters/schedules/"
                             "sheets+results) still run over every division")
    parser.add_argument("--ingest-profiles", action="store_true",
                        help="INCREMENTAL: fold HARVESTED profiles (pairing_history, "
                             "player_form, match/tournament history, CSR peaks) into "
                             "the EXISTING DB via idempotent upserts -- no wipe, no "
                             "rebuild. Player-keyed: scope with --did / --all-divisions "
                             "(rostered players), --players, or --all-dirs. Loads only "
                             "dirs that changed since last run unless --force.")
    parser.add_argument("--players", type=str, default=None,
                        help="with --ingest-profiles: comma-separated player_ids to "
                             "ingest (overrides division scope)")
    parser.add_argument("--all-dirs", action="store_true",
                        help="with --ingest-profiles: every profile dir on disk "
                             "(incl. historical-only players), not just rostered")
    parser.add_argument("--force", action="store_true",
                        help="with --ingest-profiles: bypass change-detection and "
                             "load the whole resolved scope")
    parser.add_argument("--did", type=int, default=config.DID,
                        help=f"division to load (default: {config.DID})")
    parser.add_argument("--all-divisions", action="store_true",
                        help="load every active (scrape=True) division")
    parser.add_argument("--roster", type=str, default=None,
                        help="path to a roster-grid file (default: newest archive, "
                             "else a fixtures/ capture; single-division only)")
    parser.add_argument("--date", type=str, default=dt.date.today().isoformat(),
                        help="captured_date for the snapshot (YYYY-MM-DD, default: today)")
    parser.add_argument("--db", type=str, default=config.DB_PATH,
                        help=f"database path (default: {config.DB_PATH})")
    args = parser.parse_args()

    if args.rebuild:
        report = rebuild(args.db, profiles=not args.no_profiles)
        for did, rep in report["divisions"].items():
            print(f"[rebuild] {did}: {rep}")
        print(f"[rebuild] profiles: {report['profiles']}")
        print(f"[rebuild] counts: {report['counts']}")
        return

    if args.ingest:
        dids = config.active_dids() if args.all_divisions else [args.did]
        report = ingest(args.db, dids)
        for did, rep in report["divisions"].items():
            print(f"[ingest] {did}: {rep}")
        print(f"[ingest] counts: {report['counts']}")
        return

    if getattr(args, "ingest_profiles", False):
        pids = [p.strip() for p in args.players.split(",") if p.strip()] if args.players else None
        dids = (config.active_dids() if args.all_divisions
                else None if (pids or args.all_dirs) else [args.did])
        report = ingest_profiles(args.db, dids=dids, player_ids=pids,
                                 all_dirs=args.all_dirs, force=args.force)
        print(f"[ingest-profiles] {report}")
        return

    if not args.load:
        parser.print_help()
        return

    conn = connect(args.db)
    dids = config.active_dids() if args.all_divisions else [args.did]
    for did in dids:
        _load_one(conn, did, args.date, roster=args.roster if not args.all_divisions else None)
    conn.close()


if __name__ == "__main__":
    main()
