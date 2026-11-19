# Spec: Log Secret Scrubbing

## Purpose
Keep secrets embedded in URLs and tokens out of logs and diagnostics bundles.

## Requirements

### Requirement: Exception text is scrubbed
Described exceptions SHALL have URLs reduced so that path, query, fragment and credentials are removed, Discord webhook URLs fully redacted, and token-like parameters and bearer headers masked. Host-only URLs SHALL remain intact.

#### Scenario: Webhook URL
- **WHEN** an exception message contains `https://discord.com/api/webhooks/123/SECRET`
- **THEN** the described text contains `https://discord.com/api/webhooks/<redacted>` and not `SECRET`

#### Scenario: Query token
- **WHEN** a message contains `https://ha.local:8123/api/x?access_token=abc`
- **THEN** neither `abc` nor the query appears

#### Scenario: Host-only URL preserved
- **WHEN** a message contains `http://homeassistant.local:8123`
- **THEN** it is unchanged

### Requirement: Webhook failures log no message text
A failed Discord webhook post SHALL log only the exception class name and HTTP status.

#### Scenario: HTTP error
- **WHEN** the webhook returns 404
- **THEN** the log line is "Discord notification failed: HTTPError status=404" and contains no URL
