## Why

Darkstar currently has no reliable estimate of active installations or which versions, deployment types, architectures, and inverter profiles they use. A small daily heartbeat will provide development guidance while keeping energy data and configuration local.

## What Changes

- Add installation statistics reporting, enabled by default for fresh installs and upgrades, with a persistent random installation ID and a configurable receiver URL defaulting to `https://telemetry.wxl.se/api/ping`.
- Send only installation ID, Darkstar version, stable/dev channel, installation type, CPU architecture, and a built-in inverter profile identifier (or `custom`/`unknown`). Reporting runs independently of energy control.
- Add an enabled toggle to the final onboarding step and an enabled toggle plus endpoint field in Settings. Preserve explicit opt-outs across upgrades. Do not add upgrade notices, banners, or forced onboarding.
- Include a separately deployed receiver in this repository: a small FastAPI service with its own SQLite database, a public ping endpoint, and a protected summary page at `https://telemetry.wxl.se/`.
- Report 7-day and 30-day active installation counts, metadata breakdowns, and daily aggregate history. Remove installation records after 60 days without a ping, retaining aggregate history.
- Include LXC/Cloudflare Tunnel deployment instructions alongside the receiver. Existing-user communication happens through the eventual commit description and a manually posted Discord announcement.

## Capabilities

### New Capabilities

- `installation-telemetry`: Default-enabled, user-controlled configuration, minimal payload, persistent identity, and failure-isolated daily reporting.
- `telemetry-receiver`: Public validated heartbeat ingestion, independent storage, retention, aggregate statistics, protected summary page, and self-hosted deployment.

### Modified Capabilities

- `startup-wizard`: Add a statistics toggle and concise payload explanation to the final review step without changing readiness or finish behavior.
- `settings-ux`: Add statistics reporting controls using the existing Settings save flow.

## Impact

- Sender integration: `backend/services/`, `backend/main.py`, configuration validation/default merging, `config.default.yaml`, and stable/dev deployment metadata.
- UI integration: onboarding review/finish, Settings field definitions and types, and existing configuration save APIs; follow the current design system.
- Receiver code, deployment files, and a README under a dedicated `telemetry_receiver/` directory, maintained in the same repository but not started or bundled as a running service in user installations.
- Reuse already pinned FastAPI, Uvicorn, and HTTP client dependencies plus standard-library SQLite; no new third-party libraries are planned.
- Create a separate receiver database only; no Darkstar learning database schema changes. Do not modify local `config.yaml`, `docs/`, or release notes, and do not stage, commit, deploy, or send Discord messages as part of artifact creation.
