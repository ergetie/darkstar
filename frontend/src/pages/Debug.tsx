import { useEffect, useMemo, useRef, useState } from 'react'
import { Terminal, Activity, Download, Trash2, RefreshCw, ShieldCheck } from 'lucide-react'
import Card from '../components/Card'
import MonitorStatusCard from '../components/MonitorStatusCard'
import { Api, type DebugLogsResponse, type LogInfoResponse, type LoadsDebugResponse } from '../lib/api'

type LogLevelFilter = 'all' | 'warn_error' | 'error'
type LogTimeRange = 'all' | '1h' | '6h' | '24h'

function LogsView({
    logs,
    loading,
    error,
    levelFilter,
    setLevelFilter,
    timeRange,
    setTimeRange,
    isLive,
    setIsLive,
    logInfo,
    loadLogs,
    clearLogs,
}: {
    logs: DebugLogsResponse['logs']
    loading: boolean
    error: string | null
    levelFilter: LogLevelFilter
    setLevelFilter: (v: LogLevelFilter) => void
    timeRange: LogTimeRange
    setTimeRange: (v: LogTimeRange) => void
    isLive: boolean
    setIsLive: (v: boolean) => void
    logInfo: LogInfoResponse | null
    loadLogs: () => void
    clearLogs: () => void
}) {
    const logContainerRef = useRef<HTMLDivElement>(null)
    const [now, setNow] = useState(() => Date.now())

    // Autoscroll
    useEffect(() => {
        if (isLive && logContainerRef.current) {
            logContainerRef.current.scrollTop = logContainerRef.current.scrollHeight
        }
    }, [logs, isLive])

    // Refresh the time-range cutoff periodically (purity: Date.now() may not be read during render)
    useEffect(() => {
        const id = setInterval(() => setNow(Date.now()), 60000)
        return () => clearInterval(id)
    }, [])

    const filteredLogs = useMemo(() => {
        return logs
            .filter((entry) => {
                if (levelFilter === 'all') return true
                const level = (entry.level || '').toUpperCase()
                if (levelFilter === 'error') return level === 'ERROR' || level === 'CRITICAL'
                return level === 'WARN' || level === 'WARNING' || level === 'ERROR' || level === 'CRITICAL'
            })
            .filter((entry) => {
                if (timeRange === 'all') return true
                const ts = new Date(entry.timestamp).getTime()
                if (Number.isNaN(ts)) return true

                const deltaMs = now - ts
                const oneHour = 60 * 60 * 1000
                if (timeRange === '1h') return deltaMs <= oneHour
                if (timeRange === '6h') return deltaMs <= 6 * oneHour
                if (timeRange === '24h') return deltaMs <= 24 * oneHour
                return true
            })
    }, [logs, levelFilter, timeRange, now])

    const errorLogs = logs.filter((entry) => {
        const level = (entry.level || '').toUpperCase()
        return level === 'ERROR' || level === 'CRITICAL'
    })

    return (
        <div className="grid gap-6 lg:grid-cols-3 animate-in fade-in slide-in-from-bottom-2 duration-500">
            <Card className="p-5 lg:col-span-2">
                <div className="flex items-center justify-between mb-3">
                    <div className="text-sm text-muted">Logs</div>
                    <div className="flex items-center gap-2 text-[11px] text-muted">
                        <button
                            className={`rounded-pill border px-3 py-1 transition-colors text-[11px] ${
                                isLive
                                    ? 'bg-accent/10 border-accent text-accent'
                                    : 'border-line/60 hover:border-accent text-muted'
                            }`}
                            onClick={() => setIsLive(!isLive)}
                        >
                            {isLive ? '● Live' : 'Go Live'}
                        </button>
                        <button
                            className="rounded-pill border border-line/60 px-3 py-1 hover:border-accent disabled:opacity-40 flex items-center gap-1.5"
                            onClick={() => loadLogs()}
                            disabled={loading}
                        >
                            <RefreshCw size={10} className={loading ? 'animate-spin' : ''} />
                            {loading ? 'Refreshing…' : 'Refresh'}
                        </button>
                        <button
                            className="rounded-pill border border-sky-500/60 px-3 py-1 hover:border-sky-500 hover:bg-sky-500/10 text-sky-400 flex items-center gap-1.5"
                            onClick={() => {
                                window.location.href = 'api/system/logs'
                            }}
                        >
                            <Download size={10} />
                            Logs
                        </button>
                        <button
                            className="rounded-pill border border-accent/60 px-3 py-1 hover:border-accent hover:bg-accent/10 text-accent flex items-center gap-1.5"
                            onClick={() => {
                                window.location.href = 'api/config/download'
                            }}
                        >
                            <Download size={10} />
                            Config
                        </button>
                        <button
                            className="rounded-pill border border-rose-500/40 px-3 py-1 hover:border-rose-500 text-rose-300 disabled:opacity-40 flex items-center gap-1.5"
                            onClick={clearLogs}
                        >
                            <Trash2 size={10} />
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
                {error && <div className="text-[11px] text-amber-400 mb-2">{error}</div>}
                <div
                    ref={logContainerRef}
                    className="h-[calc(100vh-300px)] min-h-[400px] overflow-auto rounded-xl2 border border-line/60 bg-surface2/40 text-[11px] font-mono text-muted/90 mb-3"
                >
                    {filteredLogs.length === 0 && !loading && !error && (
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
                                    hour12: false,
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
                            <span className="text-muted/80">{new Date(logInfo.last_modified).toLocaleString()}</span>
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
                                        hour12: false,
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
    )
}

function LoadDisaggregationView() {
    const [data, setData] = useState<LoadsDebugResponse | null>(null)
    const [loading, setLoading] = useState(false)
    const [error, setError] = useState<string | null>(null)

    const loadData = () => {
        setLoading(true)
        setError(null)
        Api.loadsDebug()
            .then(setData)
            .catch((err) => {
                console.error('Failed to fetch loads debug data:', err)
                setError('Failed to load data')
            })
            .finally(() => setLoading(false))
    }

    useEffect(() => {
        const timer = setTimeout(() => loadData(), 0)
        const interval = setInterval(() => {
            Api.loadsDebug().then(setData).catch(console.error)
        }, 3000)
        return () => {
            clearTimeout(timer)
            clearInterval(interval)
        }
    }, [])

    if (error) {
        return (
            <Card className="p-8 text-center animate-in fade-in slide-in-from-bottom-2">
                <div className="text-amber-400 mb-4">{error}</div>
                <button
                    onClick={loadData}
                    className="rounded-pill border border-line/60 px-4 py-2 hover:border-accent text-sm transition-colors"
                >
                    Try Again
                </button>
            </Card>
        )
    }

    if (!data && loading) {
        return <div className="p-8 text-center text-muted animate-pulse">Loading load data...</div>
    }

    if (!data) return null

    const controllableTotal = data.controllable_total_kw
    const driftRate = data.quality_metrics.drift_rate
    const totalCalcs = data.quality_metrics.metrics.total_calculations
    const negativeCount = data.quality_metrics.metrics.negative_base_load_count

    return (
        <Card className="animate-in fade-in slide-in-from-bottom-2 duration-500 p-8">
            <div className="mb-8">
                <h3 className="text-lg font-medium">Load Disaggregation</h3>
                <p className="text-sm text-muted">Monitor controllable loads and data quality</p>
            </div>

            <div className="grid grid-cols-1 md:grid-cols-2 gap-12">
                <div>
                    <h4 className="font-medium mb-6 text-xs text-muted uppercase tracking-wider">Current Power (kW)</h4>
                    <div className="space-y-4">
                        {data.loads.length === 0 && (
                            <div className="text-sm text-muted italic">No controllable loads configured.</div>
                        )}
                        {data.loads.map((load) => (
                            <div key={load.id} className="flex justify-between items-center group">
                                <span className="flex items-center gap-3">
                                    <div
                                        className={`w-2 h-2 rounded-full shadow-[0_0_8px] ${
                                            load.healthy
                                                ? 'bg-emerald-500 shadow-emerald-500/50'
                                                : 'bg-rose-500 shadow-rose-500/50'
                                        }`}
                                    />
                                    <span className="text-sm font-medium">{load.name}</span>
                                    <span className="text-[10px] text-muted font-mono opacity-0 group-hover:opacity-100 transition-opacity">
                                        {load.sensor}
                                    </span>
                                </span>
                                <span className="font-mono text-sm">
                                    {load.power_kw.toFixed(2)} <span className="text-[10px] text-muted">kW</span>
                                </span>
                            </div>
                        ))}
                        {data.loads.length > 0 && (
                            <div className="border-t border-line/20 pt-4 mt-6 flex justify-between font-bold text-accent">
                                <span>Total Controllable:</span>
                                <span className="font-mono text-lg">
                                    {controllableTotal.toFixed(2)} <span className="text-[10px]">kW</span>
                                </span>
                            </div>
                        )}
                    </div>
                </div>

                <div>
                    <h4 className="font-medium mb-6 text-xs text-muted uppercase tracking-wider">Data Quality</h4>
                    <div className="space-y-6 rounded-2xl bg-surface2/30 border border-line/40 p-6">
                        <div>
                            <div className="flex justify-between items-end mb-2">
                                <span className="text-sm text-muted">Drift Rate</span>
                                <span
                                    className={`text-xl font-mono ${driftRate > 0.1 ? 'text-rose-400' : 'text-emerald-400'}`}
                                >
                                    {(driftRate * 100).toFixed(1)}%
                                </span>
                            </div>
                            <div className="h-2 w-full bg-line/20 rounded-full overflow-hidden">
                                <div
                                    className={`h-full transition-all duration-700 ${driftRate > 0.1 ? 'bg-rose-500' : 'bg-emerald-500'}`}
                                    style={{ width: `${Math.min(100, driftRate * 100)}%` }}
                                />
                            </div>
                        </div>

                        <div className="grid grid-cols-2 gap-8 pt-2">
                            <div>
                                <div className="text-[10px] text-muted uppercase tracking-widest mb-1">
                                    Total Samples
                                </div>
                                <div className="text-lg font-mono tabular-nums">{totalCalcs}</div>
                            </div>
                            <div>
                                <div className="text-[10px] text-muted uppercase tracking-widest mb-1">
                                    Negative Base Load
                                </div>
                                <div
                                    className={`text-lg font-mono tabular-nums ${
                                        negativeCount > 0 ? 'text-rose-400 font-bold' : 'text-muted'
                                    }`}
                                >
                                    {negativeCount}
                                </div>
                            </div>
                        </div>
                    </div>

                    <div className="mt-6 p-4 rounded-xl border border-line/20 bg-accent/5">
                        <p className="text-[11px] text-muted/80 leading-relaxed italic">
                            Hint: Drift rate reflects how often sensors report more power consumed by controllable loads
                            than the total house load. A rate &lt; 5% is optimal.
                        </p>
                    </div>
                </div>
            </div>
        </Card>
    )
}

export function DebugContent({ className }: { className?: string }) {
    const [activeTab, setActiveTab] = useState<'logs' | 'loads' | 'monitors'>('logs')
    const [logs, setLogs] = useState<DebugLogsResponse['logs']>([])
    const [logsLoading, setLogsLoading] = useState(false)
    const [logsError, setLogsError] = useState<string | null>(null)
    const [levelFilter, setLevelFilter] = useState<LogLevelFilter>('all')
    const [timeRange, setTimeRange] = useState<LogTimeRange>('all')
    const [isLive, setIsLive] = useState(false)
    const [logInfo, setLogInfo] = useState<LogInfoResponse | null>(null)

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

    const clearLogs = () => {
        if (window.confirm('Are you sure you want to clear the log file? This cannot be undone.')) {
            Api.clearLogs()
                .then(() => {
                    setLogs([])
                    loadLogInfo()
                })
                .catch((err: Error) => console.error('Failed to clear logs:', err))
        }
    }

    // Initial load
    useEffect(() => {
        const timer = setTimeout(() => {
            loadLogs()
            loadLogInfo()
        }, 0)
        return () => clearTimeout(timer)
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

    const containerClass = className !== undefined ? className : 'mx-auto max-w-7xl px-4 pb-24 pt-8 sm:px-6 lg:pt-12'

    return (
        <div className={containerClass}>
            <div className="mb-8 flex flex-col md:flex-row md:items-end justify-between gap-4">
                <div>{/* Header text removed for Settings integration */}</div>

                <div className="flex bg-surface2/50 p-1 rounded-xl border border-line/20 shadow-sm">
                    <button
                        onClick={() => setActiveTab('logs')}
                        className={`flex items-center gap-2 px-4 py-2 text-xs font-bold uppercase tracking-wider rounded-lg transition-all ${
                            activeTab === 'logs'
                                ? 'bg-accent text-[#100f0e] shadow-lg shadow-accent/20'
                                : 'text-muted hover:text-white hover:bg-surface3/40'
                        }`}
                    >
                        <Terminal size={14} />
                        Logs
                    </button>
                    <button
                        onClick={() => setActiveTab('loads')}
                        className={`flex items-center gap-2 px-4 py-2 text-xs font-bold uppercase tracking-wider rounded-lg transition-all ${
                            activeTab === 'loads'
                                ? 'bg-accent text-[#100f0e] shadow-lg shadow-accent/20'
                                : 'text-muted hover:text-white hover:bg-surface3/40'
                        }`}
                    >
                        <Activity size={14} />
                        Load Disaggregation
                    </button>
                    <button
                        onClick={() => setActiveTab('monitors')}
                        className={`flex items-center gap-2 px-4 py-2 text-xs font-bold uppercase tracking-wider rounded-lg transition-all ${
                            activeTab === 'monitors'
                                ? 'bg-accent text-[#100f0e] shadow-lg shadow-accent/20'
                                : 'text-muted hover:text-white hover:bg-surface3/40'
                        }`}
                    >
                        <ShieldCheck size={14} />
                        Monitors
                    </button>
                </div>
            </div>

            {activeTab === 'logs' ? (
                <LogsView
                    logs={logs}
                    loading={logsLoading}
                    error={logsError}
                    levelFilter={levelFilter}
                    setLevelFilter={setLevelFilter}
                    timeRange={timeRange}
                    setTimeRange={setTimeRange}
                    isLive={isLive}
                    setIsLive={setIsLive}
                    logInfo={logInfo}
                    loadLogs={loadLogs}
                    clearLogs={clearLogs}
                />
            ) : activeTab === 'loads' ? (
                <LoadDisaggregationView />
            ) : (
                <MonitorStatusCard />
            )}
        </div>
    )
}

export default function Debug() {
    return (
        <main>
            <DebugContent />
        </main>
    )
}
