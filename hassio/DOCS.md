# Darkstar Energy Manager

AI-powered home battery optimization for Home Assistant.

## Features

- **MILP Optimization**: Uses Kepler solver to minimize electricity costs
- **AURORA ML**: Machine learning forecasts for PV and load
- **Real-time Execution**: Native executor with override support
- **Beautiful Dashboard**: React-based UI with live updates

## Configuration

After installing, edit the configuration files in `/config/darkstar/`:

### config.yaml

Main configuration for your battery system, pricing, and scheduling parameters.
Copy from `config.default.yaml` and adjust for your setup.

### secrets.yaml

Sensitive credentials:

```yaml
home_assistant:
  url: "http://homeassistant.local:8123"
  token: "your-long-lived-access-token"

notifications:
  discord_webhook_url: ""  # Optional fallback
```

## Getting a Long-Lived Access Token

1. Go to your Home Assistant profile (click your name in sidebar)
2. Scroll to "Long-Lived Access Tokens"
3. Create a new token and copy it to `secrets.yaml`

## Support

- [GitHub Issues](https://github.com/ergetie/darkstar/issues)
- [Documentation](https://github.com/ergetie/darkstar#readme)
