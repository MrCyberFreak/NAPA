"""Generate a self-contained, phone-friendly HTML view of the current NAPA data.

Reads data/napa.db (and the raw archive, for capture freshness) and emits ONE
HTML file with the player data embedded as JSON — no server, no network, no
external assets. Open it on a phone and it works offline.

What it carries:
  * a freshness strip — how current the archive actually is, per division
  * every player, searchable, with their CURRENT per-game CSR + team/division
  * the NAPA race matrix (src/race.py, ported verbatim) so any two players'
    race lengths resolve on the phone

It is a SNAPSHOT, not a live feed: the numbers are exactly as fresh as the last
committed scrape. Re-run after a rebuild to refresh.

    python tools/phone_view.py [--db data/napa.db] [--out phone.html]
"""

from __future__ import annotations

import argparse
import datetime as dt
import json
import pathlib
import sqlite3
import sys

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent.parent))  # repo root
from src import config, race as race_mod

RAW = pathlib.Path("data/raw")


# --------------------------------------------------------------------------
# gather
# --------------------------------------------------------------------------
def _latest_snapshots(c: sqlite3.Connection) -> dict[str, sqlite3.Row]:
    """Newest skill_snapshots row per player, merging forward any per-game CSR
    the newest row happens to leave NULL (same-day grids merge, but a player
    seen on a 9/10-only night keeps the 8-ball number from their last 8 grid)."""
    out: dict[str, dict] = {}
    cols = ("csr_8", "csr_9", "csr_10", "csr_10bp", "csr_f8", "csr_7b")
    q = """SELECT player_id, captured_date, csr_8, csr_9, csr_10, csr_10bp,
                  csr_f8, csr_7b, session_matches
           FROM skill_snapshots ORDER BY player_id, captured_date"""
    for r in c.execute(q):
        cur = out.setdefault(r["player_id"], {"player_id": r["player_id"]})
        for k in cols:
            if r[k] is not None:
                cur[k] = r[k]
                cur[f"{k}_on"] = r["captured_date"]
        cur["captured_date"] = r["captured_date"]
        if r["session_matches"] is not None:
            cur["session_matches"] = r["session_matches"]
    return out


def _team_map(c: sqlite3.Connection) -> dict[str, list[dict]]:
    """player_id -> the teams they are CURRENTLY rostered on.

    Scoped twice, and both are load-bearing. The database also holds the
    historical backfill (dids back to 2022), whose divisions are not in the
    registry — unscoped, a player picks up every team they were ever on and a
    2024 roster reads as today's. So: registry divisions with scrape=True only,
    and within each, only its newest season (a rolled-over did keeps the prior
    session's roster rows)."""
    active = {did for did, d in config.DIVISIONS.items() if d.scrape}
    newest: dict[int, str] = {}
    for did, season in c.execute(
            "SELECT division_id, MAX(season) FROM teams GROUP BY division_id"):
        newest[did] = season

    out: dict[str, list[dict]] = {}
    q = """SELECT tm.player_id, t.name AS team, t.division_id, t.season, tm.is_captain
           FROM team_members tm JOIN teams t ON t.team_id = tm.team_id"""
    for r in c.execute(q):
        did = r["division_id"]
        if did not in active or r["season"] != newest.get(did):
            continue
        d = config.DIVISIONS[did]
        out.setdefault(r["player_id"], []).append({
            "team": r["team"],
            "did": did,
            "div": d.name,
            "weekday": d.weekday,
            "captain": bool(r["is_captain"]),
        })
    for v in out.values():
        v.sort(key=lambda t: (t["weekday"], t["team"]))
    return out


def _rack_records(c: sqlite3.Connection) -> dict[str, dict]:
    """Lifetime rack (game) W-L per player from the score sheets, plus the most
    recent date they actually appear in a result."""
    rec: dict[str, dict] = {}

    def bump(pid, won, played):
        if not pid:
            return
        r = rec.setdefault(pid, {"w": 0, "l": 0, "last": None})
        r["w" if won else "l"] += 1
        if played and (r["last"] is None or played > r["last"]):
            r["last"] = played

    q = "SELECT home_player_id, away_player_id, home_won, played_date FROM games"
    for home, away, home_won, played in c.execute(q):
        if home_won is None:
            continue
        bump(home, bool(home_won), played)
        bump(away, not home_won, played)
    return rec


def _form_map(c: sqlite3.Connection) -> dict[str, dict]:
    """Newest player_form + hill_hill snapshot per player.

    Profile harvests are per-division and some divisions are still deferred, so
    this is deliberately PARTIAL — a player with no harvest simply has no form,
    and the card omits the line rather than implying a zero record."""
    form: dict[str, dict] = {}
    for r in c.execute("""SELECT player_id, captured_date, last10_w, last10_l,
                                 d90_played, d90_w, d90_l, lifetime_win_pct
                          FROM player_form ORDER BY captured_date"""):
        form[r["player_id"]] = {
            "on": r["captured_date"],
            "l10w": r["last10_w"], "l10l": r["last10_l"],
            "d90": r["d90_played"], "d90w": r["d90_w"], "d90l": r["d90_l"],
            "life": r["lifetime_win_pct"],
        }
    for r in c.execute("""SELECT player_id, matches, wins, losses
                          FROM hill_hill ORDER BY captured_date"""):
        if r["matches"]:
            form.setdefault(r["player_id"], {}).update(
                {"hh": r["matches"], "hhw": r["wins"], "hhl": r["losses"]})
    return form


