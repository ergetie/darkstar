import { createContext, useContext } from 'react'
import type { SensorUnit } from './api'

/**
 * What a shared entity picker needs to offer a W/kW choice for a power sensor.
 * Onboarding and Settings each provide one, built from their own draft config.
 */
export type SensorUnitControl = {
    /** True when the picker must show the W/kW selector for this selected entity. */
    isChoiceVisible: (entityId: string) => boolean
    /** The draft's `sensor_unit_overrides`, keyed by entity id. */
    overrides: Readonly<Record<string, SensorUnit>>
    /** Writes `sensor_unit_overrides.<entityId>` into the owner's draft config. */
    setOverride: (entityId: string, unit: SensorUnit) => void
}

export const SensorUnitContext = createContext<SensorUnitControl | null>(null)

/** The unit control of the enclosing onboarding wizard or settings tab, or null outside one. */
export function useSensorUnitControl(): SensorUnitControl | null {
    return useContext(SensorUnitContext) ?? null
}

const NO_OVERRIDES: Readonly<Record<string, SensorUnit>> = Object.freeze({})

/** The valid `sensor_unit_overrides` entries of a config; anything else is ignored. */
export function readUnitOverrides(config: unknown): Readonly<Record<string, SensorUnit>> {
    const raw = (config as { sensor_unit_overrides?: unknown } | null | undefined)?.sensor_unit_overrides
    if (!raw || typeof raw !== 'object' || Array.isArray(raw)) return NO_OVERRIDES
    const result: Record<string, SensorUnit> = {}
    for (const [entityId, unit] of Object.entries(raw)) {
        if (unit === 'W' || unit === 'kW') result[entityId] = unit
    }
    return result
}

/** Overrides after the user picks `unit` for `entityId`. */
export function withUnitOverride(
    overrides: Readonly<Record<string, SensorUnit>>,
    entityId: string,
    unit: SensorUnit,
): Record<string, SensorUnit> {
    return { ...overrides, [entityId]: unit }
}

/** The save patch for chosen overrides: the full map when it differs from the saved one, else nothing. */
export function unitOverridesPatch(
    saved: Readonly<Record<string, SensorUnit>>,
    draft: Readonly<Record<string, SensorUnit>> | null,
): Record<string, unknown> {
    if (!draft) return {}
    const canonical = (map: Readonly<Record<string, SensorUnit>>) => JSON.stringify(Object.entries(map).sort())
    return canonical(draft) === canonical(saved) ? {} : { sensor_unit_overrides: draft }
}

function isPlainObject(value: unknown): value is Record<string, unknown> {
    return value !== null && typeof value === 'object' && !Array.isArray(value)
}

/** Applies a save patch to a config the way the backend does: objects merge, everything else replaces. */
export function applyConfigPatch(
    config: Record<string, unknown>,
    patch: Record<string, unknown>,
): Record<string, unknown> {
    const result: Record<string, unknown> = { ...config }
    for (const [key, value] of Object.entries(patch)) {
        const current = result[key]
        result[key] = isPlainObject(current) && isPlainObject(value) ? applyConfigPatch(current, value) : value
    }
    return result
}
