import { useEffect, useRef, useState } from 'react'
import Card from '../components/Card'
import Kpi from '../components/Kpi'
import { Api, type LearningStatusResponse, type ConfigResponse, type LearningHistoryResponse } from '../lib/api'
import { Chart as ChartJS, type Chart, type ChartConfiguration } from 'chart.js/auto'

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
    const [history, setHistory] = useState<LearningHistoryResponse | null>(null)
    const [debugSIndex, setDebugSIndex] = useState<{ mode?: string; base_factor?: number; factor?: number; max_factor?: number } | null>(null)
    const historyCanvasRef = useRef<HTMLCanvasElement | null>(null)
    const historyChartRef = useRef<Chart | null>(null)

    useEffect(() => {
        let cancelled = false
        setLoading(true)
        setError(null)

        Promise.allSettled([Api.learningStatus(), Api.config(), Api.learningHistory(), Api.debug()]).then(results => {
            if (cancelled) return

            const [learningRes, configRes, historyRes, debugRes] = results

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

            if (historyRes.status === 'fulfilled') {
                setHistory(historyRes.value)
            }

            if (debugRes.status === 'fulfilled' && debugRes.value && typeof debugRes.value === 'object') {
                const sIndex = (debugRes.value as any).s_index
                if (sIndex && typeof sIndex === 'object') {
                    setDebugSIndex({
                        mode: sIndex.mode,
                        base_factor: sIndex.base_factor,
                        factor: sIndex.factor,
                        max_factor: sIndex.max_factor,
                    })
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
    const lastError = (learning as any)?.last_error as string | undefined

    const hasAnyMetricData =
        (metrics && Object.keys(metrics).length > 0) ||
        completed > 0 ||
        failed > 0 ||
        daysWithData > 0

    useEffect(() => {
        if (!historyCanvasRef.current) return

        const runs = history?.runs ?? []
        if (!runs.length) {
            if (historyChartRef.current) {
                historyChartRef.current.destroy()
                historyChartRef.current = null
            }
            return
        }

        const sorted = [...runs].sort((a, b) => new Date(a.started_at).getTime() - new Date(b.started_at).getTime())
        const labels = sorted.map(run => {
            const d = new Date(run.started_at)
            if (Number.isNaN(d.getTime())) return ''
            return d.toLocaleTimeString(undefined, { hour: '2-digit', minute: '2-digit' })
        })
        const changesApplied = sorted.map(run => run.changes_applied ?? 0)

        const data = {
            labels,
            datasets: [
                {
                    type: 'bar' as const,
                    label: 'Changes applied',
                    data: changesApplied,
                    backgroundColor: 'rgba(244, 143, 177, 0.7)',
                    borderRadius: 4,
                },
            ],
        }

        const options: ChartConfiguration['options'] = {
            responsive: true,
            maintainAspectRatio: false,
            plugins: {
                legend: { display: false },
                tooltip: {
                    callbacks: {
                        label: (ctx) => `Changes applied: ${ctx.parsed.y}`,
                    },
                },
            },
            scales: {
                x: {
                    ticks: { color: '#a6b0bf', maxRotation: 0 },
                    grid: { display: false },
                },
                y: {
                    ticks: { color: '#a6b0bf', stepSize: 1 },
                    grid: { color: 'rgba(255,255,255,0.06)' },
                    beginAtZero: true,
                },
            },
        }

        if (historyChartRef.current) {
            historyChartRef.current.data = data as any
            historyChartRef.current.options = options
            historyChartRef.current.update()
            return
        }

        historyChartRef.current = new ChartJS(historyCanvasRef.current, {
            type: 'bar',
            data: data as any,
            options,
        })

        return () => {
            if (historyChartRef.current) {
                historyChartRef.current.destroy()
                historyChartRef.current = null
            }
        }
    }, [history])

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
                        {!loading && !error && !enabled && (
                            <div className="mt-3 rounded-xl2 border border-dashed border-line/60 bg-surface2/60 px-3 py-2 text-[12px] text-muted/90">
                                Learning is currently <span className="font-semibold">disabled</span>. Enable it
                                in the Settings → Parameters section to start collecting data.
                            </div>
                        )}
                        {!loading && !error && enabled && !hasAnyMetricData && (
                            <div className="mt-3 rounded-xl2 border border-dashed border-line/60 bg-surface2/60 px-3 py-2 text-[12px] text-muted/90">
                                Learning is enabled but no runs have been recorded yet. This panel will fill
                                in after the planner has accumulated enough data.
                            </div>
                        )}
                        {!loading && !error && lastError && (
                            <div className="mt-3 rounded-xl2 border border-amber-500/60 bg-amber-500/5 px-3 py-2 text-[12px] text-amber-200">
                                <div className="font-semibold mb-0.5">Last learning error</div>
                                <div className="line-clamp-3 break-words">{lastError}</div>
                            </div>
                        )}
                    </div>
                </Card>

                <Card className="p-5 lg:col-span-2">
                    <div className="text-sm text-muted mb-3">Metrics</div>
                    <div className="grid grid-cols-2 gap-3 md:grid-cols-4">
                        <Kpi
                            label="Completed runs"
                            value={completed ? completed.toString() : '0'}
                        />
                        <Kpi
                            label="Failed runs"
                            value={failed ? failed.toString() : '0'}
                        />
                        <Kpi
                            label="Days with data"
                            value={daysWithData ? daysWithData.toString() : '0'}
                        />
                        <Kpi
                            label="DB size"
                            value={dbSize}
                        />
                    </div>
                </Card>
            </div>

            <div className="grid gap-6 mt-6 lg:grid-cols-3">
                <Card className="p-5 lg:col-span-2">
                    <div className="text-sm text-muted mb-3">Parameter impact</div>
                    <div className="text-sm text-muted/80">
                        Read-only snapshot of key thresholds that learning can adjust
                        (decision thresholds, S-index factors, daily change limits). Edits
                        are made in the Settings tab.
                    </div>
                    <div className="mt-4 grid gap-3 text-sm text-muted/90 md:grid-cols-2">
                        <div className="rounded-xl2 border border-line/60 px-3 py-2">
                            <div className="flex items-center justify-between text-[11px] uppercase tracking-wide text-muted">
                                <span>Decision thresholds</span>
                            </div>
                            <div className="mt-2 space-y-1.5 text-[13px]">
                                <div className="flex items-center justify-between">
                                    <span>Battery use margin</span>
                                    <span className="tabular-nums">
                                        {config?.decision_thresholds?.battery_use_margin_sek ?? '—'}{' '}
                                        <span className="text-[11px] text-muted">SEK/kWh</span>
                                    </span>
                                </div>
                                <div className="flex items-center justify-between">
                                    <span>Battery → Water margin</span>
                                    <span className="tabular-nums">
                                        {config?.decision_thresholds?.battery_water_margin_sek ?? '—'}{' '}
                                        <span className="text-[11px] text-muted">SEK/kWh</span>
                                    </span>
                                </div>
                                <div className="flex items-center justify-between">
                                    <span>Export profit margin</span>
                                    <span className="tabular-nums">
                                        {config?.decision_thresholds?.export_profit_margin_sek ?? '—'}{' '}
                                        <span className="text-[11px] text-muted">SEK/kWh</span>
                                    </span>
                                </div>
                            </div>
                        </div>

                        <div className="rounded-xl2 border border-line/60 px-3 py-2">
                            <div className="flex items-center justify-between text-[11px] uppercase tracking-wide text-muted">
                                <span>S-index & learning limits</span>
                            </div>
                            <div className="mt-2 space-y-1.5 text-[13px]">
                                <div className="flex items-center justify-between">
                                    <span>Current S-index</span>
                                    <span className="tabular-nums">
                                        {debugSIndex?.factor ?? debugSIndex?.base_factor ?? config?.s_index?.base_factor ?? '—'}
                                        {debugSIndex?.mode && (
                                            <span className="ml-1 text-[11px] text-muted">
                                                ({debugSIndex.mode})
                                            </span>
                                        )}
                                    </span>
                                </div>
                                <div className="flex items-center justify-between">
                                    <span>S-index base factor</span>
                                    <span className="tabular-nums">
                                        {config?.s_index?.base_factor ?? '—'}
                                        {config?.learning?.max_daily_param_change?.s_index_base_factor ? (
                                            <span className="ml-1 rounded-full bg-emerald-500/10 px-1.5 py-0.5 text-[10px] text-emerald-300">
                                                learning can adjust
                                            </span>
                                        ) : null}
                                    </span>
                                </div>
                                <div className="flex items-center justify-between">
                                    <span>PV deficit weight</span>
                                    <span className="tabular-nums">
                                        {config?.s_index?.pv_deficit_weight ?? '—'}
                                        {config?.learning?.max_daily_param_change?.s_index_pv_deficit_weight ? (
                                            <span className="ml-1 rounded-full bg-emerald-500/10 px-1.5 py-0.5 text-[10px] text-emerald-300">
                                                learning can adjust
                                            </span>
                                        ) : null}
                                    </span>
                                </div>
                                <div className="flex items-center justify-between">
                                    <span>Temp weight</span>
                                    <span className="tabular-nums">
                                        {config?.s_index?.temp_weight ?? '—'}
                                        {config?.learning?.max_daily_param_change?.s_index_temp_weight ? (
                                            <span className="ml-1 rounded-full bg-emerald-500/10 px-1.5 py-0.5 text-[10px] text-emerald-300">
                                                learning can adjust
                                            </span>
                                        ) : null}
                                    </span>
                                </div>
                                <div className="flex items-center justify-between">
                                    <span>Min improvement</span>
                                    <span className="tabular-nums">
                                        {config?.learning?.min_improvement_threshold ?? '—'}
                                    </span>
                                </div>
                                <div className="flex items-center justify-between">
                                    <span>Min samples</span>
                                    <span className="tabular-nums">
                                        {config?.learning?.min_sample_threshold ?? '—'}
                                    </span>
                                </div>
                            </div>
                        </div>
                    </div>
                </Card>

                <Card className="p-5 lg:col-span-1">
                    <div className="text-sm text-muted mb-3">History</div>
                    <div className="text-[13px] text-muted/80 mb-2">
                        Recent learning runs and how many parameter changes were applied.
                    </div>
                    <div className="h-40">
                        <canvas ref={historyCanvasRef} className="w-full h-full" />
                    </div>
                </Card>
            </div>
        </main>
    )
}