def _division_state(c: sqlite3.Connection, today: str) -> list[dict]:
    """Per active division: how fresh the capture is and what is still owed."""
    try:
        catchup = json.loads((RAW / "_catchup.json").read_text()).get("divisions", {})
    except Exception:
        catchup = {}

    rows = []
    for did, d in config.DIVISIONS.items():
        if not d.scrape:
            continue
        root = RAW / str(did)
        dates = sorted(p.name for p in root.glob("20[0-9][0-9]-*") if p.is_dir()) if root.is_dir() else []
        weeks = sorted((root / "scores").glob("week_*")) if (root / "scores").is_dir() else []
        season = c.execute("SELECT season FROM divisions WHERE division_id=?", (did,)).fetchone()
        played = c.execute(
            "SELECT COUNT(*) FROM matches WHERE division_id=? AND date<=?", (did, today)).fetchone()[0]
        loaded = c.execute(
            """SELECT COUNT(DISTINCT m.match_id) FROM matches m
               JOIN games g ON g.match_id = m.match_id
               WHERE m.division_id=? AND m.date<=?""", (did, today)).fetchone()[0]
        last_result = c.execute(
            "SELECT MAX(played_date) FROM games WHERE division_id=?", (did,)).fetchone()[0]
        pend = catchup.get(str(did), {})
        rows.append({
            "did": did,
            "name": d.name,
            "weekday": d.weekday,
            "fmt": d.fmt,
            "season": season[0] if season else None,
            "last_capture": dates[-1] if dates else None,
            "weeks": len(weeks),
            "due": played,
            "loaded": loaded,
            "last_result": last_result,
            "pending_rounds": pend.get("rounds", []),
            "pending_since": pend.get("since"),
        })
    rows.sort(key=lambda r: (r["last_capture"] or "", r["did"]), reverse=True)
    return rows


def gather(db: str) -> dict:
    c = sqlite3.connect(db)
    c.row_factory = sqlite3.Row
    today = dt.date.today().isoformat()

    snaps = _latest_snapshots(c)
    teams = _team_map(c)
    recs = _rack_records(c)
    forms = _form_map(c)

    players = []
    for r in c.execute("SELECT player_id, name, last_seen FROM players ORDER BY name"):
        pid = r["player_id"]
        s = snaps.get(pid, {})
        rec = recs.get(pid, {})
        tm = teams.get(pid, [])
        csrs = {g: s.get(f"csr_{g}") for g in ("8", "9", "10", "10bp")}
        best = max([v for v in csrs.values() if v is not None], default=None)
        players.append({
            "id": pid,
            "n": r["name"],
            "c8": csrs["8"], "c9": csrs["9"], "c10": csrs["10"], "cbp": csrs["10bp"],
            "cls": race_mod.csr_class(best) if best is not None else None,
            "on": s.get("captured_date"),
            "sm": s.get("session_matches"),
            "t": tm,
            "a": 1 if tm else 0,   # currently rostered in an active division
            "f": forms.get(pid),
            "w": rec.get("w", 0),
            "l": rec.get("l", 0),
            "last": rec.get("last") or r["last_seen"],
        })

    divisions = _division_state(c, today)
    captures = [d["last_capture"] for d in divisions if d["last_capture"]]

    return {
        "generated": dt.datetime.now(dt.timezone.utc).isoformat(timespec="seconds"),
        "today": today,
        "archive_through": max(captures) if captures else None,
        "archive_oldest": min(captures) if captures else None,
        "totals": {t: c.execute(f"SELECT COUNT(*) FROM {t}").fetchone()[0]
                   for t in ("players", "teams", "matches", "games", "skill_snapshots")},
        "divisions": divisions,
        "players": players,
    }


# --------------------------------------------------------------------------
# render
# --------------------------------------------------------------------------
TEMPLATE = pathlib.Path(__file__).resolve().parent / "phone_view_template.html"
MARKER = "<!--HEAD-END-->"


def render(data: dict) -> str:
    """Inject the gathered data into the static template as one JSON blob."""
    blob = json.dumps(data, separators=(",", ":"), ensure_ascii=False)
    blob = blob.replace("</", "<\\/")  # a literal </script> would close the tag early
    html = TEMPLATE.read_text(encoding="utf-8")
    if "__NAPA_DATA__" not in html:
        raise SystemExit(f"template {TEMPLATE} is missing the __NAPA_DATA__ placeholder")
    return html.replace("__NAPA_DATA__", blob)


def standalone(content: str) -> str:
    """Wrap the template body in a real document, so opening the file straight
    off a phone's downloads folder renders in standards mode. The artifact host
    supplies its own skeleton, hence the split."""
    head, _, body = content.partition(MARKER)
    if not body:
        head, body = "", content
    return ('<!doctype html>\n<html lang="en">\n<head>\n<meta charset="utf-8">\n'
            f'{head.strip()}\n</head>\n<body>\n{body.strip()}\n</body>\n</html>\n')


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--db", default=config.DB_PATH)
    ap.add_argument("--out", default="phone.html",
                    help="standalone HTML document (default: phone.html)")
    ap.add_argument("--artifact", default=None,
                    help="also write the unwrapped body, for hosts that supply their own skeleton")
    a = ap.parse_args()

    if not pathlib.Path(a.db).exists():
        raise SystemExit(f"no database at {a.db} - run: python -m src.db --rebuild")

    data = gather(a.db)
    content = render(data)

    written = []
    out = pathlib.Path(a.out)
    out.write_text(standalone(content), encoding="utf-8")
    written.append(out)
    if a.artifact:
        art = pathlib.Path(a.artifact)
        art.write_text(content, encoding="utf-8")
        written.append(art)

    t = data["totals"]
    for f in written:
        print(f"{f}  ({f.stat().st_size / 1024:.0f} KB)")
    print(f"  archive through {data['archive_through']}  |  {t['players']} players, "
          f"{t['games']} racks, {len(data['divisions'])} divisions")


if __name__ == "__main__":
    main()
