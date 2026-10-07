# Darkstar telemetry receiver

This standalone service accepts the minimal daily installation heartbeat and serves aggregate statistics. It runs separately from Darkstar, uses its own SQLite database, and is not included in the Darkstar application containers. The public `POST /api/ping` route has no login so installations can report; `/` and `/api/stats` require HTTP Basic authentication. The application refuses to start unless the summary credentials are set.

The receiver stores only a UUIDv4 installation ID, version, release channel, installation type, architecture, inverter profile, executor mode (`shadow`, `live`, or `unknown`), and receiver-assigned last-seen time. It removes installation rows more than 60 days old. Daily aggregate snapshots contain no IDs and are retained indefinitely. Darkstar does not send energy measurements, location, entity names, secrets, or detailed configuration. Cloudflare Tunnel handles request metadata under the operator's Cloudflare settings; this service does not retain client IP addresses or forwarded headers.

## Ubuntu 24.04 LXC setup

Use a dedicated Ubuntu 24.04 LXC with outbound network access. Install Python 3.12, Git, and the system packages needed to create a virtual environment. Keep the LXC on the private network. Do not forward port 8765 from the public Internet.

The receiver is self-contained; the LXC does not need the full Darkstar checkout. From your workstation, copy only this `telemetry_receiver/` directory to the LXC, then place it under `/opt/darkstar/telemetry_receiver`:

```sh
# On the LXC
sudo install -d -o root -g root -m 0755 /opt/darkstar

# On your workstation; replace the SSH user and LXC address
scp -r telemetry_receiver <ssh-user>@<LXC_LAN_IP>:/tmp/

# Back on the LXC
sudo install -d -o root -g root -m 0755 /opt/darkstar/telemetry_receiver
sudo cp -a /tmp/telemetry_receiver/. /opt/darkstar/telemetry_receiver/
sudo chown -R root:root /opt/darkstar/telemetry_receiver
```

Then create a dedicated account and writable database directory:

```sh
sudo useradd --system --create-home --home-dir /var/lib/darkstar-telemetry \
  --shell /usr/sbin/nologin darkstar-telemetry
sudo install -d -o darkstar-telemetry -g darkstar-telemetry -m 0750 \
  /var/lib/darkstar-telemetry
sudo python3.12 -m venv /opt/darkstar/.venv-telemetry
sudo /opt/darkstar/.venv-telemetry/bin/pip install \
  -r /opt/darkstar/telemetry_receiver/requirements.txt
```

Create `/etc/darkstar-telemetry.env` as `root:root` with mode `0600`. If the file already exists, keep it: `touch` below preserves its contents. Use long, unique credentials. These example values are placeholders; replace them before starting the service:

```sh
sudo touch /etc/darkstar-telemetry.env
sudo chown root:root /etc/darkstar-telemetry.env
sudo chmod 0600 /etc/darkstar-telemetry.env
sudo editor /etc/darkstar-telemetry.env
```

```ini
TELEMETRY_HOST=127.0.0.1
TELEMETRY_PORT=8765
TELEMETRY_DB_PATH=/var/lib/darkstar-telemetry/telemetry.sqlite3
TELEMETRY_STATS_USERNAME=replace-with-a-private-username
TELEMETRY_STATS_PASSWORD=replace-with-a-long-random-password
```

The default listener is loopback for a tunnel connector running in the same LXC. When the existing Cloudflare Tunnel connector runs on another trusted machine, set `TELEMETRY_HOST` to the LXC's private LAN address (for example, `192.168.0.10`) so the connector can reach it. Keep `TELEMETRY_PORT=8765`, and restrict the LXC firewall to accept that port only from the connector's private address. Never bind to a public interface or expose this port through router port forwarding.

Install and start the supplied single-worker unit:

```sh
sudo install -o root -g root -m 0644 \
  /opt/darkstar/telemetry_receiver/darkstar-telemetry.service \
  /etc/systemd/system/darkstar-telemetry.service
sudo systemctl daemon-reload
sudo systemctl enable --now darkstar-telemetry.service
sudo systemctl status darkstar-telemetry.service
```

The unit runs one Uvicorn process with access logging disabled, restarts on failure, and grants write access only to the receiver state directory. Check service startup errors with `sudo journalctl -u darkstar-telemetry.service`; application logs omit request bodies, IP addresses, and credentials.

## Cloudflare Tunnel routing

In the existing Cloudflare Tunnel, add the public hostname `telemetry.wxl.se` and route it to the receiver's private listener, for example `http://<LXC_LAN_IP>:8765` when the connector is on another machine. If the connector runs in this LXC, route to `http://127.0.0.1:8765` instead. Use HTTPS on the public hostname.

