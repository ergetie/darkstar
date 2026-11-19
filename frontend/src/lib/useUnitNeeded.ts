import { useCallback, useEffect, useMemo, useState } from 'react'
import { Api, type UnitNeededEntry } from './api'

export const UNIT_NEEDED_DEBOUNCE_MS = 300

export type UnitNeededState = {
    /** The backend's list for the latest draft config that finished loading. */
    unitNeeded: readonly UnitNeededEntry[]
    /**
     * Whether the W/kW selector shows for `entityId`: exactly when the backend lists it. The
     * backend lists every unitless power sensor, with or without an override, so a chosen unit
     * stays visible and editable.
     */
    isChoiceVisible: (entityId: string) => boolean
}

/**
 * Asks the backend which power sensors of a draft config report no unit.
 *
 * The backend alone decides what a power sensor is, so the frontend sends the whole draft and
 * never filters by field. Requests are debounced and rerun whenever the draft changes,
 * including when the user picks another entity or a W/kW override.
 */
export function useUnitNeeded(draftConfig: Record<string, unknown> | null): UnitNeededState {
    const [unitNeeded, setUnitNeeded] = useState<readonly UnitNeededEntry[]>([])
    const configKey = useMemo(() => (draftConfig ? JSON.stringify(draftConfig) : null), [draftConfig])

    useEffect(() => {
        if (configKey === null) return
        let cancelled = false
        const timer = setTimeout(async () => {
            try {
                const response = await Api.setup.sensorUnits(JSON.parse(configKey) as Record<string, unknown>)
                if (cancelled) return
                const entries = response.unit_needed ?? []
                setUnitNeeded(entries)
            } catch (error) {
                // Keep the previous answer: the selector is a hint and must never block editing.
                console.warn('Could not check power sensor units', error)
            }
        }, UNIT_NEEDED_DEBOUNCE_MS)
        return () => {
            cancelled = true
            clearTimeout(timer)
        }
    }, [configKey])

    const isChoiceVisible = useCallback(
        (entityId: string) => unitNeeded.some((entry) => entry.entity_id === entityId),
        [unitNeeded],
    )

    return { unitNeeded, isChoiceVisible }
}
