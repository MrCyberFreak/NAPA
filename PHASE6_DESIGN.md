# PHASE6_DESIGN.md — forecasting & scouting design (design only, no code)

**Status:** design decisions, locked against the empirical groundwork in
`PHASE6_READINESS.md`. Nothing here is implemented yet. This document is the
specification the Phase 6 build will follow; it does **not** fit, train, or ship
a model.

**What the readiness analysis established (the inputs to these decisions):**
- 8-ball data is rich; **9- and 10-ball are sparse** — 76% of players have < 30
  racks in 9-ball, 59% in 10-ball (readiness §1).
- CSR difference is a strong, monotonic, broadly-available predictor of the
  per-rack win-rate (readiness §2–3).
- The per-rack skill curve **does not differ provably by game type** on this
  season's data — the 8/9/10 slopes are statistically indistinguishable and the
  9-ball "flatter curve" hypothesis is **not** supported yet (readiness §3a).
- `games` is single-meeting (median 1 pairing), so no empirical H2H; pool through
  latent skill (readiness §4).
- The handicap balances typical mismatches but **under-compensates at large CSR
  gaps** — that residual is the scouting edge (readiness §3, §5).

---

## 0. Scope selection — division → team (the entry point)

The app is **division-agnostic**. Nothing is hard-coded to 13077. The first
interaction is a **division selector**; the user then picks a **team within that
division** (the team they play on, or any team they want to analyse), and *every*
screen after that — the §1 skill estimates, §3 matchup grid, §4 Lagger's-Choice
optimizer, §5 schedule expansion — is scoped to that (division, team) selection.

- **Testing vs rollout.** Development is exercised against **13077 only** (the
  division with the richest, fully-validated data), but the shipped build must
  let a user pick **any** active division and get the same analysis. 13077 is the
  test fixture, not a hard dependency.
- **Already supported by the data layer — this is a UI/entry-point change, not a
  re-architecture.** The `players` table is league-wide and `divisions`/`teams`
  are routing (CLAUDE.md); events are division-scoped; and `src/app.py --scout`
  already accepts `--division N` (currently defaulting to 13077). The selector
  replaces that hard-coded default with an explicit, user-driven choice.
- **What scopes vs what stays league-wide.** The selected division governs the
  **fixtures, opponents, teams, and standings** shown — all read from that
  division's `matches`/`teams`/`games` in `data/napa.db`. But **skill/CSR
  estimates remain league-wide**: a player carries one per-game skill profile
  (`skill_snapshots` are PK `player_id+captured_date`, merged across divisions),
  so a player is equally strong wherever they appear. The division/team choice is
  a lens over who-plays-whom, not over how good a player is.

---

## 1. Skill representation

Each player has, **per game type (8 / 9 / 10 separately)**:

```
estimate(player, game) = base(player, game)  +  adj(player, game)
```

- **`base` — the prior.** The official NAPA CSR for that game type (from the
  roster-grid snapshot, `skill_snapshots`). It is the trusted starting point and
  the thing every data-driven adjustment is measured *against*.
