import { useFuseStale, fuseStatusLabel } from './useFuseStatus'
import FuseHeatStatus from './FuseHeatStatus'
import { Link } from 'react-router-dom'
import { Gauge } from 'lucide-react'
import type { LoadBalancerStatusResponse } from '../lib/api'
import { batteryCapText, reliefText, STATE_LABELS, EV_STATE_LABELS } from './LoadBalancerStatusCard'

export default function LoadBalancerCompactView({ status }: { status: LoadBalancerStatusResponse | null }) {
    const stale = useFuseStale(status)
    if (!status) {
        return <div className="p-4 text-xs text-muted animate-pulse">Loading load balancer status…</div>
    }

    const activeEv = status.ev.filter((ev) => ev.state !== 'idle' || ev.relief_1p)
    const shedLoads = status.shed.filter((s) => s.shed)
    const battery = status.battery && status.battery.state !== 'idle' ? status.battery : null

    return (
        <div className="w-full h-full flex flex-col gap-2.5 p-3 text-[11px] overflow-y-auto custom-scrollbar">
            <div className="flex items-center justify-between">
                <div className="flex items-center gap-1.5">
                    <Gauge size={13} className="text-muted" />
                    <span className="font-semibold text-text">
                        {fuseStatusLabel(status, stale) ?? STATE_LABELS[status.state] ?? status.state}
                    </span>
                </div>
                <Link to="/executor" className="text-[10px] font-semibold text-accent hover:underline">
                    Details →
                </Link>
            </div>
            <FuseHeatStatus status={status} showReason />

            {activeEv.length > 0 && (
                <div className="space-y-1">
                    {activeEv.map((ev) => (
                        <div key={ev.charger_id} className="rounded bg-surface2/50 border border-line/20 px-2 py-1">
                            <div className="flex items-center justify-between gap-2">
                                <span className="truncate text-text font-medium">{ev.charger_name}</span>
                                <span className="shrink-0 text-muted text-[10px]">
                                    {EV_STATE_LABELS[ev.state] || ev.state}
                                </span>
                            </div>
                            {ev.relief_1p && (
                                <div className="text-warn text-[10px] font-semibold" data-testid="lb-compact-relief">
                                    {reliefText(ev)}
                                </div>
                            )}
                        </div>
                    ))}
                </div>
            )}

            {battery && (
                <div
                    className="rounded bg-surface2/50 border border-line/20 px-2 py-1"
                    data-testid="lb-compact-battery"
                >
                    <div className="flex items-center justify-between gap-2">
                        <span className="truncate text-text font-medium">House battery</span>
                        <span className="shrink-0 text-muted text-[10px]">
                            {EV_STATE_LABELS[battery.state] || battery.state}
                        </span>
                    </div>
                    <div className="text-muted text-[10px] font-mono">{batteryCapText(battery)}</div>
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
