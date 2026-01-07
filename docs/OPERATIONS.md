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
To update to the latest version:
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
- Check `config.yaml` for logical errors in the `battery:` section.

---

## 📞 Support and Community
Darkstar is a community-driven project. If you find a bug or have a suggestion:
1. Check the [GitHub Issues](https://github.com/ergetie/darkstar/issues).
2. Start a discussion if you need help with your specific installation.
