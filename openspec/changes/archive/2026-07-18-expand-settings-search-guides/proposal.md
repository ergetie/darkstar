# Expand Settings-Search Guides

## Why

The settings search shipped with 5 guides, but most of the features users interact with daily (quick actions, vacation mode, notifications, the advisor, Aurora, the planner/executor itself) have no in-app explanation at all. Additionally, the search only matches literal substrings, so users searching with everyday vocabulary ("breaker", "away mode") find nothing, and jargon used throughout the UI (SoC, S-Index, arbitrage) is never defined anywhere.

## What Changes

- Add 9 new guides to the guide library (growing it from 5 to 14):
  1. **Planner & Executor basics** — the foundation "how Darkstar works" guide: planner makes a schedule, executor carries it out, intervals, pausing.
  2. **Quick Actions & Command Bar** — pause/resume, Water Boost, battery force-charge/top-up, vacation toggle.
  3. **Vacation Mode** — what it changes across the system, the anti-legionella safety cycle.
  4. **Notifications & Alerts** — HA notify service and per-event toggles.
  5. **AI Advisor** — what the LLM advisor does, personalities, auto-fetch, what data it sees.
  6. **Excess PV Dispatch** — dedicated guide for sink priority (currently one paragraph inside the Solar Forecast guide).
  7. **Aurora / ML Forecasting** — load/PV forecasting toggles, training runs, when to trust it.
  8. **Arbitrage & Economics** — export logic, cycle cost trade-offs, price components.
  9. **Getting Started / HA Connection** — required sensors and control entities; doubles as "why is feature X greyed out" troubleshooting.
- Add cross-reference lines to existing guides where new guides overlap (Solar Forecast → Excess PV Dispatch, Battery/S-Index → Arbitrage & Economics, Water Heater → Vacation Mode). No rewrites of existing guides.
- Add **glossary entries** — short one-paragraph definitions of jargon (SoC, S-Index, arbitrage, give-way, curtailment, load disaggregation, …) as a lightweight searchable kind alongside guides.
- Add **synonym/alias matching** — a small alias list per guide/field so vocabulary mismatches still match (e.g. "breaker" → load balancing guide and main-fuse field).

Explicitly out of scope (decided 2026-07-18): deepening/rewriting the existing 5 guides, pages-as-search-results, quick-actions-as-search-results.

## Capabilities

### New Capabilities

None.

### Modified Capabilities

- `settings-search`: the "Initial guide library" requirement grows to the full 14-guide library; new requirements for glossary entries as a searchable result kind and synonym/alias matching in the search scoring.

## Impact

- **Frontend only**, no backend changes:
  - `frontend/src/pages/settings/search/guides.ts` — 9 new guide entries, cross-reference lines in 3 existing guides, glossary data, alias data.
  - `frontend/src/pages/settings/search/index.ts` — extend match scoring with aliases; add glossary search / result kind.
  - `frontend/src/pages/settings/search/SettingsSearch.tsx` and `GuideViewer.tsx` — render glossary results (and alias-driven matches need no UI change).
  - `frontend/src/pages/settings/search/index.test.ts` — new tests for aliases, glossary, and new-guide discoverability.
- Removes the "Expand Settings-Search User Guides" item from `docs/BACKLOG.md` at change creation time.
