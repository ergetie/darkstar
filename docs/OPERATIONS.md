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

An update is refused when tracked files were modified locally, or when the target does not contain your database's migration version (for example Dev to Stable). Downgrades are never automatic and there is no automatic backup.

**Opt-in setup.** The updater is a separate `updater` container that only starts when enabled. Without it nothing changes and you can keep updating manually. To enable it, add these values to a `.env` file next to `docker-compose.yml`, then rebuild once:
```bash
echo "DARKSTAR_UPDATER_TOKEN=$(openssl rand -hex 32)" >> .env
echo "DARKSTAR_REPO_DIR=$(pwd)" >> .env
echo "COMPOSE_PROFILES=updater" >> .env
git pull
docker compose up -d --build
```
Later changes to the updater itself are not applied from the UI (the card shows a hint); run `docker compose up -d --build updater` after pulling them.

**Security note.** The `updater` container mounts the Docker socket, which is root-equivalent on the host. It has no published port, only accepts requests carrying `DARKSTAR_UPDATER_TOKEN`, and only performs fixed operations (check, switch channel, update Darkstar). The Darkstar container itself never gets the socket. Keep `.env` private.

**Manual update** (also the fallback when the UI is unavailable):
```bash
git pull
docker compose build
docker compose up -d
```

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
