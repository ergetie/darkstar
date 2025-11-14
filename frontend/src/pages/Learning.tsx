import { useEffect, useState } from 'react'
import Card from '../components/Card'
import Kpi from '../components/Kpi'
import { Api, type LearningStatusResponse, type ConfigResponse } from '../lib/api'

function formatBytes(bytes?: number): string {
    if (!bytes || bytes <= 0) return '—'
    const units = ['B', 'KB', 'MB', 'GB']
    let value = bytes
    let unitIndex = 0
    while (value >= 1024 && unitIndex < units.length - 1) {
        value /= 1024
        unitIndex += 1
    }
    return `${value.toFixed(1)} ${units[unitIndex]}`
}

function formatTimestamp(ts?: string): string {
    if (!ts) return '—'
    const d = new Date(ts)
    if (Number.isNaN(d.getTime())) return '—'
    return d.toLocaleString(undefined, {
        month: 'short',
        day: '2-digit',
        hour: '2-digit',
        minute: '2-digit',
    })
}

export default function Learning() {
    const [learning, setLearning] = useState<LearningStatusResponse | null>(null)
    const [config, setConfig] = useState<ConfigResponse | null>(null)
    const [loading, setLoading] = useState(true)
    const [error, setError] = useState<string | null>(null)

    useEffect(() => {
        let cancelled = false
        setLoading(true)
        setError(null)

        Promise.allSettled([Api.learningStatus(), Api.config()]).then(results => {
            if (cancelled) return

            const [learningRes, configRes] = results

            if (learningRes.status === 'fulfilled') {
                setLearning(learningRes.value)
            } else {
                console.error('Failed to load learning status:', learningRes.reason)
                setError('Failed to load learning status')
            }

            if (configRes.status === 'fulfilled') {
                setConfig(configRes.value)
            } else {
                console.error('Failed to load config for learning tab:', configRes.reason)
                if (!error) {
                    setError('Failed to load config')
                }
            }

            setLoading(false)
        })

        return () => {
            cancelled = true
        }
    }, [])

    const metrics = learning?.metrics

    const completed = metrics?.completed_learning_runs ?? metrics?.total_learning_runs ?? 0
    const failed = metrics?.failed_learning_runs ?? 0
    const daysWithData = metrics?.days_with_data ?? 0
    const dbSize = formatBytes(metrics?.db_size_bytes)

    const enabled = learning?.enabled === true
    const lastRun = metrics?.last_learning_run ?? learning?.last_updated
    const lastObs = metrics?.last_observation
    const syncInterval = learning?.sync_interval_minutes

    return (
        <main className="mx-auto max-w-7xl px-6 pb-24 pt-10 lg:pt-12">
            <div className="mb-6 flex items-baseline justify-between">
                <div>
                    <div className="text-sm text-muted">Learning Engine</div>
                    <div className="text-[13px] text-muted/80">
                        Status, metrics, and history for the automatic tuning loop.
                    </div>
                </div>
                <div className="text-[11px] text-muted">
                    {loading && 'Loading…'}
                    {!loading && error && error}
                </div>
            </div>

            <div className="grid gap-6 lg:grid-cols-3">
                <Card className="p-5 lg:col-span-1">
                    <div className="text-sm text-muted mb-3">Overview</div>
                    <div className="space-y-2 text-sm text-muted">
                        <div className="flex items-center justify-between">
                            <span>Learning</span>
                            <span
                                className={`rounded-pill border px-2.5 py-0.5 text-[11px] ${
                                    enabled
                                        ? 'border-emerald-500/60 text-emerald-300'
                                        : 'border-line/70 text-muted'
                                }`}
                            >
                                {enabled ? 'enabled' : 'disabled'}
                            </span>
                        </div>
                        <div className="flex items-center justify-between">
                            <span>Last run</span>
                            <span>{formatTimestamp(lastRun)}</span>
                        </div>
                        <div className="flex items-center justify-between">
                            <span>Last observation</span>
                            <span>{formatTimestamp(lastObs)}</span>
                        </div>
                        <div className="flex items-center justify-between">
                            <span>Sync interval</span>
                            <span>
                                {syncInterval !== undefined && syncInterval !== null
                                    ? `${syncInterval} min`
                                    : '—'}
                            </span>
                        </div>
                        <div className="flex items-center justify-between">
                            <span>SQLite path</span>
                            <span className="truncate max-w-[12rem] text-[11px] text-muted/80">
                                {learning?.sqlite_path || config?.learning?.sqlite_path || '—'}
                            </span>
                        </div>
                    </div>
                </Card>

                <Card className="p-5 lg:col-span-2">
                    <div className="text-sm text-muted mb-3">Metrics</div>
                    <div className="grid grid-cols-2 gap-3 md:grid-cols-4">
                        <Kpi
                            label="Completed runs"
                            value={completed ? completed.toString() : '0'}
                            hint="learning_status.completed_learning_runs"
                        />
                        <Kpi
                            label="Failed runs"
                            value={failed ? failed.toString() : '0'}
                            hint="learning_status.failed_learning_runs"
                        />
                        <Kpi
                            label="Days with data"
                            value={daysWithData ? daysWithData.toString() : '0'}
                            hint="learning_status.days_with_data"
                        />
                        <Kpi
                            label="DB size"
                            value={dbSize}
                            hint="learning_status.db_size_bytes"
                        />
                    </div>
                </Card>
            </div>

            <div className="grid gap-6 mt-6 lg:grid-cols-3">
                <Card className="p-5 lg:col-span-2">
                    <div className="text-sm text-muted mb-3">Parameter impact</div>
                    <div className="text-sm text-muted/80">
                        Read-only snapshot of key thresholds that learning can adjust
                        (decision thresholds, S-index factors, daily change limits). Values
                        will be populated from config; edits are done in Settings.
                    </div>
                    <div className="mt-4 grid gap-2 text-sm text-muted/90 md:grid-cols-2">
                        <div className="rounded-xl2 border border-dashed border-line/60 px-3 py-2">
                            <div className="text-[11px] uppercase tracking-wide text-muted">
                                Decision thresholds
                            </div>
                            <div className="text-[13px] mt-1">
                                Placeholder for charge/export threshold snapshot.
                            </div>
                        </div>
                        <div className="rounded-xl2 border border-dashed border-line/60 px-3 py-2">
                            <div className="text-[11px] uppercase tracking-wide text-muted">
                                S-index & learning limits
                            </div>
                            <div className="text-[13px] mt-1">
                                Placeholder for S-index factors and max_daily_param_change.
                            </div>
                        </div>
                    </div>
                </Card>

                <Card className="p-5 lg:col-span-1">
                    <div className="text-sm text-muted mb-3">History</div>
                    <div className="flex h-40 items-center justify-center rounded-xl2 border border-dashed border-line/60 bg-surface2/40 text-[13px] text-muted">
                        Mini learning chart placeholder (recent runs / quality trend)
                    </div>
                </Card>
            </div>
        </main>
    )
}
