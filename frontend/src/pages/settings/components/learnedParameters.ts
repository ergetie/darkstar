import type { LearnedParameter, LearnedParameterSource } from '../../../lib/types'

export const SOURCE_BADGE: Record<LearnedParameterSource, { label: string; className: string }> = {
    locked: { label: 'locked', className: 'badge badge-accent' },
    learned: { label: 'learned', className: 'badge badge-good' },
    default: { label: 'default', className: 'badge badge-muted' },
    config: { label: 'config', className: 'badge badge-muted' },
    expired: { label: 'expired', className: 'badge badge-warn' },
}

/** Fractions are shown and entered as percent; watts as watts. */
export function displayScale(parameter: Pick<LearnedParameter, 'unit'>): number {
    return parameter.unit === 'W' ? 1 : 100
}

export function unitSuffix(parameter: Pick<LearnedParameter, 'unit'>): string {
    return parameter.unit === 'W' ? 'W' : '%'
}

export function formatValue(parameter: Pick<LearnedParameter, 'unit'>, value: number | null): string {
    if (value === null || value === undefined) return '–'
    const scaled = value * displayScale(parameter)
    return parameter.unit === 'W' ? `${Math.round(scaled)} W` : `${scaled.toFixed(1)} %`
}

/** Parse the lock input (display units) into a stored value; null when empty or not a number. */
export function parseLockInput(parameter: Pick<LearnedParameter, 'unit'>, text: string): number | null {
    const trimmed = text.trim().replace(',', '.')
    if (trimmed === '') return null
    const number = Number(trimmed)
    if (!Number.isFinite(number)) return null
    return Math.round((number / displayScale(parameter)) * 1e6) / 1e6
}

function boundsDisplay(parameter: Pick<LearnedParameter, 'unit' | 'bounds'>): [number, number] {
    const scale = displayScale(parameter)
    return [Number((parameter.bounds.min * scale).toFixed(1)), Number((parameter.bounds.max * scale).toFixed(1))]
}

export function boundsText(parameter: Pick<LearnedParameter, 'unit' | 'bounds'>): string {
    const [low, high] = boundsDisplay(parameter)
    return `${low} to ${high} ${unitSuffix(parameter)}`
}

export function validateLock(parameter: LearnedParameter, text: string): { value: number } | { error: string } {
    const value = parseLockInput(parameter, text)
    if (value === null) return { error: 'Enter a number.' }
    if (value < parameter.bounds.min || value > parameter.bounds.max) {
        const [low, high] = boundsDisplay(parameter)
        return { error: `Value must be between ${low} and ${high} ${unitSuffix(parameter)}.` }
    }
    return { value }
}

/** One line of evidence behind a learned value, from the stored evidence figures. */
export function evidenceSummary(evidence: Record<string, unknown>): string {
    const parts: string[] = []
    const number = (key: string): number | null => {
        const value = evidence[key]
        return typeof value === 'number' && Number.isFinite(value) ? value : null
    }
    const days = number('days') ?? number('span_days')
    if (days !== null) parts.push(`${Math.round(days)} days of data`)
    const runs = number('runs')
    if (runs !== null) parts.push(`${runs} continuous ${runs === 1 ? 'run' : 'runs'}`)
    const slots = number('slots')
    if (slots !== null) parts.push(`${slots} slots`)
    const sensorSlots = number('sensor_slots')
    if (sensorSlots) parts.push(`${sensorSlots} from the loss sensor`)
    return parts.join(', ')
}

export function formatDate(value: string | null): string {
    if (!value) return '–'
    const date = new Date(value)
    return Number.isNaN(date.getTime()) ? value : date.toLocaleDateString()
}

const STANDBY_KEY = 'inverter_standby_w'
const DISCHARGE_EFFICIENCY_KEY = 'inverter_discharge_efficiency'
const STANDBY_INFO = 'Shown for information; the planner does not use standby.'

/** The status sentence shown under a row. */
export function statusText(parameter: LearnedParameter): string {
    const standby = parameter.key === STANDBY_KEY
    switch (parameter.source) {
        case 'locked':
            return 'Locked to your value. Learning continues and is shown for comparison.'
        case 'expired':
            if (standby) return `Expired: no new valid estimate for 30 days. ${STANDBY_INFO}`
            return parameter.key === DISCHARGE_EFFICIENCY_KEY
                ? 'Expired: no new valid estimate for 30 days. The built-in default is used.'
                : 'Expired: no new valid estimate for 30 days. The configured efficiencies are used.'
        case 'learned': {
            const changed = parameter.applied_at ? `Last changed ${formatDate(parameter.applied_at)}.` : ''
            return standby ? `${changed} ${STANDBY_INFO}`.trim() : changed
        }
        case 'default':
            return 'Built-in default (this value cannot be measured). Lock it to use your own.'
        default:
            if (standby) {
                return parameter.status_note
                    ? `Not measured yet: ${parameter.status_note}. ${STANDBY_INFO}`
                    : `Not measured yet. ${STANDBY_INFO}`
            }
            return parameter.status_note
                ? `Nothing learned yet: ${parameter.status_note}. The configured efficiencies are used.`
                : 'Nothing learned yet. The configured efficiencies are used.'
    }
}

/**
 * The headline value of a row: the number in effect for this parameter, or a dash when there is none.
 * The round-trip efficiency and charge loss have no configured number of their own (the configuration
 * only holds the combined charge and discharge efficiencies), so a dash is the honest value for them
 * and `valueCaption` says what the planner uses instead.
 */
export function valueText(parameter: LearnedParameter): string {
    return formatValue(parameter, parameter.effective_value)
}

/** A short note under the headline value when it is a dash. */
export function valueCaption(parameter: LearnedParameter): string | null {
    if (parameter.effective_value !== null) return null
    return parameter.key === STANDBY_KEY ? 'not measured yet' : 'configured efficiencies in use'
}

/** Names of the missing components as shown on the cards ("Battery round-trip efficiency, ..."). */
export function missingText(missing: string[], parameters: Pick<LearnedParameter, 'key' | 'label'>[]): string {
    if (missing.length === 0) return 'nothing'
    const labels = new Map(parameters.map((p) => [p.key, p.label]))
    return missing.map((key) => labels.get(key) ?? key.replace(/_/g, ' ')).join(', ')
}
