import { useState, useEffect, useCallback } from 'react'
import { Cpu, Play, Power, Eye, History, AlertTriangle, CheckCircle, Clock, Zap, RefreshCw, Activity, Settings, Gauge, Flame, Battery, Sun, Plug, ArrowDownToLine, ArrowUpFromLine, Bell, X, BatteryCharging, Upload, Droplets } from 'lucide-react'
import Card from '../components/Card'

// Types for notifications
type NotificationSettings = {
    service: string
    on_charge_start: boolean
    on_charge_stop: boolean
    on_export_start: boolean
    on_export_stop: boolean
    on_water_heat_start: boolean
    on_water_heat_stop: boolean
    on_soc_target_change: boolean
    on_override_activated: boolean
    on_error: boolean
}

// Types for executor API responses
type ExecutorStatus = {
    enabled: boolean
    shadow_mode: boolean
    last_run_at?: string
    last_run_status: string
    last_error?: string
    next_run_at?: string
    current_slot?: string
    current_slot_plan?: {
        slot_start: string
        charge_kw: number
        export_kw: number
        water_kw: number
        soc_target: number
        soc_projected: number
    }
    last_action?: string
    override_active: boolean
    override_type?: string
    version?: string
}

type ExecutorStats = {
    period_days: number
    total_executions: number
    successful: number
    failed: number
    success_rate: number
    override_count: number
    override_rate: number
    override_types: Record<string, number>
}

type ExecutionRecord = {
    id: number
    executed_at: string
    slot_start: string
    success: number
    override_active: number
    override_type?: string
    override_reason?: string
    commanded_work_mode?: string
    commanded_grid_charging?: number
    commanded_charge_current_a?: number
    commanded_discharge_current_a?: number
    commanded_soc_target?: number
    commanded_water_temp?: number
    before_soc_percent?: number
    before_pv_kw?: number
    before_load_kw?: number
    duration_ms?: number
    error_message?: string
    source?: string
}

// API helpers
const executorApi = {
    status: async (): Promise<ExecutorStatus> => {
        const r = await fetch('/api/executor/status')
        if (!r.ok) throw new Error(`Status failed: ${r.status}`)
        return r.json()
    },
    toggle: async (payload: { enabled?: boolean; shadow_mode?: boolean }) => {
        const r = await fetch('/api/executor/toggle', {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify(payload)
        })
        if (!r.ok) throw new Error(`Toggle failed: ${r.status}`)
        return r.json()
    },
    run: async () => {
        const r = await fetch('/api/executor/run', { method: 'POST' })
        if (!r.ok) throw new Error(`Run failed: ${r.status}`)
        return r.json()
    },
    history: async (limit = 20): Promise<{ records: ExecutionRecord[]; count: number }> => {
        const r = await fetch(`/api/executor/history?limit=${limit}`)
        if (!r.ok) throw new Error(`History failed: ${r.status}`)
        return r.json()
    },
    stats: async (days = 7): Promise<ExecutorStats> => {
        const r = await fetch(`/api/executor/stats?days=${days}`)
        if (!r.ok) throw new Error(`Stats failed: ${r.status}`)
        return r.json()
    },
    live: async (): Promise<Record<string, { value: string; numeric?: number; unit?: string }>> => {
        const r = await fetch('/api/executor/live')
        if (!r.ok) throw new Error(`Live failed: ${r.status}`)
        return r.json()
    },
    notifications: {
        get: async (): Promise<NotificationSettings> => {
            const r = await fetch('/api/executor/notifications')
            if (!r.ok) throw new Error(`Notifications failed: ${r.status}`)
            return r.json()
        },
        update: async (settings: Partial<NotificationSettings>) => {
            const r = await fetch('/api/executor/notifications', {
                method: 'POST',
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify(settings)
            })
            if (!r.ok) throw new Error(`Notifications update failed: ${r.status}`)
            return r.json()
        },
        test: async () => {
            const r = await fetch('/api/executor/notifications/test', { method: 'POST' })
            const data = await r.json()
            if (!r.ok) throw new Error(data.error || `Test failed: ${r.status}`)
            return data
        }
    }
}

