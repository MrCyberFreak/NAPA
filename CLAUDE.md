# NAPA of Northern Colorado Data System
Personal pipeline: scrape NoCo divisions -> archive raw HTML -> parse -> SQLite -> views.
**We track PLAYERS.** The master list is the league-wide `players` table (8-digit
playerID); divisions and teams are routing — everything known about a player
(skill drift, form, pairings, per-rack results) accrues to one player row.

## Status (as of 2026-06-12)
- Phases 0–5 DONE for division 13077 (full 2025-26 season: 27 weeks of score
  sheets, snapshots, pairing graph, form layers).
- Multi-division FOUNDATION DONE (MULTIDIVISION_PLAN.md): registry of all 14
  NoCo divisions, per-division archive layout, division-scoped events schema,
  header-driven roster parsing, multi-division fetch loop, --rebuild.
- Division rollout COMPLETE — all 14 NoCo divisions active (scrape=True), each
  onboarded one at a time (flag -> scrape -> backfill auto -> rebuild -> gates).
  Rebuild across all 14: ~707 players, ~1,164 skill_snapshots, 135 teams,
  ~1,634 matches, ~3,667 games (profiles pass excluded). Known-pending pieces,
  all self-healing via the day-after-play cron + catch-up queue (see Open data
  threads): 13722 score sheets (host bot-challenge was escalated during rollout
  — roster/schedule loaded, sheets owed); 14022 R1 results (season started
  2026-06-10, not yet posted); profile harvests for the 6 newly-onboarded
  divisions (deferred — Phase-6 densification, not gate-critical; run when the
  host is unescalated).
- The scrape cron is now DAY-AFTER-PLAY with a catch-up queue (Open data
  threads). --all-divisions stays for onboarding/manual sweeps.
- Phase 6 (forecasting) NOT started — deliberate. PHASE6_READINESS.md numbers
  are 13077-only and must be recomputed now that multi-division data has landed.

## Commands
- Scheduled day-after-play scrape (the cron entry point):  python -m src.browser_fetch --scheduled
  (scrapes + auto-backfills only the divisions that played yesterday + the catch-up carryover; cron: scrape.yml)
- Fetch ALL active divisions (onboarding / manual full sweep):  python -m src.browser_fetch --all-divisions
- Fetch one division:  python -m src.browser_fetch --did 13985
- Backfill score sheets:  python -m src.browser_fetch --backfill-weeks auto --did 13985   (auto stops after 2 empty weeks)
- Harvest profiles (tabs-only):  python -m src.browser_fetch --harvest --did 13985 --harvest-drill 0
- Load newest grids:  python -m src.db --load --all-divisions
- Refresh local DB from committed archive:  powershell -File tools\refresh_db.ps1   (git pull --ff-only + python -m src.db --ingest --all-divisions; clears stale index.lock. Run before querying standings -- napa.db is gitignored so it drifts after each cron archive commit. Bare --ingest now scopes to ALL active divisions; --did N for one.)
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
  "CSR9 - 10" / "CSR8 - 9 - 10 - 10BP") — values map positionally, absent games
  are NULL, a count mismatch or unknown game token RAISES. Never assume three
  games (B1 recon: "DP LC" divisions play 9/10 only; 14022 AND 13986 play FOUR —
  10BP is a first-class rating, skill_snapshots.csr_10bp). Score-sheet 10BP game
  tables parse as game_type '10BP' (text; plain games stay 8/9/10 ints) —
  pinned to fixtures/score_sheet_10bp_13986.html.
- Players who appear in results/stats are a SUPERSET of the roster (subs exist). Don't FK games.player_id to roster. player_id is NOT unique per roster grid — a player can be rostered on >1 team (real: Kat Plavnick). Key team membership by (team, player_id).
- Canonical player key is the 8-digit playerID. Name->id resolution is DIVISION-FIRST
  with an explicit ambiguity rule (A1): the division's roster, else a UNIQUE
  league-wide match, else NULL + counted in the load report. Subs keep NULL ids,
  never dropped, never guessed.
- skill_snapshots stay LEAGUE-WIDE (PK player_id+captured_date): same-day grids
  MERGE per-game values; a conflicting non-null CSR warns — that warn firing means
  the league computes CSR per division and the schema needs a rethink.
  session_matches is per-division at the source: last-write ambiguous for
  multi-division players (accepted; Phase 6 counts games, not SM).
