# Creating Inverter Profiles (v2 Schema)

Darkstar uses a **profile-driven architecture** where each inverter profile defines an ordered list of entity+value actions. The executor is a generic loop that reads the profile and applies it — no hardcoded inverter-specific logic.

This guide explains how to create a new profile for your inverter and contribute it to the community.

---

## Quick Start (6-Step Guide)

1. **Find your Entities**: Identify Home Assistant entity IDs for your inverter (`select.inverter_work_mode`, `number.battery_max_charge_current`, etc.)
2. **Copy a Template**: Copy `profiles/generic.yaml` to `profiles/your_brand.yaml`
3. **Define Entity Registry**: List all entities with their HA domain (`select`, `number`, `switch`, `input_number`) and category (`system`, `battery`)
4. **Define 4 Modes**: Create action lists for `charge`, `export`, `idle`, and `self_consumption`
5. **Set Behavior**: Configure control unit (`A` for Amps or `W` for Watts), rounding, and settling delays
6. **Validate**: Run `uv run python scripts/validate_profiles.py profiles/your_brand.yaml`

---

## Profile Schema v2 Reference

A profile is a YAML file with `schema_version: 2` and four main sections:

```yaml
metadata:
  name: "your_brand"
  version: "2.0.0"
  schema_version: 2
  description: "Description of supported inverters"
  supported_brands:
    - "Brand A"
    - "Brand B"
  setup_notice:            # Optional, see "Setup Notice" below
    title: "Inverter setup"
    severity: info
    items:
      - "Enable Time of Use on the inverter."

entities:
  # Entity registry (see below)

modes:
  # Mode definitions (see below)

behavior:
  # Executor behavior parameters
```

### Setup Notice (optional)

`metadata.setup_notice` shows inverter-side setup steps in onboarding (profile step) and in **Settings -> System** whenever the profile is selected.

| Field | Type | Rules |
|-------|------|-------|
| `title` | string | Required, non-empty |
| `severity` | string | `info` or `warning` |
| `items` | list of strings | Required, non-empty; one plain-text line each (no markdown) |

Unknown keys, other severities or wrong types fail profile validation. Profiles without a notice show nothing. `GET /api/profiles` returns the notice as `setup_notice` (or `null`).

---

## 1. Entity Registry

The entity registry defines ALL Home Assistant entities your inverter profile uses. Each entry has:

| Property | Type | Description |
|----------|------|-------------|
| `default_entity` | string | Default HA entity ID (what most users will have) |
| `domain` | string | HA domain: `select`, `number`, `switch`, or `input_number` |
| `category` | string | Settings tab: `system` or `battery` |
| `description` | string | Human-readable text shown in Settings UI |
| `required` | bool | Whether Darkstar requires this entity to function |

### Valid Domains

| Domain | HA Service Called | Used For |
|--------|-------------------|----------|
| `select` | `select.select_option` | Mode selectors, dropdowns |
| `number` | `number.set_value` | Numeric sliders |
| `input_number` | `input_number.set_value` | HA input_number helpers |
| `switch` | `switch.turn_on/off` | On/off toggles |

### Valid Categories

| Category | Settings Tab | Example Entities |
|----------|-------------|------------------|
| `system` | System | `work_mode`, `grid_charging_enable` |
| `battery` | Battery | `max_charge_current`, `soc_target`, `max_discharge_power` |

### Example Entity Registry

```yaml
entities:
  work_mode:
    default_entity: "select.inverter_work_mode"
    domain: "select"
    category: "system"
    description: "Inverter operating mode selector"
    required: true

  grid_charging_enable:
    default_entity: "switch.grid_charging"
    domain: "switch"
    category: "system"
    description: "Grid charging on/off switch"
    required: true

  soc_target:
    default_entity: "number.battery_soc_target"
    domain: "number"
    category: "battery"
    description: "Battery SoC target percentage"
    required: true

  max_charge_current:
    default_entity: "number.battery_max_charge_current"
    domain: "number"
    category: "battery"
    description: "Maximum battery charging current (Amps)"
    required: true

  max_discharge_current:
    default_entity: "number.battery_max_discharge_current"
    domain: "number"
    category: "battery"
    description: "Maximum battery discharge current (Amps)"
    required: true
```

### Entity Resolution Order

When the executor needs an entity ID:

1. **User override** — Check `executor.inverter.custom_entities[key]` in config
2. **Standard config** — Check `executor.inverter[key]`
3. **Profile default** — Use `entities[key].default_entity`

---

## 2. Mode Definitions

Each mode contains an **ordered list of actions**. Actions execute **top-to-bottom**. This is critical for inverters that require mode changes before power writes.

### The 4 Required Modes

