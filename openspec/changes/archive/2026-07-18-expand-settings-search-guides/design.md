# Design: Expand Settings-Search Guides

## Context

The settings search (`frontend/src/pages/settings/search/`) has three parts today:

- `guides.ts` — a static array of 5 `Guide` objects (`id`, `title`, `summary`, `body`, `relatedFieldKeys`).
- `index.ts` — builds a field index from the per-tab section definitions and scores queries token-by-token against weighted haystacks (label 3 / key 2 / help 1 for fields; title 3 / summary 2 / body 1 for guides).
- `SettingsSearch.tsx` + `GuideViewer.tsx` — a two-section results panel (Settings, Guides) with combined keyboard navigation, and a modal viewer whose related-field links run the standard jump-to-field behavior.

This change is frontend-only content + small search-engine extensions. No backend, no API changes.

## Goals / Non-Goals

**Goals:**

- Grow the guide library from 5 to 14 with plain-language guides for the remaining features.
- Make jargon searchable and understandable via short glossary entries.
- Let everyday vocabulary ("breaker", "away mode") find the right results via aliases.

**Non-Goals:**

- Rewriting or deepening the existing 5 guides (cross-reference lines only).
- Pages or quick actions as search result kinds (explicitly deferred 2026-07-18).
- Any fuzzy/typo-tolerant matching — aliases solve the vocabulary problem; the matcher stays substring-based.

## Decisions

### 1. Glossary entries are a separate data type, rendered through the existing GuideViewer

A `GlossaryEntry` (`id`, `term`, `definition`, `aliases?`, `relatedFieldKeys?`, `relatedGuideIds?`) lives in a new `glossary.ts`. The results panel gets a third "Glossary" section. Selecting an entry opens the existing `GuideViewer` (the entry is adapted to the viewer's shape: term → title, definition → body), so related-field links work identically and no new modal is built.

- *Alternative considered:* reuse the `Guide` type with a `kind: 'glossary'` flag. Rejected — glossary entries have different fields (term vs title, optional related guides) and mixing them into the guides array makes the "14 guides" library fuzzy.
- *Alternative considered:* render the full definition inline in the results panel. Rejected — inconsistent interaction (some results click-through, some don't) and no place for related-field links.

### 2. Aliases live in the search module, not in field definitions

- Guides and glossary entries get an optional `aliases: string[]` property on their own objects (content and its synonyms belong together).
- Field aliases go in a central `fieldAliases: Record<string, string[]>` map inside the search module, keyed by field key. The per-tab field definitions in `types.ts` are untouched.

*Alternative considered:* add `aliases?` to `BaseField` so aliases sit on each field definition. Rejected — spreads a search-only concern across all tab definition files and invites drift; the central map keeps the feature self-contained and is still automatically validated (see Decision 4).

### 3. Aliases are an additional weighted haystack, not a query rewrite

The alias list is joined and searched as one more haystack with weight 3 (same as label/title — an alias is an alternative name, not weaker metadata). The existing "every token must match some haystack" rule is unchanged, so multi-word queries mixing an alias with a real term ("breaker limit") still work.

*Alternative considered:* a global synonym table that rewrites query tokens ("breaker" → "fuse") before matching. Rejected — one global mapping can't express per-item synonyms, and silently rewriting the query makes results harder to reason about.

### 4. Content integrity is enforced by tests, not review

Every guide's and glossary entry's `relatedFieldKeys` must exist in `fieldSearchIndex`, every glossary `relatedGuideIds` must exist in `guides`, and every `fieldAliases` key must be a real field key. A unit test asserts all three, so a renamed/removed setting breaks CI instead of shipping a dead link. (The 9 new guide bodies themselves are written from the actual settings sections and existing specs — planner, executor, command-bar, smart-advisor, aurora-forecast-controls, excess-pv-settings — not from memory.)

## Risks / Trade-offs

- [Guide content states something the system doesn't actually do] → each body is written against the relevant spec in `openspec/specs/` and the actual field definitions; the user (who knows the system's real behavior) reviews the content during verification.
- [Results panel gets long with 14 guides + glossary matching broad queries] → sections are already ordered fields → guides → glossary and each result renders two clamped lines; the panel is scrollable with a 70vh cap. No pagination needed at this scale.
- [Alias lists grow stale as vocabulary evolves] → aliases are data-only, one-line additions; the integrity test keeps keys valid.
- [Keyboard navigation index math (`fieldResults.length + i`) must extend to a third section] → covered by an explicit scenario/test for arrow-key traversal across all three sections.
