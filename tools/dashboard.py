"""Generate a visual HTML dashboard of the current NAPA data state.

Reads data/napa.db + the raw archive and emits a self-contained, styled HTML
page: league totals, per-division results-completeness (of matches already DUE,
how many have loaded results), capture/profile coverage, and the system/scope
state. Re-runnable — regenerate after a rebuild to refresh the numbers.

    python tools/dashboard.py [--out dashboard.html]
"""

from __future__ import annotations

import argparse
import datetime as dt
import sqlite3
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))  # repo root -> import src
from src import config


def _gather(db: str, today: str) -> dict:
    c = sqlite3.connect(db)
    c.row_factory = sqlite3.Row
    raw = Path("data/raw")

    def one(q, *a):
        return c.execute(q, a).fetchone()[0]

    totals = {t: one(f"SELECT COUNT(*) FROM {t}") for t in
              ["players", "teams", "matches", "games", "skill_snapshots",
               "pairing_history", "tournament_matches"]}

    prof_dirs = ({p.name for p in (raw / "profiles").iterdir() if p.is_dir()}
                 if (raw / "profiles").is_dir() else set())

    divs = []
    for did, d in config.DIVISIONS.items():
        season = one("SELECT season FROM divisions WHERE division_id=?", did)
        total = one("SELECT COUNT(*) FROM matches WHERE division_id=?", did)
        due = one("SELECT COUNT(*) FROM matches WHERE division_id=? AND date<?", did, today)
        duewg = one("""SELECT COUNT(DISTINCT m.match_id) FROM matches m
                       JOIN games g ON g.match_id=m.match_id
                       WHERE m.division_id=? AND m.date<?""", did, today)
        rounds = one("SELECT COALESCE(MAX(round),0) FROM matches WHERE division_id=?", did)
        rdone = one("SELECT COALESCE(MAX(round),0) FROM matches WHERE division_id=? AND date<?", did, today)
        sheets = len([f for f in (raw / str(did)).glob("scores/week_*/*.html")
                      if f.name != "_index.html"])
        rp = [r[0] for r in c.execute(
            """SELECT DISTINCT tm.player_id FROM team_members tm
               JOIN teams t ON tm.team_id=t.team_id
               WHERE t.division_id=? AND tm.player_id IS NOT NULL""", (did,))]
        divs.append(dict(
            did=did, name=d.name, weekday=d.weekday, fmt=d.fmt, slug=d.slug,
            season=season, games=one("SELECT COUNT(*) FROM games WHERE division_id=?", did),
            teams=one("SELECT COUNT(*) FROM teams WHERE division_id=?", did),
            total=total, due=due, duewg=duewg, rounds=rounds, rdone=rdone,
            cov=(duewg / due if due else None), sheets=sheets,
            rp=len(rp), prof=sum(1 for p in rp if p in prof_dirs)))

    dates = sorted({p.name for did in raw.iterdir() if did.is_dir() and did.name.isdigit()
                    for p in did.glob("*") if p.is_dir() and p.name.count("-") == 2})
    c.close()
    return {"totals": totals, "divisions": divs,
            "captured_through": dates[-1] if dates else "—"}


def _status(r: dict) -> tuple[str, str]:
    """(css-class, label)."""
    if r["did"] == 14050:
        return "new", "season starts tonight"
    if r["due"] == 0:
        return "new", "not yet underway"
    if r["duewg"] == 0:
        return "bad", "no results posted upstream"
    if r["cov"] >= 0.95:
        return "good", "caught up"
    return "warn", f"{r['cov'] * 100:.0f}% of due matches posted"


