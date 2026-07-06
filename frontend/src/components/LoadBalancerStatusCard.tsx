import { useEffect, useState } from 'react'
import { Link } from 'react-router-dom'
import { Gauge, PauseCircle, ShieldAlert, ShieldCheck } from 'lucide-react'
import Card from './Card'
import { Api, type LoadBalancerStatusResponse } from '../lib/api'
import { useSocket } from '../lib/hooks'

const STATE_LABELS: Record<string, string> = {
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

const EV_STATE_LABELS: Record<string, string> = {
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

function phaseColor(currentA: number, fuseA: number, marginPercent: number): string {
    if (currentA > fuseA) return 'bg-bad'
    if (currentA >= (fuseA * marginPercent) / 100) return 'bg-accent'
    return 'bg-good'
}

function chargerSetpointText(ev: LoadBalancerStatusResponse['ev'][number]): string {
    if (ev.setpoint_a === null) return 'Paused'
    if (ev.planned_target_a !== null && ev.planned_target_a !== ev.setpoint_a) {
        return `${ev.setpoint_a}A (planned ${ev.planned_target_a}A)`
    }
    return `${ev.setpoint_a}A`
}

export default function LoadBalancerStatusCard() {
    const [status, setStatus] = useState<LoadBalancerStatusResponse | null>(null)

    useEffect(() => {
        Api.executor
            .loadBalancerStatus()
            .then(setStatus)
            .catch((err) => console.error('Failed to load load-balancer status', err))
    }, [])

    useSocket('live_metrics', (data: unknown) => {
        const payload = data as { load_balancing?: LoadBalancerStatusResponse }
        if (payload.load_balancing) setStatus(payload.load_balancing)
    })

    if (!status) {
        return (
            <Card className="p-4 md:p-5">
                <div className="animate-pulse text-muted text-sm">Loading load balancer status…</div>
            </Card>
        )
    }

    if (!status.enabled || status.state === 'disabled') {
        return (
            <Card className="p-4 md:p-5">
                <div className="flex items-center gap-3">
                    <div className="p-2 rounded-lg bg-surface2 text-muted">
                        <Gauge size={18} />
                    </div>
                    <div className="flex-1">
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
        )
    }

    const fuseA = status.main_fuse_a ?? 0
    const margin = status.resume_margin_percent ?? 90
    const shedLoads = status.shed.filter((s) => s.shed)
    const stateColor = STATE_COLORS[status.state] || 'text-muted'
    const StateIcon = status.state === 'idle' ? ShieldCheck : status.state === 'paused' ? PauseCircle : ShieldAlert

    return (
        <Card className="p-4 md:p-5 space-y-4">
            <div className="flex items-center justify-between">
                <div className="flex items-center gap-2">
                    <Gauge size={16} className="text-muted" />
                    <span className="text-xs font-bold uppercase tracking-wider text-muted">Load Balancing</span>
                </div>
                <div className={`flex items-center gap-1.5 text-xs font-bold uppercase tracking-wide ${stateColor}`}>
                    <StateIcon size={14} />
                    {STATE_LABELS[status.state] || status.state}
                </div>
            </div>

            <div className="space-y-2.5">
                {[1, 2, 3].map((phase) => {
                    const currentA = status.phase_current_a[String(phase)] ?? status.phase_current_a[phase] ?? 0
                    const pct = fuseA > 0 ? Math.min(100, (currentA / fuseA) * 100) : 0
                    return (
                        <div key={phase}>
                            <div className="flex items-center justify-between text-[10px] text-muted mb-1">
                                <span className="font-bold">L{phase}</span>
                                <span className="font-mono">
                                    {currentA.toFixed(1)}A / {fuseA}A
                                </span>
                            </div>
                            <div className="relative h-2 rounded-full bg-surface2 overflow-hidden">
                                <div
                                    className={`h-full rounded-full transition-all duration-500 ${phaseColor(currentA, fuseA, margin)}`}
                                    style={{ width: `${pct}%` }}
                                />
                                <div
                                    className="absolute top-0 h-full w-px bg-line/60"
                                    style={{ left: `${margin}%` }}
                                    title={`Resume margin (${margin}%)`}
                                />
                            </div>
                        </div>
                    )
                })}
            </div>

            {status.ev.length > 0 && (
                <div className="space-y-1.5">
                    {status.ev.map((ev) => (
                        <div
                            key={ev.charger_id}
                            className="flex items-start justify-between gap-3 text-[11px] rounded-lg bg-surface2/50 border border-line/20 px-3 py-2"
                        >
                            <div className="flex items-center gap-2 min-w-0">
                                <span
                                    className={`h-1.5 w-1.5 shrink-0 rounded-full ${EV_STATE_DOTS[ev.state] || 'bg-muted'}`}
                                />
                                <div className="min-w-0">
                                    <div className="font-semibold text-text truncate">{ev.charger_name}</div>
                                    {ev.reason && <div className="text-muted text-[10px] mt-0.5">{ev.reason}</div>}
                                </div>
                            </div>
                            <div className="shrink-0 text-right">
                                <div className="font-mono text-text">{chargerSetpointText(ev)}</div>
                                <div className="text-[9px] font-bold uppercase tracking-wide text-muted">
                                    {EV_STATE_LABELS[ev.state] || ev.state}
                                </div>
                            </div>
                        </div>
                    ))}
                </div>
            )}

            {shedLoads.length > 0 && (
                <div className="text-[11px] rounded-lg bg-bad/10 border border-bad/30 text-bad px-3 py-2">
                    Shed: {shedLoads.map((s) => s.load_id).join(', ')}
                </div>
            )}

            {status.ev.length === 0 && shedLoads.length === 0 && status.state === 'idle' && (
                <p className="text-[11px] text-muted">All phases within limits.</p>
            )}
        </Card>
    )
}