| Mode | Triggered When | Purpose |
|------|---------------|---------|
| `charge` | Planner schedules `charge_kw > 0` | Force charge battery from AC grid |
| `export` | Planner schedules `export_kw > 0` | Discharge battery to grid for profit |
| `idle` | SoC at/below target, no charge/export | Block discharge, preserve battery |
| `self_consumption` | All other cases | Normal PV→battery→house operation |

> [!IMPORTANT]
> All 4 modes are **required**. The executor will fail to load a profile missing any mode.

### Action Properties

| Property | Type | Required | Description |
|----------|------|----------|-------------|
| `entity` | string | ✅ | Key from entity registry |
| `value` | string/number/boolean | ✅ | Value to write (static or dynamic template) |
| `settle_ms` | integer | ❌ | Milliseconds to wait AFTER this action |

### Mode Definition Example

```yaml
modes:
  charge:
    description: "Grid charge — Force charge battery from AC grid"
    actions:
      - entity: "work_mode"
        value: "Zero Export To CT"
      - entity: "grid_charging_enable"
        value: true
      - entity: "max_charge_current"
        value: "{{charge_value}}"
      - entity: "soc_target"
        value: "{{soc_target}}"

  export:
    description: "Grid export — Discharge battery to grid for profit"
    actions:
      - entity: "work_mode"
        value: "Export First"
      - entity: "grid_charging_enable"
        value: false
      - entity: "max_discharge_current"
        value: "{{discharge_value}}"

  self_consumption:
    description: "Self consumption — PV to battery and house"
    actions:
      - entity: "work_mode"
        value: "Zero Export To CT"
      - entity: "grid_charging_enable"
        value: false
      - entity: "soc_target"
        value: "{{soc_target}}"

  idle:
    description: "Idle — Block discharge, preserve battery"
    actions:
      - entity: "work_mode"
        value: "Zero Export To CT"
      - entity: "grid_charging_enable"
        value: false
      - entity: "max_discharge_current"
        value: 0
      - entity: "soc_target"
        value: "{{soc_target}}"
```

### What Happens if an Entity is NOT in a Mode

**Nothing.** If `self_consumption` doesn't list `grid_charging_enable`, the switch is **not touched** during that mode.

> [!TIP]
> Each mode's action list must be a **complete recipe**. If entering `self_consumption` should turn off grid charging, explicitly include `grid_charging_enable: false`.

---

## 3. Dynamic Value Templates

Actions can use template strings resolved from the controller's decision at runtime:

| Template | Source | Description |
|----------|--------|-------------|
| `{{charge_value}}` | Planned charge current/power | Calculated from `slot.charge_kw` |
| `{{discharge_value}}` | Planned discharge current/power | Calculated from `slot.export_kw` |
| `{{soc_target}}` | Battery SoC target % | From slot plan |
| `{{export_power_w}}` | Export power limit (W) | From slot plan |
| `{{max_charge}}` | User's max charge limit | From battery config |
| `{{max_discharge}}` | User's max discharge limit | From battery config |

### Example: Using Templates

```yaml
actions:
  - entity: "max_charge_current"
    value: "{{charge_value}}"     # Resolves to controller's calculated charge value
  - entity: "soc_target"
    value: "{{soc_target}}"       # Resolves to planned SoC target
```

---

## 4. Behavior Section

The behavior section defines executor-level parameters:

```yaml
behavior:
  control_unit: "A"              # "A" (Amps) or "W" (Watts)
  min_charge_a: 1.0              # Minimum charge command (Amps mode)
  min_charge_w: 10.0             # Minimum charge command (Watts mode)
  round_step_a: 1.0              # Rounding step for current (Amps)
  round_step_w: 100.0            # Rounding step for power (Watts)
  grid_charge_round_step_w: null # Optional: different rounding for grid charge
  write_threshold_w: 100.0       # Min delta before writing new value
  mode_settling_ms: 100          # Default delay after mode changes
  requires_mode_settling: false  # Whether mode changes need settling
```

---

## Settle Delays (Fronius and Similar)

Some inverters need a delay after mode changes before writing power values. Use `settle_ms` on individual actions:

```yaml
modes:
  charge:
    description: "Grid charge with mode settling"
    actions:
      - entity: "work_mode"
        value: "Charge from Grid"
        settle_ms: 500          # Wait 500ms after this action
      - entity: "grid_charge_power"
        value: "{{charge_value}}"
```

---

## Advanced: Multi-Entity Modes (Sungrow Pattern)

Some inverters require multiple entity changes for a single logical mode. Simply list all actions:

```yaml
modes:
  charge:
    description: "Force charge — Sungrow requires EMS mode + command"
    actions:
      - entity: "work_mode"
        value: "Forced mode"
      - entity: "forced_charge_discharge_cmd"
        value: "Forced charge"
      - entity: "max_charge_power"
        value: "{{charge_value}}"
      - entity: "max_discharge_power"
        value: "{{max_discharge}}"
```