def render(data: dict, today: str) -> str:
    t = data["totals"]
    cards = [
        ("divisions", 15), ("players", t["players"]), ("teams", t["teams"]),
        ("matches", t["matches"]), ("games (racks)", t["games"]),
        ("skill snapshots", t["skill_snapshots"]),
        ("H2H pairings", t["pairing_history"]), ("tournament matches", t["tournament_matches"]),
    ]
    card_html = "".join(
        f'<div class="card"><div class="num">{v:,}</div><div class="lbl">{k}</div></div>'
        for k, v in cards)

    rows = []
    for r in sorted(data["divisions"],
                    key=lambda x: (x["cov"] is None, x["cov"] if x["cov"] is not None else 1),
                    reverse=True):
        cls, label = _status(r)
        pct = 0 if r["cov"] is None else round(r["cov"] * 100)
        you = '<span class="you">YOU</span>' if r["did"] == 14050 else ""
        rname = r["name"].replace("&", "&amp;").replace("<", "&lt;")
        bar = (f'<div class="track"><div class="fill {cls}" style="width:{pct}%"></div>'
               f'<span class="pct">{pct}%</span></div>')
        rows.append(f"""<tr>
          <td class="mono">{r['did']} {you}</td>
          <td>{rname}<div class="sub">{r['weekday']} · {r['fmt']} · {r['slug']}</div></td>
          <td class="mono">{r['season']}</td>
          <td class="mono">{r['rdone']}/{r['rounds']}</td>
          <td class="mono">{r['duewg']}/{r['due']}</td>
          <td style="min-width:220px">{bar}</td>
          <td><span class="pill {cls}">{label}</span></td>
          <td class="mono">{r['prof']}/{r['rp']}</td>
        </tr>""")

    return f"""<!doctype html><html lang="en"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>NAPA Data — Current State</title>
<style>
  :root {{ color-scheme: dark; }}
  * {{ box-sizing: border-box; }}
  body {{ margin:0; font:15px/1.45 -apple-system,Segoe UI,Roboto,sans-serif;
         background:#0d1117; color:#e6edf3; padding:24px; }}
  h1 {{ font-size:22px; margin:0 0 2px; }}
  .meta {{ color:#8b949e; font-size:13px; margin-bottom:20px; }}
  .cards {{ display:flex; flex-wrap:wrap; gap:12px; margin-bottom:24px; }}
  .card {{ background:#161b22; border:1px solid #30363d; border-radius:10px;
          padding:12px 16px; min-width:120px; flex:1; }}
  .card .num {{ font-size:24px; font-weight:700; }}
  .card .lbl {{ color:#8b949e; font-size:12px; text-transform:uppercase; letter-spacing:.04em; }}
  h2 {{ font-size:15px; color:#8b949e; text-transform:uppercase; letter-spacing:.05em;
        border-bottom:1px solid #30363d; padding-bottom:6px; margin:28px 0 12px; }}
  table {{ width:100%; border-collapse:collapse; }}
  th,td {{ text-align:left; padding:9px 10px; border-bottom:1px solid #21262d; vertical-align:middle; }}
  th {{ color:#8b949e; font-size:11px; text-transform:uppercase; letter-spacing:.05em; }}
  .mono {{ font-family:ui-monospace,SFMono-Regular,Consolas,monospace; font-size:13px; }}
  .sub {{ color:#6e7681; font-size:11px; margin-top:2px; }}
  .track {{ position:relative; background:#21262d; border-radius:6px; height:20px; overflow:hidden; }}
  .fill {{ height:100%; }}
  .fill.good {{ background:#238636; }} .fill.warn {{ background:#9e6a03; }}
  .fill.bad {{ background:#5a1e1e; }} .fill.new {{ background:#1f4f7a; }}
  .pct {{ position:absolute; right:7px; top:1px; font-size:11px; font-family:ui-monospace,monospace; }}
  .pill {{ font-size:11px; padding:2px 9px; border-radius:20px; white-space:nowrap; }}
  .pill.good {{ background:#0f3d20; color:#56d364; }} .pill.warn {{ background:#3d2e05; color:#e3b341; }}
  .pill.bad {{ background:#3d1518; color:#f85149; }} .pill.new {{ background:#10283f; color:#58a6ff; }}
  .you {{ background:#1f6feb; color:#fff; font-size:10px; padding:1px 6px; border-radius:10px; }}
  .panel {{ background:#161b22; border:1px solid #30363d; border-radius:10px; padding:14px 18px; }}
  .panel li {{ margin:4px 0; }} .panel b {{ color:#fff; }}
  footer {{ color:#6e7681; font-size:12px; margin-top:24px; }}
</style></head><body>
  <h1>NAPA of Northern Colorado — Data System</h1>
  <div class="meta">Current state · generated {dt.datetime.now().strftime('%Y-%m-%d %H:%M')}
      · raw archive captured through {data['captured_through']} · reference date {today}</div>
  <div class="cards">{card_html}</div>

  <h2>Results completeness — of matches already due, how many are loaded</h2>
  <table>
    <thead><tr><th>div</th><th>division</th><th>season (R1)</th><th>rounds</th>
      <th>due / loaded</th><th>completeness</th><th>status</th><th>profiles</th></tr></thead>
    <tbody>{''.join(rows)}</tbody>
  </table>

  <h2>System &amp; scope</h2>
  <div class="panel"><ul>
    <li>Scope: <b>NoCo-only (15 divisions)</b> — El Paso + Mesa excluded (parked, not integrated).</li>
    <li>Capture: every division has rosters, schedules &amp; all available score sheets on disk.</li>
    <li>Profiles: every rostered player harvested <b>and full-drilled</b> (pairing_history {t['pairing_history']:,} lifetime H2H edges).</li>
    <li>Season-rollover discovery is <b>live</b> — 14050 onboarded as 13077's successor; the cron auto-handles future rollovers.</li>
  </ul></div>

  <footer>Completeness counts a match as "loaded" once any game result for it is in the DB.
    Green = caught up · amber = some played matches still posting · red = upstream hasn't posted ·
    blue = season not yet underway.</footer>
</body></html>"""


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--db", default=config.DB_PATH)
    ap.add_argument("--out", default="dashboard.html")
    ap.add_argument("--today", default=dt.date.today().isoformat())
    a = ap.parse_args()
    html = render(_gather(a.db, a.today), a.today)
    Path(a.out).write_text(html, encoding="utf-8")
    print(f"wrote {a.out} ({len(html):,} bytes)")


if __name__ == "__main__":
    main()
