## Purpose

Defines how execution history and the next-slot preview display mode badges in the Executor UI. Badges are derived from structured fields (`commanded_work_mode`, `ev_charging_kw`, `planned_water_kw`, `mode_intent`) rather than from inverter-specific strings.

## Requirements

### Requirement: Every execution record displays a primary mode badge

The Execution History SHALL display exactly one primary mode badge per record, derived from the record's `commanded_work_mode` field. The badge mapping SHALL be:

| `commanded_work_mode` | Emoji | Label |
|---|---|---|
| `charge` | ⚡ | Charge |
| `self_consumption` | 🔄 | Self-consumption |
| `idle` | ⏸️ | Idle |
| `export` | ↗️ | Export |

Each badge SHALL have a distinct color. If `commanded_work_mode` is null or unrecognized, no primary badge SHALL be shown.

#### Scenario: Self-consumption execution displays correct badge
- **WHEN** an execution record has `commanded_work_mode` = `"self_consumption"`
- **THEN** the record's summary row displays a badge with "🔄 Self-consumption"
- **AND THEN** no "— Idle" fallback badge is shown

#### Scenario: Idle execution displays correct badge
- **WHEN** an execution record has `commanded_work_mode` = `"idle"`
- **THEN** the record's summary row displays a badge with "⏸️ Idle"

#### Scenario: Export execution displays correct badge
- **WHEN** an execution record has `commanded_work_mode` = `"export"`
- **THEN** the record's summary row displays a badge with "↗️ Export"

#### Scenario: Legacy record with null mode
- **WHEN** an execution record has `commanded_work_mode` = `null`
- **THEN** no primary mode badge is displayed

### Requirement: Context badges display alongside primary mode badge

When water heating or EV charging is active, a context badge SHALL appear next to the primary mode badge.

- Water heating: shown when `planned_water_kw > 0`, displayed as "💧 Heating"
- EV charging: shown when `ev_charging_kw > 0`, displayed as "🔌 EV"
- EV keep-on standby: shown when `ev_charging_kw <= 0.1` but keep-on is active, displayed as "🔌 EV standby". For the next-slot preview, keep-on state SHALL be read from `current_slot_plan.ev_keep_on`; for execution-history rows (which have no structured flag), keep-on state SHALL be inferred from the record's reason text keep-on indication.

#### Scenario: Idle with EV charging shows both badges
- **WHEN** an execution record has `commanded_work_mode` = `"idle"` and `ev_charging_kw > 0`
- **THEN** the summary row displays "⏸️ Idle" and "🔌 EV" badges

#### Scenario: Self-consumption with water heating shows both badges
- **WHEN** an execution record has `commanded_work_mode` = `"self_consumption"` and `planned_water_kw > 0`
- **THEN** the summary row displays "🔄 Self-consumption" and "💧 Heating" badges

#### Scenario: Keep-on slot shows standby badge in next-slot preview
- **WHEN** the status API returns `current_slot_plan` with `ev_charging_kw` = 0 and `ev_keep_on` containing a true flag
- **THEN** the next-slot preview displays a "🔌 EV standby" badge instead of the "🔌 EV" badge

#### Scenario: History row for a keep-on tick shows standby badge
- **WHEN** an execution record has `ev_charging_kw` = 0 and its reason text contains the keep-on indication
- **THEN** the history row displays a "🔌 EV standby" badge

#### Scenario: Genuine charging still shows plain EV badge
- **WHEN** `ev_charging_kw > 0.1` for a slot, regardless of keep-on flags
- **THEN** the "🔌 EV" badge is displayed (not "EV standby")

### Requirement: Next-slot preview displays planned mode intent

The next-slot preview in the Executor status card SHALL display the mode intent badge for the upcoming slot, using the same badge mapping as the execution history.

#### Scenario: Next slot is self-consumption with discharge planned
- **WHEN** the current slot plan has `mode_intent` = `"self_consumption"`
- **THEN** the next-slot preview displays "🔄 Self-consumption" instead of "Idle / Self-consumption"

#### Scenario: Next slot is idle with no active actions
- **WHEN** the current slot plan has `mode_intent` = `"idle"` and no charge/export/water values
- **THEN** the next-slot preview displays "⏸️ Idle" instead of "Idle / Self-consumption"

#### Scenario: Next slot mode not available
- **WHEN** the status API returns `current_slot_plan` without a `mode_intent` field (e.g. controller could not run)
- **THEN** the next-slot preview falls back to showing planned value badges only (charge/export/water) without a mode badge

### Requirement: Legacy badge logic is removed

The hardcoded string `"Export First"` check, the `commanded_charge_current_a > 0` charge detection, and the catch-all "— Idle" fallback SHALL be removed from the execution history badge rendering.

#### Scenario: No legacy string checks remain
- **WHEN** the Executor page renders execution history badges
- **THEN** the badge logic does not reference `"Export First"` or any other inverter-specific mode string
- **AND THEN** badge selection is based solely on the `commanded_work_mode` field value
