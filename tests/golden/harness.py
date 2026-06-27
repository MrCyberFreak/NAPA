"""Shared scoped builder + extractor for the golden-dataset regression harness.

ONE source of truth used by BOTH:
  - tools/golden_capture.py  (writes tests/golden/golden.json from a clean build)
  - tests/test_golden_harness.py  (re-builds + diffs against golden.json)

so the captured "known good" and the asserted-against build are produced by the
SAME deterministic code path -- a parse->DB build over the COMMITTED raw archive,
NOT a live network scrape (the scrape is non-deterministic + bot-challenged; the
archive is the durable record, per CLAUDE.md "Hard rules"). The two silent
extraction failures this guards against (the empty-"NO MATCH(ES) PLAYED" score
sheet and the resume-guard glob) both lived on exactly this archive->DB path.

The builder is a SCOPED mirror of src.db.rebuild()'s pass order (rosters ->
schedules -> score sheets + match-point results -> flex -> profiles) restricted to
a handful of divisions and an explicit set of player profile dirs, so it runs in
seconds instead of the multi-hour full rebuild and never touches data/napa.db.
Every path is anchored at the repo root (resolved from __file__), so it is
CWD-independent.
"""

from __future__ import annotations

import json
from pathlib import Path

REPO = Path(__file__).resolve().parents[2]
RAW = REPO / "data" / "raw"
GOLDEN_JSON = REPO / "tests" / "golden" / "golden.json"

# The three golden divisions, chosen to span the fragile parse paths:
#   13077 -> Thursday Big Table Felt LC  (8/9/10 ints; the project anchor)
#   13298 -> Piazzas Tuesday 8-ball      (bare "CSR" header; 8-ball-only path)
#   13986 -> Zoosters Laggers            (8/9/10 + "10BP" text game_type, 4-game)
GOLDEN_DIDS = [13077, 13298, 13986]

# Fixed snapshot date for the scoped form/hill-hill load. The harness compares
# parsed VALUES (which are date-independent), never this key, so a constant keeps
# exactly one row per player and the build fully deterministic.
GOLDEN_CAPTURED_DATE = "golden"

# How many anchor rows to capture per category (bounded but a strong guard).
MAX_MATCHES = 8        # match-point pairs per division
MAX_GAMES_PER_TYPE = 4  # rack rows per distinct game_type (so 10BP/8/9/10 all land)
MAX_PLAYERS = 10       # players carried for form + hill-hill per division


def _div_root(did: int) -> Path:
    return RAW / str(did)


def _profiles_root() -> Path:
    return RAW / "profiles"


