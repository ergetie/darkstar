import { useEffect, useState } from 'react'
import Card from '../components/Card'
import AzimuthDial from '../components/AzimuthDial'
import TiltDial from '../components/TiltDial'
import EntitySelect from '../components/EntitySelect'
import { Api, ThemeInfo } from '../lib/api'
import { cls } from '../theme'
import { Sparkles } from 'lucide-react'

const tabs = [
    { id: 'system', label: 'System' },
    { id: 'parameters', label: 'Parameters' },
    { id: 'ui', label: 'UI' },
    { id: 'advanced', label: 'Advanced' },
]

type SystemField = {
    key: string
    label: string
    helper?: string
    path: string[]
    type: 'number' | 'text' | 'boolean' | 'entity'
}

type ParameterField = {
    key: string
    label: string
    helper?: string
    path: string[]
    type: 'number' | 'text' | 'boolean' | 'select' | 'array'
    options?: { label: string; value: string }[]
}

const systemSections = [
    {
        title: 'System Profile',
        description: 'Core hardware toggles and high-level system preferences.',
        fields: [
            { key: 'system.has_solar', label: 'Solar panels installed', helper: 'Enable PV forecasting and solar optimization', path: ['system', 'has_solar'], type: 'boolean' },
            { key: 'system.has_battery', label: 'Home battery installed', helper: 'Enable battery control and grid arbitrage', path: ['system', 'has_battery'], type: 'boolean' },
            { key: 'system.has_water_heater', label: 'Smart water heater', helper: 'Enable water heating optimization', path: ['system', 'has_water_heater'], type: 'boolean' },
            { key: 'export.enable_export', label: 'Enable grid export', helper: '[EXPERIMENTAL] Master switch for grid export', path: ['export', 'enable_export'], type: 'boolean' },
        ],
    },
    {
        title: 'Location & Solar Array',
        description: 'Geolocation and PV array parameters used by the forecasting engine.',
        fields: [
            { key: 'system.location.latitude', label: 'Latitude', helper: 'Decimal degrees, positive north. Example: 55.4932', path: ['system', 'location', 'latitude'], type: 'number' },
            { key: 'system.location.longitude', label: 'Longitude', helper: 'Decimal degrees, positive east. Example: 13.1112', path: ['system', 'location', 'longitude'], type: 'number' },
            { key: 'system.solar_array.azimuth', label: 'Solar azimuth (°)', helper: 'Panel direction: 0° = North, 90° = East, 180° = South, 270° = West.', path: ['system', 'solar_array', 'azimuth'], type: 'number' },
            { key: 'system.solar_array.tilt', label: 'Solar tilt (°)', helper: 'Angle from horizontal. 0° = flat, 90° = vertical.', path: ['system', 'solar_array', 'tilt'], type: 'number' },
            { key: 'system.solar_array.kwp', label: 'Solar capacity (kWp)', helper: 'Total DC peak power of the PV array.', path: ['system', 'solar_array', 'kwp'], type: 'number' },
        ],
    },
    {
        title: 'Battery Specifications',
        description: 'Capacity, max power, and SoC limits define safe operating bands.',
        fields: [
            { key: 'battery.capacity_kwh', label: 'Battery capacity (kWh)', path: ['battery', 'capacity_kwh'], type: 'number' },
            { key: 'battery.max_charge_power_kw', label: 'Max charge power (kW)', path: ['battery', 'max_charge_power_kw'], type: 'number' },
            { key: 'battery.max_discharge_power_kw', label: 'Max discharge power (kW)', path: ['battery', 'max_discharge_power_kw'], type: 'number' },
            { key: 'battery.min_soc_percent', label: 'Min SoC (%)', path: ['battery', 'min_soc_percent'], type: 'number' },
            { key: 'battery.max_soc_percent', label: 'Max SoC (%)', path: ['battery', 'max_soc_percent'], type: 'number' },
            { key: 'system.grid.max_power_kw', label: 'HARD Grid max power (kW)', helper: 'Absolute limit from your grid fuse/connection.', path: ['system', 'grid', 'max_power_kw'], type: 'number' },
            { key: 'grid.import_limit_kw', label: 'Soft import limit (kW)', helper: 'Threshold for peak power penalties (effekttariff).', path: ['grid', 'import_limit_kw'], type: 'number' },
        ],
    },
    {
        title: 'Pricing & Timezone',
        description: 'Nordpool zone and local timezone for planner calculations.',
        fields: [
            { key: 'nordpool.price_area', label: 'Nordpool Price Area', helper: 'e.g. SE4, NO1, DK2', path: ['nordpool', 'price_area'], type: 'text' },
            { key: 'pricing.vat_percent', label: 'VAT (%)', path: ['pricing', 'vat_percent'], type: 'number' },
            { key: 'pricing.grid_transfer_fee_sek', label: 'Grid transfer fee (SEK/kWh)', path: ['pricing', 'grid_transfer_fee_sek'], type: 'number' },
            { key: 'pricing.energy_tax_sek', label: 'Energy tax (SEK/kWh)', path: ['pricing', 'energy_tax_sek'], type: 'number' },
            { key: 'timezone', label: 'Timezone', helper: 'e.g. Europe/Stockholm', path: ['timezone'], type: 'text' },
        ],
    },
    {
        title: 'Notifications',
        description: 'Configure automated notifications via Home Assistant.',
        fields: [
            { key: 'executor.notifications.service', label: 'HA Notify Service', helper: 'e.g. notify.mobile_app_iphone', path: ['executor', 'notifications', 'service'], type: 'text' },
            { key: 'executor.notifications.on_charge_start', label: 'On charge start', path: ['executor', 'notifications', 'on_charge_start'], type: 'boolean' },
            { key: 'executor.notifications.on_discharge_start', label: 'On discharge start', path: ['executor', 'notifications', 'on_discharge_start'], type: 'boolean' },
            { key: 'executor.notifications.on_soc_target_change', label: 'On SoC target change', path: ['executor', 'notifications', 'on_soc_target_change'], type: 'boolean' },
            { key: 'executor.notifications.on_water_heating_start', label: 'On water heating start', path: ['executor', 'notifications', 'on_water_heating_start'], type: 'boolean' },
        ],
    },
    {
        title: '── Home Assistant Connection ──',
        isHA: true,
        description: 'Connection parameters for your Home Assistant instance.',
        fields: [
            { key: 'home_assistant.url', label: 'HA URL', helper: 'e.g. http://homeassistant.local:8123', path: ['home_assistant', 'url'], type: 'text' },
            { key: 'home_assistant.token', label: 'Long-Lived Access Token', path: ['home_assistant', 'token'], type: 'text' },
        ],
    },
    {
        title: 'Required HA Entities',
        isHA: true,
        description: 'Core sensors and switches required for battery control.',
        fields: [
            { key: 'input_sensors.battery_soc', label: 'Battery SoC (%)', path: ['input_sensors', 'battery_soc'], type: 'entity' },
            { key: 'input_sensors.pv_power', label: 'PV Power (W/kW)', path: ['input_sensors', 'pv_power'], type: 'entity' },
            { key: 'input_sensors.load_power', label: 'Load Power (W/kW)', path: ['input_sensors', 'load_power'], type: 'entity' },
            { key: 'executor.inverter.work_mode_entity', label: 'Work Mode Selector', path: ['executor', 'inverter', 'work_mode_entity'], type: 'entity' },
            { key: 'executor.inverter.grid_charging_entity', label: 'Grid Charging Switch', path: ['executor', 'inverter', 'grid_charging_entity'], type: 'entity' },
            { key: 'executor.inverter.max_charging_current_entity', label: 'Max Charge Current', path: ['executor', 'inverter', 'max_charging_current_entity'], type: 'entity' },
            { key: 'executor.inverter.max_discharging_current_entity', label: 'Max Discharge Current', path: ['executor', 'inverter', 'max_discharging_current_entity'], type: 'entity' },
        ],
    },
    {
        title: 'Optional HA Entities',
        isHA: true,
        description: 'Optional sensors for better forecasting and dashboard metrics.',
        fields: [
            { key: 'executor.automation_toggle_entity', label: 'Automation Toggle', path: ['executor', 'automation_toggle_entity'], type: 'entity' },
            { key: 'executor.manual_override_entity', label: 'Manual Override Toggle', path: ['executor', 'manual_override_entity'], type: 'entity' },
            { key: 'executor.soc_target_entity', label: 'Target SoC Feedback', path: ['executor', 'soc_target_entity'], type: 'entity' },
            { key: 'executor.water_heater.target_entity', label: 'Water Heater Setpoint', path: ['executor', 'water_heater', 'target_entity'], type: 'entity' },
            { key: 'input_sensors.vacation_mode', label: 'Vacation Mode Toggle', path: ['input_sensors', 'vacation_mode'], type: 'entity' },
            { key: 'input_sensors.alarm_state', label: 'Alarm Control Panel', path: ['input_sensors', 'alarm_state'], type: 'entity' },
            { key: 'input_sensors.water_heater_consumption', label: 'Water Heater Daily Energy', path: ['input_sensors', 'water_heater_consumption'], type: 'entity' },
            { key: 'input_sensors.today_net_cost', label: 'Today\'s Net Cost', path: ['input_sensors', 'today_net_cost'], type: 'entity' },
            { key: 'input_sensors.total_battery_charge', label: 'Total Battery Charge (kWh)', path: ['input_sensors', 'total_battery_charge'], type: 'entity' },
            { key: 'input_sensors.total_battery_discharge', label: 'Total Battery Discharge (kWh)', path: ['input_sensors', 'total_battery_discharge'], type: 'entity' },
            { key: 'input_sensors.total_grid_export', label: 'Total Grid Export (kWh)', path: ['input_sensors.total_grid_export'], type: 'entity' },
            { key: 'input_sensors.total_grid_import', label: 'Total Grid Import (kWh)', path: ['input_sensors.total_grid_import'], type: 'entity' },
            { key: 'input_sensors.total_load_consumption', label: 'Total Load Consumption (kWh)', path: ['input_sensors.total_load_consumption'], type: 'entity' },
            { key: 'input_sensors.total_pv_production', label: 'Total PV Production (kWh)', path: ['input_sensors.total_pv_production'], type: 'entity' },
        ],
    },
]

