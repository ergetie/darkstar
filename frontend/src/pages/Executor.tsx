/* eslint-disable @typescript-eslint/no-explicit-any */
import { useState, useEffect, useCallback } from 'react'
import {
    Cpu,
    Play,
    Power,
    Eye,
    History,
    AlertTriangle,
    CheckCircle,
    Clock,
    Zap,
    RefreshCw,
    Activity,
    Settings,
    Gauge,
    Battery,
    Sun,
    Plug,
    ArrowDownToLine,
    ArrowUpFromLine,
    Bell,
    X,
    BatteryCharging,
    Upload,
    Droplets,
    ChevronDown,
} from 'lucide-react'
import Card from '../components/Card'
import MiniBarGraph from '../components/MiniBarGraph'
import { useSocket } from '../lib/hooks'

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
    quick_action?: {
        type: string
        expires_at: string
        remaining_minutes: number
        reason: string
    }
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
    // Planned values from schedule
    planned_charge_kw?: number
    planned_discharge_kw?: number
    planned_export_kw?: number
    planned_water_kw?: number
    planned_soc_target?: number
    planned_soc_projected?: number
    // Commanded values (what we actually set)
    commanded_work_mode?: string
    commanded_grid_charging?: number
    commanded_charge_current_a?: number
    commanded_discharge_current_a?: number
    commanded_soc_target?: number
    commanded_water_temp?: number
    // State before execution
    before_soc_percent?: number
    before_work_mode?: string
    before_water_temp?: number
    before_pv_kw?: number
    before_load_kw?: number
    // Result
    duration_ms?: number
    error_message?: string
    source?: string
}

// API helpers - using relative paths for HA Ingress compatibility
const executorApi = {
    status: async (): Promise<ExecutorStatus> => {
        const r = await fetch('api/executor/status')
        if (!r.ok) throw new Error(`Status failed: ${r.status}`)
        return r.json()
    },
    toggle: async (payload: { enabled?: boolean; shadow_mode?: boolean }) => {
        const r = await fetch('api/executor/toggle', {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify(payload),
        })
        if (!r.ok) throw new Error(`Toggle failed: ${r.status}`)
        return r.json()
    },
    run: async () => {
        const r = await fetch('api/executor/run', { method: 'POST' })
        if (!r.ok) throw new Error(`Run failed: ${r.status}`)
        return r.json()
    },
    history: async (limit = 20): Promise<{ records: ExecutionRecord[]; count: number }> => {
        const r = await fetch(`api/executor/history?limit=${limit}`)
        if (!r.ok) throw new Error(`History failed: ${r.status}`)
        return r.json()
    },
    stats: async (days = 7): Promise<ExecutorStats> => {
        const r = await fetch(`api/executor/stats?days=${days}`)
        if (!r.ok) throw new Error(`Stats failed: ${r.status}`)
        return r.json()
    },
    live: async (): Promise<Record<string, { value: string; numeric?: number; unit?: string }>> => {
        const r = await fetch('api/executor/live')
        if (!r.ok) throw new Error(`Live failed: ${r.status}`)
        return r.json()
    },
    notifications: {
        get: async (): Promise<NotificationSettings> => {
            const r = await fetch('api/executor/notifications')
            if (!r.ok) throw new Error(`Notifications failed: ${r.status}`)
            return r.json()
        },
        update: async (settings: Partial<NotificationSettings>) => {
            const r = await fetch('api/executor/notifications', {
                method: 'POST',
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify(settings),
            })
            if (!r.ok) throw new Error(`Notifications update failed: ${r.status}`)
            return r.json()
        },
        test: async () => {
            const r = await fetch('api/executor/notifications/test', { method: 'POST' })
            const data = await r.json()
            if (!r.ok) throw new Error(data.error || `Test failed: ${r.status}`)
            return data
        },
    },
    config: {
        get: async (): Promise<EntityConfig> => {
            const r = await fetch('api/executor/config')
            if (!r.ok) throw new Error(`Config get failed: ${r.status}`)
            return r.json()
        },
        update: async (config: Partial<EntityConfig>) => {
            const r = await fetch('api/executor/config', {
                method: 'PUT',
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify(config),
            })
            if (!r.ok) throw new Error(`Config update failed: ${r.status}`)
            return r.json()
        },
    },
    quickAction: {
        get: async (): Promise<{ quick_action: QuickAction | null }> => {
            const r = await fetch('api/executor/quick-action')
            if (!r.ok) throw new Error(`Quick action get failed: ${r.status}`)
            return r.json()
        },
        set: async (type: string, duration_minutes: number) => {
            const r = await fetch('api/executor/quick-action', {
                method: 'POST',
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify({ type, duration_minutes }),
            })
            if (!r.ok) throw new Error(`Quick action set failed: ${r.status}`)
            return r.json()
        },
        clear: async () => {
            const r = await fetch('api/executor/quick-action', { method: 'DELETE' })
            if (!r.ok) throw new Error(`Quick action clear failed: ${r.status}`)
            return r.json()
        },
    },
}