def build_division_db(db_path: str | Path, dids: list[int],
                      player_ids: list[str]) -> "object":
    """Build a fresh scoped napa.db at `db_path` from the committed raw archive.

    Mirrors rebuild()'s pass order but only for `dids` (+ the listed player
    profile dirs in pass 4), driving the same idempotent load_* functions with
    absolute archive paths. Returns the open sqlite3 connection (caller closes).
    Deterministic: fixed dids, sorted file globs, a fresh DB each call.
    """
    from src.db import (connect, init_db, load_flex, load_hill_hill,
                        load_match_results, load_roster, load_schedule,
                        load_score_sheets, load_trends, _division_season)
    from src.parse.flex import parse_flex_file
    from src.parse.profile import parse_hillhill_summary, parse_trends
    from src.parse.roster import parse_roster_file
    from src.parse.schedule import parse_schedule_file
    from src.parse.weekly_scores import (parse_score_sheet_file,
                                         parse_week_results_file)

    path = Path(db_path)
    if path.exists():
        path.unlink()
    conn = connect(path)
    init_db(conn)

    # Season keys first (teams/matches key on them).
    seasons: dict[int, str] = {}
    fixtures_by_did: dict[int, list] = {}
    for did in dids:
        scheds = sorted(_div_root(did).glob("*/schedule.html"))
        fixtures_by_did[did] = parse_schedule_file(scheds[-1]) if scheds else []
        seasons[did] = _division_season(did, fixtures_by_did[did])
        conn.execute("UPDATE divisions SET season = ? WHERE division_id = ?",
                     (seasons[did], did))
    conn.commit()

    for did in dids:  # pass 1: rosters (master list + snapshots + affiliations)
        for grid in sorted(_div_root(did).glob("*/roster_grid.html")):
            load_roster(conn, parse_roster_file(grid),
                        captured_date=grid.parent.name, season=seasons[did],
                        division_id=did)

    for did in dids:  # pass 2: schedules
        if fixtures_by_did[did]:
            load_schedule(conn, fixtures_by_did[did], season=seasons[did],
                          division_id=did)

    for did in dids:  # pass 3: score sheets (per-game grain) + match-point results
        sheet_files = [f for f in sorted(_div_root(did).glob("scores/week_*/*.html"))
                       if f.name != "_index.html"]
        if sheet_files:
            load_score_sheets(conn, [parse_score_sheet_file(f) for f in sheet_files],
                              season=seasons[did], division_id=did)
        results = [r for idx in sorted(_div_root(did).glob("scores/week_*/_index.html"))
                   for r in parse_week_results_file(idx)]
        if results:
            load_match_results(conn, results, season=seasons[did], division_id=did)

    for did in dids:  # pass 3b: FLEX individual point standings
        for ff in sorted(_div_root(did).glob("*/flex.html")):
            try:
                load_flex(conn, parse_flex_file(ff), captured_date=ff.parent.name,
                          season=seasons[did], division_id=did)
            except Exception:  # noqa: BLE001 — one bad capture must not kill the build
                pass

    # pass 4 (scoped + minimal): the harness asserts only FORM (trends.html) and
    # HILL-HILL (h2h.html), so load just those two via the same load_trends /
    # load_hill_hill the real pipeline uses -- NOT the full load_profile_dir, which
    # also walks every rival_*/match_*/tournament file (irrelevant here and the
    # reason a full load over the golden players took minutes). Match points and
    # racks come from the score sheets (pass 3), not profiles. A fixed captured_date
    # keeps one row per player; the harness compares VALUES, never the date.
    proot = _profiles_root()
    for pid in player_ids:
        pdir = proot / pid
        tf, hf = pdir / "trends.html", pdir / "h2h.html"
        if tf.exists():
            load_trends(conn, pid, parse_trends(tf.read_text(encoding="utf-8", errors="replace")),
                        GOLDEN_CAPTURED_DATE)
        if hf.exists():
            load_hill_hill(conn, pid, parse_hillhill_summary(hf.read_text(encoding="utf-8", errors="replace")),
                           GOLDEN_CAPTURED_DATE)
    conn.commit()
    return conn


# --------------------------------------------------------------------------- #
# Extraction (deterministic, natural-key-ordered anchor rows per division)
# --------------------------------------------------------------------------- #

# Columns asserted per category. "Every field non-null" (the goal's words) is
# enforced over exactly these columns -- they are the load-bearing values a
# silent extraction failure would blank out or corrupt.
MATCH_COLS = ["round", "home_team", "away_team", "home_points", "away_points"]
RACK_COLS = ["played_date", "home_player_name", "away_player_name", "game_type",
             "home_race", "away_race", "home_won", "home_score", "away_score"]
FORM_COLS = ["player_id", "lifetime_played", "lifetime_w", "lifetime_l",
             "lifetime_win_pct"]
HILL_COLS = ["player_id", "matches", "wins", "losses", "win_pct"]


def _season(conn, did: int) -> str:
    row = conn.execute("SELECT season FROM divisions WHERE division_id = ?",
                       (did,)).fetchone()
    return row["season"]


def _rostered_pids(conn, did: int) -> list[str]:
    """Player ids rostered in `did` (this season), player_id-sorted."""
    season = _season(conn, did)
    return [r["player_id"] for r in conn.execute(
        """SELECT DISTINCT p.player_id
           FROM team_members tm
           JOIN teams t ON t.team_id = tm.team_id AND t.division_id = ?
           JOIN players p ON p.player_id = tm.player_id
           WHERE tm.season = ?
           ORDER BY p.player_id""", (did, season))]


def player_form_hh_complete(pid: str) -> bool:
    """Cheap selection probe: parse ONLY trends.html + h2h.html for `pid` and
    report whether the asserted form + hill-hill columns are all non-null. Avoids
    a full load_profile_dir (rivals + every rival_*/match_*/tournament file) per
    selection candidate, which made capture take many minutes over ~228 players.
    Used identically by capture and by extract_division, so both pick the same set."""
    from src.parse.profile import parse_hillhill_summary, parse_trends

    pdir = _profiles_root() / pid
    tf, hf = pdir / "trends.html", pdir / "h2h.html"
    if not (tf.exists() and hf.exists()):
        return False
    form = parse_trends(tf.read_text(encoding="utf-8", errors="replace"))
    if any(getattr(form, a) is None for a in
           ("lifetime_played", "lifetime_w", "lifetime_l", "lifetime_win_pct")):
        return False
    hh = parse_hillhill_summary(hf.read_text(encoding="utf-8", errors="replace"))
    return all(getattr(hh, a) is not None for a in ("matches", "wins", "losses", "win_pct"))