const parameterSections = [
    {
        title: 'Charging Strategy',
        description: 'Price smoothing, consolidation tolerances, and gap settings that govern charge windows.',
        fields: [
            { key: 'charging_strategy.price_smoothing_sek_kwh', label: 'Price smoothing (SEK/kWh)', path: ['charging_strategy', 'price_smoothing_sek_kwh'], type: 'number' },
            { key: 'charging_strategy.block_consolidation_tolerance_sek', label: 'Consolidation tolerance (SEK)', path: ['charging_strategy', 'block_consolidation_tolerance_sek'], type: 'number' },
            { key: 'charging_strategy.consolidation_max_gap_slots', label: 'Max gap slots', path: ['charging_strategy', 'consolidation_max_gap_slots'], type: 'number' },
            { key: 'charging_strategy.charge_threshold_percentile', label: 'Charge threshold (percentile)', path: ['charging_strategy', 'charge_threshold_percentile'], type: 'number' },
            { key: 'charging_strategy.cheap_price_tolerance_sek', label: 'Cheap price tolerance (SEK)', path: ['charging_strategy', 'cheap_price_tolerance_sek'], type: 'number' },
        ],
    },
    {
        title: 'Arbitrage & Export',
        description: 'Export thresholds, peak-only export, and future guard buffers.',
        fields: [
            { key: 'arbitrage.export_percentile_threshold', label: 'Export percentile threshold', path: ['arbitrage', 'export_percentile_threshold'], type: 'number' },
            { key: 'arbitrage.enable_peak_only_export', label: 'Enable peak-only export', path: ['arbitrage', 'enable_peak_only_export'], type: 'boolean', helper: 'Override to only export when we hit the percentile threshold.' },
            { key: 'arbitrage.export_future_price_guard', label: 'Future price guard', path: ['arbitrage', 'export_future_price_guard'], type: 'boolean' },
            { key: 'arbitrage.future_price_guard_buffer_sek', label: 'Future guard buffer (SEK)', path: ['arbitrage', 'future_price_guard_buffer_sek'], type: 'number' },
            { key: 'arbitrage.export_profit_margin_sek', label: 'Export profit margin (SEK)', path: ['arbitrage', 'export_profit_margin_sek'], type: 'number' },
        ],
    },
    {
        title: 'Water Heating',
        description: 'Quota, deferral, and sizing controls for the water heater scheduler.',
        fields: [
            { key: 'water_heating.power_kw', label: 'Water heater power (kW)', path: ['water_heating', 'power_kw'], type: 'number' },
            { key: 'water_heating.defer_up_to_hours', label: 'Max defer hours', path: ['water_heating', 'defer_up_to_hours'], type: 'number' },
            { key: 'water_heating.max_blocks_per_day', label: 'Max blocks per day', path: ['water_heating', 'max_blocks_per_day'], type: 'number' },
            { key: 'water_heating.min_kwh_per_day', label: 'Min kWh/day', path: ['water_heating', 'min_kwh_per_day'], type: 'number' },
            { key: 'water_heating.min_spacing_hours', label: 'Min spacing (hours)', path: ['water_heating', 'min_spacing_hours'], type: 'number', helper: 'Minimum gap between heating sessions to avoid efficiency loss.' },
            { key: 'water_heating.spacing_penalty_sek', label: 'Spacing penalty (SEK)', path: ['water_heating', 'spacing_penalty_sek'], type: 'number', helper: 'Penalty applied when heating sessions are too close.' },
            { key: 'water_heating.schedule_future_only', label: 'Schedule future only', path: ['water_heating', 'schedule_future_only'], type: 'boolean' },
        ],
    },
    {
        title: 'Learning Parameter Limits',
        description: 'Limits that keep learning adjustments conservative.',
        fields: [
            { key: 'learning.min_sample_threshold', label: 'Min sample threshold', path: ['learning', 'min_sample_threshold'], type: 'number' },
            { key: 'learning.min_improvement_threshold', label: 'Min improvement (%)', path: ['learning', 'min_improvement_threshold'], type: 'number' },
            { key: 'learning.max_daily_param_change.battery_use_margin_sek', label: 'Battery margin change (SEK)', path: ['learning', 'max_daily_param_change', 'battery_use_margin_sek'], type: 'number' },
            { key: 'learning.max_daily_param_change.export_profit_margin_sek', label: 'Export margin change (SEK)', path: ['learning', 'max_daily_param_change', 'export_profit_margin_sek'], type: 'number' },
            { key: 'learning.max_daily_param_change.future_price_guard_buffer_sek', label: 'Future guard buffer change (SEK)', path: ['learning', 'max_daily_param_change', 'future_price_guard_buffer_sek'], type: 'number' },
            { key: 'learning.max_daily_param_change.load_safety_margin_percent', label: 'Load safety change (%)', path: ['learning', 'max_daily_param_change', 'load_safety_margin_percent'], type: 'number' },
            { key: 'learning.max_daily_param_change.pv_confidence_percent', label: 'PV confidence change (%)', path: ['learning', 'max_daily_param_change', 'pv_confidence_percent'], type: 'number' },
            { key: 'learning.max_daily_param_change.s_index_base_factor', label: 'S-index base change', path: ['learning', 'max_daily_param_change', 's_index_base_factor'], type: 'number' },
            { key: 'learning.max_daily_param_change.s_index_pv_deficit_weight', label: 'S-index PV weight change', path: ['learning', 'max_daily_param_change', 's_index_pv_deficit_weight'], type: 'number' },
            { key: 'learning.max_daily_param_change.s_index_temp_weight', label: 'S-index temp weight change', path: ['learning', 'max_daily_param_change', 's_index_temp_weight'], type: 'number' },
        ],
    },
    {
        title: 'S-Index Safety',
        description: 'Base/max factors, weights, and time horizon shaping the S-index guard.',
        fields: [
            { key: 's_index.mode', label: 'Mode', path: ['s_index', 'mode'], type: 'select', options: [{ label: 'Static', value: 'static' }, { label: 'Dynamic', value: 'dynamic' }] },
            { key: 's_index.base_factor', label: 'Base factor', path: ['s_index', 'base_factor'], type: 'number' },
            { key: 's_index.max_factor', label: 'Max factor', path: ['s_index', 'max_factor'], type: 'number' },
            { key: 's_index.static_factor', label: 'Static fallback factor', path: ['s_index', 'static_factor'], type: 'number' },
            { key: 's_index.pv_deficit_weight', label: 'PV deficit weight', path: ['s_index', 'pv_deficit_weight'], type: 'number' },
            { key: 's_index.temp_weight', label: 'Temp weight', path: ['s_index', 'temp_weight'], type: 'number' },
            { key: 's_index.temp_baseline_c', label: 'Temp baseline (°C)', path: ['s_index', 'temp_baseline_c'], type: 'number' },
            { key: 's_index.temp_cold_c', label: 'Cold temp (°C)', path: ['s_index', 'temp_cold_c'], type: 'number' },
            { key: 's_index.days_ahead_for_sindex', label: 'Days ahead (comma list)', path: ['s_index', 'days_ahead_for_sindex'], type: 'array', helper: 'Comma-separated integers (e.g. 2,3,4).', },
        ],
    },
]

const systemFieldList: SystemField[] = systemSections.flatMap((section) => section.fields)
const systemFieldMap: Record<string, SystemField> = systemFieldList.reduce((acc, field) => {
    acc[field.key] = field
    return acc
}, {} as Record<string, SystemField>)

const parameterFieldList: ParameterField[] = parameterSections.flatMap((section) => section.fields)
const parameterFieldMap: Record<string, ParameterField> = parameterFieldList.reduce((acc, field) => {
    acc[field.key] = field
    return acc
}, {} as Record<string, ParameterField>)

type UIField = {
    key: string
    label: string
    helper?: string
    path: string[]
    type: 'text' | 'boolean' | 'select'
    options?: { label: string; value: string }[]
}