// Toggle switch component
function Toggle({ enabled, onChange, disabled = false, size = 'md' }: {
    enabled: boolean
    onChange: (v: boolean) => void
    disabled?: boolean
    size?: 'sm' | 'md'
}) {
    const sizeClasses = size === 'sm'
        ? 'h-5 w-9'
        : 'h-6 w-11'
    const knobClasses = size === 'sm'
        ? 'h-3 w-3'
        : 'h-4 w-4'
    const translateClasses = size === 'sm'
        ? (enabled ? 'translate-x-5' : 'translate-x-1')
        : (enabled ? 'translate-x-6' : 'translate-x-1')

    return (
        <button
            type="button"
            role="switch"
            aria-checked={enabled}
            disabled={disabled}
            onClick={() => onChange(!enabled)}
            className={`relative inline-flex items-center rounded-full transition-colors focus:outline-none focus:ring-2 focus:ring-accent focus:ring-offset-2 focus:ring-offset-surface ${sizeClasses} ${enabled ? 'bg-accent' : 'bg-surface2'
                } ${disabled ? 'opacity-50 cursor-not-allowed' : 'cursor-pointer'}`}
        >
            <span
                className={`inline-block transform rounded-full bg-white transition-transform ${knobClasses} ${translateClasses}`}
            />
        </button>
    )
}

