import { useEffect, useState } from 'react'
import { Activity, Database, CheckCircle, AlertTriangle, AlertCircle, Clock, Server } from 'lucide-react'
import { Api, SystemHealthResponse } from '../lib/api'
import Card from './Card'

function StatusIcon({ status }: { status: string }) {
    if (status === 'success' || status === 'good' || status === 'graduate' || status === 'statistician') {
        return <CheckCircle className="h-3 w-3 text-emerald-400" />
    }
    if (status === 'warning' || status === 'infant') {
        return <AlertTriangle className="h-3 w-3 text-amber-400" />
    }
    return <AlertCircle className="h-3 w-3 text-rose-400" />
}

export default function SystemHealthCard() {
    const [health, setHealth] = useState<SystemHealthResponse | null>(null)
    const [loading, setLoading] = useState(true)

    useEffect(() => {
        const fetchHealth = async () => {
            try {
                const res = await Api.systemHealth()
                setHealth(res)
            } catch (err) {
                console.error('Failed to fetch system health:', err)
            } finally {
                setLoading(false)
            }
        }

        fetchHealth()
        // Refresh every minute
        const interval = setInterval(fetchHealth, 60000)
        return () => clearInterval(interval)
    }, [])

    if (loading || !health) {
        return (
            <Card className="flex flex-col h-full bg-surface">
                <div className="flex items-center gap-2 mb-4">
                    <Activity className="h-4 w-4 text-accent" />
                    <span className="text-xs font-medium text-text">System Health</span>
                </div>
                <div className="flex-1 flex items-center justify-center">
                    <div className="text-[11px] text-muted">Loading...</div>
                </div>
            </Card>
        )
    }

    return (
        <Card className="flex flex-col h-full bg-surface relative overflow-hidden group hover:border-line/80 transition-colors p-4">
            <div className="flex items-center justify-between mb-4">
                <div className="flex items-center gap-2">
                    <Activity className="h-4 w-4 text-accent" />
                    <span className="text-xs font-medium text-text">System Health</span>
                </div>
            </div>

            <div className="flex-1 grid gap-3">
                {/* Learning Stats */}
                <div className="flex items-center justify-between p-2 rounded bg-surface2/30 border border-line/30">
                    <div className="flex items-center gap-2">
                        <div className="h-6 w-6 rounded-full bg-purple-500/10 flex items-center justify-center">
                            <Clock className="h-3.5 w-3.5 text-purple-400" />
                        </div>
                        <div>
                            <div className="text-[11px] font-medium text-text">Learning</div>
                            <div className="text-[9px] text-muted capitalize">
                                {health.learning.total_runs} runs • {health.learning.status}
                            </div>
                        </div>
                    </div>
                    <StatusIcon status={health.learning.status} />
                </div>

                {/* Database Stats */}
                <div className="flex items-center justify-between p-2 rounded bg-surface2/30 border border-line/30">
                    <div className="flex items-center gap-2">
                        <div className="h-6 w-6 rounded-full bg-blue-500/10 flex items-center justify-center">
                            <Database className="h-3.5 w-3.5 text-blue-400" />
                        </div>
                        <div>
                            <div className="text-[11px] font-medium text-text">Database</div>
                            <div className="text-[9px] text-muted">
                                {health.database.size_mb} MB • {health.database.slot_plans_count} plans
                            </div>
                        </div>
                    </div>
                    <StatusIcon status={health.database.health} />
                </div>

                {/* Forecast Stats (REV F65 Phase 5d) */}
                <div className="flex items-center justify-between p-2 rounded bg-surface2/30 border border-line/30">
                    <div className="flex items-center gap-2">
                        <div className="h-6 w-6 rounded-full bg-amber-500/10 flex items-center justify-center">
                            <Activity className="h-3.5 w-3.5 text-amber-400" />
                        </div>
                        <div>
                            <div className="text-[11px] font-medium text-text">Forecasting</div>
                            <div className="text-[9px] text-muted">
                                PV: {health.forecast.pv_status === 'ok' ? 'ML' : health.forecast.pv_status} • Load:{' '}
                                {health.forecast.load_status === 'ok'
                                    ? 'ML'
                                    : health.forecast.load_reason === 'baseline'
                                      ? 'Baseline'
                                      : health.forecast.load_reason === 'demo'
                                        ? 'Demo'
                                        : health.forecast.load_reason === 'no_ml'
                                          ? 'No ML'
                                          : health.forecast.load_status}
                            </div>
                        </div>
                    </div>
                    <StatusIcon
                        status={
                            health.forecast.load_status === 'ok' && health.forecast.pv_status === 'ok'
                                ? 'good'
                                : 'warning'
                        }
                    />
                </div>

                {/* System Stats */}
                <div className="flex items-center justify-between p-2 rounded bg-surface2/30 border border-line/30">
                    <div className="flex items-center gap-2">
                        <div className="h-6 w-6 rounded-full bg-slate-500/10 flex items-center justify-center">
                            <Server className="h-3.5 w-3.5 text-slate-400" />
                        </div>
                        <div>
                            <div className="text-[11px] font-medium text-text">System</div>
                            <div className="text-[9px] text-muted">
                                Uptime: {Math.floor(health.system.uptime_hours / 24)}d{' '}
                                {Math.round(health.system.uptime_hours % 24)}h
                            </div>
                        </div>
                    </div>
                    <StatusIcon status={health.system.errors_24h === 0 ? 'good' : 'warning'} />
                </div>
            </div>

            {/* Planner Status Footer */}
            <div className="mt-3 pt-2 border-t border-line/30 flex justify-between items-center">
                <span className="text-[10px] text-muted">Planner Status</span>
                <div className="flex items-center gap-1.5">
                    <span className="text-[10px] text-text capitalize">{health.planner.status}</span>
                    <div
                        className={`h-1.5 w-1.5 rounded-full ${health.planner.status === 'success' ? 'bg-emerald-400' : 'bg-rose-400'} animate-pulse`}
                    />
                </div>
            </div>
        </Card>
    )
}
