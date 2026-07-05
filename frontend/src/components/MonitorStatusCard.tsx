import { useEffect, useState } from 'react'
import { Activity, CheckCircle, AlertTriangle, AlertCircle, MinusCircle } from 'lucide-react'
import { Api, MonitorStatus } from '../lib/api'
import Card from './Card'

const StatusIcon = ({ status }: { status: string }) => {
    if (status === 'pass') return <CheckCircle className="h-3 w-3 text-emerald-400" />
    if (status === 'violation') return <AlertCircle className="h-3 w-3 text-rose-400" />
    return <MinusCircle className="h-3 w-3 text-muted" />
}

export default function MonitorStatusCard() {
    const [status, setStatus] = useState<MonitorStatus | null>(null)
    const [error, setError] = useState(false)
    const [loading, setLoading] = useState(true)

    useEffect(() => {
        const fetchStatus = async () => {
            try {
                const res = await Api.monitors()
                setStatus(res)
                setError(false)
            } catch (err) {
                console.error('Failed to fetch monitor status:', err)
                setError(true)
            } finally {
                setLoading(false)
            }
        }

        fetchStatus()
        const interval = setInterval(fetchStatus, 60000)
        return () => clearInterval(interval)
    }, [])

    if (loading) {
        return (
            <Card className="flex flex-col h-full bg-surface p-4">
                <div className="flex items-center gap-2 mb-4">
                    <Activity className="h-4 w-4 text-accent" />
                    <span className="text-xs font-medium text-text">Runtime Monitors</span>
                </div>
                <div className="flex-1 flex items-center justify-center">
                    <div className="text-[11px] text-muted">Loading...</div>
                </div>
            </Card>
        )
    }

    if (error || !status) {
        return (
            <Card className="flex flex-col h-full bg-surface p-4">
                <div className="flex items-center gap-2 mb-4">
                    <Activity className="h-4 w-4 text-accent" />
                    <span className="text-xs font-medium text-text">Runtime Monitors</span>
                </div>
                <div className="flex-1 flex items-center justify-center gap-2 text-[11px] text-rose-400">
                    <AlertTriangle className="h-3.5 w-3.5" />
                    <span>Unable to reach /api/system/monitors</span>
                </div>
            </Card>
        )
    }

    const invariantEntries = Object.entries(status.invariants)

    return (
        <Card className="flex flex-col h-full bg-surface p-4">
            <div className="flex items-center justify-between mb-4">
                <div className="flex items-center gap-2">
                    <Activity className="h-4 w-4 text-accent" />
                    <span className="text-xs font-medium text-text">Runtime Monitors</span>
                </div>
                <div className="flex items-center gap-1.5">
                    <span className="text-[10px] text-muted">
                        {status.running ? 'running' : 'stopped'} • {status.healthy ? 'healthy' : 'unhealthy'}
                    </span>
                    <div
                        className={`h-1.5 w-1.5 rounded-full ${status.healthy ? 'bg-emerald-400' : 'bg-rose-400'} animate-pulse`}
                    />
                </div>
            </div>

            <div className="flex-1 grid gap-2">
                {invariantEntries.length === 0 && <div className="text-[11px] text-muted">No invariants reported.</div>}
                {invariantEntries.map(([key, inv]) => (
                    <div
                        key={key}
                        className="flex items-center justify-between p-2 rounded bg-surface2/30 border border-line/30"
                    >
                        <div>
                            <div className="text-[11px] font-medium text-text">{inv.name}</div>
                            <div className="text-[9px] text-muted">{inv.detail}</div>
                        </div>
                        <StatusIcon status={inv.status} />
                    </div>
                ))}
            </div>

            <div className="mt-3 pt-2 border-t border-line/30">
                <div className="text-[10px] text-muted mb-1">Active Violations ({status.active_violations.length})</div>
                {status.active_violations.length === 0 ? (
                    <div className="text-[10px] text-muted">None</div>
                ) : (
                    <div className="grid gap-1">
                        {status.active_violations.map((v) => (
                            <div key={v.invariant} className="text-[10px] text-rose-400">
                                {v.invariant} — since {new Date(v.first_detected_at).toLocaleString()}: {v.detail}
                            </div>
                        ))}
                    </div>
                )}
                {status.last_error && (
                    <div className="mt-1 text-[10px] text-amber-400">Last error: {status.last_error}</div>
                )}
            </div>
        </Card>
    )
}
