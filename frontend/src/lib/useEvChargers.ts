import { useCallback, useEffect, useRef, useState } from 'react'
import { Api, type EVChargerState } from './api'
import { useSocket, useSocketStatus } from './hooks'

/**
 * Per-charger status from GET /api/ev/chargers (goal, manual charge, type,
 * current limits), refreshed whenever a goal, the plan or a manual charge
 * changes (or a replan fails), and refetched when the socket reconnects after
 * a drop so events missed while suspended are reconciled. Returns an empty
 * list while `enabled` is false. Also exposes `loading` (a fetch is in flight)
 * and `error` (the last fetch failed; cleared by the next success).
 */
export function useEvChargers(enabled: boolean) {
    const [chargers, setChargers] = useState<EVChargerState[]>([])
    const [loading, setLoading] = useState(false)
    const [error, setError] = useState<string | null>(null)
    const seqRef = useRef(0)

    const refresh = useCallback(async () => {
        if (!enabled) return
        const seq = ++seqRef.current
        setLoading(true)
        try {
            const data = await Api.ev.chargers()
            if (seq !== seqRef.current) return // a newer request has since started
            setChargers(data)
            setError(null)
        } catch (err) {
            if (seq !== seqRef.current) return
            console.error('Failed to fetch EV chargers', err)
            setError('Failed to load chargers')
        } finally {
            if (seq === seqRef.current) setLoading(false)
        }
    }, [enabled])

    useEffect(() => {
        let active = true
        Promise.resolve().then(() => {
            if (!active) return
            if (enabled) refresh()
            else {
                seqRef.current++ // discard any in-flight response
                setChargers([])
                setLoading(false)
                setError(null)
            }
        })
        return () => {
            active = false
        }
    }, [enabled, refresh])

    const socketStatus = useSocketStatus()
    const wasConnectedRef = useRef(false)
    const refreshRef = useRef(refresh)
    useEffect(() => {
        refreshRef.current = refresh
    }, [refresh])
    useEffect(() => {
        if (socketStatus !== 'connected') return
        // Reconnect after a drop (not the initial connect, which the mount fetch covers).
        if (wasConnectedRef.current) refreshRef.current()
        wasConnectedRef.current = true
    }, [socketStatus])

    useSocket('ev_manual_charge_updated', refresh)
    useSocket('ev_schedule_changed', refresh)
    useSocket('schedule_updated', refresh)
    // A failed goal-triggered replan clears plan_pending server-side.
    useSocket('planner_error', refresh)

    return { chargers: enabled ? chargers : [], loading: enabled && loading, error: enabled ? error : null, refresh }
}
