## 1. Configuration and payload contract

- [x] 1.1 Add `installation_stats.enabled: true` and `installation_stats.endpoint: https://telemetry.wxl.se/api/ping` to `config.default.yaml`; integrate effective defaults and config-save validation without overriding saved false/custom values or modifying local `config.yaml`.
- [x] 1.2 Define the explicit six-field payload contract, allowed values, shipped profile allowlist, custom/unknown handling, and version helper integration; keep sender/receiver validation aligned without importing Darkstar runtime services into the receiver.
- [x] 1.3 Add explicit stable/dev and installation-type deployment metadata to the add-on/standalone paths, with Docker overrides and unknown source-checkout fallback; normalize architecture aliases.

## 2. Sender service

- [x] 2.1 Implement channel-scoped persistent UUID/attempt state under `data/` using atomic writes, preserving identity on upgrades and failing safely on corrupt/unwritable state; ensure generated state files are ignored by git.
- [x] 2.2 Implement daily due-time scheduling and jitter, five-second verified HTTPS requests without redirects, persisted attempts, configuration rechecks, and isolated failure handling with no immediate retries/backlogs.
- [x] 2.3 Integrate the sender with FastAPI lifespan and successful config-save notifications; ensure disable/shutdown cancel or suppress subsequent dispatch without disturbing other services.

## 3. User controls

- [x] 3.1 Add normal-mode searchable toggle and editable endpoint to Settings → System, using existing form/types/save/dirty-change handling and clear payload disclosure.
- [x] 3.2 Add the toggle to onboarding's existing final review step and persist it in the finish save before completion; preserve rerun values, readiness, shadow mode, and go-live behavior, with no upgrade notice or extra wizard step.

## 4. Receiver and summary

- [x] 4.1 Create the independent `telemetry_receiver/` app with environment settings, fail-closed credential checks, separate SQLite storage, transactions/WAL/busy timeout, and bounded off-event-loop database access; include receiver sources in strict type checking.
- [x] 4.2 Implement public `POST /api/ping` with strict payload validation, streamed 2 KiB body limit, global request budget/429 handling, receiver UTC timestamps, deduplicating upserts, and successful-commit HTTP 204 responses.
- [x] 4.3 Implement inclusive 7/30-day totals and metadata breakdowns, daily/startup aggregate snapshots with UTC sample dates, history gaps, and 60-day individual-record cleanup that retains aggregate history.
- [x] 4.4 Implement HTTP Basic protection for `/` and `/api/stats`, constant-time comparisons and generic 401 challenges, no-store responses, disabled public API docs, safely escaped local HTML summary/history, and minimal logging without IP/body/credential retention.

## 5. Verification

- [x] 5.1 Add focused backend tests for default merging/false preservation and validation; payload exclusions/custom profiles; metadata/channel classification; stable/dev identity and corrupt state; restart scheduling; disable/endpoint changes; timeout/redirect isolation; and shutdown. Use temporary state and mocked HTTP/clock inputs rather than live telemetry calls.
- [x] 5.2 Add receiver tests for public ingestion, validation/body limits/throttling, database failures and restart durability, repeated-ID updates, exact 7/30/60-day boundaries, breakdown sums, snapshots/cleanup/history gaps, auth/missing credentials/no-store, HTML escaping, and absence of forbidden data in storage/logs.
- [x] 5.3 Extend onboarding and Settings tests for default-enabled controls, saved opt-out/reruns, endpoint edits and validation, search/normal-mode visibility, final-save failure, and unchanged readiness/finish behavior; visually check both controls and the receiver summary against the design system.
- [x] 5.4 Run the relevant targeted tests, then `./scripts/lint.sh`; run a local sender-to-receiver smoke check with temporary data and a test-only HTTP transport, confirming public ping and protected reads without contacting `telemetry.wxl.se`.

## 6. Deployment handoff

- [x] 6.1 Add receiver-specific pinned runtime requirements using existing project versions, a single-worker systemd example with access logging disabled and persistent storage, and `telemetry_receiver/README.md` covering LXC setup, private environment credentials, Cloudflare Tunnel to `telemetry.wxl.se`, public ping/protected read routes, smoke checks, backups, and retention. Keep runtime files/secrets ignored; do not modify `docs/` or release notes.
- [x] 6.2 Include concise default-enabled/opt-out instructions for the eventual commit and maintainer's Discord announcement in the receiver README, and identify receiver deployment before sender release as an operator step. Do not stage, commit, deploy, or post messages without a separate authorized action.
