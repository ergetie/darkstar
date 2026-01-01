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
    return trimmed
}

/**
 * Builds form state (Record<string, string>) from config object.
 */
export function buildFormState(config: Record<string, unknown> | null, fields: BaseField[]): Record<string, string> {
    const state: Record<string, string> = {}
    if (!config) return state

    fields.forEach((field) => {
        const value = getDeepValue<unknown>(config, field.path)
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

/**
 * Builds a patch object for the API by comparing form state with original config.
 */
export function buildPatch(
    original: Record<string, unknown>,
    form: Record<string, string>,
    fields: BaseField[],
): Record<string, unknown> {
    let patch: Record<string, unknown> = {}

    fields.forEach((field) => {
        const raw = form[field.key]
        if (raw === undefined) return

        const parsed = parseFieldInput(field, raw)
        if (parsed === undefined) return
        if (field.type === 'number' && parsed === null) return

        const currentValue = getDeepValue<unknown>(original, field.path)

        const areEqual = (a: unknown, b: unknown, type: string): boolean => {
            if (type === 'array') {
                if (!Array.isArray(a) || !Array.isArray(b)) return false
                if (a.length !== b.length) return false
                return a.every((val, i) => val === b[i])
            }
            return a === b
        }

        if (areEqual(parsed, currentValue, field.type)) return

        patch = setDeepValueCorrect(patch, field.path, parsed)
    })

    return patch
}
