import { useEffect, useState } from 'react'
import { Link } from 'react-router-dom'
import { Gauge, PauseCircle, ShieldAlert, ShieldCheck } from 'lucide-react'
import Card from './Card'
import { Api, type LoadBalancerStatusResponse } from '../lib/api'
import { useSocket } from '../lib/hooks'

// eslint-disable-next-line react-refresh/only-export-components -- pure data, reused by PowerFlowTabs
export const STATE_LABELS: Record<string, string> = {
    disabled: 'Disabled',
    idle: 'Within Limits',
    throttling: 'Throttling',
    shedding: 'Shedding Loads',
    paused: 'Paused',
    stale_fallback: 'Sensor Stale',
}

const STATE_COLORS: Record<string, string> = {
    idle: 'text-good',
    throttling: 'text-accent',
    shedding: 'text-bad',
    paused: 'text-bad',
    stale_fallback: 'text-bad',
}

// eslint-disable-next-line react-refresh/only-export-components -- pure data, reused by PowerFlowTabs
export const EV_STATE_LABELS: Record<string, string> = {
    idle: 'Idle',
    throttling: 'Throttling',
    paused: 'Paused',
    stale_fallback: 'Sensor Stale',
}

const EV_STATE_DOTS: Record<string, string> = {
    idle: 'bg-good',
    throttling: 'bg-accent',
    paused: 'bg-bad',
    stale_fallback: 'bg-bad',
}

// eslint-disable-next-line react-refresh/only-export-components -- pure helper, tested directly
export function phaseColor(currentA: number, fuseA: number, marginPercent: number): string {
    if (currentA > fuseA) return 'bg-bad'
    if (currentA >= (fuseA * marginPercent) / 100) return 'bg-accent'
    return 'bg-good'
}

// eslint-disable-next-line react-refresh/only-export-components -- pure helper, tested directly
export function chargerSetpointText(ev: LoadBalancerStatusResponse['ev'][number]): string {
    if (ev.setpoint_a === null) return 'Paused'
    const drawing = measuredDrawText(ev)
    if (ev.planned_target_a !== null && ev.planned_target_a !== ev.setpoint_a) {
        return `${ev.setpoint_a}A (planned ${ev.planned_target_a}A)${drawing}`
    }
    return `${ev.setpoint_a}A${drawing}`
}

/** load-balancer-graceful-degradation 6.4: "1-phase on L1 — relieving L3". */
// eslint-disable-next-line react-refresh/only-export-components -- pure helper, tested directly
export function reliefText(ev: LoadBalancerStatusResponse['ev'][number]): string {
    if (ev.relief_reason) return ev.relief_reason
    return `1-phase on L${ev.phase_1_line ?? 1} — relieving an overloaded phase`
}

/** ev-measured-draw: ", drawing X A" when the car's measured draw is known. */
function measuredDrawText(ev: LoadBalancerStatusResponse['ev'][number]): string {
    if (ev.measured_a === null || ev.measured_a === undefined) return ''
    return `, drawing ${ev.measured_a.toFixed(1)}A`
}

/** excess-pv-priority-dispatch 4.4: "Surplus charging: X kW available -> charging at Y A (N-phase)". */
function SurplusEvRow({
    ev,
    measuredSurplusKw,
}: {
    ev: LoadBalancerStatusResponse['ev'][number]
    measuredSurplusKw?: number | null
}) {
    const surplusText =
        measuredSurplusKw !== null && measuredSurplusKw !== undefined
            ? `${measuredSurplusKw.toFixed(1)} kW available`
            : 'Surplus charging'
    const dispatchText =
        ev.setpoint_a !== null
            ? `charging at ${ev.setpoint_a}A${ev.phase_mode ? ` (${ev.phase_mode}-phase)` : ''}${measuredDrawText(ev)}`
            : 'paused'

    return (
        <div className="flex items-start justify-between gap-2 rounded-lg border border-line/20 bg-surface2/50 px-3 py-2 text-[11px]">
            <div className="min-w-0 break-words">
                <div className="flex items-center gap-2">
                    <span className={`h-1.5 w-1.5 shrink-0 rounded-full ${ev.paused ? 'bg-bad' : 'bg-good'}`} />
                    <span className="break-words font-semibold text-text" title={ev.charger_name}>
                        {ev.charger_name}
                    </span>
                </div>
                <div className="mt-0.5 text-muted">
                    {surplusText} → {dispatchText}
                </div>
                {ev.paused && ev.surplus_reason && (
                    <div className="mt-0.5 text-[10px] text-bad">{ev.surplus_reason}</div>
                )}
            </div>
        </div>
    )
}

