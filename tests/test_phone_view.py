"""tools/phone_view.py — the phone snapshot export.

Two things are worth pinning. First, the race matrix is transcribed a SECOND
time in the template's JavaScript so the phone can resolve a race with no
Python around; if src/race.py is ever corrected and the port is not, the phone
would quietly hand out wrong races. These tests re-parse the JS tables out of
the template and assert they still agree with src/race.py — including a full
sweep of every CSR pair, which is what actually catches a single edited row.

Second, the export's scoping rules: the database also holds the historical
backfill, so an unscoped roster join makes a 2024 team read as today's.
"""

from __future__ import annotations

import ast
import json
import re
import sqlite3
from pathlib import Path

import pytest

from src import config, race
from tools import phone_view

TEMPLATE = Path(__file__).resolve().parent.parent / "tools" / "phone_view_template.html"


# ---------------------------------------------------------------- race port
def _js_array(name: str) -> list:
    """Pull a top-level `const <name> = [...]` literal out of the template and
    read it as Python. The two dialects overlap for these tables except for
    Infinity, which stands in for the open-ended last row of every band."""
    src = TEMPLATE.read_text(encoding="utf-8")
    m = re.search(rf"^const {name} = (\[.*?\]);$", src, re.S | re.M)
    assert m, f"{name} not found in {TEMPLATE.name}"
    # 1e999 is a literal that evaluates to inf; float("inf") is a call, which
    # literal_eval rejects.
    return ast.literal_eval(m.group(1).replace("Infinity", "1e999"))


def test_js_band_table_matches_race_py():
    js = _js_array("BANDS")
    py = [[lo, hi, [list(r) for r in rules]] for lo, hi, rules in race._BANDS]
    assert [[lo, hi, [list(r) for r in rules]] for lo, hi, rules in js] == py


def test_js_class_table_matches_race_py():
    assert [tuple(x) for x in _js_array("CLASSES")] == [tuple(x) for x in race._CLASSES]


@pytest.mark.parametrize("hi", [200])
def test_every_csr_pair_agrees(hi):
    """Sweep the whole plausible CSR range. A band table that parses but has one
    edited row only shows up here."""
    bands, classes = _js_array("BANDS"), _js_array("CLASSES")

    def js_race(a, b):
        strong, diff = max(a, b), abs(a - b)
        rules = next((r for lo, h, r in bands if lo <= strong <= h), bands[-1][2])
        rs = rw = None
        for dmax, s, w in rules:
            rs, rw = s, w
            if diff <= dmax:
                break
        return (rs, rw) if a >= b else (rw, rs)

    for a in range(0, hi + 1):
        for b in range(0, hi + 1):
            assert js_race(a, b) == race.race(a, b), f"race({a},{b})"
        assert next(l for c, l in classes if a <= c) == race.csr_class(a)