---

## Entity Discovery Guide

To find correct entity IDs:

1. Open Home Assistant
2. Go to **Developer Tools** → **States**
3. Filter by your inverter integration (e.g., "sungrow", "fronius", "modbus")
4. Look for:
   - **Select** entities: "Work Mode", "EMS Mode", "Storage Mode"
   - **Number** entities: "Max Charge Current", "Max Charge Power", "SoC Target"
   - **Switch** entities: "Grid Charge Enable"

> [!TIP]
> Always check the **raw state value** in the "State" column. This is the exact string you must use in your mode's `value` field.

---

## Testing & Validation

### Validate Schema

```bash
uv run python scripts/validate_profiles.py profiles/your_brand.yaml
```

### Test in Shadow Mode

Enable shadow mode in Darkstar config to log actions without writing to your inverter:

```yaml
executor:
  shadow_mode: true
```

### Run Test Suite

```bash
uv run python -m pytest tests/test_profiles_v2.py -v
```

---

## Complete Example: Deye/SunSynk Profile

```yaml
# ============================================================
# Inverter Profile: Deye / SunSynk
# Schema Version: 2
# ============================================================

metadata:
  name: "deye"
  version: "2.0.0"
  schema_version: 2
  description: "Deye and SunSynk hybrid inverters using Amps-based control"
  supported_brands:
    - "Deye"
    - "SunSynk"
    - "Sol-Ark"

entities:
  work_mode:
    default_entity: "select.inverter_work_mode"
    domain: "select"
    category: "system"
    description: "Inverter work mode selector"
    required: true

  grid_charging_enable:
    default_entity: "switch.inverter_battery_grid_charging"
    domain: "switch"
    category: "system"
    description: "Grid charging on/off switch"
    required: true

  soc_target:
    # Time of Use program 6 SoC: active all day when all six program times are 00:00
    default_entity: "number.inverter_program_6_soc"
    domain: "number"
    category: "battery"
    description: "Battery SoC target percentage"
    required: true

  max_charge_current:
    default_entity: "number.inverter_battery_max_charge_current"
    domain: "number"
    category: "battery"
    description: "Maximum battery charging current (Amps)"
    required: true

  max_discharge_current:
    default_entity: "number.inverter_battery_max_discharge_current"
    domain: "number"
    category: "battery"
    description: "Maximum battery discharge current (Amps)"
    required: true

modes:
  charge:
    description: "Grid charge — Force charge battery from AC grid"
    actions:
      - entity: "work_mode"
        value: "Zero Export To CT"
      - entity: "grid_charging_enable"
        value: true
      - entity: "max_charge_current"
        value: "{{charge_value}}"
      - entity: "soc_target"
        value: "{{soc_target}}"

  export:
    description: "Grid export — Discharge battery to grid"
    actions:
      - entity: "work_mode"
        value: "Export First"
      - entity: "grid_charging_enable"
        value: false
      - entity: "max_discharge_current"
        value: "{{discharge_value}}"

  self_consumption:
    description: "Self consumption — PV to battery and house"
    actions:
      - entity: "work_mode"
        value: "Zero Export To CT"
      - entity: "grid_charging_enable"
        value: false
      - entity: "soc_target"
        value: "{{soc_target}}"

  idle:
    description: "Idle — Block discharge, preserve battery"
    actions:
      - entity: "work_mode"
        value: "Zero Export To CT"
      - entity: "grid_charging_enable"
        value: false
      - entity: "max_discharge_current"
        value: 0
      - entity: "soc_target"
        value: "{{soc_target}}"

behavior:
  control_unit: "A"
  min_charge_a: 1.0
  round_step_a: 1.0
  mode_settling_ms: 100
```

---

## Submission Guidelines

1. Ensure profile name matches filename (e.g., `sungrow.yaml` → `name: "sungrow"`)
2. Set `schema_version: 2`
3. Include all 4 required modes
4. Test with `scripts/validate_profiles.py`
5. Submit a Pull Request to `profiles/` directory
6. Note which hardware/integration you tested with

---

## Migration from v1 Profiles

If you have a v1 profile, you'll need to:

1. Set `schema_version: 2`
2. Convert `capabilities` → `behavior` section
3. Convert `entities` flat list → `entities` registry with `domain`/`category`/`description`
4. Convert `modes` with `value`/`set_entities` → `modes` with ordered `actions` list
5. Remove `zero_export` and `charge_from_grid` modes — use only `charge`, `export`, `idle`, `self_consumption`

See `docs/inverter-profiles/profiles_v2_blueprint.md` for complete migration details.
