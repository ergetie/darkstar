import { Link } from 'react-router-dom'
import { Gauge } from 'lucide-react'
import type { LoadBalancerStatusResponse } from '../lib/api'
import { phaseColor, STATE_LABELS, EV_STATE_LABELS } from './LoadBalancerStatusCard'

export default function LoadBalancerCompactView({ status }: { status: LoadBalancerStatusResponse | null }) {
    if (!status) {
        return <div className="p-4 text-xs text-muted animate-pulse">Loading load balancer status…</div>
    }

    const fuseA = status.main_fuse_a ?? 0
    const margin = status.resume_margin_percent ?? 90
    const activeEv = status.ev.filter((ev) => ev.state !== 'idle')
    const shedLoads = status.shed.filter((s) => s.shed)

    return (
        <div className="w-full h-full flex flex-col gap-2.5 p-3 text-[11px] overflow-y-auto custom-scrollbar">
            <div className="flex items-center justify-between">
                <div className="flex items-center gap-1.5">
                    <Gauge size={13} className="text-muted" />
                    <span className="font-semibold text-text">{STATE_LABELS[status.state] || status.state}</span>
                </div>
                <Link to="/executor" className="text-[10px] font-semibold text-accent hover:underline">
                    Details →
                </Link>
            </div>
            {status.reason && <p className="text-muted text-[10px] -mt-1.5">{status.reason}</p>}

            <div className="space-y-2">
                {[1, 2, 3].map((phase) => {
                    const currentA = status.phase_current_a[String(phase)] ?? status.phase_current_a[phase] ?? 0
                    const pct = fuseA > 0 ? Math.min(100, (currentA / fuseA) * 100) : 0
                    return (
                        <div key={phase}>
                            <div className="flex items-center justify-between text-[10px] text-muted mb-0.5">
                                <span className="font-bold">L{phase}</span>
                                <span className="font-mono">
                                    {currentA.toFixed(1)}A / {fuseA}A
                                </span>
                            </div>
                            <div className="h-1.5 rounded-full bg-surface2 overflow-hidden">
                                <div
                                    className={`h-full rounded-full transition-all duration-500 ${phaseColor(currentA, fuseA, margin)}`}
                                    style={{ width: `${pct}%` }}
                                />
                            </div>
                        </div>
                    )
                })}
            </div>

            {activeEv.length > 0 && (
                <div className="space-y-1">
                    {activeEv.map((ev) => (
                        <div
                            key={ev.charger_id}
                            className="flex items-center justify-between gap-2 rounded bg-surface2/50 border border-line/20 px-2 py-1"
                        >
                            <span className="truncate text-text font-medium">{ev.charger_name}</span>
                            <span className="shrink-0 text-muted text-[10px]">
                                {EV_STATE_LABELS[ev.state] || ev.state}
                            </span>
                        </div>
                    ))}
                </div>
            )}

            {shedLoads.length > 0 && (
                <div className="rounded bg-bad/10 border border-bad/30 text-bad px-2 py-1">
                    Shed: {shedLoads.map((s) => s.load_id).join(', ')}
                </div>
            )}
        </div>
    )
}
