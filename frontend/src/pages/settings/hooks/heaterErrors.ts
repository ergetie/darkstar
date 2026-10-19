/**
 * Water heater validation errors from a rejected save, kept outside any single
 * settings tab: the backend validates the whole config, so the save may have been
 * triggered from another tab than the one that can fix it.
 */
export const HEATER_ERROR_PREFIX = 'water_heaters.'
export const HEATER_ERRORS_EVENT = 'heater-errors-changed'

let pending: Record<string, string> = {}

export function getPendingHeaterErrors(): Record<string, string> {
    return { ...pending }
}

export function setPendingHeaterErrors(errors: Record<string, string>): void {
    pending = { ...errors }
    window.dispatchEvent(new Event(HEATER_ERRORS_EVENT))
}

export function hasPendingHeaterErrors(): boolean {
    return Object.keys(pending).length > 0
}
