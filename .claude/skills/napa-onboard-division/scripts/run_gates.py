#!/usr/bin/env python3
"""Onboarding gate runner for ONE NoCo division (napa-onboard-division skill).

Encodes the per-division STOP gates from MULTIDIVISION_PLAN.md ("Per-division
onboarding playbook" step 5 + "Verification") against the raw archive and
data/napa.db. By default it re-runs `db.rebuild()` first, because two gates
(the CSR-disagreement warn and the unresolved-schedule-team count) exist only
in the load report, not in the rebuilt DB. napa.db is regenerable by design,
so the rebuild is safe.

Usage (from anywhere -- the script chdirs to the repo root):
  python .claude/skills/napa-onboard-division/scripts/run_gates.py --did 13985
  ... --no-rebuild              gate an existing data/napa.db (report gates SKIP)
  ... --baseline-null-slots 99  13077 pre-expansion NULL-slot baseline
  ... --as-of 2026-06-12        pending-makeup cutoff (default: today)
  ... --max-null-rate 0.20      hard ceiling for the division's NULL-slot rate

Exit code 0 = every hard gate passed; 1 = at least one FAIL.
"""
from __future__ import annotations

import argparse
import datetime as dt
import json
import os
import sys
from pathlib import Path

# .claude/skills/napa-onboard-division/scripts/run_gates.py -> repo root.
# `python script.py` does not put the repo on sys.path, and every src/ path
# (data/raw, data/napa.db) is repo-relative -- insert + chdir explicitly.
REPO = Path(__file__).resolve().parents[4]
sys.path.insert(0, str(REPO))
os.chdir(REPO)

from src import config, db  # noqa: E402

PASS, FAIL, WARN, INFO, SKIP = "PASS", "FAIL", "WARN", "INFO", "SKIP"
RESULTS: list[tuple[str, str]] = []


def emit(status: str, msg: str) -> None:
    RESULTS.append((status, msg))
    print(f"[{status:4}] {msg}")


def gate_archive(did: int) -> bool:
    """data/raw/<did>/<date>/ capture dirs + scores/week_NN sheets present.
    Raw HTML is archived BEFORE parsing -- this is the committed durable record."""
    root = config.division_root(did)
    grids = sorted(root.glob("*/roster_grid.html"))
    if grids:
        emit(PASS, f"archive: {len(grids)} dated roster grid(s) under {root}/<date>/ "
                   f"(newest {grids[-1].parent.name})")
    else:
        emit(FAIL, f"archive: no roster grids under {root}/<date>/ -- the daily "
                   "scrape never captured this division (flag not flipped, no cron "
                   "run yet, or a challenge abort upstream)")
    weeks = sorted((root / "scores").glob("week_*"))
    sheets = [f for f in (root / "scores").glob("week_*/*.html") if f.name != "_index.html"]
    if sheets:
        emit(PASS, f"archive: {len(sheets)} score sheets across {len(weeks)} week dirs "
                   f"under {root}/scores/")
    else:
        emit(WARN, f"archive: no score sheets under {root}/scores/ -- explainable ONLY "
                   "if the division's season has zero played weeks (seasons are "
                   f"STAGGERED); otherwise dispatch backfill.yml did={did} weeks=auto")
    return bool(sheets)


def gate_heartbeat(did: int) -> None:
    """data/raw/_heartbeat.json lists the division; report the unchanged ratio
    (the 'second consecutive daily run mostly unchanged' gate needs the cron
    AFTER first capture -- report PENDING, never fake it)."""
    hb_path = Path("data/raw/_heartbeat.json")
    if not hb_path.exists():
        emit(FAIL, "heartbeat: data/raw/_heartbeat.json missing")
        return
    hb = json.loads(hb_path.read_text(encoding="utf-8"))
    entry = hb.get("divisions", {}).get(str(did))
    if entry is None:
        active = ", ".join(sorted(hb.get("divisions", {})))
        emit(FAIL, f"heartbeat: division {did} not listed (run_date "
                   f"{hb.get('run_date')}; listed: {active or 'none'})")
        return
    cap, unch = len(entry.get("captured", [])), len(entry.get("unchanged", []))
    emit(PASS, f"heartbeat: division {did} listed (run_date {hb.get('run_date')}; "
               f"{cap} captured / {unch} unchanged)")
    if cap + unch and unch >= cap:
        emit(INFO, "heartbeat: latest run mostly 'unchanged' -- steady-state reached")
    else:
        emit(INFO, "heartbeat: latest run mostly 'captured' (first capture or active "
                   "change) -- the 'mostly unchanged' gate is PENDING the next daily "
                   "cron; re-check after it fires")