Do not apply Cloudflare Access login, a browser challenge, or another authentication gate to `POST /api/ping`; Darkstar installations need to reach it without an interactive login. Keep `/` and `/api/stats` protected by the receiver's HTTP Basic authentication over public HTTPS. The application sets `Cache-Control: no-store` on those read routes. Cloudflare still processes traffic metadata according to the account's configuration.

## Local checks

After starting the service, check the listener from the LXC. Enter the address configured as `TELEMETRY_HOST` at the prompt; use `127.0.0.1` for a same-LXC tunnel connector, or the LXC's private LAN address for a remote connector. An unauthenticated summary request should return `401`. Replace the sample username with `TELEMETRY_STATS_USERNAME`; curl prompts for the password rather than placing it in shell history:

```sh
read -rp 'Listener address (TELEMETRY_HOST): ' listener_host
curl -i "http://$listener_host:8765/"
curl --user 'replace-with-a-private-username' -i "http://$listener_host:8765/api/stats"
```

For a valid ingestion smoke check, send the current seven-field JSON contract to the same listener's `/api/ping` route from the LXC and expect `204 No Content`. The receiver also accepts the legacy six-field payload and records its executor mode as `unknown`. Use a disposable UUIDv4; a ping updates that test ID's row and it will be removed after 60 days without another report. For example:

```sh
curl -i "http://$listener_host:8765/api/ping" \
  -H 'Content-Type: application/json' \
  --data '{"installation_id":"0b7d8f32-a953-4e7e-8c1a-4442a8fbaf13","version":"receiver-smoke-test","release_channel":"unknown","installation_type":"unknown","architecture":"unknown","inverter_profile":"unknown","execution_mode":"unknown"}'
```

Repeat the authenticated stats request and confirm the test row appears only in aggregate counts. Do not use a real installation ID for the smoke check.

## Storage, backups, and retention

The default database is `/var/lib/darkstar-telemetry/telemetry.sqlite3`; set `TELEMETRY_DB_PATH` if it needs to live elsewhere. Back up the SQLite database regularly and protect backups as pseudonymous operational data. Use SQLite's online backup command while the service is running (install the `sqlite3` CLI if needed):

```sh
sudo -u darkstar-telemetry sh -c \
  'umask 077; sqlite3 /var/lib/darkstar-telemetry/telemetry.sqlite3 ".backup /var/lib/darkstar-telemetry/telemetry-backup.sqlite3"'
```

The receiver keeps the latest metadata for each installation ID while it has reported in the last 60 days. It keeps daily aggregate snapshots indefinitely; days when the service was unavailable remain gaps. Restrict backup access and include the database in the LXC's normal backup plan.

## Release communication and rollout

### Upgrade an existing receiver

Upgrade the receiver before releasing a sender that includes executor mode. Back up the SQLite database first, then stop the service and replace the receiver source using the same workstation-to-LXC copy steps above:

```sh
# On the LXC
sudo systemctl stop darkstar-telemetry.service

# On your workstation
scp -r telemetry_receiver <ssh-user>@<LXC_LAN_IP>:/tmp/

# Back on the LXC
sudo cp -a /tmp/telemetry_receiver/. /opt/darkstar/telemetry_receiver/
sudo chown -R root:root /opt/darkstar/telemetry_receiver
sudo systemctl start darkstar-telemetry.service
sudo systemctl status darkstar-telemetry.service
```

Keep `/etc/darkstar-telemetry.env` and the existing database at the configured `TELEMETRY_DB_PATH`; do not initialize a replacement database. Startup applies an idempotent additive migration: existing installation rows receive mode `unknown`, and prior daily snapshots retain their stored totals and metadata while their new mode breakdown is set to `unknown` for the snapshot's recorded totals. Repeating startup does not change those historic counts. Verify an authenticated `/api/stats` request succeeds before deploying the sender update.

The sender's default endpoint is `https://telemetry.wxl.se/api/ping`; reporting is enabled by default for new installations and upgrades that have no saved choice. Existing explicit opt-outs remain disabled. Users can disable reporting in **Settings → System → Installation statistics** or set `installation_stats.enabled: false` in their configuration. The onboarding final review also exposes the choice for new installations.

Suggested release note or maintainer announcement: “Darkstar sends one daily installation heartbeat containing a random installation ID, app version, release channel, installation type, CPU architecture, inverter profile, and executor mode (shadow, live, or unknown). Reporting is enabled by default. Turn it off in Settings → System → Installation statistics, or set `installation_stats.enabled: false`. Energy data, entity names, credentials, and detailed configuration are not sent.”
