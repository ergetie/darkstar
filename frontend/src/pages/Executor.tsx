/* eslint-disable @typescript-eslint/no-explicit-any */
import { useState, useEffect, useCallback } from 'react'
import {
    Cpu,
    Play,
    Eye,
    History,
    AlertTriangle,
    CheckCircle,
    Clock,
    RefreshCw,
    Settings,
    Gauge,
    Bell,
    X,
    BatteryCharging,
    Upload,
    ChevronDown,
    Download,
    Layers,
} from 'lucide-react'
import Card from '../components/Card'
import LoadBalancerStatusCard from '../components/LoadBalancerStatusCard'

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
        discharge_kw: number
        ev_charging_kw: number
        soc_target: number
        soc_projected: number
        mode_intent?: string | null
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
    profile_name?: string
    profile_error?: string
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
    ev_charging_kw?: number
    // Commanded values (what we actually set)
    commanded_work_mode?: string
    commanded_grid_charging?: number
    commanded_charge_current_a?: number
    commanded_discharge_current_a?: number
    commanded_unit?: string
    commanded_soc_target?: number
    commanded_water_temp?: number
    // State before execution
    before_soc_percent?: number
    before_work_mode?: string
    before_water_temp?: number
    before_pv_kw?: number
    before_load_kw?: number
    // Action details (REV F52 Phase 2)
    action_results?: ActionResult[]
    // Result
    duration_ms?: number
    error_message?: string
    source?: string
}

// REV F52 Phase 2: ActionResult interface for type safety
interface ActionResult {
    type: string
    success: boolean
    message: string
    entity_id?: string
    previous_value?: any
    new_value?: any
    verified_value?: any
    verification_success?: boolean
    skipped: boolean
    error_details?: string | null
}

