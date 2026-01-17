import { useEffect, useRef, useState } from 'react'
import Card from '../components/Card'
import { Api, type DebugLogsResponse, type HistorySocResponse, type LogInfoResponse } from '../lib/api'
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
    const [isLive, setIsLive] = useState(false)
    const [logInfo, setLogInfo] = useState<LogInfoResponse | null>(null)

    const logContainerRef = useRef<HTMLDivElement>(null)

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

    const loadLogInfo = () => {
        Api.logInfo()
            .then((res) => setLogInfo(res))
            .catch((err) => console.error('Failed to fetch log info:', err))
    }

    // Initial load
    useEffect(() => {
        loadLogs()
        loadLogInfo()
    }, [])

    // Polling for Live mode
    useEffect(() => {
        if (!isLive) return

        const interval = setInterval(() => {
            // Silently refresh in live mode
            Api.debugLogs().then((res) => setLogs(res.logs ?? []))
            Api.logInfo().then((res) => setLogInfo(res))
        }, 3000)

        return () => clearInterval(interval)
    }, [isLive])

    // Autoscroll
    useEffect(() => {
        if (isLive && logContainerRef.current) {
            logContainerRef.current.scrollTop = logContainerRef.current.scrollHeight
        }
    }, [logs, isLive])

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
                                className={`rounded-pill border px-3 py-1 transition-colors text-[11px] ${isLive
                                    ? 'bg-accent/10 border-accent text-accent'
                                    : 'border-line/60 hover:border-accent text-muted'
                                    }`}
                                onClick={() => setIsLive(!isLive)}
                            >
                                {isLive ? '● Live' : 'Go Live'}
                            </button>
                            <button
                                className="rounded-pill border border-line/60 px-3 py-1 hover:border-accent disabled:opacity-40"
                                onClick={() => loadLogs()}
                                disabled={logsLoading}
                            >
                                {logsLoading ? 'Refreshing…' : 'Refresh'}
                            </button>
                            <button
                                className="rounded-pill border border-line/60 px-3 py-1 hover:border-accent"
                                onClick={() => {
                                    window.location.href = 'api/system/logs'
                                }}
                            >
                                Download
                            </button>
                            <button
                                className="rounded-pill border border-rose-500/40 px-3 py-1 hover:border-rose-500 text-rose-300 disabled:opacity-40"
                                onClick={() => {
                                    if (
                                        window.confirm(
                                            'Are you sure you want to clear the log file? This cannot be undone.',
                                        )
                                    ) {
                                        Api.clearLogs()
                                            .then(() => {
                                                setLogs([])
                                                // Refresh info
                                                loadLogInfo()
                                            })
                                            .catch((err: Error) => console.error('Failed to clear logs:', err))
                                    }
                                }}
                            >
                                Clear
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
                    <div
                        ref={logContainerRef}
                        className="h-[calc(100vh-280px)] min-h-[400px] overflow-auto rounded-xl2 border border-line/60 bg-surface2/40 text-[11px] font-mono text-muted/90 mb-3"
                    >
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

                    {logInfo && (
                        <div className="flex items-center gap-4 text-[10px] text-muted/60 px-1">
                            <div>
                                File: <span className="text-muted/80">{logInfo.filename}</span>
                            </div>
                            <div>
                                Size: <span className="text-muted/80">{(logInfo.size_bytes / 1024).toFixed(1)} KB</span>
                            </div>
                            <div>
                                Last Modified:{' '}
                                <span className="text-muted/80">
                                    {new Date(logInfo.last_modified).toLocaleString()}
                                </span>
                            </div>
                        </div>
                    )}
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

        </main>
    )
}