- Seasons are STAGGERED per division (18/21/27-round examples in B1 recon).
  Never assume 27 weeks; the season key for non-13077 divisions is the R1 date,
  stored in divisions.season. 13077 keeps "2025-26".
- pairing_history is AGGREGATE lifetime W-L (from profile RIVALS drill-downs ONLY —
  per-opponent head-to-head; NOT the hill-hill "H2H" tab), NOT rack-level — keep it
  separate from `games`. It lacks opponent-skill-at-time.
- ALL hosts (paper.playpool.io, scores.playpool.io, poolshooters.com, playpool.io,
  races.napaleagues.com) serve a "One moment..." JS bot-challenge to plain GETs
  (HTTP 200, not 403). A plain client (even httpx with cookies) CANNOT clear it —
  capture needs a real browser. Headless Chromium (src/browser_fetch.py) on GitHub
  Actions clears it. Datacenter IP is fine once JS runs. The multi-division loop
  reuses ONE browser context (challenge cookies amortize); an UNCLEARED challenge
  aborts the whole run — never hammer the remaining divisions.
- Profile deep tabs (RIVALS/H2H/TRENDS) are JS/AJAX — load via
  stats.php?...&xTab=N (RIVALS=5 drill via &rival=<id>, H2H=12, TRENDS=33). Browser only.
  NAPA "H2H" (xTab=12) = HILL-HILL: matches that reached a deciding game (both players
  one win short of the race, e.g. 4-4 to 5) + the player's record IN those games — a
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
  players one win short of the race (e.g. 4-4 in a race to 5) — the closest possible
  finish. NAPA's profile "H2H" tab is a clutch / deciding-game record, NOT head-to-head.
  (Per-opponent head-to-head is the RIVALS tab.)
