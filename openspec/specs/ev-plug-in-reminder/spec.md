# ev-plug-in-reminder Specification

## Purpose
Optionally notify the user a configurable time before scheduled EV charging when the charger is not plugged in, so planned charging is not missed.
## Requirements
### Requirement: Optional plug-in reminder before planned charging
Each EV charger config SHALL support an optional `plug_in_reminder_minutes` (integer minutes; absent, null or 0 disables the reminder). When enabled, the executor SHALL send one notification through the existing executor notification channel when the charger's first upcoming slot with planned EV charging (> 0.1 kW) starts within `plug_in_reminder_minutes` and the charger's live plug state is not connected. The notification SHALL name the charger and the planned start time.

#### Scenario: Car not plugged in 30 minutes before planned charging
- **WHEN** `plug_in_reminder_minutes: 30`, charging is planned from 22:00, the time is 21:30 and the charger is unplugged
- **THEN** a notification such as "Go-e: charging planned at 22:00 but the car isn't plugged in" SHALL be sent

#### Scenario: Car already plugged in
- **WHEN** the reminder window is reached and the charger is plugged in
- **THEN** no notification SHALL be sent

#### Scenario: Reminder disabled
- **WHEN** `plug_in_reminder_minutes` is absent or 0
- **THEN** no reminder SHALL ever be sent for that charger

### Requirement: Plug-in reminder is sent at most once per charging window
The reminder SHALL be deduplicated per charger and planned charging window (keyed by the window's start time), so repeated executor ticks do not resend it. Plugging the charger in SHALL reset the dedupe for that charger; a later, different planned window MAY produce a new reminder.

#### Scenario: Repeated ticks inside the window
- **WHEN** the executor ticks every minute from 21:30 to 22:00 with the car unplugged
- **THEN** exactly one reminder SHALL be sent for the 22:00 window

#### Scenario: Plan moves to a new window
- **WHEN** a reminder was sent for 22:00, a replan moves charging to 02:00, and the car is still unplugged at 01:30
- **THEN** one new reminder SHALL be sent for the 02:00 window

### Requirement: Plug-in reminder lead time is configurable in settings
The charger settings editor SHALL expose `plug_in_reminder_minutes` with quick choices Off, 15 and 30 minutes and a custom value, and `config.default.yaml` SHALL document the key with the reminder disabled by default.

#### Scenario: User enables a 15-minute reminder
- **WHEN** the user selects 15 minutes for a charger and saves
- **THEN** that charger's config SHALL persist `plug_in_reminder_minutes: 15`
