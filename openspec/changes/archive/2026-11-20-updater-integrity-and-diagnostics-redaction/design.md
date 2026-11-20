# Design

## Context

- `updater/repo.py:65-66` runs `git fetch --tags --force --prune --prune-tags origin`; origin is whatever `.git/config` holds. `updater/service.py:391-394` checks out by ref name (`main` / tag name). The darkstar service is then built with the fetched Dockerfile and compose file through `docker.sock`.
- Diagnostics: `_write_bundle_sync` (system.py:495) writes config, log, `.log.1`, `schedule.json` raw, plus JSON payloads and a full DB snapshot. `backend/core/exception_text.py` scrubs URL paths/queries/credentials in exception text but keeps hosts, and the exported log is not filtered. The log holds `http://<HA ip>:8123` (ha_socket.py:114,253,1041). Coordinates are in `config.yaml` and in `config_versions.yaml_blob` in the DB. `secrets.yaml` is never read.

## Goals / Non-Goals

**Goals:**
- A changed origin, a moved or deleted release tag, or a diverged dev history cannot silently change what the updater builds.
- No existing install breaks at rollout and no setup is required.
- A bundle can be posted publicly without secrets, HA credentials/paths, public hosts/IPs or exact location, and stays enough to debug planner/executor issues.

**Non-Goals:**
- Signed tags or commits (decided overkill; the remaining risk is a compromised GitHub account, accepted).
- Authenticating the HTTP API, sandboxing the build, reducing the socket mount.
- Redacting entity ids, device names, prices, hardware parameters, or anything in the DB other than secret-named config keys.

## Decisions

### D1. Origin pin
`Repo.assert_origin()` runs `git config --get remote.origin.url` (the stored URL, not the `insteadOf`-rewritten one), normalises (lowercase host, strip trailing `/` and `.git`, map `git@github.com:o/r` and `ssh://git@github.com/o/r` to the https form, matching the existing `insteadOf` rewrite) and requires `https://github.com/ergetie/darkstar`. Called before every fetch and in `begin_apply`; failure raises `GitError("Origin is not github.com/ergetie/darkstar")`, shown as the check error. No override. All supported installs are clones of this repo (docs tell users to clone it), so existing installs pass.

### D2. Tags are not force-updated
Fetch becomes `git fetch --prune origin` plus `--tags` without `--force` and without `--prune-tags`. Git rejects a tag that changed upstream ("would clobber existing tag"); that rejection is non-fatal: recorded in `last_check.warnings`, check still succeeds, local tag kept. Only that rejection is tolerated, any other fetch failure stays an error. A deleted upstream tag stays local, so deleting the newest tag cannot offer a downgrade. Rollout safety: normal fetches never hit the clobber case, so existing installs are unaffected; if a tag was ever moved upstream the install keeps the old commit and shows a warning instead of failing.

### D3. Install the resolved commit
`begin_apply` resolves the target (`rev-list -n 1 <tag>` / `rev-parse origin/main`) and `_apply_steps` runs `checkout --detach <plan.commit>` (stable) and `merge --ff-only <plan.commit>` (dev) with the hash, so the commit installed is the one resolved at apply time, never a name that could move between steps. The version string and rollback logic are unchanged.

### D4. Downgrade and fast-forward rules
- Stable (HEAD detached): refuse when the target is a strict ancestor of HEAD ("Target is older than the installed version"). Switching dev to stable is unaffected (HEAD is on a branch). Existing stable installs always sit on a tag at or before the newest tag, so they pass.
- Dev: refuse when HEAD is not an ancestor of the target ("Dev branch history diverged, refusing non-fast-forward update"). This only fails earlier than the existing `merge --ff-only` already would, with a clearer message and before any checkout.

### D5. Redaction module and rules (`backend/core/redaction.py`)
Reuses `scrub_urls` / `mask_secret_params` from `exception_text.py`.