def gate_rebuild_report(did: int, do_rebuild: bool) -> None:
    """Load-report gates: CSR-disagreement warn silent league-wide; the
    division's schedule loads with 0 unresolved teams."""
    if not do_rebuild:
        emit(SKIP, "CSR-disagreement warn -- load-report-only; rerun without --no-rebuild")
        emit(SKIP, f"division {did} unresolved schedule teams -- load-report-only; "
                   "rerun without --no-rebuild")
        return
    print(f"-- rebuilding {config.DB_PATH} from the raw archive (pass-ordered: "
          "rosters -> schedules -> sheets -> profiles) --")
    report = db.rebuild(config.DB_PATH)

    conflicts = sum(rep.get("csr_conflicts", 0) for rep in report["divisions"].values())
    emit(PASS if conflicts == 0 else FAIL,
         f"CSR-disagreement warn: {conflicts} conflict(s) league-wide"
         + ("" if conflicts == 0 else " -- the warn firing means the league may "
            "compute CSR per division; the league-wide skill_snapshots schema "
            "needs a rethink (see CLAUDE.md) -- do not wave this through"))

    rep = report["divisions"].get(did)
    if rep is None:
        emit(FAIL, f"rebuild report: division {did} absent (no archive dir)")
        return
    sched = rep.get("schedule")
    if sched is None:
        emit(FAIL, f"division {did} schedule: never loaded -- no archived "
                   "schedule.html (season key can't be derived without it)")
    else:
        emit(PASS if sched["unresolved"] == 0 else FAIL,
             f"division {did} schedule: {sched['unresolved']} unresolved teams "
             f"({sched['loaded']}/{sched['fixtures']} fixtures loaded)")
    sheets = rep.get("sheets")
    if sheets:
        emit(INFO, f"division {did} sheets: {sheets['loaded']} games loaded, "
                   f"{sheets['deduped']} mirror-deduped, "
                   f"{sheets['unresolved_player_slots']} unresolved player slots, "
                   f"{sheets['ambiguous_names']} ambiguous names")
    for other, orep in report["divisions"].items():
        s = orep.get("schedule")
        if other != did and s and s["unresolved"]:
            emit(WARN, f"division {other} schedule: {s['unresolved']} unresolved "
                       "teams (pre-existing -- investigate separately, not this gate)")


def gate_db(did: int, baseline: int, max_null_rate: float, as_of: str,
            has_sheets: bool) -> None:
    conn = db.connect(config.DB_PATH)
    one = lambda sql, *a: conn.execute(sql, a).fetchone()[0]  # noqa: E731

    # Master-list completeness: every rostered player has a players row (FK)
    # and >= 1 skill_snapshot.
    rostered = one(
        """SELECT COUNT(DISTINCT tm.player_id) FROM team_members tm
           JOIN teams t ON t.team_id = tm.team_id WHERE t.division_id = ?""", did)
    missing_snap = one(
        """SELECT COUNT(*) FROM (
             SELECT DISTINCT tm.player_id FROM team_members tm
             JOIN teams t ON t.team_id = tm.team_id
             WHERE t.division_id = ?
               AND NOT EXISTS (SELECT 1 FROM skill_snapshots s
                               WHERE s.player_id = tm.player_id))""", did)
    emit(PASS if rostered and missing_snap == 0 else FAIL,
         f"master list: {rostered} rostered players in {did}; "
         f"{missing_snap} missing a skill_snapshot")

    # Division tagging: events rows carry this division_id.
    teams = one("SELECT COUNT(*) FROM teams WHERE division_id = ?", did)
    matches = one("SELECT COUNT(*) FROM matches WHERE division_id = ?", did)
    games = one("SELECT COUNT(*) FROM games WHERE division_id = ?", did)
    emit(PASS if teams and matches else FAIL,
         f"division tagging: {teams} teams / {matches} matches / {games} games "
         f"carry division_id={did}")
    if has_sheets and games == 0:
        emit(FAIL, f"division tagging: archived score sheets exist but 0 games "
                   f"loaded for {did}")

    # 13077 sub-recovery: NULL-id slots strictly BELOW the pre-expansion baseline.
    null_13077 = one(
        "SELECT COALESCE(SUM((home_player_id IS NULL)+(away_player_id IS NULL)),0) "
        "FROM games WHERE division_id = 13077")
    emit(PASS if null_13077 < baseline else FAIL,
         f"13077 sub-recovery: {null_13077} NULL-id game slots vs {baseline} "
         "baseline (gate: strictly below -- equality means the new rosters "
         "resolved no 13077 subs; investigate or get the user to accept explicitly)")

    # Per-division NULL-slot rates; hard ceiling only on the onboarding did.
    for r in conn.execute(
            """SELECT division_id, COUNT(*) AS games,
                      SUM((home_player_id IS NULL)+(away_player_id IS NULL)) AS nulls
               FROM games GROUP BY division_id ORDER BY division_id"""):
        rate = r["nulls"] / (2 * r["games"])
        line = (f"NULL-slot rate, division {r['division_id']}: "
                f"{r['nulls']}/{2 * r['games']} slots = {rate:.1%}")
        if r["division_id"] == did:
            emit(PASS if rate <= max_null_rate else FAIL,
                 line + f" (gate: <= {max_null_rate:.0%}; the real test is "
                 "'plausible sub rate' -- eyeball it; 13077's is ~7.5%)")
        else:
            emit(INFO, line)

    # Multi-division enumeration refresh (player_divisions is profile-sourced).
    multi = one("SELECT COUNT(*) FROM (SELECT player_id FROM player_divisions "
                "GROUP BY player_id HAVING COUNT(*) > 1)")
    multi_did = one(
        """SELECT COUNT(*) FROM player_divisions pd WHERE pd.division_id = ?
           AND EXISTS (SELECT 1 FROM player_divisions x
                       WHERE x.player_id = pd.player_id
                         AND x.division_id != pd.division_id)""", did)
    emit(INFO, f"multi-division players (profile-sourced): {multi} league-wide, "
               f"{multi_did} of them in division {did} (foundation baseline: 35)")

    # Pending makeups -- division-scoped; non-13077 season key is the R1 date
    # stored in divisions.season at schedule load.
    row = conn.execute("SELECT season FROM divisions WHERE division_id = ?",
                       (did,)).fetchone()
    season = row["season"] if row else None
    if not season or season == "unknown":
        emit(FAIL, f"pending makeups: divisions.season for {did} is {season!r} -- "
                   "schedule never loaded, so the season key (R1 date) is missing")
    else:
        pend = db.pending_matches(conn, as_of, season=season, division_id=did)
        emit(PASS, f"pending makeups for {did} (season {season!r}, as of {as_of}): "
                   f"{len(pend)} pending -- never finalize this division's standings "
                   "while these are open")
        for m in pend:
            emit(INFO, f"  pending R{m['round']} {m['date']}: "
                       f"{m['home_team']} vs {m['away_team']}")
    conn.close()


