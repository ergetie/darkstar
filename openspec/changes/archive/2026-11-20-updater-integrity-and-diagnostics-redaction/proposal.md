# Proposal

## Why

Two beta-exit P1 findings. (1) The updater builds whatever the fetched git ref contains while holding the Docker socket (root on the host), but the origin URL is not pinned, tags are force-fetched and moved or deleted tags go unnoticed. (2) `/api/system/diagnostics` bundles raw `config.yaml`, the full log and `schedule.json`; users post these bundles on Discord, and they hold the Home Assistant address, exact coordinates and any secret-like value that ended up in a config or its stored versions.

## What Changes

- Updater pins origin to `github.com/ergetie/darkstar` and refuses to fetch or apply from any other remote.
- Tags are no longer force-fetched or pruned; a moved tag is a non-fatal warning and the local tag is kept.
- Apply installs the commit hash resolved at apply time, not a ref name.
- A stable install refuses a downgrade to an older tag; dev applies only by fast-forward.
- No signing: no keys, no signature verification, no release-process change, no maintainer setup.
- Diagnostics bundle redacts secrets, URL credentials/paths, non-local hosts, public IPs and coordinates in config, log, schedule and status payloads, and fails closed when config redaction fails.
- The database stays in every bundle; only secret-named keys inside `config_versions.yaml_blob` of the bundled copy are masked.
- The downloaded log file uses the same text redaction. Raw config download and raw DB snapshot stay as explicit backups.

## Capabilities

### New Capabilities

### Modified Capabilities
- `docker-self-update`: origin pinning, tag immutability, commit-hash install, downgrade refusal, dev fast-forward only.
- `diagnostics-export`: redaction of bundle content and masked secrets in the bundled database copy; replaces "config exported as is" for the bundle only.

## Impact

- Code: `updater/repo.py`, `updater/service.py`, new `backend/core/redaction.py`, `backend/api/routers/system.py`.
- Docs: `docs/OPERATIONS.md` (approved).
- No new dependencies (ruamel.yaml already pinned), no schema, `config.yaml` key or UI changes.
- Out of scope: authentication of `/api/updater/*` and `/api/system/diagnostics`, signed releases, GitHub issue #8.