`redact_text(text)` (log, schedule.json, JSON payloads):
- `scrub_urls` then `mask_secret_params` (path/query/credentials, `token=`, bearer).
- URL host masking: keep the host if it is loopback, RFC1918/link-local IP, a single-label name (`homeassistant`, `supervisor`), `*.local`, `*.internal`, `host.docker.internal`, or on the public-service allowlist (`api.open-meteo.com`, `historical-forecast-api.open-meteo.com`, `archive-api.open-meteo.com`, `telemetry.wxl.se`, `openrouter.ai`, `github.com`, `discord.com`, `discordapp.com`). Also kept: any non-global IP (private, loopback, link-local, CGNAT, documentation), `*.localhost`, and subdomains of allowlisted hosts. Everything else (public IP, DDNS name, `*.ui.nabu.casa`) becomes `<redacted-host>`. A bare IPv6 address outside a URL is not redacted (only bracketed hosts in URLs are handled).
- Bare public IPv4 becomes `<redacted-ip>`.
- `latitude|longitude|lat|lon|lng` followed by `:`/`=` and a decimal number become `<redacted>`; when the key is a JSON-quoted key with an unquoted value (`"latitude": 55.1`) the replacement is the JSON string `"<redacted>"`, so redacted JSON documents stay valid JSON.

`redact_config(yaml_text)` (round-trip with ruamel; comments and order kept):
- Keys at any depth matching `token|secret|password|passwd|api_?key|webhook|credential|authorization|bearer|private_?key` (case-insensitive): non-empty value becomes `<redacted>`; empty/null kept so "unset" stays visible.
- `latitude`/`longitude` (and `lat`, `lon`, `lng`) rounded to 1 decimal (about 11 km, enough for PV debugging).
- String values pass through `redact_text`.
- Kept verbatim: entity ids, device names, tariffs, battery/inverter/solar parameters, price area, timezone, notification service name.
- Parse failure: the item is omitted and the manifest records `error: could not redact config`; never a raw fallback.

Debug-usefulness check: everything the planner/executor investigation reads (entity ids, parameters, plan and status JSON, log levels, messages, timestamps, private HA address) is unchanged; only the listed identifiers are masked.

### D6. Database always included, minimal masking
The bundle always contains the snapshot (current behaviour; the DB is needed for slot history and holds no secrets by design). On the temporary copy only, `config_versions.yaml_blob` is rewritten with the same secret-named-key rule as the config (secret values become `<redacted>`; a blob that does not parse is replaced by `<unparseable config version redacted>` rather than left raw). If masking fails the database is omitted and the manifest records `error: could not mask config versions` (fail closed, never a raw copy). Nothing else in the DB is changed, no vacuum. Consequence accepted by the user: coordinates and other non-secret values in stored config versions are not rounded or masked.

### D7. Logs redacted at export, not at source
Source logs keep the full HA URL for local debugging; export applies `redact_text` to `darkstar.log` and `darkstar.log.1` line by line (bounded memory). `/api/system/logs` download uses the same function. `/api/config/download` and `/api/system/db-snapshot` stay raw backups.

## Risks / Trade-offs

- [A compromised GitHub account can still ship code to stable or dev] -> Accepted, no signing by decision; origin pin, immutable tags and fast-forward limit silent redirection only.
- [An install with a non-ergetie origin stops updating] -> Intended; the error names the rule. Not verified that none exists among users.
- [A tag legitimately re-pointed upstream never reaches existing installs] -> Warning shown; release tags are not moved by policy.
- [Regex redaction misses a novel secret shape] -> Key-name rules, fail closed on config parse errors, one test per rule; user-typed free text is not redacted (needed for debugging).
- [Secrets stored in the DB outside `config_versions`] -> Not verified for `system_state`/`planner_debug`; user decided the DB is not sensitive.

## Migration Plan

Ship as a normal release; the updater applies itself through the existing self-update path. No data, schema or config migration. Rollback is a revert of the release.
