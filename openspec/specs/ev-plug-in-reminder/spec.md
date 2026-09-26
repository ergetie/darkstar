# ev-plug-in-reminder Specification

## Purpose
Optionally notify the user a configurable time before scheduled EV charging when the charger is not plugged in, so planned charging is not missed.
## Requirements
### Requirement: Optional plug-in reminder before planned charging
The plug-in reminder SHALL be a global notification setting: `executor.notifications.on_ev_plug_in_reminder` (boolean, default false) turns it on for every EV charger, and `executor.notifications.ev_plug_in_reminder_minutes` (integer minutes, 1-1440, default 30) sets the lead time. Chargers SHALL NOT carry a per-charger reminder setting. When enabled, the executor SHALL send one notification through the existing executor notification channel when a charger's first upcoming slot with planned EV charging (> 0.1 kW) starts within `ev_plug_in_reminder_minutes` and the charger's live plug state is not connected. The notification SHALL name the charger and the planned start time. An invalid or out-of-range lead time SHALL fall back to the default (logged).

#### Scenario: Car not plugged in 30 minutes before planned charging
- **WHEN** `on_ev_plug_in_reminder: true`, `ev_plug_in_reminder_minutes: 30`, charging is planned from 22:00, the time is 21:30 and the charger is unplugged
- **THEN** a notification such as "Go-e: charging planned at 22:00 but the car isn't plugged in" SHALL be sent

#### Scenario: Car already plugged in
- **WHEN** the reminder window is reached and the charger is plugged in
- **THEN** no notification SHALL be sent

#### Scenario: Reminder disabled
- **WHEN** `on_ev_plug_in_reminder` is absent or false
- **THEN** no reminder SHALL ever be sent for any charger

#### Scenario: One lead time for every charger
- **WHEN** the reminder is on with `ev_plug_in_reminder_minutes: 15` and two unplugged chargers have planned charging
- **THEN** each charger SHALL be reminded 15 minutes before its own planned start

### Requirement: Plug-in reminder is sent at most once per charging window
The reminder SHALL be deduplicated per charger and planned charging window (keyed by the window's start time), so repeated executor ticks do not resend it. Plugging the charger in SHALL reset the dedupe for that charger; a later, different planned window MAY produce a new reminder.

#### Scenario: Repeated ticks inside the window
- **WHEN** the executor ticks every minute from 21:30 to 22:00 with the car unplugged
- **THEN** exactly one reminder SHALL be sent for the 22:00 window

#### Scenario: Plan moves to a new window
- **WHEN** a reminder was sent for 22:00, a replan moves charging to 02:00, and the car is still unplugged at 01:30
- **THEN** one new reminder SHALL be sent for the 02:00 window

### Requirement: Plug-in reminder lead time is configurable in settings
The UI tab's Notifications section SHALL expose the reminder alongside the other `executor.notifications.on_*` toggles: an on/off toggle for `on_ev_plug_in_reminder` and, shown while it is on, the lead time `ev_plug_in_reminder_minutes` with quick choices 15 and 30 minutes and a custom value. The EV charger editor SHALL NOT show a reminder field. The Executor page's notification toggle list SHALL include the reminder toggle, and the notifications API SHALL return both keys. `config.default.yaml` SHALL document both keys with the reminder off by default. Config validation SHALL reject a lead time that is not an integer from 1 to 1440 with an error naming the key.

#### Scenario: User enables a 15-minute reminder
- **WHEN** the user turns on the plug-in reminder in UI → Notifications, selects 15 minutes and saves
- **THEN** the config SHALL persist `executor.notifications.on_ev_plug_in_reminder: true` and `ev_plug_in_reminder_minutes: 15`

#### Scenario: Custom lead time
- **WHEN** the stored lead time is 45
- **THEN** the lead-time control SHALL show "Custom…" with 45 in the number input

#### Scenario: Out-of-range lead time rejected
- **WHEN** the user saves `ev_plug_in_reminder_minutes: 0`
- **THEN** validation SHALL reject it with an error naming `executor.notifications.ev_plug_in_reminder_minutes`

### Requirement: Per-charger reminder settings migrate to the global setting
On startup the config migration SHALL convert any `ev_chargers[].plug_in_reminder_minutes` to the global setting, writing a timestamped backup before the config is written. If any charger had a value greater than 0, it SHALL set `executor.notifications.on_ev_plug_in_reminder: true` and `ev_plug_in_reminder_minutes` to the largest such value. The per-charger keys SHALL always be removed. The migration SHALL be idempotent: a config without per-charger keys SHALL be left unchanged.

#### Scenario: Two chargers with reminders
- **WHEN** the config has chargers with `plug_in_reminder_minutes` 15 and 45
- **THEN** after migration the reminder SHALL be on with a 45-minute lead time and neither charger SHALL carry the key

#### Scenario: Only disabled values
- **WHEN** every charger has `plug_in_reminder_minutes: 0`
- **THEN** the keys SHALL be removed and the reminder SHALL stay off

#### Scenario: Second run
- **WHEN** the migration runs again on the migrated config
- **THEN** nothing SHALL change and no write SHALL be triggered by this migration