def select_golden_players(conn, did: int, limit: int = MAX_PLAYERS) -> list[str]:
    """Rostered players (player_id order) whose form AND hill-hill are FULLY
    non-null over the asserted columns -- the curated complete records the harness
    locks in. Deterministic: id-sorted, first `limit`. The completeness probe is
    file-based (player_form_hh_complete), so this needs only the rosters loaded in
    `conn`, not the profiles -- the same selection runs on capture's profile-less
    base DB and on the test's union-loaded DB and yields the identical set."""
    out: list[str] = []
    for pid in _rostered_pids(conn, did):
        if player_form_hh_complete(pid):
            out.append(pid)
        if len(out) >= limit:
            break
    return out


def extract_division(conn, did: int, match_limit: int | None = None) -> dict:
    """Pull the deterministic anchor sets for one division from a built DB.

    match_limit bounds the match_points slice ONLY when FREEZING the baseline
    (golden_capture passes MAX_MATCHES), so the stored set stays small and
    anchored on the earliest rounds. At CHECK time it is left None, so the
    rebuild returns EVERY scored match and the frozen rows are verified as a
    SUBSET (test_rebuild_matches_golden). That is stable as a LIVING season
    fills in / adds matches: the old fixed top-N sample silently shifted as
    earlier rounds filled in and false-flagged "drift" on rows that were still
    correct, merely pushed past the LIMIT."""
    season = _season(conn, did)

    mp_sql = (
        "SELECT m.round AS round, h.name AS home_team, a.name AS away_team, "
        "m.home_points AS home_points, m.away_points AS away_points "
        "FROM matches m "
        "JOIN teams h ON h.team_id = m.home_team_id "
        "JOIN teams a ON a.team_id = m.away_team_id "
        "WHERE m.division_id = ? AND m.season = ? "
        "AND m.home_points IS NOT NULL AND m.away_points IS NOT NULL "
        "ORDER BY m.round, h.name, a.name"
    )
    mp_params: list = [did, season]
    if match_limit is not None:
        mp_sql += " LIMIT ?"
        mp_params.append(match_limit)
    match_points = [dict(r) for r in conn.execute(mp_sql, mp_params)]

    # Racks: a bounded slice PER distinct game_type so every fragile type path
    # (8/9/10 ints + "10BP" text) is represented, not just the most common one.
    gtypes = [r["game_type"] for r in conn.execute(
        "SELECT DISTINCT game_type FROM games WHERE division_id = ? "
        "AND game_type IS NOT NULL ORDER BY CAST(game_type AS TEXT)", (did,))]
    racks: list[dict] = []
    for gt in gtypes:
        # home_player_id/away_player_id are CAPTURED and exact-matched (the
        # resolution guard, see test_name_to_id_resolution_is_anchored) but are NOT
        # in RACK_COLS' non-null set: subs legitimately resolve to NULL (A1 rule),
        # so freezing the VALUES catches an all-NULL resolution collapse via drift
        # without falsely failing on a real sub. The *_name natural keys never go
        # NULL, which is exactly why a resolution regression was invisible before.
        racks += [dict(r) for r in conn.execute(
            """SELECT played_date, home_player_name, home_player_id,
                      away_player_name, away_player_id, game_type,
                      home_race, away_race, home_won, home_score, away_score
               FROM games
               WHERE division_id = ? AND game_type = ?
                 AND home_race IS NOT NULL AND away_race IS NOT NULL
                 AND home_won IS NOT NULL
                 AND home_score IS NOT NULL AND away_score IS NOT NULL
               ORDER BY played_date, home_player_name, away_player_name
               LIMIT ?""", (did, gt, MAX_GAMES_PER_TYPE))]

    pids = select_golden_players(conn, did)
    form = [dict(conn.execute(
        "SELECT ? AS player_id, lifetime_played, lifetime_w, lifetime_l, "
        "lifetime_win_pct FROM player_form WHERE player_id = ? "
        "ORDER BY captured_date DESC LIMIT 1", (pid, pid)).fetchone()) for pid in pids]
    hill = [dict(conn.execute(
        "SELECT ? AS player_id, matches, wins, losses, win_pct FROM hill_hill "
        "WHERE player_id = ? ORDER BY captured_date DESC LIMIT 1",
        (pid, pid)).fetchone()) for pid in pids]

    return {"match_points": match_points, "racks": racks, "form": form,
            "hill_hill": hill}


def load_golden() -> dict:
    return json.loads(GOLDEN_JSON.read_text(encoding="utf-8"))
