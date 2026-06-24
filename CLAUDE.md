# NAPA of Northern Colorado Data System
Personal pipeline: scrape NoCo divisions -> archive raw HTML -> parse -> SQLite -> views.
**We track PLAYERS.** The master list is the league-wide `players` table (8-digit
playerID); divisions and teams are routing â€” everything known about a player
(skill drift, form, pairings, per-rack results) accrues to one player row.

## Status (as of 2026-06-12)
- Phases 0â€“5 DONE for division 13077 (full 2025-26 season: 27 weeks of score
  sheets, snapshots, pairing graph, form layers).
- Multi-division FOUNDATION DONE (MULTIDIVISION_PLAN.md): registry of all 14
  NoCo divisions, per-division archive layout, division-scoped events schema,
  header-driven roster parsing, multi-division fetch loop, --rebuild.
- Division rollout COMPLETE â€” all 14 NoCo divisions active (scrape=True), each
  onboarded one at a time (flag -> scrape -> backfill auto -> rebuild -> gates).
  Rebuild across all 14: ~707 players, ~1,164 skill_snapshots, 135 teams,
  ~1,634 matches, ~3,667 games (profiles pass excluded). Known-pending pieces,
  all self-healing via the day-after-play cron + catch-up queue (see Open data
  threads): 13722 score sheets (host bot-challenge was escalated during rollout
  â€” roster/schedule loaded, sheets owed); 14022 R1 results (season started
  2026-06-10, not yet posted); profile harvests for the 6 newly-onboarded
  divisions (deferred â€” Phase-6 densification, not gate-critical; run when the
  host is unescalated).
- The scrape cron is now DAY-AFTER-PLAY with a catch-up queue (Open data
  threads). --all-divisions stays for onboarding/manual sweeps.
- Phase 6 (forecasting) NOT started â€” deliberate. PHASE6_READINESS.md numbers
  are 13077-only and must be recomputed now that multi-division data has landed.

## Commands
- Scheduled day-after-play scrape (the cron entry point):  python -m src.browser_fetch --scheduled
  (scrapes + auto-backfills only the divisions that played yesterday + the catch-up carryover; cron: scrape.yml)
- Fetch ALL active divisions (onboarding / manual full sweep):  python -m src.browser_fetch --all-divisions
- Fetch one division:  python -m src.browser_fetch --did 13985
- Backfill score sheets:  python -m src.browser_fetch --backfill-weeks auto --did 13985   (auto stops after 2 empty weeks)
- Harvest profiles (tabs-only):  python -m src.browser_fetch --harvest --did 13985 --harvest-drill 0
- Load newest grids:  python -m src.db --load --all-divisions
- Rebuild DB from archive:  python -m src.db --rebuild   (rosters -> schedules -> sheets -> profiles; --no-profiles via run_gates skips the slow profile pass for fast onboarding gates)
- Test:   pytest        (pinned to fixtures/)
- Run app / scout grid:  python -m src.app --scout "<team>" "<opp>"  [--division N]   (default 13077)

## Hard rules
- App reads ONLY from data/napa.db. Never fetch from a view.
- Always archive raw HTML to data/raw/<did>/ BEFORE parsing. Raw archive is committed
  (the durable record); napa.db is regenerable and gitignored. Profiles live at
  data/raw/profiles/<player_id>/ (player-keyed, division-independent).
- Parsers must pass against fixtures/ before touching live data.
- Roster grids: segment on `#` team-header rows; NEVER assume team count or size.
  The CSR HEADER declares the division's game set ("CSR8 - 9 - 10" / "CSR" /
  "CSR9 - 10" / "CSR8 - 9 - 10 - 10BP") â€” values map positionally, absent games
  are NULL, a count mismatch or unknown game token RAISES. Never assume three
  games (B1 recon: "DP LC" divisions play 9/10 only; 14022 AND 13986 play FOUR â€”
  10BP is a first-class rating, skill_snapshots.csr_10bp). Score-sheet 10BP game
  tables parse as game_type '10BP' (text; plain games stay 8/9/10 ints) â€”
  pinned to fixtures/score_sheet_10bp_13986.html.