export default function Executor() {
    const [status, setStatus] = useState<ExecutorStatus | null>(null)
    const [stats, setStats] = useState<ExecutorStats | null>(null)
    const [history, setHistory] = useState<ExecutionRecord[]>([])
    const [live, setLive] = useState<Record<string, { value: string; numeric?: number; unit?: string }> | null>(null)
    const [loading, setLoading] = useState(true)
    const [toggling, setToggling] = useState(false)
    const [running, setRunning] = useState(false)
    const [error, setError] = useState<string | null>(null)
    const [showNotifications, setShowNotifications] = useState(false)
    const [notifications, setNotifications] = useState<NotificationSettings | null>(null)
    const [savingNotification, setSavingNotification] = useState(false)
    const [testingNotification, setTestingNotification] = useState(false)
    const [testResult, setTestResult] = useState<{ success: boolean; message: string } | null>(null)

    const fetchAll = useCallback(async () => {
        try {
            const [statusRes, statsRes, historyRes] = await Promise.all([
                executorApi.status(),
                executorApi.stats(7),
                executorApi.history(20)
            ])
            setStatus(statusRes)
            setStats(statsRes)
            setHistory(historyRes.records)
            setError(null)
        } catch (e: any) {
            setError(e.message || 'Failed to load executor data')
        } finally {
            setLoading(false)
        }
    }, [])

    useEffect(() => {
        fetchAll()
        const interval = setInterval(fetchAll, 30000) // Refresh every 30s
        return () => clearInterval(interval)
    }, [fetchAll])

    // Faster refresh for live values (every 10s)
    useEffect(() => {
        const fetchLive = async () => {
            try {
                const liveRes = await executorApi.live()
                setLive(liveRes)
            } catch (e) {
                // Silently fail for live - not critical
            }
        }
        fetchLive()
        const liveInterval = setInterval(fetchLive, 10000)
        return () => clearInterval(liveInterval)
    }, [])

    // Fetch notifications on mount
    useEffect(() => {
        const fetchNotifications = async () => {
            try {
                const notifRes = await executorApi.notifications.get()
                setNotifications(notifRes)
            } catch (e) {
                // Silently fail
            }
        }
        fetchNotifications()
    }, [])

    const handleNotificationToggle = async (key: keyof NotificationSettings, value: boolean) => {
        if (!notifications) return
        setSavingNotification(true)
        try {
            await executorApi.notifications.update({ [key]: value })
            setNotifications(prev => prev ? { ...prev, [key]: value } : null)
        } catch (e: any) {
            setError(e.message)
        } finally {
            setSavingNotification(false)
        }
    }

    const handleToggleEnabled = async (enabled: boolean) => {
        setToggling(true)
        try {
            await executorApi.toggle({ enabled })
            await fetchAll()
        } catch (e: any) {
            setError(e.message)
        } finally {
            setToggling(false)
        }
    }

    const handleTestNotification = async () => {
        setTestingNotification(true)
        setTestResult(null)
        try {
            const res = await executorApi.notifications.test()
            setTestResult({ success: true, message: res.message || 'Test sent!' })
        } catch (e: any) {
            setTestResult({ success: false, message: e.message })
        } finally {
            setTestingNotification(false)
        }
    }

    const handleToggleShadow = async (shadow_mode: boolean) => {
        setToggling(true)
        try {
            await executorApi.toggle({ shadow_mode })
            await fetchAll()
        } catch (e: any) {
            setError(e.message)
        } finally {
            setToggling(false)
        }
    }

    const handleManualRun = async () => {
        setRunning(true)
        try {
            await executorApi.run()
            await fetchAll()
        } catch (e: any) {
            setError(e.message)
        } finally {
            setRunning(false)
        }
    }

    const formatTime = (iso?: string) => {
        if (!iso) return '—'
        try {
            return new Date(iso).toLocaleTimeString('sv-SE', { hour: '2-digit', minute: '2-digit' })
        } catch {
            return iso
        }
    }

    const formatDateTime = (iso?: string) => {
        if (!iso) return '—'
        try {
            return new Date(iso).toLocaleString('sv-SE', { month: 'short', day: 'numeric', hour: '2-digit', minute: '2-digit' })
        } catch {
            return iso
        }
    }

    // Determine status color
    const statusColor = status?.enabled
        ? status?.shadow_mode
            ? 'from-amber-900/60 via-surface to-surface'
            : 'from-emerald-900/60 via-surface to-surface'
        : 'from-slate-800/60 via-surface to-surface'

    const statusPulse = status?.enabled
        ? status?.shadow_mode
            ? 'bg-amber-400/90'
            : 'bg-emerald-400/90'
        : 'bg-slate-500/90'

    if (loading) {
        return (
            <div className="px-4 pt-16 pb-10 lg:px-8 lg:pt-10 space-y-6">
                <div className="animate-pulse space-y-4">
                    <div className="h-10 bg-surface2 rounded w-48" />
                    <div className="grid grid-cols-1 lg:grid-cols-3 gap-4">
                        <div className="h-64 bg-surface2 rounded" />
                        <div className="h-64 bg-surface2 rounded lg:col-span-2" />
                    </div>
                </div>
            </div>
        )
    }

    return (
        <div className="px-4 pt-16 pb-10 lg:px-8 lg:pt-10 space-y-6">
            {/* Header */}
            <div className="flex flex-col lg:flex-row lg:items-center lg:justify-between gap-3">
                <div>
                    <h1 className="text-lg font-medium text-text flex items-center gap-2">
                        Executor Control Center
                        <span className={`px-2 py-0.5 rounded-full border text-[10px] uppercase tracking-wider ${status?.enabled
                            ? status?.shadow_mode
                                ? 'bg-amber-500/20 border-amber-500/50 text-amber-300'
                                : 'bg-emerald-500/20 border-emerald-500/50 text-emerald-300'
                            : 'bg-slate-500/20 border-slate-500/50 text-slate-400'
                            }`}>
                            {status?.enabled ? (status?.shadow_mode ? 'Shadow' : 'Active') : 'Disabled'}
                        </span>
                    </h1>
                    <p className="text-[11px] text-muted">
                        Native execution engine — controls inverter and water heater based on the schedule.
                    </p>
                </div>
            </div>

            {error && (
                <div className="rounded-xl p-3 bg-red-500/10 border border-red-500/30 flex items-center gap-3">
                    <AlertTriangle className="h-4 w-4 text-red-400" />
                    <span className="text-red-300 text-[11px] flex-1">{error}</span>
                    <button onClick={() => setError(null)} className="text-red-400 hover:text-red-300 text-lg">×</button>
                </div>
            )}

            {/* Top Section - Status & Controls */}
            <div className="grid gap-4 lg:grid-cols-12">

                {/* Status Hero Card */}
                <Card className={`lg:col-span-5 p-4 md:p-5 bg-gradient-to-br ${statusColor} relative overflow-hidden`}>
                    <div className="relative z-10 flex items-start gap-4">
                        {/* Avatar & Pulse */}
                        <div className="relative flex items-center justify-center shrink-0">
                            <div className={`absolute h-14 w-14 rounded-full ${statusPulse} opacity-30 animate-pulse`} />
                            <div className="relative flex items-center justify-center w-12 h-12 rounded-full bg-surface/90 border border-line/80 shadow-float ring-2 ring-accent/20">
                                <Cpu className="h-6 w-6 text-accent drop-shadow-[0_0_12px_rgba(56,189,248,0.75)]" />
                            </div>
                        </div>

                        <div className="flex-1 min-w-0">
                            <div className="text-xs font-semibold text-text uppercase tracking-wide">Status</div>
                            <div className="text-lg font-medium text-text">
                                {status?.enabled
                                    ? status?.shadow_mode
                                        ? 'Shadow Mode'
                                        : 'Executing'
                                    : 'Standby'}
                            </div>
                            <div className="text-[11px] text-muted flex items-center gap-2 mt-1">
                                <span className={`h-1.5 w-1.5 rounded-full ${status?.last_run_status === 'success' ? 'bg-emerald-400' :
                                    status?.last_run_status === 'error' ? 'bg-red-400' :
                                        'bg-slate-400'
                                    }`} />
                                {status?.last_run_status === 'success' ? 'Last run successful' :
                                    status?.last_run_status === 'error' ? 'Last run failed' :
                                        'No runs yet'}
                            </div>
                        </div>
                    </div>

                    {/* Quick Stats */}
                    <div className="mt-4 pt-3 border-t border-white/10 grid grid-cols-3 gap-3">
                        <div>
                            <div className="text-[10px] text-muted/70 uppercase">Last Run</div>
                            <div className="text-sm font-mono text-text">{formatTime(status?.last_run_at)}</div>
                        </div>
                        <div>
                            <div className="text-[10px] text-muted/70 uppercase">Next Run</div>
                            <div className="text-sm font-mono text-text">{formatTime(status?.next_run_at)}</div>
                        </div>
                        <div>
                            <div className="text-[10px] text-muted/70 uppercase">Version</div>
                            <div className="text-sm font-mono text-text">{status?.version || '—'}</div>
                        </div>
                    </div>

                    {status?.override_active && (
                        <div className="mt-3 p-2 rounded-lg bg-amber-500/20 border border-amber-500/30">
                            <div className="flex items-center gap-2 text-[11px] text-amber-300">
                                <AlertTriangle className="h-3.5 w-3.5" />
                                <span className="font-medium">Override Active:</span>
                                <span>{status.override_type}</span>
                            </div>
                        </div>
                    )}
                </Card>

                {/* Controls Card */}
                <Card className="lg:col-span-4 p-4 md:p-5 flex flex-col">
                    <div className="flex items-center gap-2 mb-4">
                        <Settings className="h-4 w-4 text-accent" />
                        <span className="text-xs font-medium text-text">Controls</span>
                    </div>

                    {/* Enabled Toggle */}
                    <div className="flex items-center justify-between p-2.5 rounded-lg bg-surface2/50 border border-line/50">
                        <div className="flex flex-col">
                            <span className="text-[11px] font-medium text-text">Executor Enabled</span>
                            <span className="text-[9px] text-muted">Execute actions on Home Assistant</span>
                        </div>
                        <Toggle
                            enabled={status?.enabled ?? false}
                            onChange={handleToggleEnabled}
                            disabled={toggling}
                            size="sm"
                        />
                    </div>

                    {/* Shadow Mode Toggle */}
                    <div className="flex items-center justify-between p-2.5 rounded-lg bg-surface2/50 border border-line/50 mt-2">
                        <div className="flex flex-col">
                            <div className="text-[11px] font-medium text-text flex items-center gap-1.5">
                                Shadow Mode
                                <Eye className="h-3 w-3 text-muted" />
                            </div>
                            <span className="text-[9px] text-muted">Log only, don't execute actions</span>
                        </div>
                        <Toggle
                            enabled={status?.shadow_mode ?? false}
                            onChange={handleToggleShadow}
                            disabled={toggling}
                            size="sm"
                        />
                    </div>

                    {/* Notifications Button */}
                    <button
                        onClick={() => setShowNotifications(true)}
                        className="flex items-center justify-between p-2.5 rounded-lg bg-surface2/50 border border-line/50 mt-2 hover:bg-surface2 transition-colors w-full"
                    >
                        <div className="flex items-center gap-2">
                            <Bell className="h-4 w-4 text-muted" />
                            <span className="text-[11px] font-medium text-text">Notifications</span>
                        </div>
                        {notifications && Object.entries(notifications).some(([k, v]) => k.startsWith('on_') && v === true) && (
                            <div className="relative">
                                <span className="absolute inset-0 rounded-full bg-accent/50 blur-sm animate-pulse" />
                                <span className="relative h-2.5 w-2.5 rounded-full bg-accent block ring-2 ring-accent/30" />
                            </div>
                        )}
                    </button>

                    {/* Run Now Button */}
                    <div className="mt-auto pt-4">
                        <button
                            onClick={handleManualRun}
                            disabled={running}
                            className={`w-full flex items-center justify-center gap-2 px-4 py-2.5 rounded-xl bg-surface hover:bg-surface2 border border-line/50 text-[11px] font-medium transition-all ${running ? 'opacity-70 cursor-not-allowed text-muted' : 'text-text hover:border-accent/50'
                                }`}
                        >
                            {running ? (
                                <>
                                    <div className="h-3.5 w-3.5 border-2 border-accent/30 border-t-accent rounded-full animate-spin" />
                                    <span>Running...</span>
                                </>
                            ) : (
                                <>
                                    <Play className="h-3.5 w-3.5 text-accent" />
                                    <span>Run Now</span>
                                </>
                            )}
                        </button>
                    </div>
                </Card>

                {/* Stats Card */}
                <Card className="lg:col-span-3 p-4 md:p-5 flex flex-col">
                    <div className="flex items-center gap-2 mb-4">
                        <Gauge className="h-4 w-4 text-accent" />
                        <span className="text-xs font-medium text-text">7-Day Stats</span>
                    </div>

                    {stats && (
                        <div className="grid grid-cols-2 gap-3 flex-1">
                            <div className="p-3 rounded-lg bg-surface2/30 border border-line/30">
                                <div className="text-xl font-bold text-text">{stats.total_executions}</div>
                                <div className="text-[10px] text-muted">Total Runs</div>
                            </div>
                            <div className="p-3 rounded-lg bg-emerald-500/10 border border-emerald-500/20">
                                <div className="text-xl font-bold text-emerald-400">{stats.success_rate}%</div>
                                <div className="text-[10px] text-muted">Success Rate</div>
                            </div>
                            <div className="p-3 rounded-lg bg-amber-500/10 border border-amber-500/20">
                                <div className="text-xl font-bold text-amber-400">{stats.override_count}</div>
                                <div className="text-[10px] text-muted">Overrides</div>
                            </div>
                            <div className="p-3 rounded-lg bg-red-500/10 border border-red-500/20">
                                <div className="text-xl font-bold text-red-400">{stats.failed}</div>
                                <div className="text-[10px] text-muted">Failed</div>
                            </div>
                        </div>
                    )}
                </Card>
            </div>

            {/* Live System Values */}
            <Card className="p-4 md:p-5">
                <div className="flex items-center justify-between mb-4">
                    <div className="flex items-center gap-2">
                        <Activity className="h-4 w-4 text-accent" />
                        <span className="text-xs font-medium text-text">Live System</span>
                        <span className="text-[9px] text-muted/70">(every 10s)</span>
                    </div>
                    {live?.work_mode && (
                        <span className={`text-[10px] px-2 py-0.5 rounded-full border ${live.work_mode.value.includes('Export')
                            ? 'bg-emerald-500/20 border-emerald-500/30 text-emerald-300'
                            : 'bg-blue-500/20 border-blue-500/30 text-blue-300'
                            }`}>
                            {live.work_mode.value}
                        </span>
                    )}
                </div>

                <div className="grid grid-cols-2 md:grid-cols-5 gap-3">
                    {/* SoC */}
                    <div className="p-3 rounded-lg bg-surface2/30 border border-line/30 flex items-center gap-3">
                        <Battery className={`h-6 w-6 ${(live?.soc?.numeric ?? 0) > 50 ? 'text-emerald-400' :
                            (live?.soc?.numeric ?? 0) > 20 ? 'text-amber-400' : 'text-red-400'
                            }`} />
                        <div>
                            <div className="text-lg font-bold text-text">
                                {live?.soc?.numeric?.toFixed(0) ?? '—'}%
                            </div>
                            <div className="text-[10px] text-muted">Battery SoC</div>
                        </div>
                    </div>

                    {/* PV Power */}
                    <div className="p-3 rounded-lg bg-surface2/30 border border-line/30 flex items-center gap-3">
                        <Sun className={`h-6 w-6 ${(live?.pv_power?.numeric ?? 0) > 500 ? 'text-yellow-400' : 'text-yellow-400/40'
                            }`} />
                        <div>
                            <div className="text-lg font-bold text-yellow-400">
                                {live?.pv_power?.numeric ? (live.pv_power.numeric / 1000).toFixed(1) : '—'} kW
                            </div>
                            <div className="text-[10px] text-muted">PV Power</div>
                        </div>
                    </div>

                    {/* Load */}
                    <div className="p-3 rounded-lg bg-surface2/30 border border-line/30 flex items-center gap-3">
                        <Plug className="h-6 w-6 text-orange-400" />
                        <div>
                            <div className="text-lg font-bold text-orange-400">
                                {live?.load_power?.numeric ? (live.load_power.numeric / 1000).toFixed(1) : '—'} kW
                            </div>
                            <div className="text-[10px] text-muted">Load</div>
                        </div>
                    </div>

                    {/* Grid Import */}
                    <div className="p-3 rounded-lg bg-surface2/30 border border-line/30 flex items-center gap-3">
                        <ArrowDownToLine className={`h-6 w-6 ${(live?.grid_import?.numeric ?? 0) > 100 ? 'text-red-400' : 'text-slate-400'
                            }`} />
                        <div>
                            <div className={`text-lg font-bold ${(live?.grid_import?.numeric ?? 0) > 100 ? 'text-red-400' : 'text-text'
                                }`}>
                                {live?.grid_import?.numeric ? (live.grid_import.numeric / 1000).toFixed(2) : '—'} kW
                            </div>
                            <div className="text-[10px] text-muted">Grid Import</div>
                        </div>
                    </div>

                    {/* Grid Export */}
                    <div className="p-3 rounded-lg bg-surface2/30 border border-line/30 flex items-center gap-3">
                        <ArrowUpFromLine className={`h-6 w-6 ${(live?.grid_export?.numeric ?? 0) > 100 ? 'text-emerald-400' : 'text-slate-400'
                            }`} />
                        <div>
                            <div className={`text-lg font-bold ${(live?.grid_export?.numeric ?? 0) > 100 ? 'text-emerald-400' : 'text-text'
                                }`}>
                                {live?.grid_export?.numeric ? (live.grid_export.numeric / 1000).toFixed(2) : '—'} kW
                            </div>
                            <div className="text-[10px] text-muted">Grid Export</div>
                        </div>
                    </div>
                </div>
            </Card>

            {/* Execution History */}
            <Card className="p-4 md:p-5">
                <div className="flex items-center justify-between mb-4">
                    <div className="flex items-center gap-2">
                        <History className="h-4 w-4 text-accent" />
                        <span className="text-xs font-medium text-text">Execution History</span>
                        <span className="text-[10px] text-muted">({history.length} records)</span>
                    </div>
                    <button
                        onClick={fetchAll}
                        className="flex items-center gap-1.5 text-[10px] text-muted hover:text-accent transition px-2 py-1 rounded-lg hover:bg-surface2"
                    >
                        <RefreshCw className="h-3 w-3" />
                        Refresh
                    </button>
                </div>

                {history.length === 0 ? (
                    <div className="text-center py-12 text-muted">
                        <Clock className="h-10 w-10 mx-auto opacity-20 mb-3" />
                        <p className="text-[11px]">No execution history yet.</p>
                        <p className="text-[10px] mt-1 text-muted/70">Run the executor to see results here.</p>
                    </div>
                ) : (
                    <div className="space-y-2 max-h-[400px] overflow-y-auto pr-2 custom-scrollbar">
                        {/* Next Slot Preview */}
                        {status?.next_run_at && (
                            <div className="p-3 rounded-xl border-2 border-dashed border-line/30 bg-surface2/10 opacity-70">
                                <div className="flex items-center justify-between">
                                    <div className="flex items-center gap-2">
                                        <Clock className="h-4 w-4 text-muted animate-pulse" />
                                        <span className="text-[11px] text-muted font-mono">
                                            Next: {formatTime(status.next_run_at)}
                                        </span>
                                    </div>
                                    <span className="text-[9px] text-muted/70 bg-surface2/50 px-2 py-0.5 rounded-full">
                                        Scheduled
                                    </span>
                                </div>
                                {status.current_slot_plan && (
                                    <div className="mt-2 grid grid-cols-4 gap-2 text-[10px]">
                                        {status.current_slot_plan.charge_kw > 0 && (
                                            <div className="flex items-center gap-1 text-emerald-400">
                                                <BatteryCharging className="h-3 w-3" />
                                                <span>{status.current_slot_plan.charge_kw.toFixed(1)}kW</span>
                                            </div>
                                        )}
                                        {status.current_slot_plan.export_kw > 0 && (
                                            <div className="flex items-center gap-1 text-amber-400">
                                                <Upload className="h-3 w-3" />
                                                <span>{status.current_slot_plan.export_kw.toFixed(1)}kW</span>
                                            </div>
                                        )}
                                        {status.current_slot_plan.water_kw > 0 && (
                                            <div className="flex items-center gap-1 text-sky-400">
                                                <Droplets className="h-3 w-3" />
                                                <span>{status.current_slot_plan.water_kw.toFixed(1)}kW</span>
                                            </div>
                                        )}
                                        {status.current_slot_plan.soc_target > 0 && (
                                            <div className="flex items-center gap-1 text-muted">
                                                <span>SoC→{status.current_slot_plan.soc_target}%</span>
                                            </div>
                                        )}
                                        {!status.current_slot_plan.charge_kw && !status.current_slot_plan.export_kw && !status.current_slot_plan.water_kw && (
                                            <div className="text-muted/60 col-span-4">Idle / Self-consumption</div>
                                        )}
                                    </div>
                                )}
                            </div>
                        )}

                        {history.map((record) => (
                            <div
                                key={record.id}
                                className={`p-3 rounded-xl border transition-colors ${record.success
                                    ? 'bg-surface2/30 border-line/40 hover:border-line/60'
                                    : 'bg-red-500/10 border-red-500/30 hover:border-red-500/50'
                                    }`}
                            >
                                <div className="flex items-center justify-between">
                                    <div className="flex items-center gap-2">
                                        {record.success ? (
                                            <CheckCircle className="h-4 w-4 text-emerald-400" />
                                        ) : (
                                            <AlertTriangle className="h-4 w-4 text-red-400" />
                                        )}
                                        <span className="text-[11px] text-text font-mono">
                                            {formatDateTime(record.executed_at)}
                                        </span>
                                    </div>
                                    <div className="flex items-center gap-2">
                                        {record.override_active ? (
                                            <span className="text-[9px] text-amber-400 bg-amber-500/20 px-2 py-0.5 rounded-full border border-amber-500/30">
                                                {record.override_type}
                                            </span>
                                        ) : null}
                                        {record.duration_ms && (
                                            <span className="text-[9px] text-muted font-mono">{record.duration_ms}ms</span>
                                        )}
                                    </div>
                                </div>

                                {/* Execution Details */}
                                <div className="mt-2 grid grid-cols-2 md:grid-cols-4 gap-2 text-[10px]">
                                    {record.commanded_work_mode && (
                                        <div className="flex flex-col">
                                            <span className="text-muted/70">Work Mode</span>
                                            <span className="text-text font-medium">{record.commanded_work_mode}</span>
                                        </div>
                                    )}
                                    {record.commanded_soc_target != null && (
                                        <div className="flex flex-col">
                                            <span className="text-muted/70">SoC Target</span>
                                            <span className="text-text font-medium">{record.commanded_soc_target}%</span>
                                        </div>
                                    )}
                                    {record.commanded_charge_current_a != null && record.commanded_charge_current_a > 0 && (
                                        <div className="flex flex-col">
                                            <span className="text-muted/70">Charge Current</span>
                                            <span className="text-emerald-400 font-medium">{record.commanded_charge_current_a}A</span>
                                        </div>
                                    )}
                                    {record.commanded_discharge_current_a != null && record.commanded_discharge_current_a > 0 && (
                                        <div className="flex flex-col">
                                            <span className="text-muted/70">Discharge Current</span>
                                            <span className="text-amber-400 font-medium">{record.commanded_discharge_current_a}A</span>
                                        </div>
                                    )}
                                    {record.commanded_water_temp != null && record.commanded_water_temp > 40 && (
                                        <div className="flex flex-col">
                                            <span className="text-muted/70">Water Temp</span>
                                            <span className="text-orange-400 font-medium flex items-center gap-1">
                                                <Flame className="h-3 w-3" />
                                                {record.commanded_water_temp}°C
                                            </span>
                                        </div>
                                    )}
                                    {record.before_soc_percent != null && (
                                        <div className="flex flex-col">
                                            <span className="text-muted/70">SoC Before</span>
                                            <span className="text-text font-medium">{record.before_soc_percent?.toFixed(0)}%</span>
                                        </div>
                                    )}
                                </div>

                                {record.error_message && (
                                    <div className="mt-2 text-[10px] text-red-400 bg-red-500/10 rounded-lg p-2">
                                        {record.error_message}
                                    </div>
                                )}
                                {record.override_reason && (
                                    <div className="mt-2 text-[10px] text-amber-300/80 bg-amber-500/10 rounded-lg p-2">
                                        {record.override_reason}
                                    </div>
                                )}
                            </div>
                        ))}
                    </div>
                )}
            </Card>

            {/* Notifications Modal */}
            {showNotifications && (
                <div className="fixed inset-0 z-50 flex items-center justify-center bg-black/60 backdrop-blur-sm" onClick={() => setShowNotifications(false)}>
                    <div
                        className="bg-surface border border-line rounded-2xl p-5 w-full max-w-md shadow-2xl"
                        onClick={e => e.stopPropagation()}
                    >
                        <div className="flex items-center justify-between mb-4">
                            <div className="flex items-center gap-2">
                                <Bell className="h-5 w-5 text-accent" />
                                <span className="text-sm font-medium text-text">Notification Settings</span>
                            </div>
                            <button
                                onClick={() => setShowNotifications(false)}
                                className="text-muted hover:text-text transition p-1"
                            >
                                <X className="h-5 w-5" />
                            </button>
                        </div>

                        {notifications && (
                            <div className="space-y-2">
                                {/* Service */}
                                <div className="p-2 rounded-lg bg-surface2/30 border border-line/30 mb-3">
                                    <div className="text-[10px] text-muted mb-1">HA Notify Service</div>
                                    <div className="text-[11px] text-text font-mono">{notifications.service || 'Not configured'}</div>
                                </div>

                                {/* Toggle items */}
                                {[
                                    { key: 'on_charge_start', label: 'Charge Started', desc: 'When grid charging begins' },
                                    { key: 'on_charge_stop', label: 'Charge Stopped', desc: 'When grid charging ends' },
                                    { key: 'on_export_start', label: 'Export Started', desc: 'When battery export begins' },
                                    { key: 'on_export_stop', label: 'Export Stopped', desc: 'When battery export ends' },
                                    { key: 'on_water_heat_start', label: 'Water Heating Started', desc: 'When water heater activates' },
                                    { key: 'on_water_heat_stop', label: 'Water Heating Stopped', desc: 'When water heater deactivates' },
                                    { key: 'on_soc_target_change', label: 'SoC Target Changed', desc: 'When battery target changes' },
                                    { key: 'on_override_activated', label: 'Override Activated', desc: 'When emergency override triggers' },
                                    { key: 'on_error', label: 'Errors', desc: 'When execution fails' },
                                ].map(item => (
                                    <div key={item.key} className="flex items-center justify-between p-2.5 rounded-lg bg-surface2/50 border border-line/50">
                                        <div className="flex flex-col">
                                            <span className="text-[11px] font-medium text-text">{item.label}</span>
                                            <span className="text-[9px] text-muted">{item.desc}</span>
                                        </div>
                                        <Toggle
                                            enabled={notifications[item.key as keyof NotificationSettings] as boolean}
                                            onChange={(v) => handleNotificationToggle(item.key as keyof NotificationSettings, v)}
                                            disabled={savingNotification}
                                            size="sm"
                                        />
                                    </div>
                                ))}
                            </div>
                        )}

                        {/* Test Button & Status */}
                        <div className="mt-4 pt-3 border-t border-line/30">
                            <button
                                onClick={handleTestNotification}
                                disabled={testingNotification}
                                className={`w-full flex items-center justify-center gap-2 px-4 py-2.5 rounded-xl border text-[11px] font-medium transition-all ${testingNotification
                                    ? 'bg-surface2/50 border-line/30 text-muted cursor-not-allowed'
                                    : 'bg-accent/10 border-accent/30 text-accent hover:bg-accent/20'
                                    }`}
                            >
                                {testingNotification ? (
                                    <>
                                        <div className="h-3 w-3 border-2 border-accent/30 border-t-accent rounded-full animate-spin" />
                                        Sending...
                                    </>
                                ) : (
                                    <>
                                        <Bell className="h-3.5 w-3.5" />
                                        Send Test Notification
                                    </>
                                )}
                            </button>

                            {testResult && (
                                <div className={`mt-2 text-center text-[10px] ${testResult.success ? 'text-emerald-400' : 'text-red-400'}`}>
                                    {testResult.message}
                                </div>
                            )}

                            <div className="mt-2 text-center text-[9px] text-muted/70">
                                Changes are saved automatically
                            </div>
                        </div>
                    </div>
                </div>
            )}
        </div>
    )
}
