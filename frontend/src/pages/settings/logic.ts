import { BaseField, HaEntity } from './types'

const CURRENT_UNITS = new Set(['a', 'amp', 'amps', 'ampere', 'amperes'])
const POWER_UNITS = new Set(['w', 'watt', 'watts', 'kw', 'kilowatt', 'kilowatts'])

/** Mirrors executor.load_balancer.classify_phase_sensor_unit for the settings UI. */
export function isPowerModeEntity(entityId: string | undefined, entities: HaEntity[]): boolean {
    if (!entityId) return false
    const entity = entities.find((e) => e.entity_id === entityId)
    if (!entity) return false
    const unit = (entity.unit_of_measurement || '').trim().toLowerCase()
    if (CURRENT_UNITS.has(unit)) return false
    if (POWER_UNITS.has(unit)) return true
    return (entity.device_class || '').trim().toLowerCase() === 'power'
}

export const shouldRenderField = (
    field: BaseField,
    fullForm: Record<string, string | boolean | number | undefined>,
    config?: Record<string, unknown>,
): boolean => {
    if (field.disabled) return false

    // Helper to get value from form or config
    const getValue = (key: string): string | undefined => {
        let val = fullForm[key]
        if (val === undefined && config) {
            const parts = key.split('.')
            // eslint-disable-next-line @typescript-eslint/no-explicit-any
            const configVal = parts.reduce((acc: any, k) => acc?.[k], config)
            if (configVal !== undefined && configVal !== null) {
                val = typeof configVal === 'boolean' ? (configVal ? 'true' : 'false') : String(configVal)
            }
        }
        return val === undefined ? undefined : String(val)
    }

    if (field.showIf) {
        // For system.* showIf checks, use config if available (form may not have system fields)
        if (field.showIf.configKey.startsWith('system.') && config) {
            const systemKey = field.showIf.configKey.replace('system.', '')
            // eslint-disable-next-line @typescript-eslint/no-explicit-any
            const configValue = (config as any)?.system?.[systemKey]
            const expectedVal = field.showIf.value ?? true

            if (typeof expectedVal === 'boolean') {
                return configValue === expectedVal
            }

            if (Array.isArray(expectedVal)) {
                // eslint-disable-next-line @typescript-eslint/no-explicit-any
                return expectedVal.includes(configValue as any) || expectedVal.some((v) => v === configValue)
            }

            return configValue === expectedVal
        }

        // Standard form-based check (now using getValue fallback to config)
        const currentVal = getValue(field.showIf.configKey)
        const expectedVal = field.showIf.value ?? true

        // If expectedVal is a boolean, treat currentVal as a boolean string ('true'/'false')
        if (typeof expectedVal === 'boolean') {
            return (currentVal === 'true') === expectedVal
        }

        // Support array of valid values (OR logic)
        if (Array.isArray(expectedVal)) {
            // eslint-disable-next-line @typescript-eslint/no-explicit-any
            return expectedVal.includes(currentVal as any) || expectedVal.some((v) => String(v) === currentVal)
        }

        // Otherwise, do a direct string comparison
        return currentVal === String(expectedVal)
    }

    if (field.showIfAll) {
        return field.showIfAll.every((k) => getValue(k) === 'true')
    }

    if (field.showIfAny) {
        return field.showIfAny.some((k) => getValue(k) === 'true')
    }

    return true
}
