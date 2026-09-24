import { useCallback, useEffect, useRef, useState } from 'react'
import { Api, type EVChargerState } from './api'
import { useSocket } from './hooks'

/**
 * Per-charger status from GET /api/ev/chargers (goal, manual charge, type,
 * current limits), refreshed whenever a goal, the plan or a manual charge
 * changes. Returns an empty list while `enabled` is false.
 */
export function useEvChargers(enabled: boolean) {
    const [chargers, setChargers] = useState<EVChargerState[]>([])
    const seqRef = useRef(0)

    const refresh = useCallback(async () => {
        if (!enabled) return
        const seq = ++seqRef.current
        try {
            const data = await Api.ev.chargers()
            if (seq === seqRef.current) setChargers(data)
        } catch (err) {
            console.error('Failed to fetch EV chargers', err)
        }
    }, [enabled])

    useEffect(() => {
        let active = true
        Promise.resolve().then(() => {
            if (!active) return
            if (enabled) refresh()
            else setChargers([])
        })
        return () => {
            active = false
        }
    }, [enabled, refresh])

    useSocket('ev_manual_charge_updated', refresh)
    useSocket('ev_schedule_changed', refresh)
    useSocket('schedule_updated', refresh)

    return { chargers: enabled ? chargers : [], refresh }
}
