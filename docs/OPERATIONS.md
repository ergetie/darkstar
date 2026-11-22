# Darkstar Operations Guide

This guide covers day-to-day operations, maintenance, and troubleshooting for the Darkstar Energy Manager.

## 📊 Viewing Logs

### Docker Compose
```bash
docker compose logs -f
```

### Home Assistant Add-on
1. Navigate to **Settings -> Add-ons -> Darkstar Energy Manager**.
2. Click on the **Logs** tab.

---

## 💾 Backups

Darkstar's state consists of configuration files and a learning database. To backup your installation, save the following items:

| Item | Path | Importance |
|------|------|------------|
| `config.yaml` | Root / `/config/darkstar/` | **High** (Your mappings) |
| `secrets.yaml` | Root / `/config/darkstar/` | **High** (Passwords/Tokens) |
| `data/` | Root / `/config/darkstar/data/` | **Medium** (ML Learning DB) |

---

## 🛠️ Maintenance

### ML Retraining
Darkstar automatically retrains its forecasting models twice a week (default: Mon/Thu at 03:00). You can check the training status in the logs by looking for:
`🧠 Starting ML model retraining...`

### Updating Darkstar
Docker installs can update from the UI: click the version in the sidebar (a dot appears when an update is available), pick a channel (`dev` = latest `main`, `stable` = latest `v*` release tag), then **Update**. Darkstar is rebuilt locally from git and restarted; a failed build leaves the running container untouched.

An update is refused when tracked files were modified locally, or when the target does not contain your database's migration version (for example Dev to Stable). Downgrades are never automatic. Every update that needs a database migration is preceded by an automatic backup (see [Database safety](#database-safety)).

**Update safety rules.** The updater only fetches from and applies code of `github.com/ergetie/darkstar` (https, `git@github.com:` and `ssh://git@github.com/` forms, with or without `.git`). Before every check and update it reads `origin` and refuses anything else with "Origin is not github.com/ergetie/darkstar". If you cloned from a fork or mirror, point origin back at the official repository:
```bash
git remote set-url origin https://github.com/ergetie/darkstar.git
```
Release tags are never overwritten or pruned locally. If a tag was moved upstream, the check still succeeds and shows a warning naming the tag, and your local tag is kept; a tag deleted upstream also stays. The update installs the exact commit resolved when you press **Update**, not a name that could move meanwhile. `stable` refuses a target older than the installed version ("Target is older than the installed version"); switching from `dev` to `stable` is not affected by this rule. `dev` only fast-forwards: if your local history is not an ancestor of `origin/main` the update is refused ("Dev branch history diverged, refusing non-fast-forward update") before anything is checked out.

**Opt-in setup.** The updater is a separate `updater` container that only starts when enabled. Without it nothing changes and you can keep updating manually. To enable it, add these values to a `.env` file next to `docker-compose.yml`, then rebuild once:
```bash
echo "DARKSTAR_UPDATER_TOKEN=$(openssl rand -hex 32)" >> .env
echo "DARKSTAR_REPO_DIR=$(pwd)" >> .env
echo "COMPOSE_PROFILES=updater" >> .env
git pull
docker compose up -d --build
```
**Rollback.** If the new version fails to start or does not report the new version within 5 minutes, the updater stops it, restores the database backup made just before the migration, rebuilds the previous version and starts it. The card then shows the update as failed and says what was restored. If a rollback step itself fails, the message names the backup file and the manual restore command.

