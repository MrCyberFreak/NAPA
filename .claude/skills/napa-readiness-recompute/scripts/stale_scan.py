#!/usr/bin/env python3
"""Flag stale figures in PHASE6_READINESS.md vs the current data/napa.db.

Runs `python tools/phase6_readiness.py` (the deterministic compute), extracts the
high-value scalars that the doc cites in prose, formats each the way the doc
writes it (thousands commas), and checks whether that exact string is present in
PHASE6_READINESS.md. Reports a per-metric OK / STALE table.

This is a FLAGGING AID, not an authority: a STALE row means "the current value is
not found verbatim in the doc -> look here". A rare false OK is possible if a
number coincides elsewhere; a false STALE if the doc phrases a number differently
(e.g. spelled-out "seven"). Always eyeball the doc around each STALE metric.

Read-only. Does NOT rebuild, edit, or fetch. Run from the repo root:
    python .claude/skills/napa-readiness-recompute/scripts/stale_scan.py
Exit code 0 = every tracked metric present; 1 = at least one STALE; 2 = error.
"""
from __future__ import annotations

import re
import subprocess
import sys
from pathlib import Path

DOC = Path("PHASE6_READINESS.md")
TOOL = ["python", "tools/phase6_readiness.py"]


def commafy(n: str) -> str:
    return f"{int(n):,}"


def run_tool() -> str:
    r = subprocess.run(TOOL, capture_output=True, text=True)
    if r.returncode != 0:
        sys.stderr.write(r.stdout + r.stderr)
        raise SystemExit(2)
    return r.stdout


def grab(out: str, pattern: str) -> str | None:
    m = re.search(pattern, out)
    return m.group(1) if m else None


def collect(out: str) -> list[tuple[str, str, str]]:
    """-> list of (section, metric, doc_style_value)."""
    metrics: list[tuple[str, str, str]] = []

    def add(section, metric, raw, comma=True):
        if raw is None:
            return
        metrics.append((section, metric, commafy(raw) if comma else raw))

    # --- HEADER TOTALS: {'players': 709, 'skill_snapshots': 1693, ...} ---
    for key in ("players", "skill_snapshots", "teams", "matches", "games"):
        add("header", key, grab(out, rf"'{key}': (\d+)"))

    # --- §2 CSR coverage ALL line ---
    add("§2", "CSR coverage % (ALL)", grab(out, r"ALL\s+:\s+\d+/\d+\s+([\d.]+%)"), comma=False)

    # --- §3a slopes: "  8-ball : +5.10  CI[...]" ---
    for g in ("8-ball", "9-ball", "10-ball", "10BP"):
        add("§3a", f"slope {g}", grab(out, rf"{re.escape(g)}\s*:\s*([+\-][\d.]+)\s+CI"), comma=False)

    # --- §5 pairing_history ---
    add("§5", "directed edges", grab(out, r"directed edges:\s+(\d+)"))
    add("§5", "subjects", grab(out, r"subjects \(distinct player_id\):\s+(\d+)"))
    add("§5", "distinct pairings", grab(out, r"distinct unordered pairings:\s+(\d+)"))
    add("§5", "reciprocal %", grab(out, r"reciprocal:\s+\d+,\s+(\d+%)"), comma=False)
    add("§5", "edges with W-L (count)", grab(out, r"edges with W-L totals:\s+(\d+)"))
    add("§5", "edges with W-L (%)", grab(out, r"edges with W-L totals:\s+\d+\s+\((\d+%)\)"), comma=False)
    add("§5", "game pairs with record (count)", grab(out, r"with lifetime record:\s+(\d+)"))
    add("§5", "game pairs with record (%)", grab(out, r"with lifetime record:\s+\d+\s+\((\d+%) of game pairs\)"), comma=False)
    add("§5", "historical-only pairings", grab(out, r"lifetime pairs not in this season's games:\s+(\d+)"))
    add("§5", "pending total", grab(out, r"TOTAL pending:\s+(\d+)"), comma=False)

    # --- §5 caveats: CSR scale n= per type ---
    for g in ("8-ball", "9-ball", "10-ball", "10BP"):
        add("§5", f"CSR n {g}", grab(out, rf"{re.escape(g)}\s*:\s*[\d.]+\.\.[\d.]+\s+\(n=(\d+)\)"))

    # --- §5 caveats: latest snapshot date (span end) ---
    dates = re.search(r"snapshot dates:\s*\[([^\]]+)\]", out)
    if dates:
        last = re.findall(r"'([\d-]+)'", dates.group(1))
        if last:
            metrics.append(("§5", "latest snapshot date", last[-1]))

    return metrics


def main() -> int:
    if not DOC.exists():
        sys.stderr.write(f"{DOC} not found (run from repo root)\n")
        return 2
    out = run_tool()
    doc = DOC.read_text(encoding="utf-8", errors="replace")
    metrics = collect(out)

    stale = 0
    print(f"{'STATUS':7} {'SECTION':7} {'METRIC':28} CURRENT")
    print("-" * 62)
    for section, metric, val in metrics:
        present = val in doc
        if not present:
            stale += 1
        print(f"{'OK' if present else 'STALE':7} {section:7} {metric:28} {val}")
    print("-" * 62)
    print(f"{len(metrics)} metrics tracked, {stale} STALE "
          f"({'doc current' if stale == 0 else 'doc needs update — see STALE rows'})")
    return 1 if stale else 0


if __name__ == "__main__":
    raise SystemExit(main())
