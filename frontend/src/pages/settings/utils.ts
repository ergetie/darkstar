import { BaseField } from './types'

/**
 * Get a value from a deeply nested object using an array of keys.
 */
export function getDeepValue<T>(source: unknown, path: string[]): T | undefined {
    return path.reduce(
        (current: unknown, key) =>
            current && typeof current === 'object' ? (current as Record<string, unknown>)[key] : undefined,
        source,
    ) as T | undefined
}

/**
 * Set a value in a deeply nested object using an array of keys.
 * Returns a new object (immutable-friendly).
 */
export function setDeepValue(target: Record<string, unknown>, path: string[], value: unknown): Record<string, unknown> {
    const root = { ...target }
    let cursor = root as Record<string, unknown>

    path.forEach((key, index) => {
        if (index === path.length - 1) {
            cursor[key] = value
            return
        }
        if (!cursor[key] || typeof cursor[key] !== 'object') {
            cursor[key] = {}
        } else {
            cursor[key] = { ...(cursor[key] as Record<string, unknown>) }
        }
        cursor = cursor[key] as Record<string, unknown>
    })
    return root
}

// Improved setDeepValue
export function setDeepValueCorrect<T extends Record<string, unknown>>(target: T, path: string[], value: unknown): T {
    if (path.length === 0) return target
    const [key, ...rest] = path
    if (rest.length === 0) {
        return { ...target, [key]: value }
    }
    const subTarget = (target[key] as Record<string, unknown>) || {}
    return {
        ...target,
        [key]: setDeepValueCorrect(subTarget, rest, value),
    }
}

/**
 * Parses raw input string based on field type.
 */
export function parseFieldInput(field: BaseField, raw: string): unknown {
    const trimmed = raw.trim()
    if (field.type === 'number' || field.type === 'azimuth' || field.type === 'tilt') {
        if (trimmed === '') return null
        const parsed = Number(trimmed)
        return Number.isNaN(parsed) ? undefined : parsed
    }
    if (field.type === 'boolean') {
        return trimmed === 'true'
    }
    if (field.type === 'array') {
        if (!trimmed) return []
        return trimmed
            .split(',')
            .map((part) => part.trim())
            .filter(Boolean)
            .map((value) => {
                const num = Number(value)
                return Number.isNaN(num) ? value : num
            })
    }
    if (
        field.type === 'solar_arrays' ||
        field.type === 'entity_array' ||
        field.type === 'balanced_loads' ||
        field.type === 'give_way_list' ||
        field.type === 'excess_pv_priority'
    ) {
        try {
            return JSON.parse(raw)
        } catch {
            return []
        }
    }
    return trimmed
}

/**
 * Builds form state (Record<string, string>) from config object.
 */
export function buildFormState(config: Record<string, unknown> | null, fields: BaseField[]): Record<string, string> {
    const state: Record<string, string> = {}
    if (!config) return state

    fields.forEach((field) => {
        if (field.companionKey) {
            // Companion keys are always booleans for now
            const companionVal = getDeepValue<unknown>(config, field.companionKey.split('.'))
            state[field.companionKey] = companionVal === true ? 'true' : 'false'
        }

        const value = getDeepValue<unknown>(config, field.path)
        if (field.type === 'boolean') {
            state[field.key] = value === true ? 'true' : 'false'
        } else if (field.type === 'array' && Array.isArray(value)) {
            state[field.key] = value.join(', ')
        } else if (
            field.type === 'solar_arrays' ||
            field.type === 'entity_array' ||
            field.type === 'balanced_loads' ||
            field.type === 'give_way_list' ||
            field.type === 'excess_pv_priority'
        ) {
            // Handle complex array/object types - stringify if array/object, default to empty array
            if (Array.isArray(value) || (value !== null && typeof value === 'object')) {
                state[field.key] = JSON.stringify(value)
            } else {
                state[field.key] = JSON.stringify([])
            }
        } else if (value !== null && typeof value === 'object') {
            // Handle other objects (like dashboard.overlay_defaults) by stringifying them as JSON
            state[field.key] = JSON.stringify(value)
        } else {
            state[field.key] = value !== undefined && value !== null ? String(value) : ''
        }
    })
    return state
}

/**
 * Checks if two values are equal for the purposes of configuration patching.
 */
export function areEqual(a: unknown, b: unknown, type: string): boolean {
    // Null/Undefined equivalence (covers missing keys vs explicitly null/empty)
    if ((a === null || a === undefined) && (b === null || b === undefined)) return true

    // REV F58: Treat adding a new key (undefined -> value) as a change
    // This fixes the bug where adding new entity fields shows "No changes detected"
    if ((a === null || a === undefined) && b !== null && b !== undefined) {
        // For text/entity fields, also check if the new value is non-empty
        if (type !== 'boolean' && type !== 'number' && type !== 'array' && type !== 'solar_arrays') {
            const strB = String(b).trim()
            if (strB !== '') return false // Adding a new non-empty value is a change
        } else {
            return false // Adding any new value for non-text types is a change
        }
    }

    // Normalize empty strings vs null for text/entity/select fields
    if (
        type !== 'boolean' &&
        type !== 'number' &&
        type !== 'array' &&
        type !== 'solar_arrays' &&
        type !== 'entity_array' &&
        type !== 'balanced_loads' &&
        type !== 'give_way_list' &&
        type !== 'excess_pv_priority'
    ) {
        const strA = a !== null && a !== undefined ? String(a).trim() : ''
        const strB = b !== null && b !== undefined ? String(b).trim() : ''
        return strA === strB
    }

    // Treat false as equal to null/undefined for boolean fields (assuming default is false)
    if (type === 'boolean' && a === false && (b === null || b === undefined)) return true

    if (type === 'array') {
        const arrA = Array.isArray(a) ? (a as unknown[]) : []
        const arrB = Array.isArray(b) ? (b as unknown[]) : []
        if (arrA.length !== arrB.length) return false
        return arrA.every((val, i) => val === arrB[i])
    }

    if (
        type === 'solar_arrays' ||
        type === 'entity_array' ||
        type === 'balanced_loads' ||
        type === 'give_way_list' ||
        type === 'excess_pv_priority'
    ) {
        // Treat undefined as equivalent to empty array for array/object types
        const normalize = (v: unknown) => {
            if (v === undefined || v === null) return '[]'
            return JSON.stringify(v)
        }
        return normalize(a) === normalize(b)
    }

    // Strict equality for others (handles numbers correctly)
    return a === b
}