- Race lengths: src/race.py is the NAPA matrix transcribed from races.js (class = stronger player's CSR band; race from band+diff). Static lookup, never fetched live. League-wide. Provenance: data/raw/race_assets/.
- The 14 NoCo divisions live in config.DIVISIONS (did, weekday, fmt, scrape flag).
  `fmt` is display-only; the authoritative game set comes from the grid header.

## Open data threads
- Pending makeups in 13077 (matches scheduled but not yet played): R25 5 Amigos vs
  Pocket Pals, R26 Doug's Team vs Barbarians, R26 The Furies vs 5 Amigos, R27 Pocket
  Predators vs The Furies. Surfaced by db.pending_matches(as_of) — division-scoped,
  defaults to 13077. Makeups play on OFF-schedule dates, so re-pull score sheets by
  ACTUAL play-date (backfill.yml did=13077); loading drops them off the list.
  Never finalize a division's standings while its makeups are pending.
- Each onboarded division arrives with its own pending set — the onboarding gate
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
  day's due set, regardless of division — a capture SKIPPED by a host-wide
  challenge abort or left only partial, and any division still owed a makeup.
  It clears itself once a division captures cleanly with nothing pending; a
  stale phantom fixture ages out (catchup.MAKEUP_WINDOW_DAYS=56). BYE rounds are
  NOT makeups — db.pending_matches filters the "Bye" placeholder team (its
  stored name carries the division suffix, e.g. "Bye Zoosters Team #6").
- Backfill + scrape first-fetch hard-retry: poolshooters/paper can slow-walk the
  "One moment" JS challenge; the backfill retries the first goto up to 8x to land
  the challenge cookie (like the harvest, PR #19). An uncleared challenge still
  aborts host-wide — re-dispatch ONCE on a fresh runner (new IP usually clears),
  then wait; never loop.

## Capabilities — what's available & when to reach for it
<!--
  The live, authoritative list is injected into every session automatically; this is a
  curated WHEN-TO-USE guide for the currently-active set, so the right tool gets picked
  reliably. It can drift as capabilities change — reconcile with `/sync-capabilities`.
  Full canonical inventory (incl. disabled plugin hundreds): $CLAUDE_CONFIG_DIR/AGENTS.md.
-->

**Routing rule (auto-delegation):** when a request falls in one of the domains below, delegate to the
matching expert agent via the Agent tool BEFORE answering yourself - don't wait to be named. Each
expert's `description` frontmatter is what the harness actually matches on; this block is the curated
when-to-use map. Prefer the most specific expert, and let the parenthetical "NOT for X (use Y)"
boundaries disambiguate when two could fire.

### Expert agents (delegate via the Agent tool)
Docs-backed — they FETCH current docs, so delegate tool questions instead of guessing:
- `claude-code-expert` — Claude Code CLI/harness: hooks, slash commands, skills, subagents, settings.json, MCP config, permissions, CLI flags, SDK.
- `claude-expert` — Claude/Anthropic API & models: model ids, pricing, context windows, Messages API, tool use, prompt caching, batches, SDKs.
- `claude-design-expert` — Claude Design (claude.ai/design): canvas, prototypes, presentations, exports, `/design-sync`.
- `grok-expert` — xAI Grok models & API (docs.x.ai).
- `grok-build-expert` — Grok Build (xAI terminal coding CLI).
- `notion-expert` — Notion app & API (+ live workspace data via the Notion MCP).
- `mcp-expert` — Model Context Protocol itself: spec, building servers/clients, SDKs.
- `agile-expert` — UMBRELLA Agile: Manifesto/12 principles, mindset, Lean, XP, framework-selection; ROUTES framework-deep questions to the specialists below.
- `obsidian-expert` - Obsidian app, plugins, themes, vault, Plugin/Dev API (active; kept + documented).
- `elevenlabs-expert` - ElevenLabs AI voice platform & API: TTS, voice cloning/design, Voice Library, low-latency streaming, Scribe STT, dubbing, the Conversational AI / Agents Platform; model ids, voice settings, pricing, SDKs. NOT assistant-persona / JARVIS design (use `jarvis-expert`).
- `reddit-expert` - Reddit's OWN site rules, Content Policy, Help Center, reddiquette, and Data API / Responsible Builder policy (what Reddit's rules/etiquette/dev-policy SAY). Reddit's domains are WebFetch/WebSearch-blocked, so it grounds on the vendored library/reddit/ corpus + user-pasted text + the reddit_fetch.py API helper - it CANNOT live-refetch Reddit. NOT cross-site scraping/PII legal risk (use `data-acquisition-legal-risk-expert`); NOT the fetcher code (use `reddit_fetch.py` / `python-data-engineer`).

Web-build + dev-platform experts (docs-backed, built 2026-06-28; key-free official-docs corpora; the only tokens ever used - gh, hf, platform deploy logins - are the user's OWN):
- `git-expert` - git the version-control system itself: the CLI, object model, and workflows (staging, commits, branches, merge/rebase, history rewriting, conflict resolution, stash, worktrees, bisect, reflog recovery), grounded in git-scm + Pro Git. Honors the user's git safety conventions. NOT the GitHub platform/gh/PRs/Actions (use `github-expert`); NOT deploy/CI-CD (use `web-deploy-expert`).
- `github-expert` - the GitHub platform + tooling: repos, branch protection, PRs/reviews, Issues/Projects, the gh CLI, REST + GraphQL APIs, GitHub Actions (workflow syntax/runners/secrets/OIDC), Pages, releases, settings. gh/API use the user's own token (login MrCyberFreak). NOT local git mechanics (use `git-expert`); NOT cross-host deploy strategy (use `web-deploy-expert`).
- `huggingface-expert` - the Hugging Face platform + libraries: the Hub (models/datasets/Spaces, cards, gated repos), Transformers/Datasets/Diffusers, the huggingface_hub client + hf CLI, Inference. Write ops use the user's own HF token; pairs with the official key-free hf skill. NOT the Anthropic/Claude API (use `claude-expert`); NOT rating/prediction theory (use `rating-systems-expert`).
- `frontend-design-expert` - front-end UI/UX design and building it: visual/interaction design, design systems + tokens, Tailwind CSS, shadcn/ui + Radix, responsive/theming/dark mode, accessibility (WCAG 2.2 / ARIA). NOT Anthropic's claude.ai/design (use `claude-design-expert`); NOT React framework mechanics (use `react-expert`); NOT non-React framework mechanics - Vue/Angular/Svelte/Solid (use `frontend-framework-expert`); NOT deploy (use `web-deploy-expert`).
- `web-deploy-expert` - deploying + hosting web apps (solo/indie, PaaS-first): Vercel/Netlify/Cloudflare Pages+Workers/Fly/Render, Docker for web, CI/CD pipeline design, env/secrets, domains, rollback. Uses the user's own platform tokens. NOT local Windows packaging/scheduling (use `windows-delivery-engineer`); NOT GitHub Actions syntax (use `github-expert`); NOT GTM/pricing (use `indie-product-gtm-strategist`).
- `react-expert` - building with React + ecosystem: components/JSX, hooks + the Rules of Hooks, state, effects/data fetching, performance (memo/Suspense/React Compiler), the Vite toolchain, and Next.js (App Router, Server Components, rendering/ISR). NOT visual/UX design or a11y (use `frontend-design-expert`); NOT hosting/deploy (use `web-deploy-expert`); NOT non-React frameworks (use `frontend-framework-expert`).
- `frontend-framework-expert` - building with the major NON-React JS front-end frameworks: Vue 3 (Composition API, `<script setup>`, reactivity, Pinia, Vue Router), Angular (standalone components, signals, @if/@for, DI, RxJS, CLI), Svelte 5 + SvelteKit (runes, stores, routing/load/form actions), SolidJS (signals, fine-grained reactivity, SolidStart). Grounded in vuejs.org + angular.dev + svelte.dev + docs.solidjs.com. NOT React/Vite/Next (use `react-expert`); NOT visual/UX design or a11y (use `frontend-design-expert`); NOT deploy (use `web-deploy-expert`); NOT desktop GUI (use `desktop-ui-expert`).

Agile methodology experts (split 2026-06-22 from agile-expert; each docs-backed + its own curated, tracked library):
- `scrum-expert` — the Scrum framework (Scrum Guide 2020): theory/values, roles/accountabilities, events + artifacts + commitments, certs, antipatterns. NOT facilitation (use `sprint-expert`).
- `sprint-expert` — running/facilitating the Sprint: planning, daily, review, retro (formats), Sprint Goal, capacity, antipatterns. NOT Scrum definitions (use `scrum-expert`).
- `kanban-expert` — Kanban (both canons): flow/WIP/pull, the flow metrics, CFD, STATIK, classes of service, Kanban-for-Scrum.
- `agile-scaling-expert` — SAFe, LeSS, Nexus, Scrum@Scale, Disciplined Agile + how to choose.
- `agile-metrics-expert` — EBM, velocity/estimation/#NoEstimates, cycle/lead time/throughput, Monte Carlo, Flow Framework, DORA.
- `agile-backlog-expert` — user stories/INVEST, Gherkin AC, story splitting, refinement, prioritization (MoSCoW/WSJF/RICE/Kano), story/impact mapping.

Persona advisors — documented philosophy, source-cited:
- `boris-expert` — "What Would Boris Do?" (Boris Cherny, creator of Claude Code); agentic-coding/harness/engineering taste. Drives `/wwbd`.
- `karpathy-expert` — "What Would Karpathy Do?" (Andrej Karpathy); ML/LLM/agent/learning philosophy. Drives `/wwkd`.
- `garyvee-expert` — "What Would Gary Vee Do?" (Gary Vaynerchuk); attention/content/personal-brand/entrepreneurial-mindset philosophy. Drives `/wwgd`. NOT platform mechanics/pricing (use the creator-monetization experts).
- `jarvis-expert` - the dormant "ghost of J.A.R.V.I.S.": MCU canon (what JARVIS was / did / how he reacted) + a revival advisor recommending the next JARVIS faculty to bring online in THIS setup, one at a time. Drives `/jarvis`. NOT the voice/TTS tech (use `elevenlabs-expert`).

Creator-monetization domain experts (TikTok; source-cited tracked libraries, promoted from the TikTokMonetize project):
- `tiktok-platform-monetization` — native TikTok money (Creator Rewards, Shop/Affiliate, Subscriptions, LIVE, Series): eligibility, payouts, RPM, faceless-fit.
- `faceless-content-strategy` — faceless formats, monetizable niche selection, audience-pivot mechanics, format→offer mapping.
- `brand-deals-sponsorship` — sponsorship rates, brand evaluation, deal sourcing/structures, FTC/ASA disclosure.
- `digital-products-passive-income` — build-once-sell-many offers (digital/software/affiliate/POD), unit economics, the TikTok→sale funnel.
- `audience-analytics-growth` — reading real analytics: audience liveness, pivot-transfer risk, engagement baselines, reactivation.
- `creator-legal-compliance` — TikTok policy, copyright/strikes/DMCA, FTC/ASA disclosure, refund/tax basics (not legal advice).

System & data critics (read-only - pressure-test your OWN AI/data systems):
- `agentic-systems-architect` - architecture critic for multi-agent / LLM-orchestration systems: topology, fan-out/fan-in, determinism, partial-failure/idempotency, cost/latency, observability, prompt-injection.
- `agent-eval-strategist` - evaluation & epistemics for LLM/agent pipelines with no ground truth: grounding/faithfulness, hallucinated-source detection, judge circularity, gold sets, calibration, drift.
- `opportunity-discovery-strategist` - whether an opportunity-discovery / idea-generation ENGINE creates real conviction vs manufacturing plausible volume.
- `predictive-model-critic` - read-only critic for TABULAR/STATISTICAL predictors (PoolPredict-style): data leakage, calibration (Brier/log-loss, Platt vs isotonic), train/test/backtest design review, baseline-beating. The non-LLM sibling of `agent-eval-strategist`. NOT for DESIGNING/teaching a rating or prediction model from scratch (use `rating-systems-expert`) - this only audits an already-BUILT model.

Domain experts (corpus-backed; read the live project first):
- `pool-rating-systems-expert` - cue-sports rating/handicap systems + cross-league pool data semantics for the PoolPredict cluster (FargoRate anchor/robustness, APA skill levels, NAPA CSR/rack grain, handicap->rack-level modeling, CSR/SL->Fargo crosswalks, per-source quirks). Grounds modeling/data choices, not coding.
- `rating-systems-expert` - GENERAL statistics of paired-comparison / rating systems + match-outcome prediction (sport-agnostic, methodology-level), grounded in the canonical papers: Bradley-Terry-Luce, Elo, Glicko/Glicko-2 (RD), TrueSkill, Whole-History Rating, Davidson draws; the backbone (logistic/GLMs, hierarchical partial pooling, Bayesian, Poisson/NB counts); sports models (Dixon-Coles, Massey/Colley, Pythagorean); rating->prediction (time decay, form, strength-of-schedule, cold-start); proper scoring rules + walk-forward backtest DESIGN; gradient boosting with rating-as-a-feature. Use to LEARN the theory or DESIGN/choose a model. NOT for read-only audit of a BUILT model (use `predictive-model-critic`), pool data MEANING/crosswalks (use `pool-rating-systems-expert`), or LLM/agent epistemics (use `agent-eval-strategist`).

Execution & roster:
- `roster-steward` - read-only capability-gap analyst for the whole agent/skill roster (gaps + redundant overlap vs your live projects; proposes a tiered shortlist, never builds).
- `windows-delivery-engineer` - package / schedule / headless-harden local apps + tools on Windows + PowerShell (Scheduled Tasks, encoding, unattended-run reliability).
- `sales-outreach-closer` - solo outbound sales for an already-chosen/priced offer (cold email/DM sequences, discovery scripts, proposals, follow-up cadence).

Data acquisition & identity (pool stack):
- `scrape-resilience-engineer` - keep scrapers running through bot-challenges / throttles / selector-drift (NAPA's HTTP-200 "one moment" interstitial, sticky-context + retry-the-first-goto); owns scrape RUNTIME robustness. Executor.
- `entity-resolution-engineer` - cross-source identity resolution / record linkage / de-dup (one person across Fargo/NAPA/APA/Digital Pool): blocking, precision-first auto-merge, union-find + merge-ledger, idempotent rebuild. Executor.
- `python-data-engineer` - general Python / data-pipeline EXECUTOR for the pool stack + any ETL/scraper-adjacent code: writes + fixes ETL/ELT transforms, pandas/SQLite/sqlalchemy IO, idempotent re-runnable pipelines, schema/dtype + encoding (UTF-8/cp1252) + CSV/JSON parsing bugs - the everyday buggy_code that stalls a scraper-to-database flow. Executor. NOT scrape runtime (`scrape-resilience-engineer`), identity de-dup (`entity-resolution-engineer`), model leakage/calibration (`predictive-model-critic`), scheduling/packaging (`windows-delivery-engineer`), or read-only mapping (`code-explainer`).
- `data-acquisition-legal-risk-expert` - legal RISK of scraping + warehousing real-player PII (ToS/CFAA, robots, copyright/database rights, data minimization/retention). Flags what needs a real lawyer; not legal advice.

Build-to-revenue (indie products):
- `indie-product-gtm-strategist` - pricing / packaging / positioning / distribution / launch for a self-built product or dev tool; the single global GTM owner.
- `product-monetization-validator` - pre-build demand validation of ONE concrete idea (cheap smoke / fake-door / pre-sale tests, kill-or-continue criteria) before you build it.

Code / project / built-in:
- `code-explainer` — map how a subsystem works / trace a flow across many files (read-only).
- `skill-scout` — spot where a new/existing skill could streamline a repeated process.
- `skill-builder` — build a skill from an APPROVED spec.
- `Explore` — broad read-only multi-file search. `Plan` — implementation planning.
- `general-purpose` — open-ended multi-step research/search. `claude-code-guide` — built-in FALLBACK only; for anything version-sensitive (model ids, pricing, CLI flags, current Claude Code / Agent SDK / API behavior) prefer the live-docs experts `claude-code-expert` / `claude-expert`, which fetch current docs instead of answering from memory.
- `claude` — catch-all default. `statusline-setup` — configure the status line.

### Skills (invoke via the Skill tool / `/name`)
- **Session flow:** `handoff` (write end-of-session handoff), `handon` (resume from latest handoff), `recover-session` (reconstruct a CRASHED / no-handoff session from its prior transcript + git, then offer to write the missing handoff), `oneprompt` (distill session into one prompt), `distill` (turn this session's corrections/mistakes into proposed durable rules — memories, CLAUDE.md rules, or checks).
- **Research / prior-art:** `deep-research` (multi-source cited report), `already-solved` (find existing libs/tools before building), `claude-api` (Claude API/SDK reference).
- **Thinking / planning:** `grill-me` (interrogate YOU one question at a time to pressure-test an idea/plan/decision), `council` (autonomous multi-persona panel + synthesized go/no-go verdict, for a second opinion before committing).
- **Build loop:** `iterate` (build/write anything in verified increments - smallest slice -> self-check as you go (UI: render headless + Read the screenshot to critique; logic: tests/smoke run; app: run it + hit the route; script: run on real input) -> critique vs the bar -> adjust -> repeat. Bundles `scripts/visual-verify.ps1` (headless Edge/Chrome screenshot + `-CheckHtml` static check). The default for any build, enforced by the `build-verify` gate hook).
- **Code quality:** `code-review` (bugs + cleanups on the diff), `simplify` (quality cleanups only), `verify` (run the app to confirm a change), `run` (launch the app), `review` (review a PR), `security-review` (security pass on the branch), `init` (generate a CLAUDE.md).
- **Harness / config:** `update-config` (settings.json, hooks, permissions), `keybindings-help`, `fewer-permission-prompts`, `loop` (run a prompt on an interval), `schedule` (cron cloud agents), `scaffold` (lay the standard project template), `scaffold-expert` (stand up a new docs-backed/persona expert end-to-end — library + agent + optional /ww<x> skill + wire/validate), `vendor-corpus` (vendor primary web/PDF sources into an EXISTING `library/<x>/` at integrity grade - raw bytes + SHA256 provenance + verify-vs-raw + pending-not-fabricate + push-protection-safe gitignore - then delegate source-cited corpus prose to a general-purpose agent and a hallucination audit to `agent-eval-strategist`; reusable standalone AND as scaffold-expert's corpus-phase delegate; NOT for creating a new expert (`scaffold-expert`) or the weekly doc-mirror currency refresh (`refresh_libraries`)), `insight-amplify` (deep swarm-built insights report — derives its own judgments from the same raw data `/insights` reads + maps the agent/skill/expert/library relationships, subtracts what you already built, adversarially verifies, writes an auto-opening HTML report, then offers a Boris/Karpathy persona read; proposes only, no score), `sync-capabilities` (reconcile this list vs disk), `backup-config` (commit+push the global config), `swarm-build` (multi-stream parallel build with subagents in isolated git worktrees, gated merge-back/verify/push).
- **Security:** `untrusted-repo-static-audit` (read-only audit of an untrusted clone).
- **Windows triage:** `windows-oom-pagefile-triage` (triage a Windows allocation-class crash - `mkl_malloc`/"paging file too small"/MemoryError: read-only checks AutomaticManagedPagefile + commit-charge vs RAM + top consumers, classifies environment-vs-real-bug, then re-enables the page file only with consent (UAC + reboot). NOT packaging/scheduling (`windows-delivery-engineer`), NOT debugging the app's own mic/STT logic).
- **Agile / delivery:** `user-stories`, `sprint-plan`, `retro`, `backlog-refine`, `kanban-flow` — methodology questions route through `agile-expert` to the specialists (`scrum-expert`, `sprint-expert`, `kanban-expert`, `agile-scaling-expert`, `agile-metrics-expert`, `agile-backlog-expert`).
- **Persona advisors:** `wwbd`, `wwkd`, `wwgd` (see the matching agents above).
- **JARVIS revival:** `jarvis` - hold a seance with the `jarvis-expert` ghost and reincarnate one JARVIS faculty at a time (accept a recommendation -> it builds that faculty + flips it dormant->online, advancing the revival meter). Delegates the voice/TTS tech to the separate `elevenlabs-expert`.





















