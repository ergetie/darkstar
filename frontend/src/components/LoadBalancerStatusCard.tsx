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

function phaseColor(currentA: number, fuseA: number, marginPercent: number): string {
    if (currentA > fuseA) return 'bg-bad'
    if (currentA >= (fuseA * marginPercent) / 100) return 'bg-accent'
    return 'bg-good'
}

function limitationReason(status: LoadBalancerStatusResponse): string | null {
    const limited = status.ev.find(
        (ev) => ev.setpoint_a !== null && ev.planned_target_a !== null && ev.setpoint_a < ev.planned_target_a,
    )
    if (!limited) return null

    // Name the phase with the least headroom as "the reason"
    const worstPhase = Object.entries(status.phase_headroom_a).sort((a, b) => a[1] - b[1])[0]
    const phaseLabel = worstPhase ? `L${worstPhase[0]}` : null

    return phaseLabel
        ? `EV limited to ${limited.setpoint_a}A (planned ${limited.planned_target_a}A) because of ${phaseLabel}`
        : `EV limited to ${limited.setpoint_a}A (planned ${limited.planned_target_a}A)`
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
    const reason = limitationReason(status)
    const shedLoads = status.shed.filter((s) => s.shed)
    const pausedEv = status.ev.find((ev) => ev.state === 'paused')
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

            {reason && (
                <div className="text-[11px] rounded-lg bg-accent/10 border border-accent/30 text-accent px-3 py-2">
                    {reason}
                </div>
            )}

            {pausedEv && (
                <div className="text-[11px] rounded-lg bg-bad/10 border border-bad/30 text-bad px-3 py-2">
                    EV charging paused: {pausedEv.reason}
                </div>
            )}

            {shedLoads.length > 0 && (
                <div className="text-[11px] rounded-lg bg-bad/10 border border-bad/30 text-bad px-3 py-2">
                    Shed: {shedLoads.map((s) => s.load_id).join(', ')}
                </div>
            )}

            {!reason && !pausedEv && shedLoads.length === 0 && status.state === 'idle' && (
                <p className="text-[11px] text-muted">All phases within limits.</p>
            )}
        </Card>
    )
}