- Players who appear in results/stats are a SUPERSET of the roster (subs exist). Don't FK games.player_id to roster. player_id is NOT unique per roster grid â€” a player can be rostered on >1 team (real: Kat Plavnick). Key team membership by (team, player_id).
- Canonical player key is the 8-digit playerID. Name->id resolution is DIVISION-FIRST
  with an explicit ambiguity rule (A1): the division's roster, else a UNIQUE
  league-wide match, else NULL + counted in the load report. Subs keep NULL ids,
  never dropped, never guessed.
- skill_snapshots stay LEAGUE-WIDE (PK player_id+captured_date): same-day grids
  MERGE per-game values; a conflicting non-null CSR warns â€” that warn firing means
  the league computes CSR per division and the schema needs a rethink.
  session_matches is per-division at the source: last-write ambiguous for
  multi-division players (accepted; Phase 6 counts games, not SM).
- Seasons are STAGGERED per division (18/21/27-round examples in B1 recon).
  Never assume 27 weeks; the season key for non-13077 divisions is the R1 date,
  stored in divisions.season. 13077 keeps "2025-26".
- pairing_history is AGGREGATE lifetime W-L (from profile RIVALS drill-downs ONLY â€”
  per-opponent head-to-head; NOT the hill-hill "H2H" tab), NOT rack-level â€” keep it
  separate from `games`. It lacks opponent-skill-at-time.
- ALL hosts (paper.playpool.io, scores.playpool.io, poolshooters.com, playpool.io,
  races.napaleagues.com) serve a "One moment..." JS bot-challenge to plain GETs
  (HTTP 200, not 403). A plain client (even httpx with cookies) CANNOT clear it â€”
  capture needs a real browser. Headless Chromium (src/browser_fetch.py) on GitHub
  Actions clears it. Datacenter IP is fine once JS runs. The multi-division loop
  reuses ONE browser context (challenge cookies amortize); an UNCLEARED challenge
  aborts the whole run â€” never hammer the remaining divisions.
- Profile deep tabs (RIVALS/H2H/TRENDS) are JS/AJAX â€” load via
  stats.php?...&xTab=N (RIVALS=5 drill via &rival=<id>, H2H=12, TRENDS=33). Browser only.
  NAPA "H2H" (xTab=12) = HILL-HILL: matches that reached a deciding game (both players
  one win short of the race, e.g. 4-4 to 5) + the player's record IN those games â€” a
  clutch stat, NOT head-to-head. Per-opponent head-to-head is the RIVALS tab (xTab=5)
  -> pairing_history. Hill-hill -> the `hill_hill` table (parse_hillhill_summary +
  load_hill_hill; dated snapshot PK (player_id, captured_date), loaded from h2h.html
  in the profile pass alongside player_form).
  Profile harvests are TABS-ONLY by default (drill ~5,200 pages/division for
  per-game splits Phase 6 doesn't use; re-enable per player set when needed).
- Current per-game ratings come from each division's roster grid (one fetch per
  division), not per-player profile hits.

## Domain
- LC = Lagger's Choice; skill is per-game (8/9/10). The spread matters, not one number.
- CSR = CueSpeed Rating. Higher = stronger. SM = session matches played.
- H2H = HILL-HILL (hill-to-hill): a match that reached a deciding game with both
  players one win short of the race (e.g. 4-4 in a race to 5) â€” the closest possible
  finish. NAPA's profile "H2H" tab is a clutch / deciding-game record, NOT head-to-head.
  (Per-opponent head-to-head is the RIVALS tab.)
