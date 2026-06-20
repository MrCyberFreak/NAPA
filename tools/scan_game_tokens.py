"""One-off: enumerate every CSR game token + header shape across all archived
roster grids, so the parser's known-game set can be extended in one pass rather
than discovered one rebuild-crash at a time."""
import glob
from collections import defaultdict
from pathlib import Path

from bs4 import BeautifulSoup

from src.parse.roster import _logical_rows, _TEAM_HEADER_RE, _GAME_TOKEN_RE, read_source

tok_dids = defaultdict(set)        # token -> {dids}
header_shapes = defaultdict(set)   # games-tuple -> {dids}

for path in glob.glob("data/raw/*/*/roster_grid.html"):
    did = Path(path).parts[2]
    try:
        soup = BeautifulSoup(read_source(path), "lxml")
    except Exception as e:
        print("READ-ERR", path, e)
        continue
    for cells in _logical_rows(soup):
        text = " ".join(cells).strip()
        m = _TEAM_HEADER_RE.match(text)
        if not m:
            continue
        raw = m.group("games")
        toks = tuple(t.upper() for t in _GAME_TOKEN_RE.findall(raw)) if raw else ("8",)
        header_shapes[toks].add(did)
        for t in toks:
            tok_dids[t].add(did)
        break  # first header per file is enough to know the shape

print("=== distinct game tokens across ALL roster grids ===")
for t in sorted(tok_dids, key=lambda x: (len(x), x)):
    print(f"  {t:6} -> {len(tok_dids[t]):3} dids: {sorted(tok_dids[t])[:14]}")
print()
print("=== distinct header SHAPES ===")
for shape, dids in sorted(header_shapes.items(), key=lambda kv: -len(kv[1])):
    print(f"  {shape} -> {len(dids)} dids: {sorted(dids)}")
