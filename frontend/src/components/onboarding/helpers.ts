import type { ConfigResponse } from '../../lib/api'

export type WizardConfig = ConfigResponse & Record<string, unknown>

export function getPath(root: unknown, path: string): unknown {
    return path.split('.').reduce<unknown>((value, segment) => {
        if (Array.isArray(value) && /^\d+$/.test(segment)) return value[Number(segment)]
        if (value && typeof value === 'object') return (value as Record<string, unknown>)[segment]
        return undefined
    }, root)
}

export function setPath(root: WizardConfig, path: string, value: unknown): WizardConfig {
    const result = structuredClone(root) as Record<string, unknown>
    const parts = path.split('.')
    let node: Record<string, unknown> | unknown[] = result
    for (let index = 0; index < parts.length - 1; index += 1) {
        const part = parts[index]
        const nextIsIndex = /^\d+$/.test(parts[index + 1])
        const current = Array.isArray(node) ? node[Number(part)] : node[part]
        const next = current && typeof current === 'object' ? current : nextIsIndex ? [] : {}
        if (Array.isArray(node)) node[Number(part)] = next
        else node[part] = next
        node = next as Record<string, unknown> | unknown[]
    }
    const last = parts[parts.length - 1]
    if (Array.isArray(node)) node[Number(last)] = value
    else node[last] = value
    return result as WizardConfig
}

export function isConfigured(value: unknown): boolean {
    if (value === null || value === undefined || value === '') return false
    if (typeof value === 'number') return Number.isFinite(value) && value !== 0
    if (Array.isArray(value)) return value.length > 0
    return true
}

export function hasFiniteNumber(value: unknown): boolean {
    return (
        (typeof value === 'number' || (typeof value === 'string' && value.trim() !== '')) &&
        Number.isFinite(Number(value))
    )
}

export function flattenConfig(
    value: unknown,
    prefix = '',
    output: Record<string, unknown> = {},
): Record<string, unknown> {
    if (Array.isArray(value)) {
        value.forEach((item, index) => flattenConfig(item, `${prefix}.${index}`, output))
    } else if (value && typeof value === 'object') {
        for (const [key, nested] of Object.entries(value)) {
            flattenConfig(nested, prefix ? `${prefix}.${key}` : key, output)
        }
    } else if (prefix && !prefix.toLowerCase().includes('token')) {
        output[prefix] = value
    }
    return output
}

export type ConfigDiff = { path: string; before: unknown; after: unknown }

export function configDiff(beforeConfig: unknown, afterConfig: unknown): ConfigDiff[] {
    const before = flattenConfig(beforeConfig)
    const after = flattenConfig(afterConfig)
    return [...new Set([...Object.keys(before), ...Object.keys(after)])]
        .filter((path) => JSON.stringify(before[path]) !== JSON.stringify(after[path]))
        .map((path) => ({ path, before: before[path], after: after[path] }))
}

const SETTING_LABELS: Record<string, string> = {
    'system.inverter_profile': 'Inverter profile',
    'system.grid_meter_type': 'Grid meter type',
    'system.grid.max_power_kw': 'Grid import limit',
    'system.location.latitude': 'Latitude',
    'system.location.longitude': 'Longitude',
    'nordpool.price_area': 'Nord Pool price area',
    'nordpool.currency': 'Currency',
    'input_sensors.load_power': 'House load power sensor',
    'input_sensors.grid_power': 'Grid power sensor',
    'input_sensors.grid_import_power': 'Grid import power sensor',
    'input_sensors.grid_export_power': 'Grid export power sensor',
    'input_sensors.battery_soc': 'Battery state of charge sensor',
    'input_sensors.battery_power': 'Battery power sensor',
    'input_sensors.pv_power': 'Solar power sensor',
    'input_sensors.synthetic_daily_load_kwh': 'Estimated daily use',
    'battery.capacity_kwh': 'Battery capacity',
    'battery.min_soc_percent': 'Minimum state of charge',
    'battery.max_soc_percent': 'Maximum state of charge',
    'battery.max_charge_w': 'Maximum charge power',
    'battery.max_discharge_w': 'Maximum discharge power',
    'executor.shadow_mode': 'Executor mode',
}

