import { useEffect, useRef, useState } from 'react'
import Card from '../components/Card'
import { Api, type DebugLogsResponse, type HistorySocResponse } from '../lib/api'
import { Chart as ChartJS, type Chart, type ChartConfiguration } from 'chart.js/auto'

type LogLevelFilter = 'all' | 'warn_error' | 'error'
type LogTimeRange = 'all' | '1h' | '6h' | '24h'
type SocDateFilter = 'today' | 'yesterday'

export default function Debug() {
    const [logs, setLogs] = useState<DebugLogsResponse['logs']>([])
    const [logsLoading, setLogsLoading] = useState(false)
    const [logsError, setLogsError] = useState<string | null>(null)
    const [levelFilter, setLevelFilter] = useState<LogLevelFilter>('all')
    const [timeRange, setTimeRange] = useState<LogTimeRange>('all')

    const [socHistory, setSocHistory] = useState<HistorySocResponse | null>(null)
    const [socLoading, setSocLoading] = useState(false)
    const [socError, setSocError] = useState<string | null>(null)
    const [socDate, setSocDate] = useState<SocDateFilter>('today')
    const socCanvasRef = useRef<HTMLCanvasElement | null>(null)
    const socChartRef = useRef<Chart | null>(null)

    useEffect(() => {
        const loadLogs = () => {
            setLogsLoading(true)
            setLogsError(null)
            Api.debugLogs()
                .then((res) => setLogs(res.logs ?? []))
                .catch((err) => {
                    console.error('Failed to fetch debug logs:', err)
                    setLogsError('Failed to load logs')
                })
                .finally(() => setLogsLoading(false))
        }

        loadLogs()
    }, [])

    useEffect(() => {
        const loadSoc = () => {
            setSocLoading(true)
            setSocError(null)

            let dateParam: string = 'today'
            if (socDate === 'yesterday') {
                const d = new Date()
                d.setDate(d.getDate() - 1)
                dateParam = d.toISOString().slice(0, 10)
            }

            Api.historySoc(dateParam)
                .then((res) => setSocHistory(res))
                .catch((err) => {
                    console.error('Failed to fetch historic SoC:', err)
                    setSocError('Failed to load SoC history')
                })
                .finally(() => setSocLoading(false))
        }

        loadSoc()
    }, [socDate])

    const filteredLogs = logs
        .filter((entry) => {
            if (levelFilter === 'all') return true
            const level = (entry.level || '').toUpperCase()
            if (levelFilter === 'error') return level === 'ERROR' || level === 'CRITICAL'
            // warn_error
            return level === 'WARN' || level === 'WARNING' || level === 'ERROR' || level === 'CRITICAL'
        })
        .filter((entry) => {
            if (timeRange === 'all') return true
            const ts = new Date(entry.timestamp).getTime()
            if (Number.isNaN(ts)) return true
            // eslint-disable-next-line
            const now = Date.now()
            const deltaMs = now - ts
            const oneHour = 60 * 60 * 1000
            if (timeRange === '1h') return deltaMs <= oneHour
            if (timeRange === '6h') return deltaMs <= 6 * oneHour
            if (timeRange === '24h') return deltaMs <= 24 * oneHour
            return true
        })

    const errorLogs = logs.filter((entry) => {
        const level = (entry.level || '').toUpperCase()
        return level === 'ERROR' || level === 'CRITICAL'
    })

    useEffect(() => {
        if (!socCanvasRef.current) return
        const slots = socHistory?.slots ?? []
        if (!slots.length) {
            if (socChartRef.current) {
                socChartRef.current.destroy()
                socChartRef.current = null
            }
            return
        }

        const labels = slots.map((slot) => {
            const d = new Date(slot.timestamp)
            if (Number.isNaN(d.getTime())) return ''
            return d.toLocaleTimeString(undefined, { hour: '2-digit', minute: '2-digit' })
        })
        const values = slots.map((slot) => slot.soc_percent ?? 0)

        const data = {
            labels,
            datasets: [
                {
                    type: 'line' as const,
                    label: 'SoC (%)',
                    data: values,
                    borderColor: 'rgba(129, 200, 253, 0.9)',
                    backgroundColor: 'rgba(129, 200, 253, 0.15)',
                    pointRadius: 0,
                    tension: 0.25,
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
                        label: (ctx) => `SoC: ${ctx.parsed.y?.toFixed(1) ?? '--'}%`,
                    },
                },
            },
            scales: {
                x: {
                    ticks: { color: '#a6b0bf', maxRotation: 0 },
                    grid: { display: false },
                },
                y: {
                    ticks: { color: '#a6b0bf', stepSize: 10 },
                    grid: { color: 'rgba(255,255,255,0.06)' },
                    beginAtZero: true,
                    suggestedMax: 100,
                },
            },
        }

        if (socChartRef.current) {
            socChartRef.current.data = data as any
            socChartRef.current.options = options
            socChartRef.current.update()
            return
        }

        socChartRef.current = new ChartJS(socCanvasRef.current, {
            type: 'line',
            data: data as any,
            options,
        })

        return () => {
            if (socChartRef.current) {
                socChartRef.current.destroy()
                socChartRef.current = null
            }
        }
    }, [socHistory])

    return (
        <main className="mx-auto max-w-7xl px-4 pb-24 pt-8 sm:px-6 lg:pt-12">
            <div className="mb-6">
                <div className="text-sm text-muted">Debug & Diagnostics</div>
                <div className="text-[13px] text-muted/80">
                    Logs and SoC history to understand what the planner has been doing recently.
                </div>
            </div>

            <div className="grid gap-6 lg:grid-cols-3">
                <Card className="p-5 lg:col-span-2">
                    <div className="flex items-center justify-between mb-3">
                        <div className="text-sm text-muted">Logs</div>
                        <div className="flex items-center gap-2 text-[11px] text-muted">
                            <button
                                className="rounded-pill border border-line/60 px-3 py-1 hover:border-accent disabled:opacity-40"
                                onClick={() => {
                                    setLogsLoading(true)
                                    setLogsError(null)
                                    Api.debugLogs()
                                        .then((res) => setLogs(res.logs ?? []))
                                        .catch((err) => {
                                            console.error('Failed to refresh debug logs:', err)
                                            setLogsError('Failed to refresh logs')
                                        })
                                        .finally(() => setLogsLoading(false))
                                }}
                                disabled={logsLoading}
                            >
                                {logsLoading ? 'Refreshing…' : 'Refresh'}
                            </button>
                            <select
                                className="rounded-md bg-surface2 border border-line/60 px-2 py-1 text-[11px]"
                                value={timeRange}
                                onChange={(e) => setTimeRange(e.target.value as LogTimeRange)}
                            >
                                <option value="all">All time</option>
                                <option value="1h">Last 1 hour</option>
                                <option value="6h">Last 6 hours</option>
                                <option value="24h">Last 24 hours</option>
                            </select>
                            <select
                                className="rounded-md bg-surface2 border border-line/60 px-2 py-1 text-[11px]"
                                value={levelFilter}
                                onChange={(e) => setLevelFilter(e.target.value as LogLevelFilter)}
                            >
                                <option value="all">All levels</option>
                                <option value="warn_error">Warn + Error</option>
                                <option value="error">Errors only</option>
                            </select>
                        </div>
                    </div>
                    {logsError && <div className="text-[11px] text-amber-400 mb-2">{logsError}</div>}
                    <div className="h-64 overflow-auto rounded-xl2 border border-line/60 bg-surface2/40 text-[11px] font-mono text-muted/90">
                        {filteredLogs.length === 0 && !logsLoading && !logsError && (
                            <div className="px-3 py-2 text-muted/70">No logs captured yet.</div>
                        )}
                        {filteredLogs.map((entry, idx) => (
                            <div
                                key={`${entry.timestamp}-${idx}`}
                                className="px-3 py-1.5 border-b border-line/20 last:border-b-0"
                            >
                                <span className="text-muted/60 mr-2">
                                    {new Date(entry.timestamp).toLocaleTimeString(undefined, {
                                        hour: '2-digit',
                                        minute: '2-digit',
                                        second: '2-digit',
                                    })}
                                </span>
                                <span className="mr-2 rounded-full px-1.5 py-0.5 text-[10px] uppercase tracking-wide border border-line/50">
                                    {entry.level}
                                </span>
                                <span className="text-muted/70 mr-2">{entry.logger}</span>
                                <span>{entry.message}</span>
                            </div>
                        ))}
                    </div>
                </Card>

                <Card className="p-5 lg:col-span-1">
                    <div className="text-sm text-muted mb-3">Recent events</div>
                    <div className="text-[13px] text-muted/80 mb-2">
                        Quick view of recent errors and warnings from the log stream.
                    </div>
                    <div className="space-y-2 text-[12px] text-muted/90">
                        <div className="flex items-center justify-between">
                            <span>Total log entries</span>
                            <span className="tabular-nums">{logs.length}</span>
                        </div>
                        <div className="flex items-center justify-between">
                            <span>Error/critical entries</span>
                            <span className="tabular-nums">{errorLogs.length}</span>
                        </div>
                        <div className="mt-3 text-[11px] text-muted/70 uppercase tracking-wide">Last errors</div>
                        <div className="space-y-1.5 max-h-40 overflow-auto">
                            {errorLogs.slice(-5).map((entry, idx) => (
                                <div
                                    key={`${entry.timestamp}-err-${idx}`}
                                    className="rounded-md bg-rose-500/5 border border-rose-500/40 px-2 py-1.5"
                                >
                                    <div className="text-[10px] text-rose-200/80 mb-0.5">
                                        {new Date(entry.timestamp).toLocaleTimeString(undefined, {
                                            hour: '2-digit',
                                            minute: '2-digit',
                                            second: '2-digit',
                                        })}{' '}
                                        · {entry.logger}
                                    </div>
                                    <div className="text-[11px] text-rose-50/90 line-clamp-2">{entry.message}</div>
                                </div>
                            ))}
                            {errorLogs.length === 0 && (
                                <div className="text-[11px] text-muted/70">No error-level entries yet.</div>
                            )}
                        </div>
                    </div>
                </Card>
            </div>

            <div className="grid gap-6 mt-6 lg:grid-cols-3">
                <Card className="p-5 lg:col-span-2">
                    <div className="flex items-center justify-between mb-3">
                        <div className="text-sm text-muted">Historical SoC</div>
                        <div className="flex items-center gap-2 text-[11px] text-muted">
                            <span className="text-muted/70">Range</span>
                            <select
                                className="rounded-md bg-surface2 border border-line/60 px-2 py-1 text-[11px]"
                                value={socDate}
                                onChange={(e) => setSocDate(e.target.value as SocDateFilter)}
                            >
                                <option value="today">Today</option>
                                <option value="yesterday">Yesterday</option>
                            </select>
                        </div>
                    </div>
                    <div className="text-[13px] text-muted/80 mb-2">
                        SoC (%) over the selected day from the learning database. Use this to correlate planner
                        behaviour with actual SoC movement.
                    </div>
                    {socError && <div className="text-[11px] text-amber-400 mb-2">{socError}</div>}
                    <div className="h-48">
                        <canvas ref={socCanvasRef} className="w-full h-full" />
                    </div>
                </Card>
            </div>
        </main>
    )
}
