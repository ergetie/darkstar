import { useCallback, useEffect, useRef, useState } from 'react'
import { Api, ApiError, type UpdaterChannel, type UpdaterStatus } from './api'

const REFRESH_MS = 30 * 60 * 1000
/** How long an update counts as running after the last time the updater reported one. */
const IN_FLIGHT_EXPIRY_MS = 10 * 60 * 1000

export type UseUpdater = {
    /** False on installs without the update feature (HA add-on, no updater configured). */
    available: boolean
    status: UpdaterStatus | null
    /** Last request error shown in the card (e.g. apply refused). */
    error: string | null
    busy: boolean
    /**
     * An update is running (or Darkstar is restarting as part of it). Survives the card closing
     * and unreachable replies, so no host command is suggested mid-update; expires after 10 minutes
     * without the updater reporting an update in progress.
     */
    applyInFlight: boolean
    refresh: () => Promise<UpdaterStatus | null>
    check: () => Promise<void>
    setChannel: (channel: UpdaterChannel) => Promise<void>
    /** Resolves true when the updater accepted the request. */
    apply: () => Promise<boolean>
}

function errorText(error: unknown): string {
    if (error instanceof ApiError) {
        const detail = error.detail as { error?: string; files?: string[] } | undefined
        if (detail && typeof detail === 'object' && typeof detail.error === 'string') {
            return detail.files?.length ? `${detail.error}: ${detail.files.join(', ')}` : detail.error
        }
    }
    return error instanceof Error ? error.message : String(error)
}

/** Update status for the whole app: loads once, then every 30 minutes. */
export function useUpdater(): UseUpdater {
    const [available, setAvailable] = useState(false)
    const [status, setStatus] = useState<UpdaterStatus | null>(null)
    const [error, setError] = useState<string | null>(null)
    const [busy, setBusy] = useState(false)
    const [applyInFlight, setApplyInFlight] = useState(false)
    const mounted = useRef(true)
    const expiry = useRef<number | undefined>(undefined)

    const clearInFlight = useCallback(() => {
        window.clearTimeout(expiry.current)
        expiry.current = undefined
        setApplyInFlight(false)
    }, [])

    const markInFlight = useCallback(() => {
        window.clearTimeout(expiry.current)
        expiry.current = window.setTimeout(() => {
            expiry.current = undefined
            if (mounted.current) setApplyInFlight(false)
        }, IN_FLIGHT_EXPIRY_MS)
        setApplyInFlight(true)
    }, [])

    useEffect(() => {
        mounted.current = true
        return () => {
            mounted.current = false
            window.clearTimeout(expiry.current)
        }
    }, [])

    const run = useCallback(
        async (call: () => Promise<UpdaterStatus>): Promise<UpdaterStatus | null> => {
            try {
                const next = await call()
                if (!mounted.current) return null
                setAvailable(true)
                setStatus(next)
                // An unreachable reply carries no apply data: it must not end the in-flight guard.
                if (next.reachable) {
                    const state = next.apply?.state
                    if (state === 'building' || state === 'restarting') markInFlight()
                    else clearInFlight()
                }
                return next
            } catch (e) {
                if (!mounted.current) return null
                // 404: feature not offered here. Anything else (incl. restart): keep last state.
                if (e instanceof ApiError && e.status === 404) setAvailable(false)
                throw e
            }
        },
        [markInFlight, clearInFlight],
    )

    const refresh = useCallback(() => run(Api.updater.status).catch(() => null), [run])

    useEffect(() => {
        const first = window.setTimeout(() => void refresh(), 0)
        const id = window.setInterval(() => void refresh(), REFRESH_MS)
        return () => {
            window.clearTimeout(first)
            window.clearInterval(id)
        }
    }, [refresh])

    const act = useCallback(
        async (call: () => Promise<UpdaterStatus>): Promise<boolean> => {
            setBusy(true)
            setError(null)
            try {
                await run(call)
                return true
            } catch (e) {
                if (mounted.current) setError(errorText(e))
                return false
            } finally {
                if (mounted.current) setBusy(false)
            }
        },
        [run],
    )

    return {
        available,
        status,
        error,
        busy,
        applyInFlight,
        refresh,
        check: async () => void (await act(Api.updater.check)),
        setChannel: async (channel) => void (await act(() => Api.updater.setChannel(channel))),
        apply: async () => {
            const accepted = await act(Api.updater.apply)
            if (accepted && mounted.current) markInFlight()
            return accepted
        },
    }
}
