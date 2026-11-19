# Proposal

## Why

Darkstar is leaving beta, but the user-facing docs still describe a public beta, never state that only Sweden is supported, never disclose the on-by-default installation statistics, and contain wrong or incomplete install and setup steps (add-on docs that tell users to edit a file the add-on regenerates, a Docker path that never says to clone the repo, broken links, steps pointing to the wrong UI location). These are the six documentation items of the beta-exit readiness audit (`docs/reports/BETA_EXIT_READINESS.md`, sections 1 and 5).

## What Changes

- State that Darkstar supports Sweden only (price areas SE1-SE4) in `README.md`, `docs/SETUP_GUIDE.md` and `darkstar/DOCS.md`; fix the Settings price-area hint (`frontend/src/pages/settings/types.ts:255`) and the `config.default.yaml:268` comment, which still list NO/DK/FI.
- Document the installation statistics (what is sent, that it is on by default, how to turn it off) in `README.md`, `docs/USER_MANUAL.md` and `docs/SETUP_GUIDE.md`. The opt-out model is unchanged.
- Replace "Public beta" wording in `README.md` (badge label, warning box) and `docs/SETUP_GUIDE.md`, keeping the risk disclaimer and adding a no-financial-guarantee sentence.
- Fix the setup guide: broken anchor and path links, duplicated and malformed units warning, wrong UI locations for Logs and Shadow Mode, no mention of the setup wizard. Fix the same Shadow Mode location in `docs/USER_MANUAL.md`.
- Rewrite `darkstar/DOCS.md` to match what the add-on does (wizard, Supervisor token, `secrets.yaml` and the two add-on options), and correct the README claim that the dev add-on can run next to the stable one.
- Give a complete Docker install path in `README.md` (clone, config files, long-lived token creation, build and start) and use `docker compose` consistently.

No behavior changes. `docs/RELEASE_NOTES.md` is not touched. Editing `docs/` is approved by the user for this change.

## Capabilities

### New Capabilities

None.

### Modified Capabilities

None. This is a documentation and copy change with no spec-level behavior change, so `.openspec.yaml` sets `skip_specs: true`.

## Impact

- Docs: `README.md`, `docs/SETUP_GUIDE.md`, `docs/USER_MANUAL.md`, `darkstar/DOCS.md`.
- Copy only: `frontend/src/pages/settings/types.ts` (one helper string), `config.default.yaml` (one comment).
- No API, dependency, schema or runtime changes. Source: backlog items "Make Darkstar Officially Sweden-Only", "Document Telemetry In README And Manual", "Replace Beta Wording, Keep Risk Disclaimer", "Setup Guide Errors", "Add-on Docs Are Wrong", "Docker Install Steps Incomplete" (removed from `docs/BACKLOG.md` when this change was created).