**Updater updates.** After a successful update, if the updater code or `docker-compose.yml` changed, the updater recreates itself automatically (one attempt per change; the card shows the result and, if it failed, the command to run by hand). Rollback is only active in an updater that has been rebuilt once: see [First update that ships database safety](#first-update-that-ships-database-safety).

**Security note.** The `updater` container mounts the Docker socket, which is root-equivalent on the host. It has no published port, only accepts requests carrying `DARKSTAR_UPDATER_TOKEN`, and only performs fixed operations (check, switch channel, update Darkstar). The Darkstar container itself never gets the socket. Keep `.env` private.

**Manual update** (also the fallback when the UI is unavailable):
```bash
git pull
docker compose build
docker compose up -d
```

---

## 🛡️ Database safety

### Automatic backup before a migration
At every start Darkstar checks whether a database migration is pending (or the one-time storage switch below). Only then it writes a consistent copy of the database to `backups/` next to the database file, named `pre-migration-<UTC timestamp>-<previous revision>.db`:

| Install | Backup folder |
|---------|---------------|
| Docker Compose | `./data/backups/` |
| Home Assistant add-on | `/share/darkstar/backups/` |

The newest 3 backups are kept, older ones are removed after a new backup has been verified. A start with nothing pending makes no backup. If the backup fails (for example not enough free disk space: the database size plus 64 MB is needed), a pending migration is **not run** and the container stops with a message in the log; the database is left untouched.

If the migration itself fails, the backup is restored automatically and the start is aborted. Darkstar never runs Alembic downgrades.

The old `planner_learning_*.db.bak` files in the data folder and the files in `/host_backups` (`./backups` on the host) came from the previous backup mechanism. They are no longer used or touched and you may delete them.

### Restoring a backup manually
Docker Compose (run in the folder with `docker-compose.yml`):
```bash
docker compose stop darkstar
docker compose run --rm --no-deps darkstar python -m backend.db_safety restore data/backups/<backup file>
docker compose up -d darkstar
```
Add-on: open a terminal in the add-on container and run `DB_PATH=/share/darkstar/planner_learning.db python -m backend.db_safety restore /share/darkstar/backups/<backup file>`, then restart the add-on.

The restore replaces the database file atomically and removes the old `-wal` and `-shm` files. Rows written after the backup are lost. If the previous version is not running afterwards, also go back to it (`git checkout` the previous tag or commit and `docker compose build darkstar`).

### Automatic rollback (Docker with the updater)
See **Updating Darkstar** above. The Home Assistant add-on has no automatic rollback of the version (Home Assistant owns add-on versions); it gets the backup and the automatic restore after a failed migration.

### First update that ships database safety
The updater that is already running has the old code and a read-only data mount, and an old updater cannot change itself. So the update that first ships this change is applied by the old updater:

- Protected: a failed build (old container untouched), a failed backup (migration not run), and a failed migration (the new container restores the backup).
- Not protected: the new container failing to start, or being unhealthy, after a successful migration. The old updater then reports that no automatic rollback was done; use the manual restore above with the newest file in `data/backups/`.

After that update, the card shows a hint to rebuild the updater once:
```bash
docker compose up -d --build updater
```
From then on rollback is active and the updater recreates itself automatically whenever it or `docker-compose.yml` changes.

### Retention and database size
A background task prunes old rows once a day (first check about 10 minutes after start) in small batches, then returns the freed space to the filesystem without pausing the executor. Settings in `config.yaml` (defaults in `config.default.yaml`); values below the minimum are raised to it, invalid values fall back to the default:

| Key | Default | Minimum if set | Data |
|-----|---------|----------------|------|
| `executor.history_retention_days` | 30 | 7 | Executor history (`execution_log`) |
| `learning.retention_days` | 0 (forever) | 400 | Slot observations, plans and forecasts |
| `learning.price_forecast_retention_days` | 0 (forever) | 400 | Price forecasts |
| `learning.learning_runs_retention_days` | 0 (forever) | 365 | Learning run history |
| `learning.s_index_history_retention_days` | 365 | 90 | S-Index calibration history |
| `learning.planner_debug_retention_days` | 14 | 1 | Planner debug payloads |
| `debug.plan_archive_retention_days` | 60 | 7 | Plan archive files (`data/plan_archive/`, not in the database) |

`0` means keep forever and is only accepted by the keys whose default is 0. The learning data grows by roughly 80 MB per year.

**One-time shrink.** On the first start with this version the database is backed up, old rows are pruned and the database is rebuilt once with incremental auto-vacuum, which can take from seconds to a few minutes and needs free disk space of about 1.2 times the used database size plus 64 MB (otherwise the rebuild is skipped with a warning and retried at the next start; the pruning stays). A large database (for example 800 MB) typically ends up around 230 MB.

---

## 🔎 Diagnostics bundle

`GET /api/system/diagnostics` (the diagnostics download on the Debug page) returns one zip meant to be attached to a bug report. It is redacted so it can be posted publicly, while keeping what is needed to debug the planner and executor.

**Removed or masked**
- Logs (`darkstar.log`, `darkstar.log.1`), `schedule.json` and the JSON outputs (version, status, health, monitors, balancer trace): URL credentials, paths and queries, `token=` style parameters and bearer values are removed; hosts that are not private, local or a known service (for example a `*.ui.nabu.casa` or DDNS name) become `<redacted-host>`; public IPv4 addresses become `<redacted-ip>`; numeric latitude/longitude values become `<redacted>` (`"<redacted>"` in JSON, so the files stay valid JSON).
- `config.yaml`: values of keys named like token, secret, password, api key, webhook, credential, authorization, bearer or private key (at any depth) become `<redacted>` when set; latitude and longitude are rounded to one decimal; URL strings follow the text rules above. Comments and key order are kept. `secrets.yaml` is never read.
- Database: `planner_learning.db` is always included as a consistent snapshot. In the copy only, secret-named keys inside the stored config versions are masked (a version that cannot be parsed is replaced by a placeholder). If masking fails the database is left out and `manifest.json` shows `error: could not mask config versions`; a raw copy is never used instead.
- If `config.yaml` cannot be parsed it is left out and `manifest.json` shows `error: could not redact config`; the raw file is never used instead.

**Kept as is**
- Entity ids, device names, tariffs and battery, inverter and solar parameters, price area, timezone, log levels, messages and timestamps.
- Private and local addresses and names, such as `http://192.168.0.100:8123` or `homeassistant`, and known public service hosts (Open-Meteo and similar).
- Everything in the database apart from the secret-named keys in stored config versions. Coordinates and other non-secret values in stored config versions are not rounded or masked.
- Free text you typed yourself is not redacted. Look through the files before posting if in doubt; `manifest.json` records `redacted: true` and the status of each item.

**Other downloads**
- `GET /api/system/logs` (log download) is redacted the same way as the logs in the bundle. The log file on disk is not changed.
- `GET /api/config/download` and `GET /api/system/db-snapshot` are raw backups and are not redacted. Do not post them publicly.

---

## ❓ Troubleshooting

### "Failed to fetch Home Assistant entity"
- Ensure your HA token hasn't expired.
- Check if your Home Assistant IP/URL has changed.
- Verify that the entity ID exists in HA.

### "No valid solar forecast"
- Check that your `latitude` and `longitude` are correct in `config.yaml`.
- Ensure the container has internet access to reach the Open-Meteo API.

### "Solver failed to find optimal solution"
- This usually happens when the battery constraints are impossible (e.g., `min_soc` > `max_soc`).
- Check your settings for logical errors in the battery section.

### Performance Hotspots / High CPU
If the system is experiencing performance degradation or CPU spikes, you can profile the running Python process inside the docker container using `py-spy`.
For detailed commands, see the **Live Profiling** section in [DEVELOPER.md](DEVELOPER.md#live-profiling-py-spy).

---

## ⚡ Controls and Overrides

While Darkstar is fully automated, you can manually intervene via the **Dashboard**:

- **Pause/Resume**: Stop the executor from sending commands to your inverter.
- **Water Boost**: Manually trigger high-temperature water heating.
- **Manual Charge/Export**: Force a specific battery action for a set duration.

---

## 📞 Support and Community
Darkstar is a community-driven project. If you find a bug or have a suggestion:
1. Check the [GitHub Issues](https://github.com/ergetie/darkstar/issues).
2. Start a discussion if you need help with your specific installation.
