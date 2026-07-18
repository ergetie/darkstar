# Tasks: Expand Settings-Search Guides

## 1. Search engine extensions (aliases + glossary kind)

- [x] 1.1 Add optional `aliases: string[]` to the `Guide` interface in `guides.ts` and include it as a weight-3 haystack in `searchGuides` in `index.ts`
- [x] 1.2 Create `glossary.ts` with a `GlossaryEntry` interface (`id`, `term`, `definition`, `aliases?`, `relatedFieldKeys?`, `relatedGuideIds?`) and export a `glossaryEntries` array (empty for now)
- [x] 1.3 Add `searchGlossary()` in `index.ts` (haystacks: term 3, aliases 3, definition 1), add `GlossarySearchResult` to the `SearchResult` union, and return glossary results from `search()`
- [x] 1.4 Add a central `fieldAliases: Record<string, string[]>` map in the search module and include a field's aliases as a weight-3 haystack in `searchFields`

## 2. Glossary and alias content

- [x] 2.1 Write glossary entries (plain-language, one paragraph each) for at minimum: SoC, S-Index, arbitrage, give-way, curtailment, load disaggregation — with related field keys / guide ids where applicable
- [x] 2.2 Populate alias lists: field aliases (e.g. "breaker" → `system.grid.main_fuse_a`) and guide/glossary aliases (e.g. "breaker" on Load Balancing guide, "away mode" on Vacation Mode guide)

## 3. New guides (content written against specs and actual field definitions)

- [x] 3.1 Add "Planner & Executor Basics" guide (planner makes the schedule, executor carries it out, intervals, pausing) — ground in `openspec/specs/planner` and `openspec/specs/executor`
- [x] 3.2 Add "Quick Actions & Command Bar" guide (pause/resume, Water Boost with duration, battery force-charge/top-up, vacation toggle) — ground in `openspec/specs/command-bar` and `CommandBar.tsx`
- [x] 3.3 Add "Vacation Mode" guide (what it changes across the system, anti-legionella safety cycle, how to activate)
- [x] 3.4 Add "Notifications & Alerts" guide (HA notify service, per-event toggles)
- [x] 3.5 Add "AI Advisor" guide (what it does, personalities, auto-fetch, what data it sees) — ground in `openspec/specs/smart-advisor`
- [x] 3.6 Add "Excess PV Dispatch" guide (sink priority with concrete examples, SoC threshold) — ground in `openspec/specs/excess-pv-settings` and `excess-pv-planner-dispatch`
- [x] 3.7 Add "Aurora / ML Forecasting" guide (load/PV forecasting toggles, training runs, when to trust it) — ground in `openspec/specs/aurora-forecast-controls` and the Aurora page
- [x] 3.8 Add "Arbitrage & Economics" guide (export logic, cycle cost trade-offs, price components incl. spot vs fees/VAT)
- [x] 3.9 Add "Getting Started / HA Connection" guide (required sensors and control entities, why features are greyed out until configured)
- [x] 3.10 Add cross-reference lines to the three existing guides: Solar Forecast → Excess PV Dispatch, Battery/S-Index → Arbitrage & Economics, Water Heater → Vacation Mode (no rewrites)

## 4. UI

- [x] 4.1 Render a "Glossary" section in `SettingsSearch.tsx` after Guides, with combined keyboard-navigation indexing across all three sections
- [x] 4.2 Open glossary entries in `GuideViewer` (adapt entry to the viewer's shape: term → title, definition → body; related-guide links open that guide)

## 5. Tests and verification

- [x] 5.1 Integrity test: every guide/glossary `relatedFieldKeys` exists in `fieldSearchIndex`, every glossary `relatedGuideIds` exists in `guides`, every `fieldAliases` key is a real field key
- [x] 5.2 Search tests: alias-only token matches (e.g. "breaker" finds fuse field + Load Balancing guide), alias + literal token combination, glossary term match, non-matching query still yields empty results
- [x] 5.3 Discoverability test: each of the 14 guide topics returns its guide
- [x] 5.4 UI test: keyboard navigation traverses fields → guides → glossary and Enter opens the highlighted glossary entry
- [x] 5.5 Run frontend lint, typecheck, and full test suite; visually verify the Settings page search (three sections, glossary viewer, jump-to-field from a glossary entry)