# ---------------------------------------------------------------- export
def _db(tmp_path: Path) -> str:
    """Two divisions of one player: an ACTIVE registry division and a historical
    did that is not in the registry at all (what the backfill leaves behind)."""
    active = next(d for d in config.DIVISIONS.values() if d.scrape)
    path = tmp_path / "t.db"
    c = sqlite3.connect(path)
    c.executescript("""
        CREATE TABLE players(player_id TEXT, name TEXT, gender TEXT, home_base TEXT,
            member_since TEXT, first_seen TEXT, last_seen TEXT, peak_csr_8 INTEGER,
            peak_csr_9 INTEGER, peak_csr_10 INTEGER, peak_on_8 TEXT, peak_on_9 TEXT,
            peak_on_10 TEXT);
        CREATE TABLE skill_snapshots(player_id TEXT, captured_date TEXT, csr_8 INTEGER,
            csr_9 INTEGER, csr_10 INTEGER, csr_10bp INTEGER, csr_f8 INTEGER,
            csr_7b INTEGER, session_matches INTEGER);
        CREATE TABLE teams(team_id INTEGER, division_id INTEGER, name TEXT, season TEXT);
        CREATE TABLE team_members(team_id INTEGER, player_id TEXT, season TEXT, is_captain INTEGER);
        CREATE TABLE matches(match_id INTEGER, division_id INTEGER, season TEXT, round INTEGER,
            date TEXT, home_team_id INTEGER, away_team_id INTEGER, home_points INTEGER,
            away_points INTEGER);
        CREATE TABLE games(game_id INTEGER, division_id INTEGER, match_id INTEGER,
            played_date TEXT, home_player_id TEXT, away_player_id TEXT, home_player_name TEXT,
            away_player_name TEXT, game_type INTEGER, home_race INTEGER, away_race INTEGER,
            home_won INTEGER, home_score INTEGER, away_score INTEGER);
        CREATE TABLE divisions(division_id INTEGER, name TEXT, weekday TEXT, format TEXT,
            season TEXT, slug TEXT, status TEXT, successor_did INTEGER);
        CREATE TABLE player_form(player_id TEXT, captured_date TEXT, lifetime_played INTEGER,
            lifetime_w INTEGER, lifetime_l INTEGER, lifetime_win_pct INTEGER, avg_ppm REAL,
            last10_w INTEGER, last10_l INTEGER, last10_win_pct INTEGER, last10_assessment TEXT,
            d30_played INTEGER, d30_w INTEGER, d30_l INTEGER, d60_played INTEGER, d60_w INTEGER,
            d60_l INTEGER, d90_played INTEGER, d90_w INTEGER, d90_l INTEGER);
        CREATE TABLE hill_hill(player_id TEXT, captured_date TEXT, matches INTEGER, wins INTEGER,
            losses INTEGER, win_pct INTEGER, g8_w INTEGER, g8_l INTEGER, g9_w INTEGER,
            g9_l INTEGER, g10_w INTEGER, g10_l INTEGER);
    """)
    c.execute("INSERT INTO players(player_id,name,last_seen) VALUES('10000001','Ada Rail','2026-08-18')")
    # two same-day-ish grids: the newer one omits 8-ball, which must NOT erase it
    c.execute("INSERT INTO skill_snapshots VALUES('10000001','2026-06-01',77,NULL,NULL,NULL,NULL,NULL,4)")
    c.execute("INSERT INTO skill_snapshots VALUES('10000001','2026-08-20',NULL,64,58,NULL,NULL,NULL,9)")
    c.execute("INSERT INTO teams VALUES(1,?,'Rail Riders','2026-06-02')", (active.did,))
    c.execute("INSERT INTO teams VALUES(2,11296,'Old Crew','2024-01-01')")
    c.executemany("INSERT INTO team_members VALUES(?,?,?,?)",
                  [(1, "10000001", "2026-06-02", 1), (2, "10000001", "2024-01-01", 0)])
    c.execute("INSERT INTO divisions VALUES(?,'x','Tuesday','LC','2026-06-02','s','active',NULL)", (active.did,))
    c.execute("INSERT INTO matches VALUES(500,?,'2026-06-02',1,'2026-06-02',1,1,10,5)", (active.did,))
    c.execute("""INSERT INTO games VALUES(1,?,500,'2026-06-02','10000001',NULL,'Ada Rail','Sub',
                 9,5,4,1,5,4)""", (active.did,))
    c.commit()
    return str(path), active


def test_roster_is_scoped_to_active_registry_divisions(tmp_path, monkeypatch):
    path, active = _db(tmp_path)
    monkeypatch.setattr(phone_view, "RAW", tmp_path / "nope")
    data = phone_view.gather(path)
    p = next(p for p in data["players"] if p["id"] == "10000001")

    assert [t["did"] for t in p["t"]] == [active.did], "historical did leaked into the roster"
    assert p["a"] == 1 and p["t"][0]["captain"] is True


def test_snapshot_merges_forward_per_game(tmp_path, monkeypatch):
    path, _ = _db(tmp_path)
    monkeypatch.setattr(phone_view, "RAW", tmp_path / "nope")
    p = next(p for p in phone_view.gather(path)["players"] if p["id"] == "10000001")

    assert (p["c8"], p["c9"], p["c10"]) == (77, 64, 58), "a NULL in the newest grid erased a rating"
    assert p["cls"] == race.csr_class(77)
    assert (p["w"], p["l"]) == (1, 0)


def test_render_embeds_valid_json_and_closes_no_tags(tmp_path, monkeypatch):
    path, _ = _db(tmp_path)
    monkeypatch.setattr(phone_view, "RAW", tmp_path / "nope")
    html = phone_view.render(phone_view.gather(path))

    assert "__NAPA_DATA__" not in html
    blob = re.search(r"^const DATA = (\{.*\});$", html, re.M).group(1)
    assert json.loads(blob.replace("<\\/", "</"))["players"]
    assert "</script>" not in blob, "an unescaped </script> would truncate the payload"


def test_standalone_wraps_a_real_document(tmp_path, monkeypatch):
    path, _ = _db(tmp_path)
    monkeypatch.setattr(phone_view, "RAW", tmp_path / "nope")
    doc = phone_view.standalone(phone_view.render(phone_view.gather(path)))

    assert doc.startswith("<!doctype html>")
    assert doc.count("<head>") == 1 and doc.count("<body>") == 1
    assert doc.index("<title>") < doc.index("</head>"), "title must land in the head"
    assert phone_view.MARKER not in doc