// Mode badge mapping for commanded_work_mode / mode_intent
type ModeBadge = { emoji: string; label: string; className: string }
const MODE_BADGES: Record<string, ModeBadge> = {
    charge: { emoji: '⚡', label: 'Charge', className: 'text-good bg-good/20' },
    self_consumption: { emoji: '🔄', label: 'Self-consumption', className: 'text-blue-400 bg-blue-400/20' },
    idle: { emoji: '⏸️', label: 'Idle', className: 'text-muted bg-surface2/50' },
    export: { emoji: '↗️', label: 'Export', className: 'text-warn bg-warn/20' },
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
    history: async (
        params: {
            limit?: number
            offset?: number
            start_date?: string
            end_date?: string
            success_only?: boolean
        } = {},
    ): Promise<{ records: ExecutionRecord[]; count: number }> => {
        const query = new URLSearchParams()
        if (params.limit) query.append('limit', params.limit.toString())
        if (params.offset) query.append('offset', params.offset.toString())
        if (params.start_date) query.append('start_date', params.start_date)
        if (params.end_date) query.append('end_date', params.end_date)
        if (params.success_only !== undefined) query.append('success_only', params.success_only.toString())

        const r = await fetch(`api/executor/history?${query.toString()}`)
        if (!r.ok) throw new Error(`History failed: ${r.status}`)
        return r.json()
    },
    downloadHistory: (params: { start_date?: string; end_date?: string; success_only?: boolean } = {}) => {
        const query = new URLSearchParams()
        if (params.start_date) query.append('start_date', params.start_date)
        if (params.end_date) query.append('end_date', params.end_date)
        if (params.success_only !== undefined) query.append('success_only', params.success_only.toString())

        window.open(`api/executor/history/download?${query.toString()}`, '_blank')
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

type EntityConfig = {
    inverter: {
        soc_target: string
        work_mode: string
        grid_charging_enable: string
        max_charge_current: string
        max_discharge_current: string
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
            className={`relative inline-flex items-center rounded-full transition-colors focus:outline-none focus:ring-2 focus:ring-accent focus:ring-offset-2 focus:ring-offset-surface ${sizeClasses} ${
                enabled ? 'bg-accent' : 'bg-surface2'
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

function ActionStatusIndicator({ result }: { result: ActionResult }) {
    if (result.skipped && result.message?.includes('[SHADOW]')) {
        return <span className="text-[9px] text-purple-400 font-medium">⬢ SHADOW</span>
    }
    if (result.skipped) {
        return <span className="text-[9px] text-sky-400 font-medium">● SKIPPED</span>
    }
    if (!result.success || result.verification_success === false) {
        return <span className="text-[9px] text-red-400 font-medium">✖ FAILED</span>
    }
    if (result.verification_success === true) {
        return <span className="text-[9px] text-emerald-400 font-medium">✔ VERIFIED</span>
    }
    return <span className="text-[9px] text-emerald-400/70 font-medium">✔ OK</span>
}

export default function Executor() {
    const [status, setStatus] = useState<ExecutorStatus | null>(null)
    const [stats, setStats] = useState<ExecutorStats | null>(null)
    const [history, setHistory] = useState<ExecutionRecord[]>([])

    const [loading, setLoading] = useState(true)
    const [toggling, setToggling] = useState(false)
    const [running, setRunning] = useState(false)
    const [error, setError] = useState<string | null>(null)
    const [showNotifications, setShowNotifications] = useState(false)
    const [notifications, setNotifications] = useState<NotificationSettings | null>(null)

    // History Filters
    const [dateRange, setDateRange] = useState<'1h' | '8h' | '24h' | '7d' | 'custom'>('24h')
    const [startDate, setStartDate] = useState<string>('')
    const [endDate, setEndDate] = useState<string>('')
    const [successOnlyFilter, setSuccessOnlyFilter] = useState<boolean | undefined>(undefined)

    const [savingNotification, setSavingNotification] = useState(false)
    const [testingNotification, setTestingNotification] = useState(false)
    const [testResult, setTestResult] = useState<{ success: boolean; message: string } | null>(null)
    const [expandedRecordId, setExpandedRecordId] = useState<number | null>(null)

    // Helper to format date in local timezone with offset (matches backend format)
    const toLocalISO = (date: Date): string => {
        const offset = -date.getTimezoneOffset()
        const offsetHours = Math.floor(Math.abs(offset) / 60)
        const offsetMinutes = Math.abs(offset) % 60
        const offsetSign = offset >= 0 ? '+' : '-'
        const offsetStr = `${offsetSign}${String(offsetHours).padStart(2, '0')}:${String(offsetMinutes).padStart(2, '0')}`
        return date.toISOString().slice(0, -1) + offsetStr
    }

    const fetchAll = useCallback(async () => {
        try {
            const filters: any = {}

            // Auto-calculate limit based on date range (assuming ~1 record/min, with 20% margin)
            const calculateLimit = (): number => {
                switch (dateRange) {
                    case '1h':
                        return 80
                    case '8h':
                        return 580
                    case '24h':
                        return 1730
                    case '7d':
                        return 12100
                    case 'custom':
                        if (startDate && endDate) {
                            const start = new Date(startDate)
                            const end = new Date(endDate)
                            // Cap at 30 days
                            const maxDays = 30
                            const daysDiff = Math.min(
                                maxDays,
                                Math.max(1, (end.getTime() - start.getTime()) / (1000 * 60 * 60 * 24)),
                            )
                            return Math.ceil(daysDiff * 24 * 60 * 1.2)
                        }
                        return 1730
                    default:
                        return 1730
                }
            }

            filters.limit = calculateLimit()

            if (dateRange === '1h') {
                filters.start_date = toLocalISO(new Date(Date.now() - 60 * 60 * 1000))
            } else if (dateRange === '8h') {
                filters.start_date = toLocalISO(new Date(Date.now() - 8 * 3600 * 1000))
            } else if (dateRange === '24h') {
                filters.start_date = toLocalISO(new Date(Date.now() - 24 * 3600 * 1000))
            } else if (dateRange === '7d') {
                filters.start_date = toLocalISO(new Date(Date.now() - 7 * 24 * 3600 * 1000))
            } else if (dateRange === 'custom') {
                if (startDate) filters.start_date = toLocalISO(new Date(startDate))
                if (endDate) {
                    // Set end date to end of day (23:59:59)
                    const end = new Date(endDate)
                    end.setHours(23, 59, 59, 999)
                    filters.end_date = toLocalISO(end)
                }
            }

            if (successOnlyFilter !== undefined) {
                filters.success_only = successOnlyFilter
            }

            const [statusRes, statsRes, historyRes] = await Promise.all([
                executorApi.status(),
                executorApi.stats(7),
                executorApi.history(filters),
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
    }, [dateRange, startDate, endDate, successOnlyFilter])

    // --- WebSocket Event Handlers (Rev E1) ---

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
        <div className="px-4 pt-16 pb-24 lg:px-8 lg:pt-8 lg:pb-8 min-h-screen lg:h-screen flex flex-col gap-6 overflow-auto lg:overflow-hidden">
            {/* Header */}
            <div className="flex flex-col lg:flex-row lg:items-center lg:justify-between gap-3">
                <div>
                    <h1 className="text-lg font-medium text-text flex items-center gap-2">
                        Executor Control Center
                        <span
                            className={`px-2 py-0.5 rounded-full border text-[10px] uppercase tracking-wider ${
                                status?.enabled
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
                                    className={`h-1.5 w-1.5 rounded-full ${
                                        status?.last_run_status === 'success'
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
                            <div className="text-[10px] text-muted/70 uppercase">Profile</div>
                            <div
                                className="text-sm font-mono text-text truncate max-w-[80px]"
                                title={status?.profile_name}
                            >
                                {status?.profile_name || '—'}
                            </div>
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

                    {status?.profile_error && (
                        <div className="mt-3 p-2 rounded-lg bg-bad/20 border border-bad/30">
                            <div className="flex items-center gap-2 text-[11px] text-bad">
                                <AlertTriangle className="h-3.5 w-3.5" />
                                <span className="font-medium">Profile Error:</span>
                                <span>{status.profile_error}</span>
                            </div>
                        </div>
                    )}

                    {status?.profile_name === 'generic' && !status?.profile_error && (
                        <div className="mt-3 p-2 rounded-lg bg-warn/10 border border-warn/20">
                            <div className="flex items-center gap-2 text-[11px] text-warn/80">
                                <AlertTriangle className="h-3.5 w-3.5" />
                                <span className="font-medium">Using Generic Profile</span>
                                <span className="text-[10px] opacity-70">(Legacy compatibility mode)</span>
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
                            className={`w-full flex items-center justify-center gap-2 px-4 py-2.5 rounded-xl bg-surface hover:bg-surface2 border border-line/50 text-[11px] font-medium transition-all ${
                                running
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
            </div>

            {/* Load Balancer Status */}
            <LoadBalancerStatusCard />

            {/* Execution History */}
            <Card className="p-4 md:p-5 flex-1 flex flex-col overflow-hidden">
                {/* Recording-policy explainer: a sparse history is a quiet system, not a dead one */}
                <div
                    data-testid="history-explainer"
                    className="mb-3 rounded-lg border border-line/20 bg-surface2/30 px-3 py-2 text-[10px] text-muted"
                >
                    {status?.last_run_at ? (
                        <>
                            Last executor tick {formatTime(status.last_run_at)} —{' '}
                            <span className={status.last_run_status === 'success' ? 'text-good' : 'text-bad'}>
                                {String(status.last_run_status ?? 'unknown')}
                            </span>
                            {status.last_action ? `: ${String(status.last_action)}` : ''}
                            {'. '}
                        </>
                    ) : (
                        'No executor tick recorded yet. '
                    )}
                    Only changes (mode, dispatched actions, overrides, load-balancer transitions) plus one heartbeat per
                    15-minute slot are recorded — most ticks produce no row by design.
                </div>
                <div className="flex items-center justify-between mb-4">
                    <div className="flex flex-col md:flex-row md:items-center gap-4">
                        <div className="flex items-center gap-2">
                            <History className="h-4 w-4 text-accent" />
                            <span className="text-xs font-medium text-text">Execution History</span>
                            <span className="text-[10px] text-muted">({history?.length ?? 0} records)</span>
                        </div>

                        {/* Filters */}
                        <div className="flex flex-wrap items-center gap-2">
                            <div className="flex bg-surface2/50 rounded-lg p-0.5 border border-line/30">
                                {(['1h', '8h', '24h', '7d', 'custom'] as const).map((r) => (
                                    <button
                                        key={r}
                                        onClick={() => setDateRange(r)}
                                        className={`px-2 py-1 text-[9px] rounded-md transition-all ${
                                            dateRange === r
                                                ? 'bg-accent text-white shadow-sm'
                                                : 'text-muted hover:text-text'
                                        }`}
                                    >
                                        {r === '1h'
                                            ? '1h'
                                            : r === '8h'
                                              ? '8h'
                                              : r === '24h'
                                                ? '24h'
                                                : r === '7d'
                                                  ? '7d'
                                                  : 'Custom'}
                                    </button>
                                ))}
                            </div>

                            {dateRange === 'custom' && (
                                <div className="flex items-center gap-1">
                                    <input
                                        type="date"
                                        value={startDate}
                                        onChange={(e) => setStartDate(e.target.value)}
                                        className="bg-surface2/50 border border-line/30 rounded-lg px-2 py-1 text-[9px] text-text focus:outline-none focus:ring-1 focus:ring-accent"
                                    />
                                    <span className="text-muted text-[9px]">to</span>
                                    <input
                                        type="date"
                                        value={endDate}
                                        onChange={(e) => setEndDate(e.target.value)}
                                        className="bg-surface2/50 border border-line/30 rounded-lg px-2 py-1 text-[9px] text-text focus:outline-none focus:ring-1 focus:ring-accent"
                                    />
                                </div>
                            )}

                            <select
                                value={successOnlyFilter === undefined ? 'all' : successOnlyFilter.toString()}
                                onChange={(e) => {
                                    const val = e.target.value
                                    setSuccessOnlyFilter(val === 'all' ? undefined : val === 'true')
                                }}
                                className="bg-surface2/50 border border-line/30 rounded-lg px-2 py-1 text-[9px] text-text focus:outline-none focus:ring-1 focus:ring-accent appearance-none cursor-pointer"
                            >
                                <option value="all">All Status</option>
                                <option value="true">Success Only</option>
                                <option value="false">Errors Only</option>
                            </select>
                        </div>
                    </div>

                    <div className="flex items-center gap-2">
                        <button
                            onClick={() => {
                                const filters: any = {}
                                if (dateRange === '1h') {
                                    filters.start_date = new Date(Date.now() - 60 * 60 * 1000).toISOString()
                                } else if (dateRange === '8h') {
                                    filters.start_date = new Date(Date.now() - 8 * 3600 * 1000).toISOString()
                                } else if (dateRange === '24h') {
                                    filters.start_date = new Date(Date.now() - 24 * 3600 * 1000).toISOString()
                                } else if (dateRange === '7d') {
                                    filters.start_date = new Date(Date.now() - 7 * 24 * 3600 * 1000).toISOString()
                                }
                                if (startDate) filters.start_date = new Date(startDate).toISOString()
                                if (endDate) filters.end_date = new Date(endDate).toISOString()
                                if (successOnlyFilter !== undefined) filters.success_only = successOnlyFilter

                                executorApi.downloadHistory(filters)
                            }}
                            className="flex items-center gap-1.5 text-[10px] text-muted hover:text-accent transition px-2 py-1 rounded-lg hover:bg-surface2"
                        >
                            <Download className="h-3 w-3" />
                            Export CSV
                        </button>
                        <button
                            onClick={fetchAll}
                            className="flex items-center gap-1.5 text-[10px] text-muted hover:text-accent transition px-2 py-1 rounded-lg hover:bg-surface2"
                        >
                            <RefreshCw className="h-3 w-3" />
                            Refresh
                        </button>
                    </div>
                </div>

                {(history?.length ?? 0) === 0 ? (
                    <div className="text-center py-12 text-muted">
                        <Clock className="h-10 w-10 mx-auto opacity-20 mb-3" />
                        <p className="text-[11px]">No execution history yet.</p>
                        <p className="text-[10px] mt-1 text-muted/70">Run the executor to see results here.</p>
                    </div>
                ) : (
                    <div className="space-y-2 flex-1 min-h-0 overflow-y-auto pr-2 custom-scrollbar">
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
                                        {/* Primary mode badge from mode_intent */}
                                        {status.current_slot_plan.mode_intent &&
                                            MODE_BADGES[status.current_slot_plan.mode_intent] && (
                                                <div
                                                    className={`flex items-center gap-1 col-span-4 ${MODE_BADGES[status.current_slot_plan.mode_intent].className} px-1.5 py-0.5 rounded w-fit`}
                                                >
                                                    <span>
                                                        {MODE_BADGES[status.current_slot_plan.mode_intent].emoji}{' '}
                                                        {MODE_BADGES[status.current_slot_plan.mode_intent].label}
                                                    </span>
                                                </div>
                                            )}
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
                                            <div className="flex items-center gap-1 text-water bg-water/20 px-1.5 py-0.5 rounded w-fit">
                                                <span>💧 Heating</span>
                                            </div>
                                        )}
                                        {(status.current_slot_plan.ev_charging_kw ?? 0) > 0 && (
                                            <div className="flex items-center gap-1 text-purple-400 bg-purple-400/20 px-1.5 py-0.5 rounded w-fit">
                                                <span>🔌 EV</span>
                                            </div>
                                        )}
                                        {status.current_slot_plan.soc_target > 0 && (
                                            <div className="flex items-center gap-1 text-muted">
                                                <span>SoC→{status.current_slot_plan.soc_target}%</span>
                                            </div>
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
                                    className={`rounded-xl border transition-all ${
                                        record.success
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
                                            {/* Primary mode badge from commanded_work_mode */}
                                            {record.commanded_work_mode && MODE_BADGES[record.commanded_work_mode] && (
                                                <span
                                                    className={`text-[9px] px-1.5 py-0.5 rounded ${MODE_BADGES[record.commanded_work_mode].className}`}
                                                >
                                                    {MODE_BADGES[record.commanded_work_mode].emoji}{' '}
                                                    {MODE_BADGES[record.commanded_work_mode].label}
                                                </span>
                                            )}
                                            {/* Context badges */}
                                            {(record.planned_water_kw ?? 0) > 0 && (
                                                <span className="text-[9px] text-water bg-water/20 px-1.5 py-0.5 rounded">
                                                    💧 Heating
                                                </span>
                                            )}
                                            {(record.ev_charging_kw ?? 0) > 0 && (
                                                <span className="text-[9px] text-purple-400 bg-purple-400/20 px-1.5 py-0.5 rounded">
                                                    🔌 EV
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

                                            {/* Commanded Values (Consolidated) */}
                                            {record.action_results && record.action_results.length > 0 ? (
                                                <div className="mt-3">
                                                    <div className="text-[9px] text-muted uppercase tracking-wide mb-1.5">
                                                        Commanded (What We Set)
                                                    </div>
                                                    <div className="space-y-2">
                                                        {(() => {
                                                            const groups: any[] = []
                                                            let currentGroup: any = null

                                                            record.action_results.forEach((res) => {
                                                                if (res.type === 'work_mode') {
                                                                    currentGroup = { parent: res, children: [] }
                                                                    groups.push(currentGroup)
                                                                } else if (
                                                                    res.type === 'composite_mode' &&
                                                                    currentGroup
                                                                ) {
                                                                    currentGroup.children.push(res)
                                                                } else {
                                                                    groups.push({ parent: res, children: [] })
                                                                    currentGroup = null
                                                                }
                                                            })

                                                            return groups.map((group, groupIdx) => (
                                                                <div key={groupIdx} className="space-y-1">
                                                                    {/* Parent Action */}
                                                                    <div className="flex items-center justify-between p-2 rounded-lg bg-surface2/40 border border-line/20">
                                                                        <div className="flex flex-col min-w-0">
                                                                            <div className="flex items-center gap-2">
                                                                                <span className="text-[10px] text-text font-medium capitalize">
                                                                                    {group.parent.type.replace(
                                                                                        /_/g,
                                                                                        ' ',
                                                                                    )}
                                                                                </span>
                                                                                <ActionStatusIndicator
                                                                                    result={group.parent}
                                                                                />
                                                                            </div>
                                                                            {group.parent.entity_id && (
                                                                                <span className="text-[8px] text-muted truncate font-mono">
                                                                                    {group.parent.entity_id}
                                                                                </span>
                                                                            )}
                                                                            {group.parent.message &&
                                                                                !group.parent.success && (
                                                                                    <div className="flex flex-col gap-1 mt-1">
                                                                                        <span className="text-[9px] text-bad bg-bad/5 rounded px-1.5 py-0.5 border border-bad/20 inline-block w-fit">
                                                                                            {group.parent.message}
                                                                                        </span>
                                                                                        {group.parent.error_details && (
                                                                                            <span
                                                                                                className="text-[8px] text-bad/70 font-mono bg-bad/5 rounded px-1.5 py-0.5 border border-bad/20 inline-block w-fit max-w-xs truncate"
                                                                                                title={
                                                                                                    group.parent
                                                                                                        .error_details
                                                                                                }
                                                                                            >
                                                                                                {
                                                                                                    group.parent
                                                                                                        .error_details
                                                                                                }
                                                                                            </span>
                                                                                        )}
                                                                                    </div>
                                                                                )}
                                                                        </div>
                                                                        <div className="text-right ml-4">
                                                                            <div className="text-[10px] text-text font-medium">
                                                                                {typeof group.parent.new_value ===
                                                                                'boolean'
                                                                                    ? group.parent.new_value
                                                                                        ? 'on'
                                                                                        : 'off'
                                                                                    : (group.parent.new_value ?? '—')}
                                                                                {group.parent.type.includes('temp')
                                                                                    ? '°C'
                                                                                    : ''}
                                                                            </div>
                                                                            {group.parent.verified_value !==
                                                                                undefined &&
                                                                                group.parent.verified_value !==
                                                                                    null && (
                                                                                    <div className="text-[8px] text-muted italic">
                                                                                        Read back:{' '}
                                                                                        <span
                                                                                            className={
                                                                                                group.parent
                                                                                                    .verification_success
                                                                                                    ? 'text-emerald-400'
                                                                                                    : 'text-red-400'
                                                                                            }
                                                                                        >
                                                                                            {
                                                                                                group.parent
                                                                                                    .verified_value
                                                                                            }
                                                                                            {group.parent.type.includes(
                                                                                                'temp',
                                                                                            )
                                                                                                ? '°C'
                                                                                                : ''}
                                                                                        </span>
                                                                                    </div>
                                                                                )}
                                                                        </div>
                                                                    </div>

                                                                    {/* Composite Children */}
                                                                    {group.children.map(
                                                                        (child: ActionResult, childIdx: number) => (
                                                                            <div
                                                                                key={childIdx}
                                                                                className="ml-4 flex items-center justify-between p-2 rounded-lg bg-surface2/20 border border-line/10 border-l-2 border-l-accent/30"
                                                                            >
                                                                                <div className="flex flex-col min-w-0">
                                                                                    <div className="flex items-center gap-2">
                                                                                        <Layers className="h-2.5 w-2.5 text-accent/50" />
                                                                                        <span className="text-[9px] text-muted font-medium">
                                                                                            {child.message &&
                                                                                            child.message.includes('→')
                                                                                                ? child.entity_id
                                                                                                      ?.split('.')
                                                                                                      .pop()
                                                                                                      ?.replace(
                                                                                                          /_/g,
                                                                                                          ' ',
                                                                                                      )
                                                                                                : child.type.replace(
                                                                                                      /_/g,
                                                                                                      ' ',
                                                                                                  )}
                                                                                        </span>
                                                                                        <ActionStatusIndicator
                                                                                            result={child}
                                                                                        />
                                                                                    </div>
                                                                                    {child.entity_id && (
                                                                                        <span className="text-[8px] text-muted/50 truncate font-mono">
                                                                                            {child.entity_id}
                                                                                        </span>
                                                                                    )}
                                                                                    {!child.success &&
                                                                                        child.error_details && (
                                                                                            <span
                                                                                                className="text-[8px] text-bad/70 font-mono bg-bad/5 rounded px-1.5 py-0.5 border border-bad/20 inline-block w-fit max-w-xs truncate"
                                                                                                title={
                                                                                                    child.error_details
                                                                                                }
                                                                                            >
                                                                                                {child.error_details}
                                                                                            </span>
                                                                                        )}
                                                                                </div>
                                                                                <div className="text-right ml-4">
                                                                                    <div className="text-[9px] text-muted font-medium">
                                                                                        {typeof child.new_value ===
                                                                                        'boolean'
                                                                                            ? child.new_value
                                                                                                ? 'on'
                                                                                                : 'off'
                                                                                            : (child.new_value ?? '—')}
                                                                                    </div>
                                                                                    {child.verified_value !==
                                                                                        undefined &&
                                                                                        child.verified_value !==
                                                                                            null && (
                                                                                            <div className="text-[8px] text-muted/60 italic">
                                                                                                <span
                                                                                                    className={
                                                                                                        child.verification_success
                                                                                                            ? 'text-emerald-400/80'
                                                                                                            : 'text-red-400/80'
                                                                                                    }
                                                                                                >
                                                                                                    {
                                                                                                        child.verified_value
                                                                                                    }
                                                                                                </span>
                                                                                            </div>
                                                                                        )}
                                                                                </div>
                                                                            </div>
                                                                        ),
                                                                    )}
                                                                </div>
                                                            ))
                                                        })()}
                                                    </div>
                                                </div>
                                            ) : (
                                                /* Fallback for old records */
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
                                                                {record.commanded_charge_current_a ?? '—'}{' '}
                                                                {record.commanded_unit ?? 'A'}
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
                                                                {record.commanded_discharge_current_a ?? '—'}{' '}
                                                                {record.commanded_unit ?? 'A'}
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
                                            )}

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
                                className={`w-full flex items-center justify-center gap-2 px-4 py-2.5 rounded-xl border text-[11px] font-medium transition-all ${
                                    testingNotification
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
