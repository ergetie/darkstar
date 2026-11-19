# Darkstar Energy Manager

AI-powered home battery optimization for Home Assistant.

Darkstar supports Sweden only (Nord Pool price areas SE1, SE2, SE3 and SE4). Other countries and price areas are not supported.

## Features

- **MILP Optimization**: Uses Kepler solver to minimize electricity costs
- **AURORA ML**: Machine learning forecasts for PV and load
- **Real-time Execution**: Native executor with override support
- **Beautiful Dashboard**: React-based UI with live updates

## First start

1. Install and start the add-on.
2. Click **Open Web UI**. The setup wizard walks you through the rest.

The add-on connects to Home Assistant automatically through the Supervisor, so you do not need to create an access token.

## Settings

Everything is configured in the web UI (the setup wizard first, then **Settings**). The add-on **Configuration** tab has two options:

- `timezone` (default `Europe/Stockholm`): applied to `config.yaml` at every start, so change it here and not in Settings.
- `log_level` (`debug`, `info`, `warning` or `error`).

Your price area is chosen in the setup wizard.

## Files

- `/config/darkstar/config.yaml`: your settings. Edit them in the web UI. If you edit the file by hand, restart the add-on afterwards.
- `/config/darkstar/secrets.yaml`: regenerated from the Supervisor token at every start. Do not edit it, because any change (including a Discord webhook) is lost on the next start.
- `/share/darkstar`: data, including the learning database.

## Dev add-on

Do not run **[DEV] Darkstar Energy Manager** and this add-on at the same time. They use the same host port (5000), the same configuration folder and the same data folder.

## Support

- [GitHub Issues](https://github.com/ergetie/darkstar/issues)
- [Documentation](https://github.com/ergetie/darkstar#readme)