- **`adj` — the data-driven adjustment.** A deviation learned from this league's
  rack results, **shrunk toward zero when the rack data is thin.** The adjustment
  is trusted in proportion to the number of races/racks the player has in that
  game type:
  - rich data (e.g. a regular's 8-ball) → `adj` can move meaningfully off zero;
  - thin data (e.g. 6 games of 9-ball) → `adj` is pulled hard back to ~0, so the
    estimate falls back to the NAPA CSR prior.

**Rationale.** With 76% of players under 30 racks in 9-ball (readiness §1), a raw
per-player empirical rating is noise for most of the field. Shrinkage toward the
CSR prior is mandatory, and the shrinkage strength must be **per game type**
because a player can be data-rich in 8-ball and data-poor in 9-ball at the same
time. The base/adjustment split makes that fallback explicit and inspectable.

> Estimation mechanism (regularized partial pooling vs. an explicit
> shrinkage/credibility weight) is an implementation choice for the build; the
> *contract* fixed here is base + shrink-to-prior adjustment, per game type, with
> trust scaling in games played. No estimator is selected or fit in this doc.

---

## 2. Display requirement (FIRM) — never a bare number

Every skill estimate shown anywhere in the app **must display all three pieces**:

1. the official **NAPA CSR** (the prior / base),
2. the **data-driven adjustment**, annotated with the **games-count** backing it,
3. the **resulting estimate**.

Example renderings:

```
8-ball:  CSR 78  ·  adj +6 (51 games)   →  84      ← well-supported nudge
9-ball:  CSR 52  ·  adj  0 (only 6 games) →  52      ← thin data, falls back to CSR
10-ball: CSR 44  ·  adj −3 (22 games)   →  41
```

A bare `84` is never acceptable: the user must always see that it is CSR 78 plus
a +6 adjustment earned over 51 games — versus a number that is really just the
CSR because the data was too thin to move it. This is the guardrail that keeps a
sparse-data artifact from masquerading as a confident rating.

---

## 3. Matchup outputs — per pairing, per game

For every player-vs-player pairing, and for **each game type**, the app surfaces:

| Output | Source |
|---|---|
| **NAPA race** (e.g. 7–4) | the `races.js` formula already in `src/race.py` (static lookup) |
| **Handicap-expected win prob** | what the race length implies — **~50/50 by design** |
| **Data-predicted win prob** | from the per-game skill→prob curve (§"Per-game curves") applied to the two players' §1 estimates |
| **Edge** | `edge = data-predicted − handicap-expected`, **shown explicitly** |

The **edge is the scouting signal.** Readiness §3 showed the race matrix
under-compensates at large CSR gaps (the stronger player still won ~73% of
matches at 46+ CSR difference), so a positive edge flags pairings where the
handicap leaves value on the table for the stronger side (and a negative edge
flags where it over-compensates in the underdog's favour). The edge is reported
as a first-class number, not buried — it is the reason the tool exists.

---

## 4. Lag / game-choice toggle (Lagger's Choice)

For a selected **A-vs-B** pairing:

- Assume **A wins the lag** (Lagger's Choice → A picks the game). Show **which
  game type (8/9/10) maximises A's win probability**, with that win prob and the
  edge, and the runner-up games ranked beneath.
- Provide a **toggle to flip to B's best choice** (the symmetric view: if B had
  the lag, which game maximises B's win prob).

**Why this matters:** the best game **differs by opponent** — that is the core
Lagger's-Choice insight. Player A's strongest game in the abstract is not
necessarily A's best *pick against this particular B*, because it depends on the
gap between their per-game estimates and the per-game curves. The toggle makes the
choice opponent-specific and explicit for both sides.

---

## 5. Auto-populated from the schedule (no manual entry, ever)

Matchup views **pre-load from the loaded schedule** (`matches` / `teams`): who
plays whom, on which date, for the selected round. The user never types in a
fixture or a pairing by hand. The scout/matchup screen takes a round (or "this
week") and expands the scheduled team matchups into the per-player, per-game
pairing grid automatically. This keeps the app reading **only** from `data/napa.db`
(the hard rule) and means the weekly scrape that refreshes the schedule also
refreshes the matchup views with zero manual steps.

---

## 6. Per-game curves

The skill→probability curve (mapping a pair of §1 estimates, or their difference,
to a per-rack/per-match win probability) is **fit per game type** (one curve each
for 8 / 9 / 10).

Per readiness §3a, the three per-type slopes are **statistically
indistinguishable on this season's data** and the 9-ball "flatter curve"
hypothesis is **not** confirmed. Therefore:

- Fit the three curves **partially pooled toward a shared slope**, so the thin
  9/10-ball curves borrow strength from 8-ball instead of chasing noise.
- **Do not hard-code** a flatter 9-ball curve. Leave each game's curve free to
  diverge as more data accrues.
- **Re-run the readiness §3a flatness test each season**; promote a genuinely
  distinct 9-ball curve only when the data supports it (the current 9-ball CI is
  [3.17, 7.32] pp/+10 CSR — far too wide to act on).

---

## 7. Called-9 rule note (why 9-ball is its own animal)

**Rule, documented for the model's sake:** this division (13077) requires the
**9 to be called** to win the rack, but **slop continues play** — a slopped ball
that isn't the called game-winner does not end the rack; the table keeps going.
This is *unlike* standard / APA-style 9-ball, where a slopped/wild 9 can win.

**Implication for the model:**
- 9-ball in this league is mechanically a different game from "9-ball" elsewhere.
  Its scoring dynamics (weaker players staying alive on slop) plausibly compress
  the skill→win-rate relationship, even though the current sample can't yet prove
  it (§6, readiness §3a).
- **Do not pool this league's 9-ball with any outside 9-ball data** (APA,
  FargoRate, other leagues) — they are not the same game. This is a hard
  boundary, and it directly governs the Phase 8 corroboration design below.

---

## Future — Phase 8 cross-league corroboration (idea capture, deferred)

**Not for now. Explicitly deferred until the base app (Phases 6–7) is built and
working.** Captured here so the design isn't lost.

**Idea:** use external rating systems as an independent **second opinion on the
per-game adjustments** from §1 — a corroboration / sanity layer, never a
replacement for this league's own rack data.

- **Match per (player × game), never collapse into one rating.** APA carries
  **separate 8-ball and 9-ball scales**; FargoRate is its own scale. Each external
  signal is matched to the specific (player, game-type) adjustment it can speak
  to — there is no single blended "true skill" number.
- **Weight 8-ball corroboration highest.** 8-ball is the richest, most
  comparable game across systems, so external 8-ball is the most trustworthy
  cross-check on a player's 8-ball adjustment.
- **Distrust cross-league 9-ball.** APA 9-ball uses slop / wild-9; this league
  **calls the 9** (§7). They are different games, so APA 9-ball must **not** be
  used to corroborate this league's 9-ball adjustment.
- **Use FargoRate for 10-ball.** FargoRate is the better external reference for
  10-ball corroboration.
- **Role is corroboration only:** external systems adjust confidence in / flag
  outliers among the data-driven adjustments; they never overwrite the NAPA CSR
  prior or this league's rack-derived `adj`.

**Status:** deferred. Revisit after the base scouting app is delivering the §3–§5
outputs on this league's own data.
