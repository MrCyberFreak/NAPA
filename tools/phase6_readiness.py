"""Recompute the empirical numbers in PHASE6_READINESS.md from data/napa.db.

The original readiness figures were 13077-only and computed ad-hoc. This script
reproduces every section against the current (multi-division) DB so the doc can
be regenerated deterministically each time data lands. Pure-stdlib (no numpy) so
it runs anywhere the repo runs; the §3a bootstrap is seeded for reproducibility.

Game types are 8 / 9 / 10 (ints) plus '10BP' (text) — the 4-game divisions
(13986, 14022) add the BP variant, keyed to skill_snapshots.csr_10bp.

Run:  python -m tools.phase6_readiness   (or: python tools/phase6_readiness.py)
"""

from __future__ import annotations

import math
import random
import sqlite3
import statistics
from collections import Counter, defaultdict

DB = "data/napa.db"
AS_OF = "2026-06-12"
BOOT_REPS = 3000
SEED = 20260612

TYPES = [8, 9, 10, "10BP"]
CSR_COL = {8: "csr_8", 9: "csr_9", 10: "csr_10", "10BP": "csr_10bp"}
LABEL = {8: "8-ball", 9: "9-ball", 10: "10-ball", "10BP": "10BP"}


def pctile(sorted_vals, p):
    if not sorted_vals:
        return None
    k = (len(sorted_vals) - 1) * p / 100.0
    f, ce = math.floor(k), math.ceil(k)
    if f == ce:
        return sorted_vals[int(k)]
    return sorted_vals[f] * (ce - k) + sorted_vals[ce] * (k - f)


def wls_slope(data):
    """Rack-weighted OLS slope of y on x; data = [(x, y, w), ...].
    CSR diff is constant within a game, so weighting game-level fractions by
    racks is identical to OLS on individual 0/1 rack outcomes."""
    sw = sum(w for _, _, w in data)
    if sw == 0:
        return None
    xb = sum(w * x for x, _, w in data) / sw
    yb = sum(w * y for _, y, w in data) / sw
    num = sum(w * (x - xb) * (y - yb) for x, y, w in data)
    den = sum(w * (x - xb) ** 2 for x, _, w in data)
    return None if den == 0 else num / den


def bootstrap_slopes(data, reps=BOOT_REPS):
    """Game-clustered bootstrap: resample whole games (races) with replacement.
    Returns slopes in pp of rack-WR per +10 CSR points."""
    n = len(data)
    out = []
    for _ in range(reps):
        sample = [data[random.randrange(n)] for _ in range(n)]
        s = wls_slope(sample)
        if s is not None:
            out.append(s * 1000.0)  # per-CSR prob -> *10 (per +10) *100 (pp)
    return out