def main() -> None:
    ap = argparse.ArgumentParser(
        description="Run the per-division onboarding STOP gates (one division).")
    ap.add_argument("--did", type=int, required=True,
                    help="division id being onboarded (must be in config.DIVISIONS)")
    ap.add_argument("--no-rebuild", action="store_true",
                    help="gate the existing data/napa.db; SKIPs the two "
                         "load-report-only gates (CSR warn, unresolved teams)")
    ap.add_argument("--baseline-null-slots", type=int, default=99,
                    help="13077 pre-expansion NULL-id slot baseline (default 99, "
                         "the 2026-06-10 foundation measurement)")
    ap.add_argument("--max-null-rate", type=float, default=0.20,
                    help="hard ceiling for the division's NULL-slot rate (default 0.20)")
    ap.add_argument("--as-of", default=dt.date.today().isoformat(),
                    help="pending-makeup cutoff date (default today)")
    args = ap.parse_args()

    if args.did not in config.DIVISIONS:
        sys.exit(f"did {args.did} is not in config.DIVISIONS -- the registry is the "
                 "gate (13337 is deliberately unregistered; ask the user).")
    d = config.DIVISIONS[args.did]
    print(f"== onboarding gates: division {args.did} ({d.name}; {d.weekday}; "
          f"fmt {d.fmt!r} is DISPLAY-ONLY -- the grid header is authoritative) ==")
    if not d.scrape:
        emit(FAIL, f"registry: scrape flag for {args.did} is False in src/config.py "
                   "-- flip it (playbook step 1) before gating")

    has_sheets = gate_archive(args.did)
    gate_heartbeat(args.did)
    gate_rebuild_report(args.did, do_rebuild=not args.no_rebuild)
    if not Path(config.DB_PATH).exists():
        emit(FAIL, f"{config.DB_PATH} missing -- run: python -m src.db --rebuild")
    else:
        gate_db(args.did, args.baseline_null_slots, args.max_null_rate,
                args.as_of, has_sheets)

    counts = {s: sum(1 for st, _ in RESULTS if st == s)
              for s in (PASS, FAIL, WARN, INFO, SKIP)}
    print(f"\n== gate summary: {counts[PASS]} PASS / {counts[FAIL]} FAIL / "
          f"{counts[WARN]} WARN / {counts[SKIP]} SKIP ==")
    if counts[FAIL]:
        print("FAILED gates:")
        for st, msg in RESULTS:
            if st == FAIL:
                print(f"  - {msg}")
    sys.exit(1 if counts[FAIL] else 0)


if __name__ == "__main__":
    main()