const uiSections = [
    {
        title: 'Dashboard Defaults',
        description: 'Overlay defaults and refresh cadence for the planner dashboard.',
        fields: [
            {
                key: 'dashboard.auto_refresh_enabled',
                label: 'Auto refresh',
                helper: 'Enable automatic refresh of the dashboard schedule.',
                path: ['dashboard', 'auto_refresh_enabled'],
                type: 'boolean',
            },
        ],
    },
    {
        title: 'AI Advisor',
        description: 'Control the Smart Advisor LLM settings.',
        fields: [
            {
                key: 'advisor.enable_llm',
                label: 'Enable LLM advice',
                path: ['advisor', 'enable_llm'],
                type: 'boolean',
            },
            {
                key: 'advisor.auto_fetch',
                label: 'Auto-fetch advice on dashboard load',
                path: ['advisor', 'auto_fetch'],
                type: 'boolean',
            },
            {
                key: 'advisor.personality',
                label: 'Advisor personality',
                path: ['advisor', 'personality'],
                type: 'select',
                options: [
                    { label: 'Concise (Money focus)', value: 'concise' },
                    { label: 'Friendly (Emoji style)', value: 'friendly' },
                    { label: 'Technical (Data heavy)', value: 'technical' },
                ],
            },
        ],
    },
]

type AdvancedField = {
    key: string
    label: string
    helper?: string
    path: string[]
    type: 'boolean'
}

const advancedSections = [
    {
        title: 'Experimental Features',
        description: 'Toggle advanced and experimental modes.',
        fields: [
            {
                key: 'automation.external_executor_mode',
                label: 'External Executor Mode',
                helper: 'When enabled, Darkstar expects an external system to execute the plan.',
                path: ['automation', 'external_executor_mode'],
                type: 'boolean',
            },
            {
                key: 'automation.write_to_mariadb',
                label: 'Log to MariaDB',
                helper: 'Requires MariaDB credentials in secrets.yaml',
                path: ['automation', 'write_to_mariadb'],
                type: 'boolean',
            },
        ],
    },
    {
        title: 'Danger Zone',
        description: 'Sensitive actions. Proceed with caution.',
        fields: [], // Handled specially in render
    },
]

const uiFieldList: UIField[] = uiSections.flatMap((section) => section.fields)
const uiFieldMap: Record<string, UIField> = uiFieldList.reduce((acc, field) => {
    acc[field.key] = field
    return acc
}, {} as Record<string, UIField>)

const advancedFieldList: AdvancedField[] = advancedSections.flatMap((section) => section.fields)
const advancedFieldMap: Record<string, AdvancedField> = advancedFieldList.reduce((acc, field) => {
    acc[field.key] = field
    return acc
}, {} as Record<string, AdvancedField>)

function getDeepValue(source: any, path: string[]): any {
    return path.reduce((current, key) => (current && typeof current === 'object' ? current[key] : undefined), source)
}

function setDeepValue(target: Record<string, any>, path: string[], value: any) {
    let cursor: Record<string, any> = target
    path.forEach((key, index) => {
        if (index === path.length - 1) {
            cursor[key] = value
            return
        }
        if (!cursor[key] || typeof cursor[key] !== 'object') {
            cursor[key] = {}
        }
        cursor = cursor[key]
    })
}

function buildSystemFormState(config: Record<string, any> | null): Record<string, string> {
    const state: Record<string, string> = {}
    systemFieldList.forEach((field) => {
        const value = config ? getDeepValue(config, field.path) : undefined
        if (field.type === 'boolean') {
            state[field.key] = value === true ? 'true' : 'false'
        } else {
            state[field.key] = value !== undefined && value !== null ? String(value) : ''
        }
    })
    return state
}

function buildParameterFormState(config: Record<string, any> | null): Record<string, string> {
    const state: Record<string, string> = {}
    parameterFieldList.forEach((field) => {
        const value = config ? getDeepValue(config, field.path) : undefined
        if (field.type === 'boolean') {
            state[field.key] = value === true ? 'true' : 'false'
        } else if (field.type === 'array' && Array.isArray(value)) {
            state[field.key] = value.join(', ')
        } else {
            state[field.key] = value !== undefined && value !== null ? String(value) : ''
        }
    })
    return state
}

function parseFieldInput(field: SystemField, raw: string): number | string | boolean | null | undefined {
    const trimmed = raw.trim()
    if (field.type === 'number') {
        if (trimmed === '') return null
        const parsed = Number(trimmed)
        return Number.isNaN(parsed) ? undefined : parsed
    }
    if (field.type === 'boolean') {
        return trimmed === 'true'
    }
    return trimmed
}

function parseParameterFieldInput(field: ParameterField, raw: string): any {
    const trimmed = raw.trim()
    if (field.type === 'number') {
        if (trimmed === '') return null
        const parsed = Number(trimmed)
        return Number.isNaN(parsed) ? undefined : parsed
    }
    if (field.type === 'boolean') {
        return trimmed === 'true'
    }
    if (field.type === 'array') {
        if (!trimmed) return []
        const parts = trimmed.split(',').map((part) => part.trim()).filter(Boolean)
        const parsed = parts.map((value) => Number(value)).filter((value) => !Number.isNaN(value))
        return parsed
    }
    return trimmed
}

function buildSystemPatch(original: Record<string, any>, form: Record<string, string>): Record<string, any> {
    const patch: Record<string, any> = {}
    systemFieldList.forEach((field) => {
        const raw = form[field.key] ?? ''
        const parsed = parseFieldInput(field, raw)
        if (parsed === undefined) return
        if (field.type === 'number' && parsed === null) return
        const currentValue = getDeepValue(original, field.path)
        if (parsed === currentValue) return
        setDeepValue(patch, field.path, parsed)
    })
    return patch
}

function buildParameterPatch(original: Record<string, any>, form: Record<string, string>): Record<string, any> {
    const patch: Record<string, any> = {}
    parameterFieldList.forEach((field) => {
        const raw = form[field.key] ?? ''
        const parsed = parseParameterFieldInput(field, raw)
        if (parsed === undefined) return
        const currentValue = getDeepValue(original, field.path)
        const equal = (() => {
            if (field.type === 'array') {
                if (!Array.isArray(parsed)) return false
                if (!Array.isArray(currentValue)) return false
                if (parsed.length !== currentValue.length) return false
                for (let i = 0; i < parsed.length; i += 1) {
                    if (parsed[i] !== currentValue[i]) return false
                }
                return true
            }
            return parsed === currentValue
        })()
        if (equal) return
        setDeepValue(patch, field.path, parsed)
    })
    return patch
}

function buildUIFormState(config: Record<string, any> | null): Record<string, string> {
    const state: Record<string, string> = {}
    uiFieldList.forEach((field) => {
        const value = config ? getDeepValue(config, field.path) : undefined
        if (field.type === 'boolean') {
            state[field.key] = value === true ? 'true' : 'false'
        } else {
            state[field.key] = value !== undefined && value !== null ? String(value) : ''
        }
    })
    // Manual mapping for overlay_defaults which is not in uiFieldList
    if (config?.dashboard?.overlay_defaults !== undefined) {
        state['dashboard.overlay_defaults'] = String(config.dashboard.overlay_defaults)
    }
    return state
}

function buildAdvancedFormState(config: Record<string, any> | null): Record<string, string> {
    const state: Record<string, string> = {}
    advancedFieldList.forEach((field) => {
        const value = config ? getDeepValue(config, field.path) : undefined
        if (field.type === 'boolean') {
            state[field.key] = value === true ? 'true' : 'false'
        } else {
            state[field.key] = value !== undefined && value !== null ? String(value) : ''
        }
    })
    return state
}

function parseUIFieldInput(field: UIField, raw: string): string | boolean | null | undefined {
    const trimmed = raw.trim()
    if (field.type === 'boolean') {
        if (trimmed === '') return null
        if (trimmed === 'true') return true
        if (trimmed === 'false') return false
        return undefined
    }
    return trimmed
}

function parseAdvancedFieldInput(field: AdvancedField, raw: string): string | boolean | null | undefined {
    const trimmed = raw.trim()
    if (field.type === 'boolean') {
        if (trimmed === '') return null
        if (trimmed === 'true') return true
        if (trimmed === 'false') return false
        return undefined
    }
    return trimmed
}

function buildUIPatch(original: Record<string, any>, form: Record<string, string>): Record<string, any> {
    const patch: Record<string, any> = {}
    uiFieldList.forEach((field) => {
        const raw = form[field.key] ?? ''
        const parsed = parseUIFieldInput(field, raw)
        if (parsed === undefined) return
        if (field.type === 'boolean' && parsed === null) return
        const currentValue = getDeepValue(original, field.path)
        if (parsed === currentValue) return
        setDeepValue(patch, field.path, parsed)
    })
    // Handle overlay defaults separately
    const overlayDefaults = form['dashboard.overlay_defaults']
    if (overlayDefaults !== undefined) {
        const currentOverlayDefaults = getDeepValue(original, ['dashboard', 'overlay_defaults'])
        if (overlayDefaults !== currentOverlayDefaults) {
            if (!patch.dashboard) patch.dashboard = {}
            patch.dashboard.overlay_defaults = overlayDefaults
        }
    }
    return patch
}