def main():
    random.seed(SEED)
    c = sqlite3.connect(DB)
    c.row_factory = sqlite3.Row

    # ---- as-of CSR: most recent NON-NULL per game type, per player ---------
    asof = defaultdict(dict)
    for r in c.execute(
        "SELECT player_id, captured_date, csr_8, csr_9, csr_10, csr_10bp "
        "FROM skill_snapshots ORDER BY captured_date"
    ):
        for t in TYPES:
            v = r[CSR_COL[t]]
            if v is not None:
                asof[r["player_id"]][t] = v  # ascending => ends most-recent non-null

    games = c.execute(
        "SELECT division_id, game_type, home_player_id, away_player_id, "
        "home_player_name, away_player_name, home_score, away_score, home_won "
        "FROM games"
    ).fetchall()

    # ---- header totals -----------------------------------------------------
    counts = {t: c.execute(f"SELECT COUNT(*) FROM {t}").fetchone()[0]
              for t in ("players", "skill_snapshots", "teams", "matches", "games")}
    n_div_games = len({g["division_id"] for g in games})
    print("=== HEADER TOTALS ===")
    print(counts, f"| divisions with games: {n_div_games}")

    # ---- §1 racks per player by game type ----------------------------------
    per = {t: defaultdict(int) for t in TYPES}
    total_racks = {t: 0 for t in TYPES}
    sub_racks = {t: 0 for t in TYPES}
    sub_games = {t: 0 for t in TYPES}
    games_per_player = {t: defaultdict(int) for t in TYPES}
    type_game_count = Counter()
    for g in games:
        t = g["game_type"]
        type_game_count[t] += 1
        racks = (g["home_score"] or 0) + (g["away_score"] or 0)
        total_racks[t] += racks
        has_sub = False
        for pid in (g["home_player_id"], g["away_player_id"]):
            if pid is not None:
                per[t][pid] += racks
                games_per_player[t][pid] += 1
            else:
                has_sub = True
        if has_sub:
            sub_games[t] += 1
            sub_racks[t] += racks

    print("\n=== §1 RACKS/PLAYER BY GAME TYPE ===")
    print("game | players | min | median | mean | p90 | max | <20 | <30")
    for t in TYPES:
        v = sorted(per[t].values())
        if not v:
            print(f"{LABEL[t]}: (no games)")
            continue
        print(f"{LABEL[t]:7s}| {len(v):3d} | {min(v):3d} | {statistics.median(v):6.0f} "
              f"| {statistics.mean(v):4.1f} | {pctile(v,90):4.0f} | {max(v):3d} "
              f"| {sum(1 for x in v if x<20):3d} ({100*sum(1 for x in v if x<20)/len(v):.0f}%) "
              f"| {sum(1 for x in v if x<30):3d} ({100*sum(1 for x in v if x<30)/len(v):.0f}%)")
    print("total racks (per game, each rack once):", total_racks,
          "sum =", sum(total_racks.values()))
    print("sub games / sub racks per type:", dict(sub_games), dict(sub_racks))

    pooled = defaultdict(int)
    pooled_games = defaultdict(int)
    for t in TYPES:
        for pid, r in per[t].items():
            pooled[pid] += r
        for pid, n in games_per_player[t].items():
            pooled_games[pid] += n
    pv = sorted(pooled.values())
    print(f"POOLED: players {len(pv)} | min {min(pv)} | median {statistics.median(pv):.0f} "
          f"| mean {statistics.mean(pv):.1f} | p90 {pctile(pv,90):.0f} | max {max(pv)} "
          f"| <20 {sum(1 for x in pv if x<20)} | <30 {sum(1 for x in pv if x<30)}")
    gpp = sorted(pooled_games.values())
    print(f"races/player (pooled): median {statistics.median(gpp):.0f}")
    for t in TYPES:
        gv = sorted(games_per_player[t].values())
        if gv:
            print(f"  races/player {LABEL[t]}: median {statistics.median(gv):.0f}")

    # ---- §2 CSR-at-match coverage ------------------------------------------
    print("\n=== §2 CSR-AT-MATCH COVERAGE ===")
    cov_tot = cov_ok = 0
    for t in TYPES:
        tot = ok = 0
        for g in games:
            if g["game_type"] != t:
                continue
            tot += 1
            hid, aid = g["home_player_id"], g["away_player_id"]
            if hid and aid and asof.get(hid, {}).get(t) is not None \
               and asof.get(aid, {}).get(t) is not None:
                ok += 1
        cov_tot += tot
        cov_ok += ok
        if tot:
            print(f"{LABEL[t]:7s}: {ok:4d}/{tot:4d}  {100*ok/tot:.1f}%")
    print(f"ALL    : {cov_ok}/{cov_tot}  {100*cov_ok/cov_tot:.1f}%  "
          f"(uncovered {cov_tot-cov_ok} = {100*(cov_tot-cov_ok)/cov_tot:.1f}%)")

    # ---- build covered-game records for §3 / §3a ---------------------------
    def covered_records(types):
        recs = []
        for g in games:
            t = g["game_type"]
            if t not in types:
                continue
            hid, aid = g["home_player_id"], g["away_player_id"]
            if not (hid and aid):
                continue
            hc = asof.get(hid, {}).get(t)
            ac = asof.get(aid, {}).get(t)
            if hc is None or ac is None:
                continue
            racks = (g["home_score"] or 0) + (g["away_score"] or 0)
            if racks == 0:
                continue
            diff = abs(hc - ac)
            home_strong = hc >= ac
            st_racks = (g["home_score"] if home_strong else g["away_score"]) or 0
            hw = g["home_won"]
            st_won = None if hw is None else (bool(hw) if home_strong else not bool(hw))
            recs.append((diff, racks, st_racks, st_won))
        return recs

    def bin_table(recs, edges):
        # edges: list of (lo, hi) inclusive; hi None = open
        print(f"{'bin':>8} | {'games':>5} | {'racks':>5} | {'rackWR':>6} | {'matchWR':>7}")
        for lo, hi in edges:
            sel = [r for r in recs if r[0] >= lo and (hi is None or r[0] <= hi)]
            if not sel:
                continue
            gms = len(sel)
            racks = sum(r[1] for r in sel)
            st = sum(r[2] for r in sel)
            mw = [r[3] for r in sel if r[3] is not None]
            label = f"{lo}-{hi}" if hi is not None else f"{lo}+"
            print(f"{label:>8} | {gms:5d} | {racks:5d} | {100*st/racks:5.1f}% "
                  f"| {100*sum(mw)/len(mw):6.1f}%")

    print("\n=== §3 POOLED (all game types) ===")
    pooled_recs = covered_records(set(TYPES))
    bin_table(pooled_recs, [(0,2),(3,5),(6,10),(11,15),(16,20),(21,30),(31,45),(46,None)])

    for t in TYPES:
        recs = covered_records({t})
        if not recs:
            continue
        print(f"\n--- §3 {LABEL[t]} ---")
        bin_table(recs, [(0,2),(3,5),(6,10),(11,18),(19,30),(31,None)])

    # ---- §3a flatness ------------------------------------------------------
    print("\n=== §3a FLATNESS ===")
    print("(a) rise small(<=10) -> large(>=20) pooled rack-WR:")
    boots = {}
    for t in TYPES:
        recs = covered_records({t})
        if not recs:
            continue
        small = [r for r in recs if r[0] <= 10]
        large = [r for r in recs if r[0] >= 20]
        sm = sum(r[2] for r in small) / sum(r[1] for r in small)
        lg = sum(r[2] for r in large) / sum(r[1] for r in large)
        print(f"  {LABEL[t]:7s}: {100*sm:.1f}% ({sum(r[1] for r in small)}) -> "
              f"{100*lg:.1f}% ({sum(r[1] for r in large)})  rise +{100*(lg-sm):.1f} pp")

    print("(b) rack-weighted slope (pp rack-WR / +10 CSR) + game-clustered 95% CI:")
    for t in TYPES:
        recs = covered_records({t})
        if not recs:
            continue
        data = [(r[0], r[2] / r[1], r[1]) for r in recs]  # (diff, frac, racks)
        slope = wls_slope(data) * 1000.0
        bs = bootstrap_slopes(data)          # KEEP generation order (independent draws)
        boots[t] = bs
        ci = sorted(bs)
        lo, hi = pctile(ci, 2.5), pctile(ci, 97.5)
        n_races = len(data)
        n_racks = sum(r[1] for r in recs)
        print(f"  {LABEL[t]:7s}: {slope:+.2f}  CI[{lo:.2f}, {hi:.2f}]  "
              f"races {n_races}  racks {n_racks}")

    # Independent-bootstrap comparison: each type's draws are generated from
    # independent resampling, so compare them element-wise in GENERATION order
    # (NOT sorted — comparing order statistics of overlapping distributions
    # spuriously saturates to 0/1).
    print("pairwise P(slope_a > slope_b) [independent bootstrap]:")
    keys = [t for t in TYPES if t in boots]
    for i, a in enumerate(keys):
        for b in keys[i+1:]:
            n = min(len(boots[a]), len(boots[b]))
            p = sum(boots[a][k] > boots[b][k] for k in range(n)) / n
            print(f"  P({LABEL[a]} > {LABEL[b]}) = {p:.2f}")

    # ---- §4 pairing depth (from games) -------------------------------------
    print("\n=== §4 PAIRING DEPTH (games) ===")
    by_name = Counter()
    by_id = Counter()
    for g in games:
        nh, na = g["home_player_name"], g["away_player_name"]
        if nh and na:
            by_name[frozenset((nh, na))] += 1
        ih, ia = g["home_player_id"], g["away_player_id"]
        if ih and ia:
            by_id[frozenset((ih, ia))] += 1
    dist = Counter(by_name.values())
    tot_pairs = len(by_name)
    print(f"distinct pairings (by name): {tot_pairs}  "
          f"median {statistics.median(sorted(by_name.values())):.0f}  "
          f"mean {statistics.mean(by_name.values()):.2f}  max {max(by_name.values())}")
    for k in sorted(dist):
        print(f"   {k} meeting(s): {dist[k]} pairs  ({100*dist[k]/tot_pairs:.0f}%)")
    print(f"id-resolved pairs (both rostered): {len(by_id)}  "
          f"median {statistics.median(sorted(by_id.values())):.0f}")

    # ---- §5 caveats --------------------------------------------------------
    print("\n=== §5 CAVEATS ===")
    print("snapshot dates:",
          [r[0] for r in c.execute(
              "SELECT DISTINCT captured_date FROM skill_snapshots ORDER BY captured_date")])
    print("CSR scale (as-of, per type) min..max:")
    for t in TYPES:
        vals = [d[t] for d in asof.values() if t in d]
        if vals:
            print(f"  {LABEL[t]:7s}: {min(vals)}..{max(vals)}  (n={len(vals)})")

    # pending makeups per division (db.pending_matches logic, bye-filtered)
    print("pending makeups (date<=as_of, no games, byes excluded):")
    import sys
    sys.path.insert(0, ".")
    from src import db, config  # noqa: E402
    total_pending = 0
    for did in config.DIVISIONS:
        row = c.execute("SELECT season FROM divisions WHERE division_id=?", (did,)).fetchone()
        if not row or not row["season"]:
            continue
        pend = db.pending_matches(c, AS_OF, season=row["season"], division_id=did)
        if pend:
            total_pending += len(pend)
            print(f"  {did}: {len(pend)} -> " +
                  "; ".join(f"R{p['round']} {p['home_team']} vs {p['away_team']}" for p in pend))
    print(f"  TOTAL pending: {total_pending}")
    # ---- §5 pairing_history (lifetime H2H layer) ---------------------------
    # Profile RIVALS-sourced and DISTINCT from `games`: aggregate lifetime W-L,
    # no rack detail, no opponent-skill-at-time. Tabs-only harvests record only
    # existence rows (player_id, rival_id, rival_name); per-game W-L splits are
    # filled later by rival drill-downs (xTab=5&rival=). Report depth, split
    # availability, and overlap with this season's game pairs (§4 by_id).
    ph = c.execute(
        "SELECT player_id, rival_id, total_matches, "
        "g8_w, g8_l, g9_w, g9_l, g10_w, g10_l FROM pairing_history"
    ).fetchall()
    print("\n--- §5 pairing_history (lifetime H2H) ---")
    print(f"directed edges: {len(ph)}")
    if ph:
        subjects = {r["player_id"] for r in ph}
        undirected = defaultdict(int)          # frozenset{a,b} -> #directed rows
        for r in ph:
            undirected[frozenset((r["player_id"], r["rival_id"]))] += 1
        recip = sum(1 for v in undirected.values() if v >= 2)
        print(f"subjects (distinct player_id): {len(subjects)}")
        print(f"distinct unordered pairings: {len(undirected)}  "
              f"(both-sided/reciprocal: {recip}, {100*recip/len(undirected):.0f}%)")

        # per-game-split availability (NULL until a rival drill-down runs)
        split_cols = ("g8_w", "g8_l", "g9_w", "g9_l", "g10_w", "g10_l")
        with_wl = sum(1 for r in ph if r["total_matches"] is not None)
        with_split = sum(1 for r in ph
                         if any(r[k] is not None for k in split_cols))
        print(f"edges with W-L totals: {with_wl} ({100*with_wl/len(ph):.0f}%)  "
              f"with per-game splits: {with_split} ({100*with_split/len(ph):.0f}%)")
        if with_wl == 0:
            print("  -> all tabs-only (existence only); drill-downs "
                  "(stats.php xTab=5&rival=<id>) needed for W-L depth")

        # overlap with this season's game pairs (§4 by_id) — densification value
        ph_pairs = {frozenset((str(r["player_id"]), str(r["rival_id"]))) for r in ph}
        game_pairs = {frozenset(str(x) for x in p) for p in by_id}
        both = ph_pairs & game_pairs
        print(f"distinct lifetime pairs: {len(ph_pairs)}")
        if game_pairs:
            print(f"this-season game pairs (§4 by_id): {len(game_pairs)}  "
                  f"with lifetime H2H: {len(both)} "
                  f"({100*len(both)/len(game_pairs):.0f}% of game pairs)")
        print(f"lifetime pairs not in this season's games: "
              f"{len(ph_pairs - game_pairs)}")
    else:
        print("(0 rows => profiles pass deferred / no RIVALS harvested)")


if __name__ == "__main__":
    main()