const SEGMENT_LABELS: Record<string, string> = {
    enabled: 'Enabled',
    name: 'Name',
    power_kw: 'Rated power',
    sensor: 'Power sensor',
    target_entity: 'Control entity',
    type: 'Control type',
    rated_power_kw: 'Rated power',
    battery_capacity_kwh: 'Vehicle battery capacity',
    soc_sensor: 'State of charge sensor',
    plug_sensor: 'Plug status sensor',
    switch_entity: 'Enable or disable control',
    current_entity: 'Current setpoint control',
    min_current_a: 'Minimum current',
    max_current_a: 'Maximum current',
    phases: 'Phases',
    kwp: 'Peak power',
    tilt: 'Tilt',
    azimuth: 'Azimuth',
    has_solar: 'Solar enabled',
    has_battery: 'Battery enabled',
    has_water_heater: 'Water heater enabled',
    has_ev_charger: 'EV charger enabled',
    main_fuse_a: 'Main fuse rating',
    vat_percent: 'VAT',
    energy_tax_sek: 'Energy tax',
    grid_transfer_fee_sek: 'Grid transfer fee',
}

const SECTION_LABELS: Record<string, string> = {
    system: 'System',
    input_sensors: 'Sensors',
    pricing: 'Pricing',
    battery: 'Battery',
    executor: 'Executor',
    water_heaters: 'Water heater',
    ev_chargers: 'EV charger',
    solar_arrays: 'Solar array',
}

function humanize(segment: string): string {
    return segment
        .replace(/_/g, ' ')
        .replace(/\bkwp\b/gi, 'kWp')
        .replace(/\bkw\b/gi, 'kW')
        .replace(/\bw\b/gi, 'W')
        .replace(/\b(ev|vat|soc|ha|pv)\b/gi, (value) => value.toUpperCase())
        .replace(/\b\w/g, (character) => character.toUpperCase())
}

export function settingLabel(path: string): string {
    const withoutIndex = path.replace(/\.\d+(?=\.)/g, '')
    const direct = SETTING_LABELS[withoutIndex]
    if (direct) return direct

    const parts = path.split('.')
    const indexAt = parts.findIndex((part) => /^\d+$/.test(part))
    if (indexAt > 0) {
        const section = SECTION_LABELS[parts[indexAt - 1]] ?? humanize(parts[indexAt - 1])
        const detail = parts
            .slice(indexAt + 1)
            .map((part) => SEGMENT_LABELS[part] ?? humanize(part))
            .join(' · ')
        return `${section} ${Number(parts[indexAt]) + 1}${detail ? ` · ${detail}` : ''}`
    }

    const section = SECTION_LABELS[parts[0]] ?? humanize(parts[0])
    const detail = parts
        .slice(1)
        .map((part) => SEGMENT_LABELS[part] ?? humanize(part))
        .join(' · ')
    return detail ? `${section} · ${detail}` : section
}

export function flattenPatch(
    value: unknown,
    prefix = '',
    output: Record<string, unknown> = {},
): Record<string, unknown> {
    if (Array.isArray(value)) {
        if (prefix) output[prefix] = value
        return output
    }
    if (value && typeof value === 'object') {
        for (const [key, nested] of Object.entries(value)) {
            flattenPatch(nested, prefix ? `${prefix}.${key}` : key, output)
        }
    } else if (prefix) {
        output[prefix] = value
    }
    return output
}

export function prefillHighConfidence(
    config: WizardConfig,
    patch: Record<string, unknown>,
    candidates: Record<string, { confidence: string }[]>,
): WizardConfig {
    let next = config
    for (const [path, value] of Object.entries(flattenPatch(patch))) {
        const best = candidates[path]?.[0]
        if (best?.confidence === 'high' && !isConfigured(getPath(next, path))) {
            next = setPath(next, path, value)
        }
    }
    return next
}

export function mergeConfig(base: WizardConfig, patch: Record<string, unknown>): WizardConfig {
    const result = structuredClone(base) as Record<string, unknown>
    const merge = (target: Record<string, unknown>, source: Record<string, unknown>) => {
        for (const [key, value] of Object.entries(source)) {
            if (value && typeof value === 'object' && !Array.isArray(value)) {
                const current = target[key]
                const next = current && typeof current === 'object' && !Array.isArray(current) ? current : {}
                merge(next as Record<string, unknown>, value as Record<string, unknown>)
                target[key] = next
            } else {
                target[key] = value
            }
        }
    }
    merge(result, patch)
    return result as WizardConfig
}

export function isFeatureEnabled(
    config: WizardConfig,
    key: 'has_solar' | 'has_battery' | 'has_water_heater' | 'has_ev_charger',
) {
    return getPath(config, `system.${key}`) === true
}

export function fusePowerKw(amps: number, phases: number, voltage = 230): number {
    if (!Number.isFinite(amps) || !Number.isFinite(phases) || amps <= 0 || phases <= 0) return 0
    return Number(((amps * phases * voltage) / 1000).toFixed(1))
}