// Quick action type
type QuickAction = {
    type: string
    expires_at: string
    remaining_minutes: number
    reason: string
}

// Entity config type
type EntityConfig = {
    soc_target_entity: string
    inverter: {
        work_mode_entity: string
        grid_charging_entity: string
        max_charging_current_entity: string
        max_discharging_current_entity: string
    }
    water_heater: {
        target_entity: string
        temp_normal: number
        temp_off: number
        temp_boost: number
        temp_max: number
    }
}

// Toggle switch component
function Toggle({
    enabled,
    onChange,
    disabled = false,
    size = 'md',
}: {
    enabled: boolean
    onChange: (v: boolean) => void
    disabled?: boolean
    size?: 'sm' | 'md'
}) {
    const sizeClasses = size === 'sm' ? 'h-5 w-9' : 'h-6 w-11'
    const knobClasses = size === 'sm' ? 'h-3 w-3' : 'h-4 w-4'
    const translateClasses =
        size === 'sm' ? (enabled ? 'translate-x-5' : 'translate-x-1') : enabled ? 'translate-x-6' : 'translate-x-1'

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

import {
    Chart as ChartJS,
    CategoryScale,
    LinearScale,
    PointElement,
    LineElement,
    Title,
    Tooltip,
    Legend,
    Filler,
} from 'chart.js'

ChartJS.register(CategoryScale, LinearScale, PointElement, LineElement, Title, Tooltip, Legend, Filler)

export default function Executor() {
    const [status, setStatus] = useState<ExecutorStatus | null>(null)
    const [stats, setStats] = useState<ExecutorStats | null>(null)
    const [history, setHistory] = useState<ExecutionRecord[]>([])
    const [live, setLive] = useState<Record<string, { value: string; numeric?: number; unit?: string }> | null>(null)
    // Buffer for sparklines (last 20 points)
    const [historyBuffer, setHistoryBuffer] = useState<{
        soc: number[]
        pv: number[]
        load: number[]
        import: number[]
        export: number[]
        labels: string[]
    }>({ soc: [], pv: [], load: [], import: [], export: [], labels: [] })

    const [loading, setLoading] = useState(true)
    const [toggling, setToggling] = useState(false)
    const [running, setRunning] = useState(false)
    const [error, setError] = useState<string | null>(null)
    const [showNotifications, setShowNotifications] = useState(false)
    const [notifications, setNotifications] = useState<NotificationSettings | null>(null)
    const [savingNotification, setSavingNotification] = useState(false)
    const [testingNotification, setTestingNotification] = useState(false)
    const [testResult, setTestResult] = useState<{ success: boolean; message: string } | null>(null)
    const [expandedRecordId, setExpandedRecordId] = useState<number | null>(null)

    const fetchAll = useCallback(async () => {
        try {
            const [statusRes, statsRes, historyRes] = await Promise.all([
                executorApi.status(),
                executorApi.stats(7),
                executorApi.history(20),
            ])
            setStatus(statusRes)
            setStats(statsRes)
            setHistory(historyRes.records ?? [])
            setError(null)
        } catch (e: any) {
            setError(e.message || 'Failed to load executor data')
        } finally {
            setLoading(false)
        }
    }, [])

    // --- WebSocket Event Handlers (Rev E1) ---
    useSocket('live_metrics', (data: any) => {
        setLive((prev) => {
            const next = { ...(prev || {}) }
            if (data.soc !== undefined) next.soc = { value: `${data.soc.toFixed(0)}%`, numeric: data.soc, unit: '%' }
            if (data.pv_kw !== undefined)
                next.pv_power = { value: `${data.pv_kw.toFixed(1)} kW`, numeric: data.pv_kw * 1000, unit: 'W' }
            if (data.load_kw !== undefined)
                next.load_power = { value: `${data.load_kw.toFixed(1)} kW`, numeric: data.load_kw * 1000, unit: 'W' }
            if (data.grid_import_kw !== undefined)
                next.grid_import = {
                    value: `${data.grid_import_kw.toFixed(2)} kW`,
                    numeric: data.grid_import_kw * 1000,
                    unit: 'W',
                }
            if (data.grid_export_kw !== undefined)
                next.grid_export = {
                    value: `${data.grid_export_kw.toFixed(2)} kW`,
                    numeric: data.grid_export_kw * 1000,
                    unit: 'W',
                }
            if (data.work_mode) next.work_mode = { value: data.work_mode }
            return next
        })

        setHistoryBuffer((prev) => {
            const limit = 20
            const newLabels = [...prev.labels, '']
            const newSoc = [...prev.soc, data.soc ?? prev.soc[prev.soc.length - 1] ?? 0]
            const newPv = [...prev.pv, data.pv_kw ?? prev.pv[prev.pv.length - 1] ?? 0]
            const newLoad = [...prev.load, data.load_kw ?? prev.load[prev.load.length - 1] ?? 0]
            const newImport = [...prev.import, data.grid_import_kw ?? prev.import[prev.import.length - 1] ?? 0]
            const newExport = [...prev.export, data.grid_export_kw ?? prev.export[prev.export.length - 1] ?? 0]

            if (newLabels.length > limit) {
                newLabels.shift()
                newSoc.shift()
                newPv.shift()
                newLoad.shift()
                newImport.shift()
                newExport.shift()
            }

            return {
                labels: newLabels,
                soc: newSoc,
                pv: newPv,
                load: newLoad,
                import: newImport,
                export: newExport,
            }
        })
    })

    useSocket('executor_status', (data: any) => {
        setStatus(data)
    })

    // Initial data load
    useEffect(() => {
        setLoading(true)
        fetchAll()
        const interval = setInterval(fetchAll, 30000) // Keep status polling as backup
        return () => clearInterval(interval)
    }, [fetchAll])

    // Initial fetch for live values (just once)
    useEffect(() => {
        const loadInitialLive = async () => {
            try {
                const data: any = await executorApi.live()
                // Transform raw data to UI format (same as socket handler)
                const formatted: any = {}

                if (data.soc !== undefined)
                    formatted.soc = { value: `${Number(data.soc).toFixed(0)}%`, numeric: Number(data.soc), unit: '%' }

                if (data.pv_kw !== undefined)
                    formatted.pv_power = {
                        value: `${Number(data.pv_kw).toFixed(1)} kW`,
                        numeric: Number(data.pv_kw) * 1000,
                        unit: 'W',
                    }

                if (data.load_kw !== undefined)
                    formatted.load_power = {
                        value: `${Number(data.load_kw).toFixed(1)} kW`,
                        numeric: Number(data.load_kw) * 1000,
                        unit: 'W',
                    }

                if (data.grid_import_kw !== undefined)
                    formatted.grid_import = {
                        value: `${Number(data.grid_import_kw).toFixed(2)} kW`,
                        numeric: Number(data.grid_import_kw) * 1000,
                        unit: 'W',
                    }

                if (data.grid_export_kw !== undefined)
                    formatted.grid_export = {
                        value: `${Number(data.grid_export_kw).toFixed(2)} kW`,
                        numeric: Number(data.grid_export_kw) * 1000,
                        unit: 'W',
                    }

                if (data.work_mode) formatted.work_mode = { value: data.work_mode }

                setLive(formatted)
            } catch (e) {
                console.error('Failed to load initial live metrics', e)
            }
        }
        loadInitialLive()
    }, [])

    // Fetch notifications on mount
    useEffect(() => {
        const fetchNotifications = async () => {
            try {
                const notifRes = await executorApi.notifications.get()
                setNotifications(notifRes)
            } catch {
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
            setNotifications((prev) => (prev ? { ...prev, [key]: value } : null))
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
            return new Date(iso).toLocaleString('sv-SE', {
                month: 'short',
                day: 'numeric',
                hour: '2-digit',
                minute: '2-digit',
            })
        } catch {
            return iso
        }
    }

    // Determine status color
    const statusColor = status?.enabled
        ? status?.shadow_mode
            ? 'from-warn-900/60 via-surface to-surface'
            : 'from-good-900/60 via-surface to-surface'
        : 'from-neutral-800/60 via-surface to-surface'

    const statusPulse = status?.enabled ? (status?.shadow_mode ? 'bg-warn/90' : 'bg-good/90') : 'bg-neutral/90'

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
                        <span
                            className={`px-2 py-0.5 rounded-full border text-[10px] uppercase tracking-wider ${status?.enabled
                                    ? status?.shadow_mode
                                        ? 'bg-warn/20 border-warn/50 text-warn'
                                        : 'bg-good/20 border-good/50 text-good'
                                    : 'bg-neutral/20 border-neutral/50 text-neutral'
                                }`}
                        >
                            {status?.enabled ? (status?.shadow_mode ? 'Shadow' : 'Active') : 'Disabled'}
                        </span>
                    </h1>
                    <p className="text-[11px] text-muted">
                        Native execution engine — controls inverter and water heater based on the schedule.
                    </p>
                </div>
            </div>

            {error && (
                <div className="rounded-xl p-3 bg-bad/10 border border-bad/30 flex items-center gap-3">
                    <AlertTriangle className="h-4 w-4 text-bad" />
                    <span className="text-bad text-[11px] flex-1">{error}</span>
                    <button onClick={() => setError(null)} className="text-bad hover:text-bad/80 text-lg">
                        ×
                    </button>
                </div>
            )}

            {/* Top Section - Status & Controls */}
            <div className="grid gap-4 lg:grid-cols-12">
                {/* Status Hero Card */}
                <Card className={`lg:col-span-5 p-4 md:p-5 bg-gradient-to-br ${statusColor} relative overflow-hidden`}>
                    <div className="relative z-10 flex items-start gap-4">
                        {/* Avatar & Pulse */}
                        <div className="relative flex items-center justify-center shrink-0">
                            <div
                                className={`absolute h-14 w-14 rounded-full ${statusPulse} opacity-30 animate-pulse`}
                            />
                            <div className="relative flex items-center justify-center w-12 h-12 rounded-full bg-surface/90 border border-line/80 shadow-float ring-2 ring-accent/20">
                                <Cpu className="h-6 w-6 text-accent drop-shadow-[0_0_12px_rgba(56,189,248,0.75)]" />
                            </div>
                        </div>

                        <div className="flex-1 min-w-0">
                            <div className="text-xs font-semibold text-text uppercase tracking-wide">Status</div>
                            <div className="text-lg font-medium text-text">
                                {status?.enabled ? (status?.shadow_mode ? 'Shadow Mode' : 'Executing') : 'Standby'}
                            </div>
                            <div className="text-[11px] text-muted flex items-center gap-2 mt-1">
                                <span
                                    className={`h-1.5 w-1.5 rounded-full ${status?.last_run_status === 'success'
                                            ? 'bg-good'
                                            : status?.last_run_status === 'error'
                                                ? 'bg-bad'
                                                : 'bg-neutral'
                                        }`}
                                />
                                {status?.last_run_status === 'success'
                                    ? 'Last run successful'
                                    : status?.last_run_status === 'error'
                                        ? 'Last run failed'
                                        : 'No runs yet'}
                            </div>
                        </div>
                    </div>

                    {/* Quick Stats */}
                    <div className="mt-4 pt-3 border-t border-line/10 grid grid-cols-3 gap-3">
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
                        <div className="mt-3 p-2 rounded-lg bg-warn/20 border border-warn/30">
                            <div className="flex items-center gap-2 text-[11px] text-warn">
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
                        {notifications &&
                            Object.entries(notifications).some(([k, v]) => k.startsWith('on_') && v === true) && (
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
                            className={`w-full flex items-center justify-center gap-2 px-4 py-2.5 rounded-xl bg-surface hover:bg-surface2 border border-line/50 text-[11px] font-medium transition-all ${running
                                    ? 'opacity-70 cursor-not-allowed text-muted'
                                    : 'text-text hover:border-accent/50'
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
                            <div className="p-3 rounded-lg bg-good/10 border border-good/20">
                                <div className="text-xl font-bold text-good">{stats.success_rate}%</div>
                                <div className="text-[10px] text-muted">Success Rate</div>
                            </div>
                            <div className="p-3 rounded-lg bg-warn/10 border border-warn/20">
                                <div className="text-xl font-bold text-warn">{stats.override_count}</div>
                                <div className="text-[10px] text-muted">Overrides</div>
                            </div>
                            <div className="p-3 rounded-lg bg-bad/10 border border-bad/20">
                                <div className="text-xl font-bold text-bad">{stats.failed}</div>
                                <div className="text-[10px] text-muted">Failed</div>
                            </div>
                        </div>
                    )}
                </Card>

                {/* Quick Actions Card - Hidden as per user request */}
                {/* <Card className="lg:col-span-3 p-4 md:p-5 flex flex-col">
                    <div className="flex items-center gap-2 mb-4">
                        <Zap className="h-4 w-4 text-accent" />
                        <span className="text-xs font-medium text-text">Quick Actions</span>
                    </div>

                    {status?.quick_action && (
                        <div className="mb-3 p-3 rounded-lg bg-accent/10 border border-accent/30">
                            <div className="flex items-center justify-between">
                                <div>
                                    <div className="text-[11px] font-medium text-accent capitalize">
                                        {status.quick_action.type.replace('_', ' ')} Active
                                    </div>
                                    <div className="text-[10px] text-muted">
                                        {status.quick_action.remaining_minutes.toFixed(0)} min remaining
                                    </div>
                                </div>
                                <button
                                    onClick={async () => {
                                        try {
                                            await executorApi.quickAction.clear()
                                            fetchAll()
                                        } catch (e) {
                                            // ignore
                                            console.error(e)
                                        }
                                    }}
                                    className="text-[10px] px-2 py-1 rounded bg-bad/20 text-bad hover:bg-bad/30 transition-colors"
                                >
                                    Cancel
                                </button>
                            </div>
                        </div>
                    )}

                    <div className="space-y-2 flex-1">
                        {[
                            {
                                type: 'force_charge',
                                label: 'Force Charge',
                                icon: BatteryCharging,
                                labelClass: 'text-good',
                                btnClass: 'bg-good/10 border-good/20 text-good hover:bg-good/20',
                            },
                            {
                                type: 'force_discharge',
                                label: 'Force Export',
                                icon: Upload,
                                labelClass: 'text-warn',
                                btnClass: 'bg-warn/10 border-warn/20 text-warn hover:bg-warn/20',
                            },
                            {
                                type: 'force_water_heater',
                                label: 'Boost Water',
                                icon: Droplets,
                                labelClass: 'text-warn',
                                btnClass: 'bg-warn/10 border-warn/20 text-warn hover:bg-warn/20',
                            },
                            {
                                type: 'inverter_off',
                                label: 'Inverter Off',
                                icon: Power,
                                labelClass: 'text-bad',
                                btnClass: 'bg-bad/10 border-bad/20 text-bad hover:bg-bad/20',
                            },
                        ].map((action) => (
                            <div key={action.type} className="flex items-center gap-2">
                                <span
                                    className={`text-[11px] ${action.labelClass} w-20 font-medium flex items-center gap-1`}
                                >
                                    <action.icon className="h-3 w-3" />
                                    {action.label}
                                </span>
                                <div className="flex gap-1 flex-1">
                                    {[15, 30, 60].map((mins) => (
                                        <button
                                            key={mins}
                                            onClick={async () => {
                                                try {
                                                    await executorApi.quickAction.set(action.type, mins)
                                                    fetchAll()
                                                } catch (e: any) {
                                                    alert('Failed: ' + e.message)
                                                }
                                            }}
                                            disabled={status?.quick_action?.type === action.type}
                                            className={`flex-1 px-2 py-1.5 text-[10px] rounded-lg border transition-all ${
                                                status?.quick_action?.type === action.type
                                                    ? 'bg-accent/20 border-accent/40 text-accent'
                                                    : action.btnClass
                                            }`}
                                        >
                                            {mins}m
                                        </button>
                                    ))}
                                </div>
                            </div>
                        ))}
                    </div>

                    <div className="mt-3 text-[9px] text-muted/60 text-center">
                        Overrides schedule for selected duration
                    </div>
                </Card> */}
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
                        <span
                            className={`text-[10px] px-2 py-0.5 rounded-full border ${live.work_mode.value.includes('Export')
                                    ? status?.shadow_mode
                                        ? 'bg-warn/20 border-warn/30 text-warn'
                                        : 'bg-good/20 border-good/30 text-good'
                                    : 'bg-water/20 border-water/30 text-water'
                                }`}
                        >
                            {live.work_mode.value}
                        </span>
                    )}
                </div>

                <div className="grid grid-cols-2 md:grid-cols-5 gap-3">
                    {/* SoC - Battery Green */}
                    <div className="metric-card-border metric-card-border-battery p-3 bg-surface2/30 relative overflow-hidden group">
                        <div className="mini-bars-container absolute right-2 bottom-2 transition-opacity pointer-events-none">
                            <MiniBarGraph data={historyBuffer.soc} colorClass="bg-good" />
                        </div>
                        <div className="relative z-10 flex items-center gap-3">
                            <Battery
                                className={`h-6 w-6 ${(live?.soc?.numeric ?? 0) > 50
                                        ? 'text-good'
                                        : (live?.soc?.numeric ?? 0) > 20
                                            ? 'text-warn'
                                            : 'text-bad'
                                    }`}
                            />
                            <div>
                                <div className="text-lg font-bold text-good">
                                    {live?.soc?.numeric?.toFixed(0) ?? '—'}%
                                </div>
                                <div className="text-[10px] text-muted">Battery SoC</div>
                            </div>
                        </div>
                    </div>

                    {/* PV Power - Solar Gold */}
                    <div className="metric-card-border metric-card-border-solar p-3 bg-surface2/30 relative overflow-hidden group">
                        <div className="mini-bars-container absolute right-2 bottom-2 transition-opacity pointer-events-none">
                            <MiniBarGraph data={historyBuffer.pv} colorClass="bg-accent" />
                        </div>
                        <div className="relative z-10 flex items-center gap-3">
                            <Sun
                                className={`h-6 w-6 ${(live?.pv_power?.numeric ?? 0) > 500 ? 'text-accent' : 'text-accent/40'
                                    }`}
                            />
                            <div>
                                <div className="text-lg font-bold text-accent">
                                    {live?.pv_power?.numeric ? (live.pv_power.numeric / 1000).toFixed(1) : '—'} kW
                                </div>
                                <div className="text-[10px] text-muted">PV Power</div>
                            </div>
                        </div>
                    </div>

                    {/* Load - House Purple */}
                    <div className="metric-card-border metric-card-border-house p-3 bg-surface2/30 relative overflow-hidden group">
                        <div className="mini-bars-container absolute right-2 bottom-2 transition-opacity pointer-events-none">
                            <MiniBarGraph data={historyBuffer.load} colorClass="bg-house" />
                        </div>
                        <div className="relative z-10 flex items-center gap-3">
                            <Plug className="h-6 w-6 text-house" />
                            <div>
                                <div className="text-lg font-bold text-house">
                                    {live?.load_power?.numeric ? (live.load_power.numeric / 1000).toFixed(1) : '—'} kW
                                </div>
                                <div className="text-[10px] text-muted">Load</div>
                            </div>
                        </div>
                    </div>

                    {/* Grid Import - Grid Slate / Bad when high */}
                    <div className="metric-card-border metric-card-border-grid p-3 bg-surface2/30 relative overflow-hidden group">
                        <div className="mini-bars-container absolute right-2 bottom-2 transition-opacity pointer-events-none">
                            <MiniBarGraph
                                data={historyBuffer.import}
                                colorClass={(live?.grid_import?.numeric ?? 0) > 100 ? 'bg-bad' : 'bg-grid'}
                            />
                        </div>
                        <div className="relative z-10 flex items-center gap-3">
                            <ArrowDownToLine
                                className={`h-6 w-6 ${(live?.grid_import?.numeric ?? 0) > 100 ? 'text-bad' : 'text-grid'
                                    }`}
                            />
                            <div>
                                <div
                                    className={`text-lg font-bold ${(live?.grid_import?.numeric ?? 0) > 100 ? 'text-bad' : 'text-text'
                                        }`}
                                >
                                    {live?.grid_import?.numeric ? (live.grid_import.numeric / 1000).toFixed(2) : '—'} kW
                                </div>
                                <div className="text-[10px] text-muted">Grid Import</div>
                            </div>
                        </div>
                    </div>

                    {/* Grid Export - TE Orange */}
                    <div className="metric-card-border metric-card-border-bad p-3 bg-surface2/30 relative overflow-hidden group">
                        <div className="mini-bars-container absolute right-2 bottom-2 transition-opacity pointer-events-none">
                            <MiniBarGraph data={historyBuffer.export} colorClass="bg-bad" />
                        </div>
                        <div className="relative z-10 flex items-center gap-3">
                            <ArrowUpFromLine className="h-6 w-6 text-bad" />
                            <div>
                                <div className="text-lg font-bold text-bad">
                                    {live?.grid_export?.numeric ? (live.grid_export.numeric / 1000).toFixed(2) : '—'} kW
                                </div>
                                <div className="text-[10px] text-muted">Grid Export</div>
                            </div>
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
                        <span className="text-[10px] text-muted">({history?.length ?? 0} records)</span>
                    </div>
                    <button
                        onClick={fetchAll}
                        className="flex items-center gap-1.5 text-[10px] text-muted hover:text-accent transition px-2 py-1 rounded-lg hover:bg-surface2"
                    >
                        <RefreshCw className="h-3 w-3" />
                        Refresh
                    </button>
                </div>

                {(history?.length ?? 0) === 0 ? (
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
                                            <div className="flex items-center gap-1 text-good">
                                                <BatteryCharging className="h-3 w-3" />
                                                <span>{status.current_slot_plan.charge_kw.toFixed(1)}kW</span>
                                            </div>
                                        )}
                                        {status.current_slot_plan.export_kw > 0 && (
                                            <div className="flex items-center gap-1 text-warn">
                                                <Upload className="h-3 w-3" />
                                                <span>{status.current_slot_plan.export_kw.toFixed(1)}kW</span>
                                            </div>
                                        )}
                                        {status.current_slot_plan.water_kw > 0 && (
                                            <div className="flex items-center gap-1 text-water">
                                                <Droplets className="h-3 w-3" />
                                                <span>{status.current_slot_plan.water_kw.toFixed(1)}kW</span>
                                            </div>
                                        )}
                                        {status.current_slot_plan.soc_target > 0 && (
                                            <div className="flex items-center gap-1 text-muted">
                                                <span>SoC→{status.current_slot_plan.soc_target}%</span>
                                            </div>
                                        )}
                                        {!status.current_slot_plan.charge_kw &&
                                            !status.current_slot_plan.export_kw &&
                                            !status.current_slot_plan.water_kw && (
                                                <div className="text-muted/60 col-span-4">Idle / Self-consumption</div>
                                            )}
                                    </div>
                                )}
                            </div>
                        )}

                        {history.map((record) => {
                            const isExpanded = expandedRecordId === record.id
                            return (
                                <div
                                    key={record.id}
                                    className={`rounded-xl border transition-all ${record.success
                                            ? 'bg-surface2/30 border-line/40 hover:border-line/60'
                                            : 'bg-bad/10 border-bad/30 hover:border-bad/50'
                                        }`}
                                >
                                    {/* Header Row - Always visible, clickable */}
                                    <div
                                        className="p-3 cursor-pointer flex items-center justify-between"
                                        onClick={() => setExpandedRecordId(isExpanded ? null : record.id)}
                                    >
                                        <div className="flex items-center gap-2">
                                            <ChevronDown
                                                className={`h-3 w-3 text-muted transition-transform ${isExpanded ? 'rotate-180' : ''}`}
                                            />
                                            {record.success ? (
                                                <CheckCircle className="h-4 w-4 text-good" />
                                            ) : (
                                                <AlertTriangle className="h-4 w-4 text-bad" />
                                            )}
                                            <span className="text-[11px] text-text font-mono">
                                                {formatDateTime(record.executed_at)}
                                            </span>
                                            {/* Quick summary badges */}
                                            {record.commanded_charge_current_a &&
                                                record.commanded_charge_current_a > 0 && (
                                                    <span className="text-[9px] text-good bg-good/20 px-1.5 py-0.5 rounded">
                                                        ⚡ Charge
                                                    </span>
                                                )}
                                            {record.commanded_work_mode === 'Export First' && (
                                                <span className="text-[9px] text-warn bg-warn/20 px-1.5 py-0.5 rounded">
                                                    ↗ Export
                                                </span>
                                            )}
                                            {record.commanded_water_temp && record.commanded_water_temp > 50 && (
                                                <span className="text-[9px] text-warn bg-warn/20 px-1.5 py-0.5 rounded">
                                                    🔥 Heat
                                                </span>
                                            )}
                                            {/* Idle badge if no active actions */}
                                            {(!record.commanded_charge_current_a ||
                                                record.commanded_charge_current_a === 0) &&
                                                record.commanded_work_mode !== 'Export First' &&
                                                (!record.commanded_water_temp || record.commanded_water_temp <= 50) && (
                                                    <span className="text-[9px] text-muted/60 bg-surface2/50 px-1.5 py-0.5 rounded">
                                                        — Idle
                                                    </span>
                                                )}
                                        </div>
                                        <div className="flex items-center gap-2">
                                            {record.override_active ? (
                                                <span className="text-[9px] text-warn bg-warn/20 px-2 py-0.5 rounded-full border border-warn/30">
                                                    {record.override_type}
                                                </span>
                                            ) : null}
                                            {record.duration_ms && (
                                                <span className="text-[9px] text-muted font-mono">
                                                    {record.duration_ms}ms
                                                </span>
                                            )}
                                        </div>
                                    </div>

                                    {/* Expanded Details */}
                                    {isExpanded && (
                                        <div className="px-3 pb-3 border-t border-line/20">
                                            {/* Planned Actions */}
                                            <div className="mt-3">
                                                <div className="text-[9px] text-muted uppercase tracking-wide mb-1.5">
                                                    Planned (from Schedule)
                                                </div>
                                                <div className="grid grid-cols-3 md:grid-cols-6 gap-2 text-[10px]">
                                                    <div className="flex flex-col">
                                                        <span className="text-muted/60">Charge</span>
                                                        <span
                                                            className={
                                                                record.planned_charge_kw ? 'text-good' : 'text-muted/40'
                                                            }
                                                        >
                                                            {record.planned_charge_kw?.toFixed(1) ?? '—'} kW
                                                        </span>
                                                    </div>
                                                    <div className="flex flex-col">
                                                        <span className="text-muted/60">Export</span>
                                                        <span
                                                            className={
                                                                record.planned_export_kw ? 'text-warn' : 'text-muted/40'
                                                            }
                                                        >
                                                            {record.planned_export_kw?.toFixed(1) ?? '—'} kW
                                                        </span>
                                                    </div>
                                                    <div className="flex flex-col">
                                                        <span className="text-muted/60">Water</span>
                                                        <span
                                                            className={
                                                                record.planned_water_kw ? 'text-warn' : 'text-muted/40'
                                                            }
                                                        >
                                                            {record.planned_water_kw?.toFixed(1) ?? '—'} kW
                                                        </span>
                                                    </div>
                                                    <div className="flex flex-col">
                                                        <span className="text-muted/60">SoC Target</span>
                                                        <span className="text-text">
                                                            {record.planned_soc_target ?? '—'}%
                                                        </span>
                                                    </div>
                                                    <div className="flex flex-col">
                                                        <span className="text-muted/60">SoC Projected</span>
                                                        <span className="text-text">
                                                            {record.planned_soc_projected ?? '—'}%
                                                        </span>
                                                    </div>
                                                </div>
                                            </div>

                                            {/* Commanded Values (What we actually set) */}
                                            <div className="mt-3">
                                                <div className="text-[9px] text-muted uppercase tracking-wide mb-1.5">
                                                    Commanded (What We Set)
                                                </div>
                                                <div className="grid grid-cols-3 md:grid-cols-6 gap-2 text-[10px]">
                                                    <div className="flex flex-col">
                                                        <span className="text-muted/60">Work Mode</span>
                                                        <span className="text-text font-medium">
                                                            {record.commanded_work_mode ?? '—'}
                                                        </span>
                                                    </div>
                                                    <div className="flex flex-col">
                                                        <span className="text-muted/60">Grid Charging</span>
                                                        <span
                                                            className={
                                                                record.commanded_grid_charging
                                                                    ? 'text-good'
                                                                    : 'text-muted/40'
                                                            }
                                                        >
                                                            {record.commanded_grid_charging ? 'ON' : 'OFF'}
                                                        </span>
                                                    </div>
                                                    <div className="flex flex-col">
                                                        <span className="text-muted/60">Charge I</span>
                                                        <span
                                                            className={
                                                                record.commanded_charge_current_a
                                                                    ? 'text-good'
                                                                    : 'text-muted/40'
                                                            }
                                                        >
                                                            {record.commanded_charge_current_a ?? '—'} A
                                                        </span>
                                                    </div>
                                                    <div className="flex flex-col">
                                                        <span className="text-muted/60">Discharge I</span>
                                                        <span
                                                            className={
                                                                record.commanded_discharge_current_a
                                                                    ? 'text-warn'
                                                                    : 'text-muted/40'
                                                            }
                                                        >
                                                            {record.commanded_discharge_current_a ?? '—'} A
                                                        </span>
                                                    </div>
                                                    <div className="flex flex-col">
                                                        <span className="text-muted/60">SoC Target</span>
                                                        <span className="text-text">
                                                            {record.commanded_soc_target ?? '—'}%
                                                        </span>
                                                    </div>
                                                    <div className="flex flex-col">
                                                        <span className="text-muted/60">Water Temp</span>
                                                        <span
                                                            className={
                                                                record.commanded_water_temp &&
                                                                    record.commanded_water_temp > 50
                                                                    ? 'text-warn'
                                                                    : 'text-muted/40'
                                                            }
                                                        >
                                                            {record.commanded_water_temp ?? '—'}°C
                                                        </span>
                                                    </div>
                                                </div>
                                            </div>

                                            {/* Before State */}
                                            <div className="mt-3">
                                                <div className="text-[9px] text-muted uppercase tracking-wide mb-1.5">
                                                    State Before Execution
                                                </div>
                                                <div className="grid grid-cols-3 md:grid-cols-5 gap-2 text-[10px]">
                                                    <div className="flex flex-col">
                                                        <span className="text-muted/60">SoC</span>
                                                        <span className="text-text">
                                                            {record.before_soc_percent?.toFixed(0) ?? '—'}%
                                                        </span>
                                                    </div>
                                                    <div className="flex flex-col">
                                                        <span className="text-muted/60">Work Mode</span>
                                                        <span className="text-text">
                                                            {record.before_work_mode ?? '—'}
                                                        </span>
                                                    </div>
                                                    <div className="flex flex-col">
                                                        <span className="text-muted/60">PV Power</span>
                                                        <span className="text-yellow-400">
                                                            {record.before_pv_kw?.toFixed(1) ?? '—'} kW
                                                        </span>
                                                    </div>
                                                    <div className="flex flex-col">
                                                        <span className="text-muted/60">Load</span>
                                                        <span className="text-sky-400">
                                                            {record.before_load_kw?.toFixed(1) ?? '—'} kW
                                                        </span>
                                                    </div>
                                                    <div className="flex flex-col">
                                                        <span className="text-muted/60">Water Temp</span>
                                                        <span className="text-text">
                                                            {record.before_water_temp ?? '—'}°C
                                                        </span>
                                                    </div>
                                                </div>
                                            </div>

                                            {/* Error / Override Messages */}
                                            {record.error_message && (
                                                <div className="mt-2 text-[10px] text-red-400 bg-red-500/10 rounded-lg p-2">
                                                    {record.error_message}
                                                </div>
                                            )}
                                            {record.override_reason && (
                                                <div className="mt-2 text-[10px] text-amber-300/80 bg-amber-500/10 rounded-lg p-2">
                                                    Override: {record.override_reason}
                                                </div>
                                            )}
                                        </div>
                                    )}
                                </div>
                            )
                        })}
                    </div>
                )}
            </Card>

            {/* Notifications Modal */}
            {showNotifications && (
                <div
                    className="fixed inset-0 z-50 flex items-center justify-center bg-black/60 backdrop-blur-sm"
                    onClick={() => setShowNotifications(false)}
                >
                    <div
                        className="bg-surface border border-line rounded-2xl p-5 w-full max-w-md shadow-2xl"
                        onClick={(e) => e.stopPropagation()}
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
                                    <div className="text-[11px] text-text font-mono">
                                        {notifications.service || 'Not configured'}
                                    </div>
                                </div>

                                {/* Toggle items */}
                                {[
                                    {
                                        key: 'on_charge_start',
                                        label: 'Charge Started',
                                        desc: 'When grid charging begins',
                                    },
                                    { key: 'on_charge_stop', label: 'Charge Stopped', desc: 'When grid charging ends' },
                                    {
                                        key: 'on_export_start',
                                        label: 'Export Started',
                                        desc: 'When battery export begins',
                                    },
                                    {
                                        key: 'on_export_stop',
                                        label: 'Export Stopped',
                                        desc: 'When battery export ends',
                                    },
                                    {
                                        key: 'on_water_heat_start',
                                        label: 'Water Heating Started',
                                        desc: 'When water heater activates',
                                    },
                                    {
                                        key: 'on_water_heat_stop',
                                        label: 'Water Heating Stopped',
                                        desc: 'When water heater deactivates',
                                    },
                                    {
                                        key: 'on_soc_target_change',
                                        label: 'SoC Target Changed',
                                        desc: 'When battery target changes',
                                    },
                                    {
                                        key: 'on_override_activated',
                                        label: 'Override Activated',
                                        desc: 'When emergency override triggers',
                                    },
                                    { key: 'on_error', label: 'Errors', desc: 'When execution fails' },
                                ].map((item) => (
                                    <div
                                        key={item.key}
                                        className="flex items-center justify-between p-2.5 rounded-lg bg-surface2/50 border border-line/50"
                                    >
                                        <div className="flex flex-col">
                                            <span className="text-[11px] font-medium text-text">{item.label}</span>
                                            <span className="text-[9px] text-muted">{item.desc}</span>
                                        </div>
                                        <Toggle
                                            enabled={notifications[item.key as keyof NotificationSettings] as boolean}
                                            onChange={(v) =>
                                                handleNotificationToggle(item.key as keyof NotificationSettings, v)
                                            }
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
                                <div
                                    className={`mt-2 text-center text-[10px] ${testResult.success ? 'text-emerald-400' : 'text-red-400'}`}
                                >
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
