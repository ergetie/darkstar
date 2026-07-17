## MODIFIED Requirements

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