function buildAdvancedPatch(original: Record<string, any>, form: Record<string, string>): Record<string, any> {
    const patch: Record<string, any> = {}
    advancedFieldList.forEach((field) => {
        const raw = form[field.key] ?? ''
        const parsed = parseAdvancedFieldInput(field, raw)
        if (parsed === undefined) return
        if (field.type === 'boolean' && parsed === null) return
        const currentValue = getDeepValue(original, field.path)
        if (parsed === currentValue) return
        setDeepValue(patch, field.path, parsed)
    })
    return patch
}

export default function Settings() {
    const [activeTab, setActiveTab] = useState('system')
    const [config, setConfig] = useState<Record<string, any> | null>(null)
    const [systemForm, setSystemForm] = useState<Record<string, string>>(() => buildSystemFormState(null))
    const [parameterForm, setParameterForm] = useState<Record<string, string>>(() => buildParameterFormState(null))
    const [uiForm, setUIForm] = useState<Record<string, string>>(() => buildUIFormState(null))
    const [advancedForm, setAdvancedForm] = useState<Record<string, string>>(() => buildAdvancedFormState(null))
    const [systemFieldErrors, setSystemFieldErrors] = useState<Record<string, string>>({})
    const [parameterFieldErrors, setParameterFieldErrors] = useState<Record<string, string>>({})
    const [uiFieldErrors, setUIFieldErrors] = useState<Record<string, string>>({})
    const [advancedFieldErrors, setAdvancedFieldErrors] = useState<Record<string, string>>({})
    const [loadingConfig, setLoadingConfig] = useState(true)
    const [loadError, setLoadError] = useState<string | null>(null)
    const [systemSaving, setSystemSaving] = useState(false)
    const [parameterSaving, setParameterSaving] = useState(false)
    const [uiSaving, setUISaving] = useState(false)
    const [advancedSaving, setAdvancedSaving] = useState(false)
    const [systemStatusMessage, setSystemStatusMessage] = useState<string | null>(null)
    const [parameterStatusMessage, setParameterStatusMessage] = useState<string | null>(null)
    const [uiStatusMessage, setUIStatusMessage] = useState<string | null>(null)
    const [advancedStatusMessage, setAdvancedStatusMessage] = useState<string | null>(null)
    const [themes, setThemes] = useState<ThemeInfo[]>([])
    const [selectedTheme, setSelectedTheme] = useState<string | null>(null)
    const [themeAccentIndex, setThemeAccentIndex] = useState<number | null>(null)
    const [themeLoading, setThemeLoading] = useState(true)
    const [themeError, setThemeError] = useState<string | null>(null)
    const [themeApplying, setThemeApplying] = useState(false)
    const [themeStatusMessage, setThemeStatusMessage] = useState<string | null>(null)
    const [resetting, setResetting] = useState(false)
    const [resetConfirmOpen, setResetConfirmOpen] = useState(false)
    const [resetStatusMessage, setResetStatusMessage] = useState<string | null>(null)
    const [haEntities, setHaEntities] = useState<{ entity_id: string; friendly_name: string; domain: string }[]>([])
    const [haLoading, setHaLoading] = useState(false)
    const [haTestStatus, setHaTestStatus] = useState<string | null>(null)

    const reloadEntities = async () => {
        setHaLoading(true)
        try {
            const data = await Api.haEntities()
            setHaEntities(data.entities || [])
        } catch (e) {
            console.error('Failed to load HA entities', e)
        } finally {
            setHaLoading(false)
        }
    }

    const handleTestConnection = async () => {
        setHaTestStatus('Testing...')
        try {
            const url = systemForm['home_assistant.url']
            const token = systemForm['home_assistant.token']
            const data = await Api.haTest({ url, token })

            if (data.success) {
                setHaTestStatus('Success: Connected!')
                reloadEntities()
            } else {
                setHaTestStatus(`Error: ${data.message}`)
            }
        } catch (e: any) {
            setHaTestStatus(`Error: ${e.message}`)
        }
    }

    const reloadConfig = async () => {
        setLoadingConfig(true)
        setLoadError(null)
        try {
            const cfg = await Api.config()
            setConfig(cfg)
            setSystemForm(buildSystemFormState(cfg))
            setParameterForm(buildParameterFormState(cfg))
            setUIForm(buildUIFormState(cfg))
            setAdvancedForm(buildAdvancedFormState(cfg))
            const accent = cfg?.ui?.theme_accent_index
            setThemeAccentIndex(typeof accent === 'number' ? accent : null)
        } catch (err: any) {
            setLoadError(err?.message || 'Failed to load configuration')
        } finally {
            setLoadingConfig(false)
        }
    }

    const reloadThemes = async () => {
        setThemeLoading(true)
        setThemeError(null)
        try {
            const themeData = await Api.theme()
            setThemes(themeData.themes)
            setSelectedTheme(themeData.current ?? null)
            setThemeAccentIndex(themeData.accent_index ?? null)
        } catch (err: any) {
            setThemeError(err?.message || 'Failed to load themes')
        } finally {
            setThemeLoading(false)
        }
    }

    useEffect(() => {
        reloadConfig()
        reloadThemes()
        reloadEntities()
    }, [])

    const handleFieldChange = (key: string, value: string) => {
        const field = systemFieldMap[key]
        if (!field) return
        setSystemForm((prev) => ({ ...prev, [key]: value }))
        setSystemStatusMessage(null)
        if (field.type === 'number') {
            const trimmed = value.trim()
            setSystemFieldErrors((prev) => {
                const next = { ...prev }
                if (trimmed === '') {
                    next[key] = 'Required'
                } else if (Number.isNaN(Number(trimmed))) {
                    next[key] = 'Must be a number'
                } else if (key.includes('percent') && (Number(trimmed) < 0 || Number(trimmed) > 100)) {
                    next[key] = 'Must be between 0 and 100'
                } else if (key.includes('power_kw') && Number(trimmed) < 0) {
                    next[key] = 'Must be positive'
                } else if (key.includes('capacity_kwh') && Number(trimmed) <= 0) {
                    next[key] = 'Must be greater than 0'
                } else if (key === 'nordpool.resolution_minutes' && ![15, 30, 60].includes(Number(trimmed))) {
                    next[key] = 'Must be 15, 30, or 60'
                } else {
                    delete next[key]
                }

                // Cross-field check for SoC min/max
                const minKey = 'battery.min_soc_percent'
                const maxKey = 'battery.max_soc_percent'
                const minRaw = key === minKey ? trimmed : (systemForm[minKey] ?? '').trim()
                const maxRaw = key === maxKey ? trimmed : (systemForm[maxKey] ?? '').trim()
                const minVal = Number(minRaw)
                const maxVal = Number(maxRaw)
                if (!Number.isNaN(minVal) && !Number.isNaN(maxVal)) {
                    if (minVal >= maxVal) {
                        next[minKey] = 'Min SoC must be less than max SoC'
                        next[maxKey] = 'Max SoC must be greater than min SoC'
                    } else {
                        if (next[minKey] && next[minKey].startsWith('Min SoC')) {
                            delete next[minKey]
                        }
                        if (next[maxKey] && next[maxKey].startsWith('Max SoC')) {
                            delete next[maxKey]
                        }
                    }
                }

                return next
            })
        }
    }

    const handleParameterFieldChange = (key: string, value: string) => {
        const field = parameterFieldMap[key]
        if (!field) return
        setParameterForm((prev) => ({ ...prev, [key]: value }))
        setParameterStatusMessage(null)
        if (field.type === 'number') {
            const trimmed = value.trim()
            setParameterFieldErrors((prev) => {
                const next = { ...prev }
                if (trimmed === '') {
                    next[key] = 'Required'
                } else if (Number.isNaN(Number(trimmed))) {
                    next[key] = 'Must be a number'
                } else if (key.includes('percent') && (Number(trimmed) < 0 || Number(trimmed) > 100)) {
                    next[key] = 'Must be between 0 and 100'
                } else if (key.includes('sek') && Number(trimmed) < 0) {
                    next[key] = 'Must be positive'
                } else if (key.includes('power_kw') && Number(trimmed) < 0) {
                    next[key] = 'Must be positive'
                } else if (key.includes('kwh') && Number(trimmed) <= 0) {
                    next[key] = 'Must be greater than 0'
                } else {
                    delete next[key]
                }
                return next
            })
        }
    }

    const handleUIFieldChange = (key: string, value: string) => {
        const field = uiFieldMap[key]
        if (!field && key !== 'dashboard.overlay_defaults') return
        setUIForm((prev) => ({ ...prev, [key]: value }))
        setUIStatusMessage(null)

        // Handle overlay defaults separately
        if (key === 'dashboard.overlay_defaults') {
            // No validation needed for overlay defaults
            return
        }

        if (field.type === 'boolean') {
            const trimmed = value.trim()
            setUIFieldErrors((prev) => {
                const next = { ...prev }
                if (trimmed === '') {
                    next[key] = 'Required'
                } else if (trimmed !== 'true' && trimmed !== 'false') {
                    next[key] = 'Invalid value'
                } else {
                    delete next[key]
                }
                return next
            })
        }
    }

    const handleAdvancedFieldChange = (key: string, value: string) => {
        const field = advancedFieldMap[key]
        if (!field) return

        setAdvancedForm((prev) => ({ ...prev, [key]: value }))
        setAdvancedStatusMessage(null)

        if (field.type === 'boolean') {
            const val = value.trim()
            setAdvancedFieldErrors((prev) => {
                const newErrors = { ...prev }
                if (val === '') {
                    newErrors[key] = 'Required'
                } else if (val !== 'true' && val !== 'false') {
                    newErrors[key] = 'Invalid value'
                } else {
                    delete newErrors[key]
                }
                return newErrors
            })
        }
    }

    const systemErrors = Object.values(systemFieldErrors).filter(Boolean).length
    const hasSystemValidationErrors = systemErrors > 0

    const parameterErrors = Object.values(parameterFieldErrors).filter(Boolean).length
    const hasParameterValidationErrors = parameterErrors > 0

    const uiErrors = Object.values(uiFieldErrors).filter(Boolean).length
    const hasUIValidationErrors = uiErrors > 0

    const handleSaveSystem = async () => {
        if (!config) return
        if (hasSystemValidationErrors) {
            setSystemStatusMessage('Fix validation errors before saving.')
            return
        }
        const patch = buildSystemPatch(config, systemForm)
        if (!Object.keys(patch).length) {
            setSystemStatusMessage('No changes detected.')
            return
        }
        setSystemSaving(true)
        setSystemStatusMessage(null)
        try {
            const resp = await Api.configSave(patch)
            if (resp.status !== 'success') {
                const fieldErrors: Record<string, string> = {}
                resp.errors?.forEach((err) => {
                    if (err.field) {
                        fieldErrors[err.field] = err.message || 'Invalid value'
                    }
                })
                if (Object.keys(fieldErrors).length) {
                    setSystemFieldErrors((prev) => ({ ...prev, ...fieldErrors }))
                    setSystemStatusMessage('Fix highlighted fields before saving.')
                } else {
                    setSystemStatusMessage(
                        resp.errors && resp.errors[0]?.message
                            ? resp.errors[0].message
                            : 'Save failed.',
                    )
                }
                return
            }
            const fresh = await Api.config()
            setConfig(fresh)
            setSystemForm(buildSystemFormState(fresh))
            setParameterForm(buildParameterFormState(fresh))
            setSystemFieldErrors({})
            setSystemStatusMessage('System settings saved.')
        } catch (err: any) {
            setSystemStatusMessage(err?.message ? `Failed to save: ${err.message}` : 'Save failed.')
        } finally {
            setSystemSaving(false)
        }
    }

    const handleSaveParameters = async () => {
        if (!config) return
        if (hasParameterValidationErrors) {
            setParameterStatusMessage('Fix validation errors before saving.')
            return
        }
        const patch = buildParameterPatch(config, parameterForm)
        if (!Object.keys(patch).length) {
            setParameterStatusMessage('No changes detected.')
            return
        }
        setParameterSaving(true)
        setParameterStatusMessage(null)
        try {
            const resp = await Api.configSave(patch)
            if (resp.status !== 'success') {
                const fieldErrors: Record<string, string> = {}
                resp.errors?.forEach((err) => {
                    if (err.field) {
                        fieldErrors[err.field] = err.message || 'Invalid value'
                    }
                })
                if (Object.keys(fieldErrors).length) {
                    setParameterFieldErrors((prev) => ({ ...prev, ...fieldErrors }))
                    setParameterStatusMessage('Fix highlighted fields before saving.')
                } else {
                    setParameterStatusMessage(
                        resp.errors && resp.errors[0]?.message
                            ? resp.errors[0].message
                            : 'Save failed.',
                    )
                }
                return
            }
            const fresh = await Api.config()
            setConfig(fresh)
            setSystemForm(buildSystemFormState(fresh))
            setParameterForm(buildParameterFormState(fresh))
            setParameterFieldErrors({})
            setParameterStatusMessage('Parameters saved.')
        } catch (err: any) {
            setParameterStatusMessage(err?.message ? `Failed to save: ${err.message}` : 'Save failed.')
        } finally {
            setParameterSaving(false)
        }
    }

    const handleSaveUI = async () => {
        if (!config) return

        const hasErrors = Object.values(uiFieldErrors).filter(Boolean).length > 0
        if (hasErrors) {
            setUIStatusMessage('Fix validation errors before saving.')
            return
        }

        const patch = buildUIPatch(config, uiForm)
        if (!Object.keys(patch).length) {
            setUIStatusMessage('No changes detected.')
            return
        }

        setUISaving(true)
        setUIStatusMessage(null)
        try {
            const result = await Api.configSave(patch)
            if (result.status !== 'success') {
                const newErrors: Record<string, string> = {}
                result.errors?.forEach((err) => {
                    if (err.field) {
                        newErrors[err.field] = err.message || 'Invalid value'
                    }
                })
                if (Object.keys(newErrors).length) {
                    setUIFieldErrors((prev) => ({ ...prev, ...newErrors }))
                    setUIStatusMessage('Fix highlighted fields before saving.')
                } else {
                    setUIStatusMessage(result.errors && result.errors[0]?.message ? result.errors[0].message : 'Save failed.')
                }
                return
            }
            const data = await Api.config()
            setConfig(data)
            setUIForm(buildUIFormState(data))
            setUIFieldErrors({})
            setUIStatusMessage('UI preferences saved.')
        } catch (err) {
            setUIStatusMessage(err instanceof Error ? `Failed to save: ${err.message}` : 'Save failed.')
        } finally {
            setUISaving(false)
        }
    }

    const handleSaveAdvanced = async () => {
        if (!config) return

        const hasErrors = Object.values(advancedFieldErrors).filter(Boolean).length > 0
        if (hasErrors) {
            setAdvancedStatusMessage('Fix validation errors before saving.')
            return
        }

        const patch = buildAdvancedPatch(config, advancedForm)
        if (!Object.keys(patch).length) {
            setAdvancedStatusMessage('No changes detected.')
            return
        }

        setAdvancedSaving(true)
        setAdvancedStatusMessage(null)
        try {
            const result = await Api.configSave(patch)
            if (result.status !== 'success') {
                const newErrors: Record<string, string> = {}
                result.errors?.forEach((err) => {
                    if (err.field) {
                        newErrors[err.field] = err.message || 'Invalid value'
                    }
                })
                if (Object.keys(newErrors).length) {
                    setAdvancedFieldErrors((prev) => ({ ...prev, ...newErrors }))
                    setAdvancedStatusMessage('Fix highlighted fields before saving.')
                } else {
                    setAdvancedStatusMessage(result.errors && result.errors[0]?.message ? result.errors[0].message : 'Save failed.')
                }
                return
            }
            const data = await Api.config()
            setConfig(data)
            setAdvancedForm(buildAdvancedFormState(data))
            setAdvancedFieldErrors({})
            setAdvancedStatusMessage('Advanced settings saved.')
        } catch (err) {
            setAdvancedStatusMessage(err instanceof Error ? `Failed to save: ${err.message}` : 'Save failed.')
        } finally {
            setAdvancedSaving(false)
        }
    }



    const handleApplyTheme = async () => {
        if (!selectedTheme) {
            setThemeStatusMessage('Select a theme before applying.')
            return
        }
        setThemeApplying(true)
        setThemeStatusMessage(null)
        try {
            await Api.setTheme({
                theme: selectedTheme,
                accent_index: themeAccentIndex ?? undefined,
            })
            await reloadThemes()
            await reloadConfig()
            setThemeStatusMessage('Theme applied successfully.')
        } catch (err: any) {
            setThemeStatusMessage(err?.message ? `Failed to apply theme: ${err.message}` : 'Failed to apply theme.')
        } finally {
            setThemeApplying(false)
        }
    }

    const handleAccentChange = (value: string) => {
        const trimmed = value.trim()
        if (trimmed === '') {
            setThemeAccentIndex(null)
            return
        }
        const parsed = Number(trimmed)
        if (!Number.isNaN(parsed)) {
            setThemeAccentIndex(Math.max(0, Math.min(15, parsed)))
        }
    }

    const handleResetSettings = async () => {
        setResetting(true)
        setResetStatusMessage(null)
        try {
            await Api.configReset()
            // Clear errors and reload
            setSystemFieldErrors({})
            setParameterFieldErrors({})
            setUIFieldErrors({})
            setAdvancedFieldErrors({})
            await reloadConfig()
            await reloadThemes()
            setResetStatusMessage('All settings have been reset to default values.')
            setResetConfirmOpen(false)
        } catch (err: any) {
            setResetStatusMessage(err?.message ? `Reset failed: ${err.message}` : 'Reset failed.')
        } finally {
            setResetting(false)
        }
    }

    const renderSystemForm = () => {
        if (loadingConfig) {
            return (
                <Card className="p-6 text-sm text-muted">
                    Loading system configuration…
                </Card>
            )
        }
        if (loadError) {
            return (
                <Card className="p-6 text-sm text-red-400">
                    {loadError}
                </Card>
            )
        }
        return (
            <div className="space-y-4">
                {systemSections.map((section, idx) => {
                    const prevSection = idx > 0 ? systemSections[idx - 1] : null
                    const showDivider = section.isHA && prevSection && !prevSection.isHA

                    return (
                        <div key={section.title}>
                            {showDivider && (
                                <div className="py-8 flex items-center gap-4">
                                    <div className="h-px flex-1 bg-line/30" />
                                    <span className="text-[11px] font-bold uppercase tracking-[0.2em] text-muted whitespace-nowrap">
                                        Home Assistant Integration
                                    </span>
                                    <div className="h-px flex-1 bg-line/30" />
                                </div>
                            )}
                            <Card className="p-6">
                                <div className="flex items-baseline justify-between gap-2">
                                    <div>
                                        <div className="text-sm font-semibold">{section.title}</div>
                                        <p className="text-xs text-muted mt-1">{section.description}</p>
                                    </div>
                                    <span className="text-[10px] uppercase text-muted tracking-wide">System</span>
                                </div>
                                <div className="mt-5 grid gap-4 sm:grid-cols-2">
                                    {section.fields.map((field) => {
                                        const isAzimuth = field.key === 'system.solar_array.azimuth'
                                        const isTilt = field.key === 'system.solar_array.tilt'

                                        if (isAzimuth) {
                                            const rawValue = systemForm[field.key]
                                            const numericValue =
                                                rawValue && rawValue.trim() !== '' ? Number(rawValue) : null
                                            return (
                                                <div key={field.key} className="space-y-1">
                                                    <label className="text-[10px] uppercase tracking-wide text-muted">
                                                        {field.label}
                                                    </label>
                                                    <AzimuthDial
                                                        value={
                                                            typeof numericValue === 'number' &&
                                                                !Number.isNaN(numericValue)
                                                                ? numericValue
                                                                : null
                                                        }
                                                        onChange={(deg) =>
                                                            handleFieldChange(field.key, String(Math.round(deg)))
                                                        }
                                                    />
                                                    <input
                                                        type="number"
                                                        inputMode="decimal"
                                                        value={systemForm[field.key] ?? ''}
                                                        onChange={(event) =>
                                                            handleFieldChange(field.key, event.target.value)
                                                        }
                                                        className="mt-2 w-full rounded-lg border border-line/50 bg-surface2 px-3 py-2 text-sm text-white focus:border-accent focus:outline-none"
                                                    />
                                                    {field.helper && (
                                                        <p className="text-[11px] text-muted">{field.helper}</p>
                                                    )}
                                                    {systemFieldErrors[field.key] && (
                                                        <p className="text-[11px] text-red-400">
                                                            {systemFieldErrors[field.key]}
                                                        </p>
                                                    )}
                                                </div>
                                            )
                                        }

                                        if (isTilt) {
                                            const rawValue = systemForm[field.key]
                                            const numericValue =
                                                rawValue && rawValue.trim() !== '' ? Number(rawValue) : null
                                            return (
                                                <div key={field.key} className="space-y-1">
                                                    <label className="text-[10px] uppercase tracking-wide text-muted">
                                                        {field.label}
                                                    </label>
                                                    <TiltDial
                                                        value={
                                                            typeof numericValue === 'number' &&
                                                                !Number.isNaN(numericValue)
                                                                ? numericValue
                                                                : null
                                                        }
                                                        onChange={(deg) =>
                                                            handleFieldChange(field.key, String(Math.round(deg)))
                                                        }
                                                    />
                                                    <input
                                                        type="number"
                                                        inputMode="decimal"
                                                        value={systemForm[field.key] ?? ''}
                                                        onChange={(event) =>
                                                            handleFieldChange(field.key, event.target.value)
                                                        }
                                                        className="mt-2 w-full rounded-lg border border-line/50 bg-surface2 px-3 py-2 text-sm text-white focus:border-accent focus:outline-none"
                                                    />
                                                    {field.helper && (
                                                        <p className="text-[11px] text-muted">{field.helper}</p>
                                                    )}
                                                    {systemFieldErrors[field.key] && (
                                                        <p className="text-[11px] text-red-400">
                                                            {systemFieldErrors[field.key]}
                                                        </p>
                                                    )}
                                                </div>
                                            )
                                        }

                                        if (field.type === 'entity') {
                                            return (
                                                <div key={field.key} className="space-y-1">
                                                    <label className="text-[10px] uppercase tracking-wide text-muted">
                                                        {field.label}
                                                    </label>
                                                    <EntitySelect
                                                        entities={haEntities}
                                                        value={systemForm[field.key] ?? ''}
                                                        onChange={(value) => handleFieldChange(field.key, value)}
                                                        loading={haLoading}
                                                        placeholder="Select entity..."
                                                    />
                                                    {field.helper && (
                                                        <p className="text-[11px] text-muted">{field.helper}</p>
                                                    )}
                                                </div>
                                            )
                                        }

                                        // Regular fields (boolean checkboxes, number/text inputs)
                                        if (field.type === 'boolean') {
                                            return (
                                                <div key={field.key} className="space-y-1">
                                                    <label className="flex items-center gap-2 text-sm">
                                                        <input
                                                            type="checkbox"
                                                            checked={systemForm[field.key] === 'true'}
                                                            onChange={(event) =>
                                                                handleFieldChange(field.key, event.target.checked ? 'true' : 'false')
                                                            }
                                                            className="h-4 w-4 rounded border border-line/60 text-accent focus:ring-0"
                                                        />
                                                        <span className="font-semibold">{field.label}</span>
                                                    </label>
                                                    {field.helper && (
                                                        <p className="text-[11px] text-muted ml-6">{field.helper}</p>
                                                    )}
                                                </div>
                                            )
                                        }

                                        return (
                                            <div key={field.key} className="space-y-1">
                                                <label className="text-[10px] uppercase tracking-wide text-muted">
                                                    {field.label}
                                                </label>
                                                <input
                                                    type={field.type === 'number' ? 'number' : 'text'}
                                                    inputMode={field.type === 'number' ? 'decimal' : undefined}
                                                    value={systemForm[field.key] ?? ''}
                                                    onChange={(event) =>
                                                        handleFieldChange(field.key, event.target.value)
                                                    }
                                                    className="w-full rounded-lg border border-line/50 bg-surface2 px-3 py-2 text-sm text-white focus:border-accent focus:outline-none"
                                                />
                                                {field.helper && (
                                                    <p className="text-[11px] text-muted">{field.helper}</p>
                                                )}
                                                {systemFieldErrors[field.key] && (
                                                    <p className="text-[11px] text-red-400">
                                                        {systemFieldErrors[field.key]}
                                                    </p>
                                                )}
                                            </div>
                                        )
                                    })}
                                </div>
                                {section.title === 'Home Assistant Connection' && (
                                    <div className="mt-4 flex items-center gap-3">
                                        <button
                                            type="button"
                                            onClick={handleTestConnection}
                                            className="text-xs px-3 py-2 rounded bg-surface border border-line/50 hover:bg-surface2 transition"
                                        >
                                            {haTestStatus && haTestStatus.startsWith('Testing') ? 'Testing...' : 'Test Connection'}
                                        </button>
                                        {haTestStatus && (
                                            <span className={`text-xs ${haTestStatus.startsWith('Success') ? 'text-green-400' : 'text-red-400'}`}>
                                                {haTestStatus}
                                            </span>
                                        )}
                                    </div>
                                )}
                            </Card>
                        </div>
                    )
                })}
                <div className="flex flex-wrap items-center gap-3">
                    <button
                        disabled={systemSaving || loadingConfig}
                        onClick={handleSaveSystem}
                        className={cls.accentBtn}
                    >
                        {systemSaving ? 'Saving…' : 'Save System Settings'}
                    </button>
                    {systemStatusMessage && (
                        <div className={`rounded-lg p-3 text-sm ${systemStatusMessage.startsWith('Failed')
                            ? 'bg-red-500/10 border border-red-500/30 text-red-400'
                            : 'bg-green-500/10 border border-green-500/30 text-green-400'
                            }`}>
                            {systemStatusMessage}
                        </div>
                    )}
                </div>
            </div>
        )
    }

    const renderParameterForm = () => {
        if (loadingConfig) {
            return (
                <Card className="p-6 text-sm text-muted">
                    Loading parameter configuration…
                </Card>
            )
        }
        if (loadError) {
            return (
                <Card className="p-6 text-sm text-red-400">
                    {loadError}
                </Card>
            )
        }
        return (
            <div className="space-y-4">
                {parameterSections.map((section) => (
                    <Card key={section.title} className="p-6">
                        <div className="flex items-baseline justify-between gap-2">
                            <div>
                                <div className="text-sm font-semibold">{section.title}</div>
                                <p className="text-xs text-muted mt-1">{section.description}</p>
                            </div>
                            <span className="text-[10px] uppercase text-muted tracking-wide">Parameters</span>
                        </div>
                        <div className="mt-5 grid gap-4 sm:grid-cols-2">
                            {section.fields.map((field) => (
                                <div key={field.key} className="space-y-1">
                                    <label className="text-[10px] uppercase tracking-wide text-muted">
                                        {field.label}
                                    </label>
                                    {field.type === 'select' ? (
                                        <select
                                            value={parameterForm[field.key] ?? ''}
                                            onChange={(event) =>
                                                handleParameterFieldChange(field.key, event.target.value)
                                            }
                                            className="w-full rounded-lg border border-line/50 bg-surface2 px-3 py-2 text-sm text-white focus:border-accent focus:outline-none"
                                        >
                                            <option value="">Select</option>
                                            {field.options?.map((option) => (
                                                <option key={option.value} value={option.value}>
                                                    {option.label}
                                                </option>
                                            ))}
                                        </select>
                                    ) : field.type === 'boolean' ? (
                                        <div className="flex items-center gap-2 pt-2">
                                            <input
                                                type="checkbox"
                                                checked={parameterForm[field.key] === 'true'}
                                                onChange={(event) =>
                                                    handleParameterFieldChange(
                                                        field.key,
                                                        event.target.checked ? 'true' : 'false'
                                                    )
                                                }
                                                className="h-4 w-4 rounded border border-line/60 text-accent focus:ring-0"
                                            />
                                            <span className="text-sm font-semibold">Enabled</span>
                                        </div>
                                    ) : (
                                        <input
                                            type={field.type === 'number' ? 'number' : 'text'}
                                            inputMode={field.type === 'number' ? 'decimal' : undefined}
                                            value={parameterForm[field.key] ?? ''}
                                            onChange={(event) =>
                                                handleParameterFieldChange(field.key, event.target.value)
                                            }
                                            className="w-full rounded-lg border border-line/50 bg-surface2 px-3 py-2 text-sm text-white focus:border-accent focus:outline-none"
                                        />
                                    )}
                                    {field.helper && (
                                        <p className="text-[11px] text-muted">{field.helper}</p>
                                    )}
                                    {parameterFieldErrors[field.key] && (
                                        <p className="text-[11px] text-red-400">
                                            {parameterFieldErrors[field.key]}
                                        </p>
                                    )}
                                </div>
                            ))}
                        </div>
                    </Card>
                ))}
                <div className="flex flex-wrap items-center gap-3">
                    <button
                        disabled={parameterSaving || loadingConfig}
                        onClick={handleSaveParameters}
                        className={cls.accentBtn}
                    >
                        {parameterSaving ? 'Saving & Re-planning…' : 'Save & Re-plan'}
                    </button>
                    {parameterStatusMessage && (
                        <div className={`rounded-lg p-3 text-sm ${parameterStatusMessage.startsWith('Failed')
                            ? 'bg-red-500/10 border border-red-500/30 text-red-400'
                            : 'bg-green-500/10 border border-green-500/30 text-green-400'
                            }`}>
                            {parameterStatusMessage}
                        </div>
                    )}
                </div>
            </div>
        )
    }

    const renderUIForm = () => {
        if (loadingConfig) {
            return (
                <Card className="p-6 text-sm text-muted">
                    Loading UI configuration…
                </Card>
            )
        }
        if (loadError) {
            return (
                <Card className="p-6 text-sm text-red-400">
                    {loadError}
                </Card>
            )
        }
        return (
            <div className="space-y-4">
                <Card className="p-6 space-y-4">
                    <div className="flex items-baseline justify-between gap-2">
                        <div>
                            <div className="text-sm font-semibold">Theme & Appearance</div>
                            <p className="text-xs text-muted mt-1">
                                Select a theme for the app and adjust the accent color.
                            </p>
                        </div>
                        <span className="text-[10px] uppercase text-muted tracking-wide">UI</span>
                    </div>
                    {themeLoading ? (
                        <p className="text-sm text-muted">Loading themes…</p>
                    ) : themeError ? (
                        <p className="text-sm text-red-400">{themeError}</p>
                    ) : (
                        <div className="grid gap-3 md:grid-cols-3">
                            {themes.map((theme) => {
                                const active = selectedTheme === theme.name
                                return (
                                    <button
                                        key={theme.name}
                                        type="button"
                                        onClick={() => setSelectedTheme(theme.name)}
                                        className={`group flex flex-col gap-2 rounded-xl border p-3 text-left transition ${active ? 'border-accent shadow-sm' : 'border-line/50 hover:border-white/40'
                                            }`}
                                    >
                                        <div className="text-sm font-semibold">{theme.name}</div>
                                        <div className="flex h-6 overflow-hidden rounded-sm border border-line/40">
                                            {theme.palette.slice(0, 4).map((color) => (
                                                <span
                                                    key={`${theme.name}-${color}`}
                                                    className="flex-1"
                                                    style={{ backgroundColor: color }}
                                                />
                                            ))}
                                        </div>
                                        <div className="text-[10px] uppercase text-muted tracking-wide">
                                            {active ? 'Selected' : 'Select'}
                                        </div>
                                    </button>
                                )
                            })}
                        </div>
                    )}
                    <div className="flex flex-wrap items-center gap-3">
                        <label className="text-[10px] uppercase tracking-wide text-muted">Accent index</label>
                        <input
                            type="number"
                            min={0}
                            max={15}
                            value={themeAccentIndex ?? ''}
                            onChange={(event) => handleAccentChange(event.target.value)}
                            className="h-10 w-20 rounded-lg border border-line/50 bg-surface2 px-3 text-sm focus:border-accent focus:outline-none"
                        />
                        <button
                            disabled={themeApplying || themeLoading}
                            onClick={handleApplyTheme}
                            className="rounded-pill bg-accent px-4 py-2 text-sm font-semibold text-[#100f0e] shadow-sm transition hover:bg-accent2 disabled:opacity-50"
                        >
                            {themeApplying ? 'Applying…' : 'Apply theme'}
                        </button>
                        {themeStatusMessage && (
                            <p className={`text-sm ${themeStatusMessage.startsWith('Failed') ? 'text-red-400' : 'text-muted'}`}>
                                {themeStatusMessage}
                            </p>
                        )}
                    </div>
                </Card>

                {uiSections.map((section) => (
                    <Card key={section.title} className="p-6">
                        <div className="flex items-baseline justify-between gap-2">
                            <div>
                                <div className="text-sm font-semibold">{section.title}</div>
                                <p className="text-xs text-muted mt-1">{section.description}</p>
                            </div>
                            <span className="text-[10px] uppercase text-muted tracking-wide">UI</span>
                        </div>
                        <div className="space-y-4">
                            {/* Overlay Defaults - Special Case */}
                            {section.title === 'Dashboard Defaults' && (
                                <div className="space-y-3">
                                    <div>
                                        <label className="text-[10px] uppercase tracking-wide text-muted">Overlay defaults</label>
                                        <p className="text-[11px] text-muted mb-3">Select which overlays are enabled by default on the dashboard.</p>
                                        <div className="grid grid-cols-2 gap-2 sm:grid-cols-3">
                                            {/* Special-case toggles for overlays that use *_off semantics */}
                                            {(() => {
                                                const overlayDefaults = uiForm['dashboard.overlay_defaults'] || ''
                                                const cleanOverlays = [...new Set(overlayDefaults.split(',').map(s => s.trim().toLowerCase()))]

                                                const loadIsActive = !cleanOverlays.includes('load_off')

                                                const toggleToken = (token: string, shouldEnable: boolean) => {
                                                    const current = [...new Set(overlayDefaults.split(',').map(s => s.trim().toLowerCase()))]
                                                    let updated: string[]
                                                    if (shouldEnable) {
                                                        updated = current.filter(item => item !== token.toLowerCase())
                                                    } else {
                                                        updated = [...current, token.toLowerCase()]
                                                    }
                                                    handleUIFieldChange('dashboard.overlay_defaults', updated.join(', '))
                                                }

                                                return (
                                                    <>
                                                        <button
                                                            type="button"
                                                            onClick={() => toggleToken('load_off', !loadIsActive)}
                                                            className={`rounded-pill px-3 py-1 border text-[11px] transition ${loadIsActive
                                                                ? 'bg-accent text-canvas border-accent'
                                                                : 'border-line/60 text-muted hover:border-accent'
                                                                }`}
                                                        >
                                                            Load
                                                        </button>
                                                        {[
                                                            ['Charge', 'charge'],
                                                            ['Discharge', 'discharge'],
                                                            ['Export', 'export'],
                                                            ['Water', 'water'],
                                                            ['SoC Target', 'socTarget'],
                                                            ['SoC Projected', 'socProjected'],
                                                        ].map(([label, key]) => {
                                                            const isActive = cleanOverlays.includes(key.toLowerCase())
                                                            return (
                                                                <button
                                                                    key={key}
                                                                    type="button"
                                                                    onClick={() => {
                                                                        const current = [...new Set(overlayDefaults.split(',').map(s => s.trim().toLowerCase()))]
                                                                        let updated: string[]
                                                                        if (isActive) {
                                                                            updated = current.filter(item => item !== key.toLowerCase())
                                                                        } else {
                                                                            updated = [...current, key.toLowerCase()]
                                                                        }
                                                                        handleUIFieldChange('dashboard.overlay_defaults', updated.join(', '))
                                                                    }}
                                                                    className={`rounded-pill px-3 py-1 border text-[11px] transition ${isActive
                                                                        ? 'bg-accent text-canvas border-accent'
                                                                        : 'border-line/60 text-muted hover:border-accent'
                                                                        }`}
                                                                >
                                                                    {label}
                                                                </button>
                                                            )
                                                        })}
                                                    </>
                                                )
                                            })()}
                                        </div>
                                    </div>
                                </div>
                            )}

                            {/* Regular Fields */}
                            <div className="grid gap-4 sm:grid-cols-2">
                                {section.fields.map((field) => (
                                    <div key={field.key} className="space-y-1">
                                        {field.type === 'boolean' ? (
                                            <div className="flex items-center gap-2 pt-2">
                                                <input
                                                    type="checkbox"
                                                    checked={uiForm[field.key] === 'true'}
                                                    onChange={(event) =>
                                                        handleUIFieldChange(field.key, event.target.checked ? 'true' : 'false')
                                                    }
                                                    className="h-4 w-4 rounded border border-line/60 text-accent focus:ring-0"
                                                />
                                                <span className="text-sm font-semibold">{field.label}</span>
                                            </div>
                                        ) : field.type === 'select' ? (
                                            <>
                                                <label className="text-[10px] uppercase tracking-wide text-muted">{field.label}</label>
                                                <select
                                                    value={uiForm[field.key] ?? ''}
                                                    onChange={(event) => handleUIFieldChange(field.key, event.target.value)}
                                                    className="w-full rounded-lg border border-line/50 bg-surface2 px-3 py-2 text-sm text-white focus:border-accent focus:outline-none"
                                                >
                                                    <option value="">Select</option>
                                                    {field.options?.map((option) => (
                                                        <option key={option.value} value={option.value}>
                                                            {option.label}
                                                        </option>
                                                    ))}
                                                </select>
                                            </>
                                        ) : (
                                            <>
                                                <label className="text-[10px] uppercase tracking-wide text-muted">{field.label}</label>
                                                <input
                                                    type="text"
                                                    value={uiForm[field.key] ?? ''}
                                                    onChange={(event) => handleUIFieldChange(field.key, event.target.value)}
                                                    className="w-full rounded-lg border border-line/50 bg-surface2 px-3 py-2 text-sm text-white focus:border-accent focus:outline-none"
                                                />
                                            </>
                                        )}
                                        {field.helper && (
                                            <p className="text-[11px] text-muted">{field.helper}</p>
                                        )}
                                        {uiFieldErrors[field.key] && (
                                            <p className="text-[11px] text-red-400">{uiFieldErrors[field.key]}</p>
                                        )}
                                    </div>
                                ))}
                            </div>
                        </div>
                    </Card>
                ))}
                <div className="flex flex-wrap items-center gap-3">
                    <button
                        disabled={uiSaving || loadingConfig}
                        onClick={handleSaveUI}
                        className={cls.accentBtn}
                    >
                        {uiSaving ? 'Saving…' : 'Save UI Preferences'}
                    </button>
                    {uiStatusMessage && (
                        <div className={`rounded-lg p-3 text-sm ${uiStatusMessage.startsWith('Failed')
                            ? 'bg-red-500/10 border border-red-500/30 text-red-400'
                            : 'bg-green-500/10 border border-green-500/30 text-green-400'
                            }`}>
                            {uiStatusMessage}
                        </div>
                    )}
                </div>
            </div>
        )
    }

    const renderAdvancedForm = () => {
        if (loadingConfig) return <Card className="p-6 text-sm text-muted">Loading advanced configuration…</Card>
        if (loadError) return <Card className="p-6 text-sm text-red-400">{loadError}</Card>

        return (
            <div className="space-y-4">
                {advancedSections.map((section) => (
                    <Card key={section.title} className="p-6">
                        <div className="flex items-baseline justify-between gap-2">
                            <div>
                                <div className="text-sm font-semibold">{section.title}</div>
                                <p className="text-xs text-muted mt-1">{section.description}</p>
                            </div>
                            <span className="text-[10px] uppercase text-muted tracking-wide">Advanced</span>
                        </div>

                        <div className="mt-5 grid gap-4 sm:grid-cols-2">
                            {section.fields.map((field) => (
                                <div key={field.key} className="space-y-1">
                                    {field.type === 'boolean' && (
                                        <div className="flex items-center gap-2 pt-2">
                                            <input
                                                type="checkbox"
                                                checked={advancedForm[field.key] === 'true'}
                                                onChange={(event) =>
                                                    handleAdvancedFieldChange(
                                                        field.key,
                                                        event.target.checked ? 'true' : 'false'
                                                    )
                                                }
                                                className="h-4 w-4 rounded border border-line/60 text-accent focus:ring-0"
                                            />
                                            <span className="text-sm font-semibold">{field.label}</span>
                                        </div>
                                    )}
                                    {field.helper && (
                                        <p className="text-[11px] text-muted ml-6">{field.helper}</p>
                                    )}
                                    {advancedFieldErrors[field.key] && (
                                        <p className="text-[11px] text-red-400 ml-6">
                                            {advancedFieldErrors[field.key]}
                                        </p>
                                    )}
                                </div>
                            ))}
                        </div>
                    </Card>
                ))}

                <div className="flex flex-wrap items-center gap-3">
                    <button
                        disabled={advancedSaving || loadingConfig}
                        onClick={handleSaveAdvanced}
                        className={cls.accentBtn}
                    >
                        {advancedSaving ? 'Saving…' : 'Save Advanced Settings'}
                    </button>
                    {advancedStatusMessage && (
                        <div className={`rounded-lg p-3 text-sm ${advancedStatusMessage.startsWith('Failed')
                            ? 'bg-red-500/10 border border-red-500/30 text-red-400'
                            : 'bg-green-500/10 border border-green-500/30 text-green-400'
                            }`}>
                            {advancedStatusMessage}
                        </div>
                    )}
                </div>

                <div className="py-8">
                    <div className="h-px bg-line/20" />
                </div>

                <Card className="border-red-500/30 bg-red-500/5 p-6">
                    <div className="flex items-center justify-between gap-4">
                        <div>
                            <div className="text-sm font-bold text-red-400">Danger Zone</div>
                            <p className="text-xs text-red-400/70 mt-1">
                                Irreversible actions that affect your entire system configuration.
                            </p>
                        </div>
                    </div>

                    <div className="mt-6 flex flex-wrap items-center gap-4">
                        {!resetConfirmOpen ? (
                            <button
                                type="button"
                                onClick={() => setResetConfirmOpen(true)}
                                className="rounded-lg border border-red-500/30 px-4 py-2 text-xs font-bold uppercase tracking-wider text-red-400 transition hover:bg-red-500/10"
                            >
                                Reset all settings to defaults
                            </button>
                        ) : (
                            <div className="flex items-center gap-3 rounded-xl bg-canvas p-4 border border-line">
                                <span className="text-xs font-semibold text-white">Are you absolutely sure?</span>
                                <button
                                    type="button"
                                    disabled={resetting}
                                    onClick={handleResetSettings}
                                    className="rounded-lg bg-red-500 px-3 py-1.5 text-xs font-bold text-white shadow-lg transition hover:bg-red-600 disabled:opacity-50"
                                >
                                    {resetting ? 'Resetting...' : 'Yes, reset everything'}
                                </button>
                                <button
                                    type="button"
                                    disabled={resetting}
                                    onClick={() => setResetConfirmOpen(false)}
                                    className="rounded-lg bg-surface px-3 py-1.5 text-xs font-semibold text-muted transition hover:text-white"
                                >
                                    Cancel
                                </button>
                            </div>
                        )}
                    </div>
                </Card>
            </div>
        )
    }

    return (
        <main className="mx-auto max-w-7xl px-4 pb-24 pt-8 sm:px-6 lg:pt-12 space-y-6">
            <div className="flex items-center justify-between">
                <div>
                    <h1 className="text-3xl font-semibold">Settings</h1>
                    <p className="text-sm text-muted">System, parameters, and UI preferences collected into one modern surface.</p>
                </div>
            </div>

            <div className="flex flex-wrap gap-2">
                {tabs.map((tab) => {
                    const active = activeTab === tab.id
                    return (
                        <button
                            key={tab.id}
                            onClick={() => setActiveTab(tab.id)}
                            className={`rounded-full px-4 py-2 text-sm font-semibold transition ${active ? 'bg-accent text-[#0F1216] shadow-sm' : 'bg-surface border border-line/50 text-muted'
                                }`}
                        >
                            {tab.label}
                        </button>
                    )
                })}
            </div>

            {resetStatusMessage && (
                <div className={`rounded-lg p-3 text-sm ${resetStatusMessage.startsWith('Reset failed')
                    ? 'bg-red-500/10 border border-red-500/30 text-red-400'
                    : 'bg-green-500/10 border border-green-500/30 text-green-400'
                    }`}>
                    {resetStatusMessage}
                </div>
            )}

            {activeTab === 'system'
                ? renderSystemForm()
                : activeTab === 'parameters'
                    ? renderParameterForm()
                    : activeTab === 'ui'
                        ? renderUIForm()
                        : renderAdvancedForm()}
        </main>
    )
}