// eslint-disable-next-line react-refresh/only-export-components -- pure helper, tested directly
export function formatAge(ageSeconds: number): string {
    if (ageSeconds < 60) return `${Math.max(0, Math.round(ageSeconds))}s ago`
    if (ageSeconds < 3600) return `${Math.floor(ageSeconds / 60)}m ago`
    return `${Math.floor(ageSeconds / 3600)}h ago`
}

export default function LoadBalancerStatusCard() {
    const [status, setStatus] = useState<LoadBalancerStatusResponse | null>(null)
    // Timestamp (ms epoch) of the latest received payload, for "updated Xs ago"
    const [lastUpdatedAt, setLastUpdatedAt] = useState<number | null>(null)
    const [nowMs, setNowMs] = useState<number>(() => Date.now())

    useEffect(() => {
        Api.executor
            .loadBalancerStatus()
            .then((s) => {
                setStatus(s)
                setLastUpdatedAt(Date.now())
            })
            .catch((err) => console.error('Failed to load load-balancer status', err))
    }, [])

    useSocket('live_metrics', (data: unknown) => {
        const payload = data as { load_balancing?: LoadBalancerStatusResponse; timestamp?: string }
        if (payload.load_balancing) {
            setStatus(payload.load_balancing)
            const ts = payload.timestamp ? Date.parse(payload.timestamp) : NaN
            setLastUpdatedAt(Number.isNaN(ts) ? Date.now() : ts)
        }
    })

    // Keep the freshness indicator ticking continuously.
    useEffect(() => {
        const timer = setInterval(() => setNowMs(Date.now()), 1000)
        return () => clearInterval(timer)
    }, [])

    if (!status) {
        return (
            <div className="grid shrink-0 grid-cols-1 gap-3 lg:grid-cols-3">
                <Card className="min-w-0 p-3 md:p-4 lg:col-span-2">
                    <div className="animate-pulse text-muted text-sm">Loading load balancer status…</div>
                </Card>
                <Card className="min-w-0 p-3 md:p-4">
                    <div className="text-xs font-bold uppercase tracking-wider text-muted">Controlled Loads</div>
                    <p className="mt-2 text-[11px] text-muted">Loading…</p>
                </Card>
            </div>
        )
    }

    if (!status.enabled || status.state === 'disabled') {
        // excess-pv-priority-dispatch 4.4: surplus-mode chargers still need to
        // surface here even when fuse protection itself is off/unconfigured.
        const surplusOnlyEv = status.ev.filter((ev) => ev.surplus_mode)
        return (
            <div className="grid shrink-0 grid-cols-1 gap-3 lg:grid-cols-3">
                <Card className="min-w-0 p-3 md:p-4 lg:col-span-2">
                    <div className="flex flex-wrap items-start gap-3">
                        <div className="p-2 rounded-lg bg-surface2 text-muted">
                            <Gauge size={18} />
                        </div>
                        <div className="min-w-0 flex-1">
                            <div className="text-sm font-semibold text-text">Load Balancing is disabled</div>
                            <p className="text-[11px] text-muted mt-0.5">
                                Enable it in Settings once your main fuse rating and per-phase current sensors are
                                configured to protect your fuse in real time.
                            </p>
                        </div>
                        <Link
                            to="/settings?tab=load-balancing"
                            className="shrink-0 text-xs font-semibold text-accent hover:underline whitespace-nowrap"
                        >
                            Go to Settings
                        </Link>
                    </div>
                </Card>
                <Card className="min-w-0 p-3 md:p-4">
                    <div className="text-xs font-bold uppercase tracking-wider text-muted">Controlled Loads</div>
                    <div
                        role="region"
                        aria-label="Controlled loads"
                        className="mt-2 min-w-0 space-y-1.5 lg:max-h-[160px] lg:overflow-y-auto lg:pr-1"
                    >
                        {surplusOnlyEv.length > 0 ? (
                            surplusOnlyEv.map((ev) => (
                                <SurplusEvRow
                                    key={ev.charger_id}
                                    ev={ev}
                                    measuredSurplusKw={status.measured_surplus_kw}
                                />
                            ))
                        ) : (
                            <p className="text-[11px] text-muted">No controlled loads.</p>
                        )}
                    </div>
                </Card>
            </div>
        )
    }

    const fuseA = status.main_fuse_a ?? 0
    const margin = status.target_margin_percent ?? 85
    const shedLoads = status.shed.filter((s) => s.shed)
    const stateColor = STATE_COLORS[status.state] || 'text-muted'
    const StateIcon = status.state === 'idle' ? ShieldCheck : status.state === 'paused' ? PauseCircle : ShieldAlert

    // Freshness: quiet near-zero bars must stay distinguishable from a dead
    // feed. Stale once the payload age materially exceeds the tick interval.
    const tickIntervalS = status.tick_interval_s ?? 300
    const ageSeconds = lastUpdatedAt !== null ? (nowMs - lastUpdatedAt) / 1000 : null
    const isStale = ageSeconds !== null && ageSeconds > Math.max(3 * tickIntervalS, 15)

    return (
        <div className="grid shrink-0 grid-cols-1 gap-3 lg:grid-cols-3">
            <Card className="min-w-0 space-y-2.5 p-3 md:p-4 lg:col-span-2">
                <div className="flex flex-wrap items-center justify-between gap-x-3 gap-y-1">
                    <div className="flex min-w-0 flex-wrap items-center gap-2">
                        <Gauge size={16} className="text-muted" />
                        <span className="text-xs font-bold uppercase tracking-wider text-muted">Load Balancing</span>
                        {ageSeconds !== null && (
                            <span
                                data-testid="lb-freshness"
                                className={`text-[10px] font-medium ${
                                    isStale ? 'rounded bg-bad/10 px-1.5 py-0.5 font-bold text-bad' : 'text-muted'
                                }`}
                            >
                                {isStale
                                    ? `stale — last update ${formatAge(ageSeconds)}`
                                    : `updated ${formatAge(ageSeconds)}`}
                            </span>
                        )}
                    </div>
                    <div
                        className={`flex shrink-0 items-center gap-1.5 text-xs font-bold uppercase tracking-wide ${stateColor}`}
                    >
                        <StateIcon size={14} />
                        {STATE_LABELS[status.state] || status.state}
                    </div>
                </div>

                <div className="grid min-w-0 grid-cols-1 gap-2.5 sm:grid-cols-3 sm:gap-3">
                    {[1, 2, 3].map((phase) => {
                        const currentA = status.phase_current_a[String(phase)] ?? status.phase_current_a[phase] ?? 0
                        const pct = fuseA > 0 ? Math.min(100, (currentA / fuseA) * 100) : 0
                        return (
                            <div key={phase} className="min-w-0">
                                <div className="mb-1 flex min-w-0 flex-wrap items-center justify-between gap-x-1 text-[10px] text-muted">
                                    <span className="font-bold">L{phase}</span>
                                    <span
                                        className="whitespace-nowrap font-mono text-right"
                                        title={`Raw current: ${currentA.toFixed(3)}A`}
                                    >
                                        {currentA.toFixed(1)} / {fuseA} A
                                    </span>
                                    <span className="sr-only" data-testid={`lb-raw-l${phase}`}>
                                        {currentA.toFixed(3)}A
                                    </span>
                                </div>
                                <div className="relative h-2 overflow-hidden rounded-full bg-surface2">
                                    <div
                                        className={`h-full rounded-full transition-all duration-500 ${phaseColor(currentA, fuseA, margin)}`}
                                        style={{ width: `${pct}%` }}
                                    />
                                    <div
                                        className="absolute top-0 h-full w-px bg-line/60"
                                        style={{ left: `${margin}%` }}
                                        title={`Target safety margin (${margin}%)`}
                                    />
                                </div>
                            </div>
                        )
                    })}
                </div>
            </Card>

            <Card className="min-w-0 p-3 md:p-4">
                <div className="text-xs font-bold uppercase tracking-wider text-muted">Controlled Loads</div>
                <div
                    role="region"
                    aria-label="Controlled loads"
                    className="mt-2 min-w-0 space-y-1.5 lg:max-h-[180px] lg:overflow-y-auto lg:pr-1"
                >
                    {status.ev.map((ev) => (
                        <div
                            key={ev.charger_id}
                            className="flex min-w-0 items-start justify-between gap-2 rounded-lg border border-line/20 bg-surface2/50 px-2 py-1.5 text-[11px]"
                        >
                            <div className="flex min-w-0 flex-1 items-start gap-2">
                                <span
                                    className={`mt-1 h-1.5 w-1.5 shrink-0 rounded-full ${EV_STATE_DOTS[ev.state] || 'bg-muted'}`}
                                />
                                <div className="min-w-0 flex-1">
                                    <div className="break-words font-semibold text-text" title={ev.charger_name}>
                                        {ev.charger_name}
                                    </div>
                                    {ev.relief_1p && (
                                        <div
                                            className="mt-0.5 break-words text-[10px] font-semibold text-warn"
                                            data-testid="lb-relief"
                                        >
                                            {reliefText(ev)}
                                        </div>
                                    )}
                                    {ev.reason && !(ev.relief_1p && ev.reason === ev.relief_reason) && (
                                        <div className="mt-0.5 break-words text-[10px] text-muted">{ev.reason}</div>
                                    )}
                                    {ev.surplus_mode && (
                                        <div className="mt-0.5 break-words text-[10px] text-muted">
                                            Surplus charging
                                            {status.measured_surplus_kw !== null &&
                                            status.measured_surplus_kw !== undefined
                                                ? `: ${status.measured_surplus_kw.toFixed(1)} kW available`
                                                : ''}
                                            {ev.phase_mode ? ` (${ev.phase_mode}-phase)` : ''}
                                            {ev.paused && ev.surplus_reason ? ` — ${ev.surplus_reason}` : ''}
                                        </div>
                                    )}
                                </div>
                            </div>
                            <div className="w-[42%] min-w-0 shrink-0 text-right">
                                <div className="break-words font-mono text-text">{chargerSetpointText(ev)}</div>
                                <div className="text-[10px] font-bold uppercase tracking-wide text-muted">
                                    {EV_STATE_LABELS[ev.state] || ev.state}
                                </div>
                            </div>
                        </div>
                    ))}
                    {shedLoads.map((load) => (
                        <div
                            key={load.load_id}
                            className="rounded-lg border border-bad/30 bg-bad/10 px-2 py-1.5 text-[11px] text-bad"
                        >
                            <div className="break-words font-semibold">Shed: {load.load_id}</div>
                            {load.reason && <div className="mt-0.5 break-words">{load.reason}</div>}
                        </div>
                    ))}
                    {status.ev.length === 0 && shedLoads.length === 0 && (
                        <p className="text-[11px] text-muted">No controlled loads.</p>
                    )}
                </div>
            </Card>
        </div>
    )
}
