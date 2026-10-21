import { useEffect, useState } from 'react'
import type { LoadBalancerStatusResponse } from '../lib/api'

export function useFuseStale(
    status: LoadBalancerStatusResponse | null,
    feedStale = false,
    includePhase = true,
): boolean {
    const [now, setNow] = useState(() => Date.now())
    useEffect(() => {
        const timer = setInterval(() => setNow(Date.now()), 1000)
        return () => clearInterval(timer)
    }, [])
    const sampledAt = status?.heat_sampled_at ? Date.parse(status.heat_sampled_at) : NaN
    return (
        Boolean(status?.enabled) &&
        (feedStale ||
            (includePhase && Object.values(status?.phase_heat_state ?? {}).includes('stale')) ||
            (Number.isFinite(sampledAt) &&
                (now - sampledAt) / 1000 > Math.max(3 * (status?.tick_interval_s ?? 300), 15)))
    )
}

export function fuseStatusLabel(status: LoadBalancerStatusResponse, stale: boolean): string | null {
    if (!status.enabled) return null
    if (stale) return 'Readings Stale'
    if (
        [...status.ev.map((ev) => ev.reason), status.battery?.reason, ...status.shed.map((load) => load.reason)].some(
            (reason) => reason?.includes('heat must cool below 50%'),
        )
    )
        return 'Cooling Hold'
    if (status.state === 'idle' && Object.values(status.phase_heat_state ?? {}).includes('heating'))
        return 'Monitoring Overload'
    return null
}