export type ChangedField = {
    key: string
    label: string
    oldValue: string
    newValue: string
}

/**
 * Stringifies a value for display in the changed-fields list.
 */
function displayValue(value: unknown, type: string): string {
    if (value === null || value === undefined || value === '') return '—'
    if (type === 'boolean') return value === true || value === 'true' ? 'on' : 'off'
    if (Array.isArray(value)) return value.length ? value.join(', ') : '—'
    if (typeof value === 'object') return JSON.stringify(value)
    return String(value)
}

/**
 * Lists human-readable changed fields by comparing form state with original config.
 * Mirrors buildPatch's comparison semantics but returns a flat display list
 * (label + old/new values) instead of a nested config patch.
 */
export function listChangedFields(
    original: Record<string, unknown>,
    form: Record<string, string>,
    fields: BaseField[],
): ChangedField[] {
    const changes: ChangedField[] = []

    fields.forEach((field) => {
        // Skip virtual/UI-only fields that don't correspond to actual config paths
        if (field.path.length === 0) return

        if (field.companionKey) {
            const rawCompanion = form[field.companionKey]
            if (rawCompanion !== undefined) {
                const parsedCompanion = rawCompanion === 'true'
                const companionPath = field.companionKey.split('.')
                const currentCompanion = getDeepValue<unknown>(original, companionPath)

                if (parsedCompanion !== currentCompanion) {
                    changes.push({
                        key: field.companionKey,
                        label: field.label,
                        oldValue: displayValue(currentCompanion, 'boolean'),
                        newValue: displayValue(parsedCompanion, 'boolean'),
                    })
                }
            }
        }

        const raw = form[field.key]
        if (raw === undefined) return

        const parsed = parseFieldInput(field, raw)
        if (parsed === undefined) return

        // Specialized number/null handling
        if (field.type === 'number' && parsed === null) {
            const current = getDeepValue<unknown>(original, field.path)
            if (current === null || current === undefined) return
        }

        const currentValue = getDeepValue<unknown>(original, field.path)

        if (areEqual(parsed, currentValue, field.type)) return

        changes.push({
            key: field.key,
            label: field.label,
            oldValue: displayValue(currentValue, field.type),
            newValue: displayValue(parsed, field.type),
        })
    })

    return changes
}

/**
 * Builds a patch object for the API by comparing form state with original config.
 */
export function buildPatch(
    original: Record<string, unknown>,
    form: Record<string, string>,
    fields: BaseField[],
): Record<string, unknown> {
    let patch: Record<string, unknown> = {}
    const debug = true

    // System toggle fields that are only for section visibility (not editable in this tab)
    // NOTE: system.has_ev_charger and system.has_water_heater were previously excluded but they ARE editable toggles
    // and must be saved - they control visibility of EV/Water Heater sections
    const visibilityOnlyFields = new Set<string>()

    fields.forEach((field) => {
        // Skip visibility-only fields - they're not meant to be edited in this tab
        if (visibilityOnlyFields.has(field.key)) return
        // Skip virtual/UI-only fields that don't correspond to actual config paths
        if (field.path.length === 0) return
        if (field.companionKey) {
            const rawCompanion = form[field.companionKey]
            if (rawCompanion !== undefined) {
                const parsedCompanion = rawCompanion === 'true'
                const companionPath = field.companionKey.split('.')
                const currentCompanion = getDeepValue<unknown>(original, companionPath)

                if (parsedCompanion !== currentCompanion) {
                    patch = setDeepValueCorrect(patch, companionPath, parsedCompanion)
                }
            }
        }

        const raw = form[field.key]
        if (raw === undefined) return

        const parsed = parseFieldInput(field, raw)
        if (parsed === undefined) return

        // Specialized number/null handling
        if (field.type === 'number' && parsed === null) {
            const current = getDeepValue<unknown>(original, field.path)
            if (current === null || current === undefined) return
        }

        const currentValue = getDeepValue<unknown>(original, field.path)

        if (areEqual(parsed, currentValue, field.type)) return

        if (debug) {
            console.warn(`[CONFIG_PATCH] Field '${field.key}' changed:`, {
                path: field.path,
                old: currentValue,
                new: parsed,
                type: field.type,
            })
        }

        patch = setDeepValueCorrect(patch, field.path, parsed)
    })

    return patch
}