- Race lengths: src/race.py is the NAPA matrix transcribed from races.js (class = stronger player's CSR band; race from band+diff). Static lookup, never fetched live. League-wide. Provenance: data/raw/race_assets/.
- The 14 NoCo divisions live in config.DIVISIONS (did, weekday, fmt, scrape flag).
  `fmt` is display-only; the authoritative game set comes from the grid header.

## Open data threads
- Pending makeups in 13077 (matches scheduled but not yet played): R25 5 Amigos vs
  Pocket Pals, R26 Doug's Team vs Barbarians, R26 The Furies vs 5 Amigos, R27 Pocket
  Predators vs The Furies. Surfaced by db.pending_matches(as_of) â€” division-scoped,
  defaults to 13077. Makeups play on OFF-schedule dates, so re-pull score sheets by
  ACTUAL play-date (backfill.yml did=13077); loading drops them off the list.
  Never finalize a division's standings while its makeups are pending.
- Each onboarded division arrives with its own pending set â€” the onboarding gate
  surfaces it.
- The scrape cron (scrape.yml) is DAY-AFTER-PLAY: ONE daily run (15:00 UTC ~=
  09:00 MT) that scrapes + auto-backfills only the divisions whose league night
  was YESTERDAY (config.divisions_due, reckoned in America/Denver) instead of
  sweeping all 14 twice a day. Registry weekdays were verified against every
  division's real schedule (modal fixture weekday, 0 off-day) before relying on
  them. `python -m src.browser_fetch --scheduled` is the entry point;
  --all-divisions stays for onboarding / manual full sweeps.
- Catch-up queue (data/raw/_catchup.json, src/catchup.py): anything that slips
  through a run is carried forward and folded into the NEXT run ON TOP of that
  day's due set, regardless of division â€” a capture SKIPPED by a host-wide
  challenge abort or left only partial, and any division still owed a makeup.
  It clears itself once a division captures cleanly with nothing pending; a
  stale phantom fixture ages out (catchup.MAKEUP_WINDOW_DAYS=56). BYE rounds are
  NOT makeups â€” db.pending_matches filters the "Bye" placeholder team (its
  stored name carries the division suffix, e.g. "Bye Zoosters Team #6").
- Backfill + scrape first-fetch hard-retry: poolshooters/paper can slow-walk the
  "One moment" JS challenge; the backfill retries the first goto up to 8x to land
  the challenge cookie (like the harvest, PR #19). An uncleared challenge still
  aborts host-wide â€” re-dispatch ONCE on a fresh runner (new IP usually clears),
  then wait; never loop.

## Capabilities â€” what's available & when to reach for it
<!--
  The live, authoritative list is injected into every session automatically; this is a
  curated WHEN-TO-USE guide for the currently-active set, so the right tool gets picked
  reliably. It can drift as capabilities change â€” reconcile with `/sync-capabilities`.
  Full canonical inventory (incl. disabled plugin hundreds): $CLAUDE_CONFIG_DIR/AGENTS.md.
-->

**Routing rule (auto-delegation):** when a request falls in one of the domains below, delegate to the
matching expert agent via the Agent tool BEFORE answering yourself - don't wait to be named. Each
expert's `description` frontmatter is what the harness actually matches on; this block is the curated
when-to-use map. Prefer the most specific expert, and let the parenthetical "NOT for X (use Y)"
boundaries disambiguate when two could fire.

### Expert agents (delegate via the Agent tool)
Docs-backed â€” they FETCH current docs, so delegate tool questions instead of guessing:
- `claude-code-expert` â€” Claude Code CLI/harness: hooks, slash commands, skills, subagents, settings.json, MCP config, permissions, CLI flags, SDK.
- `claude-expert` â€” Claude/Anthropic API & models: model ids, pricing, context windows, Messages API, tool use, prompt caching, batches, SDKs.
- `claude-design-expert` â€” Claude Design (claude.ai/design): canvas, prototypes, presentations, exports, `/design-sync`.
- `grok-expert` â€” xAI Grok models & API (docs.x.ai).
- `grok-build-expert` â€” Grok Build (xAI terminal coding CLI).
- `notion-expert` â€” Notion app & API (+ live workspace data via the Notion MCP).
- `mcp-expert` â€” Model Context Protocol itself: spec, building servers/clients, SDKs.
- `agile-expert` â€” UMBRELLA Agile: Manifesto/12 principles, mindset, Lean, XP, framework-selection; ROUTES framework-deep questions to the specialists below.
- `obsidian-expert` - Obsidian app, plugins, themes, vault, Plugin/Dev API (active; kept + documented).

Agile methodology experts (split 2026-06-22 from agile-expert; each docs-backed + its own curated, tracked library):
- `scrum-expert` â€” the Scrum framework (Scrum Guide 2020): theory/values, roles/accountabilities, events + artifacts + commitments, certs, antipatterns. NOT facilitation (use `sprint-expert`).
- `sprint-expert` â€” running/facilitating the Sprint: planning, daily, review, retro (formats), Sprint Goal, capacity, antipatterns. NOT Scrum definitions (use `scrum-expert`).
- `kanban-expert` â€” Kanban (both canons): flow/WIP/pull, the flow metrics, CFD, STATIK, classes of service, Kanban-for-Scrum.
- `agile-scaling-expert` â€” SAFe, LeSS, Nexus, Scrum@Scale, Disciplined Agile + how to choose.
- `agile-metrics-expert` â€” EBM, velocity/estimation/#NoEstimates, cycle/lead time/throughput, Monte Carlo, Flow Framework, DORA.
- `agile-backlog-expert` â€” user stories/INVEST, Gherkin AC, story splitting, refinement, prioritization (MoSCoW/WSJF/RICE/Kano), story/impact mapping.

Persona advisors â€” documented philosophy, source-cited:
- `boris-expert` â€” "What Would Boris Do?" (Boris Cherny, creator of Claude Code); agentic-coding/harness/engineering taste. Drives `/wwbd`.
- `karpathy-expert` â€” "What Would Karpathy Do?" (Andrej Karpathy); ML/LLM/agent/learning philosophy. Drives `/wwkd`.
- `garyvee-expert` â€” "What Would Gary Vee Do?" (Gary Vaynerchuk); attention/content/personal-brand/entrepreneurial-mindset philosophy. Drives `/wwgd`. NOT platform mechanics/pricing (use the creator-monetization experts).

Creator-monetization domain experts (TikTok; source-cited tracked libraries, promoted from the TikTokMonetize project):
- `tiktok-platform-monetization` â€” native TikTok money (Creator Rewards, Shop/Affiliate, Subscriptions, LIVE, Series): eligibility, payouts, RPM, faceless-fit.
- `faceless-content-strategy` â€” faceless formats, monetizable niche selection, audience-pivot mechanics, formatâ†’offer mapping.
- `brand-deals-sponsorship` â€” sponsorship rates, brand evaluation, deal sourcing/structures, FTC/ASA disclosure.
- `digital-products-passive-income` â€” build-once-sell-many offers (digital/software/affiliate/POD), unit economics, the TikTokâ†’sale funnel.
- `audience-analytics-growth` â€” reading real analytics: audience liveness, pivot-transfer risk, engagement baselines, reactivation.
- `creator-legal-compliance` â€” TikTok policy, copyright/strikes/DMCA, FTC/ASA disclosure, refund/tax basics (not legal advice).

System & data critics (read-only - pressure-test your OWN AI/data systems):
- `agentic-systems-architect` - architecture critic for multi-agent / LLM-orchestration systems: topology, fan-out/fan-in, determinism, partial-failure/idempotency, cost/latency, observability, prompt-injection.
- `agent-eval-strategist` - evaluation & epistemics for LLM/agent pipelines with no ground truth: grounding/faithfulness, hallucinated-source detection, judge circularity, gold sets, calibration, drift.
- `opportunity-discovery-strategist` - whether an opportunity-discovery / idea-generation ENGINE creates real conviction vs manufacturing plausible volume.
- `predictive-model-critic` - read-only critic for TABULAR/STATISTICAL predictors (PoolPredict-style): data leakage, calibration (Brier/log-loss, Platt vs isotonic), train/test/backtest design, baseline-beating. The non-LLM sibling of `agent-eval-strategist`.

Domain experts (corpus-backed; read the live project first):
- `pool-rating-systems-expert` - cue-sports rating/handicap systems + cross-league pool data semantics for the PoolPredict cluster (FargoRate anchor/robustness, APA skill levels, NAPA CSR/rack grain, handicap->rack-level modeling, CSR/SL->Fargo crosswalks, per-source quirks). Grounds modeling/data choices, not coding.

Execution & roster:
- `roster-steward` - read-only capability-gap analyst for the whole agent/skill roster (gaps + redundant overlap vs your live projects; proposes a tiered shortlist, never builds).
- `windows-delivery-engineer` - package / schedule / headless-harden local apps + tools on Windows + PowerShell (Scheduled Tasks, encoding, unattended-run reliability).
- `sales-outreach-closer` - solo outbound sales for an already-chosen/priced offer (cold email/DM sequences, discovery scripts, proposals, follow-up cadence).

Data acquisition & identity (pool stack):
- `scrape-resilience-engineer` - keep scrapers running through bot-challenges / throttles / selector-drift (NAPA's HTTP-200 "one moment" interstitial, sticky-context + retry-the-first-goto); owns scrape RUNTIME robustness. Executor.
- `entity-resolution-engineer` - cross-source identity resolution / record linkage / de-dup (one person across Fargo/NAPA/APA/Digital Pool): blocking, precision-first auto-merge, union-find + merge-ledger, idempotent rebuild. Executor.
- `data-acquisition-legal-risk-expert` - legal RISK of scraping + warehousing real-player PII (ToS/CFAA, robots, copyright/database rights, data minimization/retention). Flags what needs a real lawyer; not legal advice.

Build-to-revenue (indie products):
- `indie-product-gtm-strategist` - pricing / packaging / positioning / distribution / launch for a self-built product or dev tool; the single global GTM owner.
- `product-monetization-validator` - pre-build demand validation of ONE concrete idea (cheap smoke / fake-door / pre-sale tests, kill-or-continue criteria) before you build it.

Code / project / built-in:
- `code-explainer` â€” map how a subsystem works / trace a flow across many files (read-only).
- `skill-scout` â€” spot where a new/existing skill could streamline a repeated process.
- `skill-builder` â€” build a skill from an APPROVED spec.
- `Explore` â€” broad read-only multi-file search. `Plan` â€” implementation planning.
- `general-purpose` â€” open-ended multi-step research/search. `claude-code-guide` â€” Q&A on Claude Code / Agent SDK / Claude API.
- `claude` â€” catch-all default. `statusline-setup` â€” configure the status line.

### Skills (invoke via the Skill tool / `/name`)
- **Session flow:** `handoff` (write end-of-session handoff), `handon` (resume from latest handoff), `oneprompt` (distill session into one prompt), `distill` (turn this session's corrections/mistakes into proposed durable rules â€” memories, CLAUDE.md rules, or checks).
- **Research / prior-art:** `deep-research` (multi-source cited report), `already-solved` (find existing libs/tools before building), `claude-api` (Claude API/SDK reference).
- **Thinking / planning:** `grill-me` (interrogate YOU one question at a time to pressure-test an idea/plan/decision), `council` (autonomous multi-persona panel + synthesized go/no-go verdict, for a second opinion before committing).
- **Code quality:** `code-review` (bugs + cleanups on the diff), `simplify` (quality cleanups only), `verify` (run the app to confirm a change), `run` (launch the app), `review` (review a PR), `security-review` (security pass on the branch), `init` (generate a CLAUDE.md).
- **Harness / config:** `update-config` (settings.json, hooks, permissions), `keybindings-help`, `fewer-permission-prompts`, `loop` (run a prompt on an interval), `schedule` (cron cloud agents), `scaffold` (lay the standard project template), `scaffold-expert` (stand up a new docs-backed/persona expert end-to-end â€” library + agent + optional /ww<x> skill + wire/validate), `insight-amplify` (deep swarm-built insights report â€” derives its own judgments from the same raw data `/insights` reads + maps the agent/skill/expert/library relationships, subtracts what you already built, adversarially verifies, writes an auto-opening HTML report, then offers a Boris/Karpathy persona read; proposes only, no score), `sync-capabilities` (reconcile this list vs disk), `backup-config` (commit+push the global config).
- **Security:** `untrusted-repo-static-audit` (read-only audit of an untrusted clone).
- **Agile / delivery:** `user-stories`, `sprint-plan`, `retro`, `backlog-refine`, `kanban-flow` â€” methodology questions route through `agile-expert` to the specialists (`scrum-expert`, `sprint-expert`, `kanban-expert`, `agile-scaling-expert`, `agile-metrics-expert`, `agile-backlog-expert`).
- **Persona advisors:** `wwbd`, `wwkd`, `wwgd` (see the matching agents above).









