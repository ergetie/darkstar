import { useEffect, useState, useCallback, useRef } from 'react'
import Card from '../components/Card'
import ChartCard from '../components/ChartCard'
import QuickActions from '../components/QuickActions'
import Kpi from '../components/Kpi'
import { motion } from 'framer-motion'
import { Api, Sel } from '../lib/api'
import type { ScheduleSlot } from '../lib/types'
import { isToday, isTomorrow, type DaySel } from '../lib/time'
import SmartAdvisor from '../components/SmartAdvisor'
import { ArrowDownToLine, ArrowUpFromLine } from 'lucide-react'

type PlannerMeta = { plannedAt?: string; version?: string; sIndex?: any } | null

function formatLocalIso(d: Date | null): string {
    if (!d) return '—'
    const year = d.getFullYear()
    const month = String(d.getMonth() + 1).padStart(2, '0')
    const day = String(d.getDate()).padStart(2, '0')
    const hours = String(d.getHours()).padStart(2, '0')
    const minutes = String(d.getMinutes()).padStart(2, '0')
    return `${year}-${month}-${day} ${hours}:${minutes}`
}



export default function Dashboard() {
    const [soc, setSoc] = useState<number | null>(null)
    const [horizon, setHorizon] = useState<{ pvDays?: number; weatherDays?: number } | null>(null)
    const [plannerLocalMeta, setPlannerLocalMeta] = useState<PlannerMeta>(null)
    const [plannerDbMeta, setPlannerDbMeta] = useState<PlannerMeta>(null)
    const [plannerMeta, setPlannerMeta] = useState<PlannerMeta>(null)
    const [currentPlanSource, setCurrentPlanSource] = useState<'local' | 'server'>('local')
    const [batteryCapacity, setBatteryCapacity] = useState<number | null>(null)
    const [pvToday, setPvToday] = useState<number | null>(null)
    const [avgLoad, setAvgLoad] = useState<{ kw?: number; dailyKwh?: number } | null>(null)
    const [currentSlotTarget, setCurrentSlotTarget] = useState<number | null>(null)
    const [waterToday, setWaterToday] = useState<{ kwh?: number; source?: string } | null>(null)
    const [comfortLevel, setComfortLevel] = useState<number>(3)  // Rev K18
    const [vacationMode, setVacationMode] = useState<boolean>(false)  // Rev K19
    const [riskAppetite, setRiskAppetite] = useState<number>(3)  // Risk Appetite on Dashboard
    const [learningStatus, setLearningStatus] = useState<{ enabled?: boolean; status?: string; samples?: number } | null>(null)
    const [exportGuard, setExportGuard] = useState<{ enabled?: boolean; mode?: string } | null>(null)
    const [serverSchedule, setServerSchedule] = useState<ScheduleSlot[] | null>(null)
    const [serverScheduleLoading, setServerScheduleLoading] = useState(false)
    const [serverScheduleError, setServerScheduleError] = useState<string | null>(null)
    const [isRefreshing, setIsRefreshing] = useState(false)
    const [lastRefresh, setLastRefresh] = useState<Date | null>(null)
    const [chartRefreshToken, setChartRefreshToken] = useState(0)
    const [statusMessage, setStatusMessage] = useState<string | null>(null)
    const [autoRefresh, setAutoRefresh] = useState(true)
    const pollingIntervalRef = useRef<ReturnType<typeof setInterval> | null>(null)
    const [automationConfig, setAutomationConfig] = useState<{ enable_scheduler?: boolean; write_to_mariadb?: boolean; external_executor_mode?: boolean; every_minutes?: number | null } | null>(null)
    const [automationSaving, setAutomationSaving] = useState(false)
    const [schedulerStatus, setSchedulerStatus] = useState<{ last_run_at?: string | null; last_run_status?: string | null; next_run_at?: string | null } | null>(null)
    const [localSchedule, setLocalSchedule] = useState<ScheduleSlot[] | null>(null)
    const [historySlots, setHistorySlots] = useState<ScheduleSlot[] | null>(null)
    const [lastError, setLastError] = useState<{ message: string; at: string } | null>(null)
    const [executorStatus, setExecutorStatus] = useState<{ shadow_mode?: boolean; paused?: { paused_at?: string; paused_minutes?: number } | null } | null>(null)
    const [todayStats, setTodayStats] = useState<{
        gridImport: number | null;
        gridExport: number | null;
        batteryCycles: number | null;
        pvProduction: number | null;
        pvForecast: number | null;
        loadConsumption: number | null;
        netCost: number | null;
    } | null>(null)

    const handlePlanSourceChange = useCallback((source: 'local' | 'server') => {
        setCurrentPlanSource(source)
    }, [])

    const handleServerScheduleLoaded = useCallback((schedule: ScheduleSlot[]) => {
        setServerScheduleLoading(true)
        setServerScheduleError(null)

        if (!schedule || schedule.length === 0) {
            setServerSchedule([])
            setServerScheduleLoading(false)
            return
        }

        Api.scheduleTodayWithHistory()
            .then((res) => {
                const historySlots = res.slots ?? []
                const byStart = new Map<string, any>()
                historySlots.forEach((slot: any) => {
                    if (slot.start_time) {
                        byStart.set(String(slot.start_time), slot)
                    }
                })

                const merged: ScheduleSlot[] = schedule.map((slot) => {
                    const key = (slot as any).start_time
                    const hist = key ? byStart.get(String(key)) : undefined
                    if (!hist) return slot

                    const anyHist = hist as any
                    const mergedSlot: any = { ...slot }

                    if (anyHist.soc_actual_percent != null) {
                        mergedSlot.soc_actual_percent = anyHist.soc_actual_percent
                    }
                    if (anyHist.is_executed === true) {
                        mergedSlot.is_executed = true
                    }

                    return mergedSlot as ScheduleSlot
                })

                setServerSchedule(merged)
            })
            .catch((err) => {
                console.error('Failed to merge history into server schedule:', err)
                setServerSchedule(schedule ?? [])
                setServerScheduleError('Failed to merge execution history; showing DB plan only.')
            })
            .finally(() => {
                setServerScheduleLoading(false)
            })
    }, [])

    const fetchAllData = useCallback(async () => {
        setIsRefreshing(true)
        let hadError = false
        try {
            // Parallel fetch all data
            const [
                statusData,
                horizonData,
                configData,
                haAverageData,
                scheduleData,
                waterData,
                learningData,
                schedulerStatusData,
                historyData,
                executorStatusData,
                energyTodayData,
            ] = await Promise.allSettled([
                Api.status(),
                Api.horizon(),
                Api.config(),
                Api.haAverage(),
                Api.schedule(),
                Api.haWaterToday(),
                Api.learningStatus(),
                Api.schedulerStatus(),
                Api.scheduleTodayWithHistory(),
                Api.executor.status(),
                Api.energyToday(),
            ])

            // Process status data
            if (statusData.status === 'fulfilled') {
                const data = statusData.value
                setSoc(Sel.socValue(data) ?? null)

                const local = data.local ?? {}
                const db = (data.db && 'planned_at' in data.db) ? (data.db as any) : null

                const nextLocalMeta: PlannerMeta =
                    local?.planned_at || local?.planner_version
                        ? { plannedAt: local.planned_at, version: local.planner_version, sIndex: local.s_index }
                        : null
                const nextDbMeta: PlannerMeta =
                    db?.planned_at || db?.planner_version
                        ? { plannedAt: db.planned_at, version: db.planner_version, sIndex: db.s_index }
                        : null

                setPlannerLocalMeta(nextLocalMeta)
                setPlannerDbMeta(nextDbMeta)

                // Provide a sensible initial meta for first load / refresh; this will be
                // reconciled with currentPlanSource by a dedicated effect.
                if (nextLocalMeta) {
                    setPlannerMeta(nextLocalMeta)
                } else if (nextDbMeta) {
                    setPlannerMeta(nextDbMeta)
                } else {
                    setPlannerMeta(null)
                }
            } else {
                hadError = true
                console.error('Failed to load status for Dashboard:', statusData.reason)
            }

            // Process horizon data
            if (horizonData.status === 'fulfilled') {
                const data = horizonData.value
                setHorizon({
                    pvDays: Sel.pvDays(data) ?? undefined,
                    weatherDays: Sel.wxDays(data) ?? undefined,
                })
            } else {
                hadError = true
                console.error('Failed to load horizon for Dashboard:', horizonData.reason)
            }

            // Process config data
            if (configData.status === 'fulfilled') {
                const data = configData.value
                if (data.system?.battery?.capacity_kwh) {
                    setBatteryCapacity(data.system.battery.capacity_kwh)
                }
                // Get export guard status from arbitrage config
                const arbitrage = data.arbitrage || {}
                setExportGuard({
                    enabled: arbitrage.enable_export,
                    mode: arbitrage.enable_peak_only_export ? 'peak_only' : 'passive'
                })

                // Automation / scheduler config
                if (data.automation) {
                    const automation = data.automation
                    setAutomationConfig({
                        enable_scheduler: automation.enable_scheduler,
                        write_to_mariadb: automation.write_to_mariadb,
                        external_executor_mode: automation.external_executor_mode,
                        // Optional Rev57-style schedule block; falls back to null when absent
                        every_minutes: automation.schedule?.every_minutes ?? null,
                    })
                } else {
                    setAutomationConfig(null)
                }

                // Initialize auto-refresh from dashboard config if present
                if (typeof data.dashboard?.auto_refresh_enabled === 'boolean') {
                    setAutoRefresh(data.dashboard.auto_refresh_enabled)
                }

                // Load comfort level and vacation mode from water_heating config
                if (data.water_heating) {
                    if (typeof data.water_heating.comfort_level === 'number') {
                        setComfortLevel(data.water_heating.comfort_level)
                    }
                    if (typeof data.water_heating.vacation_mode?.enabled === 'boolean') {
                        setVacationMode(data.water_heating.vacation_mode.enabled)
                    }
                }
            } else {
                hadError = true
                console.error('Failed to load config for Dashboard:', configData.reason)
            }

            // Process HA average data
            if (haAverageData.status === 'fulfilled') {
                const data = haAverageData.value
                setAvgLoad({
                    kw: data.average_load_kw,
                    dailyKwh: data.daily_kwh
                })
            } else {
                hadError = true
                console.error('Failed to load HA average for Dashboard:', haAverageData.reason)
            }

            // Process schedule data
            if (scheduleData.status === 'fulfilled') {
                const data = scheduleData.value
                const sched = data.schedule ?? []
                setLocalSchedule(sched)
                // Calculate PV today from schedule data
                const today = new Date().toISOString().split('T')[0]
                const todaySlots = data.schedule?.filter(slot =>
                    slot.start_time?.startsWith(today)
                ) || []
                const pvTotal = todaySlots.reduce((sum, slot) =>
                    sum + (slot.pv_forecast_kwh || 0), 0
                )
                setPvToday(pvTotal)

                // Check for critical errors in meta
                if (data.meta?.last_error) {
                    setLastError({
                        message: data.meta.last_error,
                        at: data.meta.last_error_at || '',
                    })
                } else {
                    setLastError(null)
                }

                // Get current slot target
                const now = new Date()
                const currentSlot = sched.find(slot => {
                    const slotTime = new Date(slot.start_time || '')
                    const slotEnd = new Date(slotTime.getTime() + 30 * 60 * 1000) // 30 min slots
                    return now >= slotTime && now < slotEnd
                })
                if (currentSlot?.soc_target_percent !== undefined) {
                    setCurrentSlotTarget(currentSlot.soc_target_percent)
                }
            } else {
                hadError = true
                console.error('Failed to load schedule for Dashboard:', scheduleData.reason)
            }

            // Process water data
            if (waterData.status === 'fulfilled') {
                const data = waterData.value
                setWaterToday({
                    kwh: data.water_kwh_today,
                    source: data.source
                })
            } else {
                hadError = true
                console.error('Failed to load water data for Dashboard:', waterData.reason)
            }

            // Process learning data
            if (learningData.status === 'fulfilled') {
                const data = learningData.value
                const hasData = data.metrics?.total_slots && data.metrics.total_slots > 0
                const isLearning = data.metrics?.completed_learning_runs && data.metrics.completed_learning_runs > 0
                setLearningStatus({
                    enabled: data.enabled,
                    status: hasData ? (isLearning ? 'learning' : 'ready') : 'gathering',
                    samples: data.metrics?.total_slots
                })
            } else {
                hadError = true
                console.error('Failed to load learning status for Dashboard:', learningData.reason)
            }

            // Process scheduler status
            if (schedulerStatusData.status === 'fulfilled') {
                const data = schedulerStatusData.value
                setSchedulerStatus({
                    last_run_at: data.last_run_at ?? null,
                    last_run_status: data.last_run_status ?? null,
                    next_run_at: data.next_run_at ?? null,
                })
            } else {
                console.error('Failed to load scheduler status for Dashboard:', schedulerStatusData.reason)
            }

            // Process execution history for today (for SoC Actual in charts)
            if (historyData.status === 'fulfilled') {
                const data = historyData.value
                const histSlots = data.slots ?? []
                setHistorySlots(histSlots)

                // No longer calculating stats here - now using Api.energyToday()
            } else {
                console.error('Failed to load schedule history for Dashboard:', historyData.reason)
            }

            // Calculate PV Forecast for today from history slots (if available)
            let pvForecastSum = 0
            if (historyData.status === 'fulfilled' && historyData.value.slots) {
                const todayStart = new Date()
                todayStart.setHours(0, 0, 0, 0)
                const todaySlots = historyData.value.slots.filter(s => {
                    const slotTime = new Date(s.start_time)
                    return slotTime >= todayStart
                })
                todaySlots.forEach(s => {
                    pvForecastSum += s.pv_forecast_kwh ?? 0
                })
            }

            // Process executor status
            if (executorStatusData.status === 'fulfilled') {
                const data = executorStatusData.value
                setExecutorStatus({
                    shadow_mode: data.shadow_mode ?? false,
                    paused: data.paused ?? null,
                })
            } else {
                console.error('Failed to load executor status for Dashboard:', executorStatusData.reason)
            }

            // Process energy today from HA sensors
            if (energyTodayData.status === 'fulfilled') {
                const data = energyTodayData.value
                setTodayStats({
                    gridImport: data.grid_import_kwh,
                    gridExport: data.grid_export_kwh,
                    batteryCycles: data.battery_cycles,
                    pvProduction: data.pv_production_kwh,
                    pvForecast: Math.round(pvForecastSum * 10) / 10,
                    loadConsumption: data.load_consumption_kwh,
                    netCost: data.net_cost_kr,
                })
            } else {
                console.error('Failed to load energy today for Dashboard:', energyTodayData.reason)
            }

            setLastRefresh(new Date())
        } catch (error) {
            console.error('Error fetching dashboard data:', error)
            hadError = true
        } finally {
            setIsRefreshing(false)
            setStatusMessage(hadError ? 'Some dashboard data failed to load.' : null)
            // Nudge the overview chart to reload its schedule data so that
            // planner runs / server-plan loads are reflected without manual
            // day toggling.
            setChartRefreshToken(token => token + 1)
        }
    }, [])

    // Keep displayed plannerMeta aligned with currentPlanSource and stored metadata.
    useEffect(() => {
        let nextMeta: PlannerMeta = null
        if (currentPlanSource === 'server') {
            nextMeta = plannerDbMeta
        } else {
            nextMeta = plannerLocalMeta
        }
        setPlannerMeta(nextMeta)
    }, [currentPlanSource, plannerLocalMeta, plannerDbMeta])

    // Initial data fetch
    useEffect(() => {
        fetchAllData()
    }, [fetchAllData])

    // Set up polling
    useEffect(() => {
        if (autoRefresh) {
            pollingIntervalRef.current = setInterval(() => {
                fetchAllData()
            }, 30000) // Refresh every 30 seconds
        } else {
            if (pollingIntervalRef.current) {
                clearInterval(pollingIntervalRef.current)
                pollingIntervalRef.current = null
            }
        }

        return () => {
            if (pollingIntervalRef.current) {
                clearInterval(pollingIntervalRef.current)
            }
        }
    }, [autoRefresh, fetchAllData])

    const toggleAutomationScheduler = async () => {
        if (automationSaving) return
        const current = automationConfig?.enable_scheduler ?? false
        const next = !current
        setAutomationSaving(true)
        try {
            await Api.configSave({ automation: { enable_scheduler: next } })
            setAutomationConfig(prev => ({
                enable_scheduler: next,
                write_to_mariadb: prev?.write_to_mariadb,
                external_executor_mode: prev?.external_executor_mode,
                every_minutes: prev?.every_minutes ?? null,
            }))
        } catch (err) {
            console.error('Failed to toggle planner automation:', err)
        } finally {
            setAutomationSaving(false)
        }
    }

    const [dbSyncLoading, setDbSyncLoading] = useState(false)
    const [dbSyncFeedback, setDbSyncFeedback] = useState<{ type: 'success' | 'error'; message: string } | null>(null)

    const handleLoadFromDb = async () => {
        setDbSyncLoading(true)
        setDbSyncFeedback(null)
        try {
            const schedule = await Api.loadServerPlan()
            handleServerScheduleLoaded(schedule.schedule ?? [])
            handlePlanSourceChange('server')
            setDbSyncFeedback({ type: 'success', message: 'Plan loaded from DB' })
        } catch (err) {
            setDbSyncFeedback({ type: 'error', message: err instanceof Error ? err.message : 'Load failed' })
        } finally {
            setDbSyncLoading(false)
            setTimeout(() => setDbSyncFeedback(null), 3000)
        }
    }

    const handlePushToDb = async () => {
        setDbSyncLoading(true)
        setDbSyncFeedback(null)
        try {
            await Api.pushToDb()
            setDbSyncFeedback({ type: 'success', message: 'Plan pushed to DB' })
            fetchAllData()
        } catch (err) {
            setDbSyncFeedback({ type: 'error', message: err instanceof Error ? err.message : 'Push failed' })
        } finally {
            setDbSyncLoading(false)
            setTimeout(() => setDbSyncFeedback(null), 3000)
        }
    }

    const socDisplay = soc !== null ? `${soc.toFixed(1)}%` : '—'
    const pvDays = horizon?.pvDays ?? '—'
    const weatherDays = horizon?.weatherDays ?? '—'
    const planBadge = `${currentPlanSource} plan`
    const planMeta = plannerMeta?.plannedAt || plannerMeta?.version ? ` · ${plannerMeta?.plannedAt ?? ''} ${plannerMeta?.version ?? ''}`.trim() : ''

    // Derive last/next planner runs for automation card
    const lastRunIso = schedulerStatus?.last_run_at || plannerLocalMeta?.plannedAt || plannerDbMeta?.plannedAt
    const lastRunDate = lastRunIso ? new Date(lastRunIso) : null
    const everyMinutes = automationConfig?.every_minutes && automationConfig.every_minutes > 0
        ? automationConfig.every_minutes
        : null
    let nextRunDate: Date | null = null
    if (schedulerStatus?.next_run_at) {
        nextRunDate = new Date(schedulerStatus.next_run_at)
    } else if (automationConfig?.enable_scheduler && lastRunDate && everyMinutes) {
        nextRunDate = new Date(lastRunDate.getTime() + everyMinutes * 60 * 1000)
    }
    // Build slotsOverride for the chart:
    // - Server plan: use merged serverSchedule (already contains execution history).
    // - Local plan: mirror Planning view by merging today's history with tomorrow's schedule
    //   so SoC Actual appears in both 24h and 48h modes.
    let slotsOverride: ScheduleSlot[] | undefined
    if (currentPlanSource === 'server' && serverSchedule && serverSchedule.length > 0) {
        slotsOverride = serverSchedule
    } else if (currentPlanSource === 'local' && localSchedule && localSchedule.length > 0) {
        const todayAndTomorrow = localSchedule.filter(
            slot => isToday(slot.start_time) || isTomorrow(slot.start_time),
        )
        if (historySlots && historySlots.length > 0) {
            const tomorrowSlots = todayAndTomorrow.filter(slot => isTomorrow(slot.start_time))
            slotsOverride = [...historySlots, ...tomorrowSlots]
        } else {
            slotsOverride = todayAndTomorrow
        }
    }

    // S-Index Display Logic
    const sIndexVal = plannerMeta?.sIndex?.effective_load_margin
    const targetSocVal = plannerMeta?.sIndex?.target_soc?.target_percent
    const sIndexDisplay = sIndexVal ? `x${sIndexVal.toFixed(2)}` : '—'
    const termDisplay = targetSocVal ? `EOD ${targetSocVal.toFixed(0)}%` : ''

    return (
        <main className="mx-auto max-w-7xl px-4 pb-24 pt-6 sm:px-6 lg:pt-10 space-y-6">
            {/* Header Removed as per user request */}

            {/* Critical Error Banner */}
            {lastError && (
                <motion.div
                    initial={{ opacity: 0, y: -10 }}
                    animate={{ opacity: 1, y: 0 }}
                    className="bg-red-500/20 border border-red-500/50 rounded-lg p-4 mb-4"
                >
                    <div className="flex items-start justify-between gap-4">
                        <div>
                            <div className="flex items-center gap-2 text-red-400 font-semibold text-sm mb-1">
                                <span>⚠️</span>
                                <span>Planner Error</span>
                            </div>
                            <div className="text-red-300 text-xs">{lastError.message}</div>
                            {lastError.at && (
                                <div className="text-red-400/60 text-[10px] mt-1">
                                    {new Date(lastError.at).toLocaleString()}
                                </div>
                            )}
                        </div>
                        <button
                            onClick={() => setLastError(null)}
                            className="text-red-400/60 hover:text-red-300 text-xs px-2 py-1"
                            title="Dismiss"
                        >
                            ✕
                        </button>
                    </div>
                </motion.div>
            )}

            {/* Shadow Mode Banner */}
            {executorStatus?.shadow_mode && (
                <motion.div
                    initial={{ opacity: 0, y: -10 }}
                    animate={{ opacity: 1, y: 0 }}
                    className="bg-purple-500/20 border border-purple-500/50 rounded-lg px-4 py-3 mb-4"
                >
                    <div className="flex items-center gap-2 text-purple-300 text-sm font-medium">
                        <span>👻</span>
                        <span>Shadow Mode Active</span>
                        <span className="text-purple-400/70 text-xs ml-2">— Actions logged but not executed on Home Assistant</span>
                    </div>
                </motion.div>
            )}

            {/* Executor Paused Banner */}
            {executorStatus?.paused && (
                <motion.div
                    initial={{ opacity: 0, y: -10 }}
                    animate={{ opacity: 1, y: 0 }}
                    className="bg-orange-500/20 border border-orange-500/50 rounded-lg px-4 py-3 mb-4"
                >
                    <div className="flex items-center gap-2 text-orange-300 text-sm font-medium">
                        <span>⏸️</span>
                        <span>Executor Paused (Idle Mode)</span>
                        {executorStatus.paused.paused_minutes !== undefined && (
                            <span className="text-orange-400/70 text-xs ml-2">
                                — Paused for {Math.round(executorStatus.paused.paused_minutes)} minutes
                            </span>
                        )}
                    </div>
                </motion.div>
            )}


            {/* Row 1: Schedule Overview (24h / 48h) */}
            <motion.div initial={{ opacity: 0, y: 8 }} animate={{ opacity: 1, y: 0 }}>
                <ChartCard
                    useHistoryForToday={currentPlanSource === 'local'}
                    refreshToken={chartRefreshToken}
                    slotsOverride={slotsOverride}
                    range="48h"
                    showDayToggle={true}
                />
            </motion.div>

            {/* Row 2: Advisor + System Status + Quick Actions / Automation */}
            <div className="grid gap-6 lg:grid-cols-3 items-stretch">
                <motion.div className="h-full" initial={{ opacity: 0, y: 8 }} animate={{ opacity: 1, y: 0 }}>
                    <SmartAdvisor />
                </motion.div>
                <motion.div className="h-full" initial={{ opacity: 0, y: 8 }} animate={{ opacity: 1, y: 0 }}>
                    <Card className="h-full p-4 md:p-5">
                        <div className="flex items-baseline justify-between mb-3">
                            <div className="text-sm text-muted">System Status</div>
                            <div className="flex items-center gap-2">
                                <div className="text-[10px] text-muted">
                                    {autoRefresh ? 'auto-refresh' : 'manual'}
                                    {lastRefresh && ` · ${lastRefresh.toLocaleTimeString()}`}
                                </div>
                                {statusMessage && (
                                    <div className="text-[10px] text-amber-400">
                                        {statusMessage}
                                    </div>
                                )}
                                <button
                                    onClick={() => fetchAllData()}
                                    disabled={isRefreshing}
                                    className={`rounded-pill px-2 py-1 text-[10px] font-medium transition ${isRefreshing
                                        ? 'bg-surface border border-line/60 text-muted cursor-not-allowed'
                                        : 'bg-surface border border-line/60 text-muted hover:border-accent hover:text-accent'
                                        }`}
                                    title="Refresh data"
                                >
                                    <span className={isRefreshing ? 'inline-block animate-spin' : ''}>
                                        {isRefreshing ? '⟳' : '↻'}
                                    </span>
                                </button>
                                <button
                                    onClick={() => setAutoRefresh(!autoRefresh)}
                                    className={`rounded-pill px-2 py-1 text-[10px] font-medium transition ${autoRefresh
                                        ? 'bg-accent text-canvas border border-accent'
                                        : 'bg-surface border border-line/60 text-muted hover:border-accent hover:text-accent'
                                        }`}
                                    title={autoRefresh ? 'Disable auto-refresh' : 'Enable auto-refresh (30s)'}
                                >
                                    ⏱
                                </button>
                            </div>
                        </div>
                        <div className="flex flex-wrap gap-4 pb-4 text-[11px] uppercase tracking-wider text-muted">
                            <div className="text-text">Now showing: {planBadge}{planMeta}</div>
                        </div>
                        <div className="grid grid-cols-1 gap-3 sm:grid-cols-2">
                            <Kpi label="Current SoC" value={socDisplay} hint={currentSlotTarget !== null ? `slot ${currentSlotTarget.toFixed(0)}%` : ''} />
                            <Kpi label="S-Index" value={sIndexDisplay} hint={termDisplay} />
                            <Kpi label="PV Today" value={pvToday !== null ? `${pvToday.toFixed(1)} kWh` : '— kWh'} hint={`PV ${pvDays}d · Weather ${weatherDays}d`} />
                            <Kpi label="Avg Load" value={avgLoad?.kw !== undefined ? `${avgLoad.kw.toFixed(1)} kW` : '— kW'} hint={avgLoad?.dailyKwh !== undefined ? `HA ${avgLoad.dailyKwh.toFixed(1)} kWh/day` : ''} />
                        </div>
                    </Card>
                </motion.div>
                <motion.div className="h-full" initial={{ opacity: 0, y: 8 }} animate={{ opacity: 1, y: 0 }}>
                    <div className="flex h-full flex-col gap-6">
                        <Card className="flex-1 p-4 md:p-5">
                            <div className="text-sm text-muted mb-3">Quick Actions</div>
                            <QuickActions
                                onDataRefresh={fetchAllData}
                                onPlanSourceChange={handlePlanSourceChange}
                                onServerScheduleLoaded={handleServerScheduleLoaded}
                            />
                        </Card>
                        <Card className="flex-1 p-4 md:p-5">
                            <div className="flex items-baseline justify-between mb-2">
                                <div className="text-sm text-muted">Planner Automation</div>
                                <div className="flex items-center gap-3">
                                    <div className="flex items-center gap-2 text-[10px] text-muted">
                                        <span
                                            className={`inline-flex h-2.5 w-2.5 rounded-full ${automationConfig?.enable_scheduler
                                                ? 'bg-emerald-400 shadow-[0_0_0_2px_rgba(16,185,129,0.4)]'
                                                : 'bg-line'
                                                }`}
                                        />
                                        <span>{automationConfig?.enable_scheduler ? 'Active' : 'Disabled'}</span>
                                    </div>
                                    <button
                                        type="button"
                                        onClick={toggleAutomationScheduler}
                                        disabled={automationSaving}
                                        className="rounded-pill px-3 py-1 text-[10px] font-semibold border border-line/60 text-muted hover:border-accent hover:text-accent disabled:opacity-50 transition"
                                    >
                                        {automationConfig?.enable_scheduler ? 'Disable' : 'Enable'}
                                    </button>
                                </div>
                            </div>
                            <div className="text-[11px] text-muted">
                                {automationConfig?.enable_scheduler
                                    ? 'Planner will auto-run on the configured schedule.'
                                    : 'Auto-planner is off. Use Quick Actions to run manually.'}
                            </div>
                            <div className="mt-2 space-y-1 text-[10px] text-muted">
                                <div>
                                    Last plan run: {formatLocalIso(lastRunDate)}
                                </div>
                                <div>
                                    Next expected run:{' '}
                                    {automationConfig?.enable_scheduler ? formatLocalIso(nextRunDate) : '—'}
                                </div>
                                <div>
                                    DB sync: {automationConfig?.write_to_mariadb ? 'enabled' : 'disabled'}
                                </div>
                            </div>
                        </Card>

                        {automationConfig?.external_executor_mode && (
                            <Card className="flex-1 p-4 md:p-5 flex flex-col">
                                <div className="flex items-baseline justify-between mb-3">
                                    <div className="text-sm text-muted">DB Sync</div>
                                    <div className={`text-[10px] ${dbSyncFeedback?.type === 'success' ? 'text-green-400' : 'text-red-400'}`}>
                                        {dbSyncFeedback?.message}
                                    </div>
                                </div>
                                <div className="grid grid-cols-2 gap-3 mt-auto">
                                    <button
                                        type="button"
                                        onClick={handleLoadFromDb}
                                        disabled={dbSyncLoading}
                                        className="flex items-center justify-center gap-2 rounded-xl px-3 py-2 text-[11px] font-semibold bg-surface2 border border-line/60 text-muted hover:border-accent hover:text-accent transition disabled:opacity-50"
                                        title="Pull plan from MariaDB current_schedule table"
                                    >
                                        <ArrowDownToLine className="h-4 w-4" />
                                        <span>Load from DB</span>
                                    </button>
                                    <button
                                        type="button"
                                        onClick={handlePushToDb}
                                        disabled={dbSyncLoading}
                                        className="flex items-center justify-center gap-2 rounded-xl px-3 py-2 text-[11px] font-semibold bg-surface2 border border-line/60 text-muted hover:border-accent hover:text-accent transition disabled:opacity-50"
                                        title="Push local schedule.json to MariaDB"
                                    >
                                        <ArrowUpFromLine className="h-4 w-4" />
                                        <span>Push to DB</span>
                                    </button>
                                </div>
                            </Card>
                        )}
                    </div>
                </motion.div>
            </div>

            {/* Row 3: Context Cards */}
            <div className="grid grid-cols-1 gap-6 lg:grid-cols-3">
                <Card className="p-5">
                    <div className="flex justify-between items-center mb-3">
                        <div className="flex items-center gap-2">
                            <span className="text-sm text-muted">Water heater</span>
                            {vacationMode && (
                                <span className="rounded-pill bg-amber-500/20 border border-amber-500/50 px-2 py-0.5 text-amber-300 text-[10px] font-medium">
                                    🌴 Vacation
                                </span>
                            )}
                        </div>
                        <div className="rounded-pill bg-surface2 border border-line/60 px-3 py-1 text-muted text-xs">
                            today {waterToday?.kwh !== undefined ? `${waterToday.kwh.toFixed(1)} kWh` : '— kWh'}
                        </div>
                    </div>
                    <div className="text-[10px] text-muted mb-2 uppercase tracking-wide">Comfort Level</div>
                    <div className="flex gap-1 mb-2">
                        {[1, 2, 3, 4, 5].map((level) => {
                            const colorMap: Record<number, string> = {
                                1: 'bg-emerald-500/30 text-emerald-300 border-emerald-500/50 ring-emerald-500/20',
                                2: 'bg-teal-500/30 text-teal-300 border-teal-500/50 ring-teal-500/20',
                                3: 'bg-blue-500/30 text-blue-300 border-blue-500/50 ring-blue-500/20',
                                4: 'bg-amber-500/30 text-amber-300 border-amber-500/50 ring-amber-500/20',
                                5: 'bg-red-500/30 text-red-300 border-red-500/50 ring-red-500/20'
                            }
                            return (
                                <button
                                    key={level}
                                    onClick={async () => {
                                        setComfortLevel(level)
                                        await Api.configSave({ water_heating: { comfort_level: level } })
                                    }}
                                    className={`w-8 h-8 rounded text-xs font-medium transition-all duration-300 border active:scale-95 ${comfortLevel === level
                                        ? `${colorMap[level]} ring-2 soft-glow`
                                        : 'bg-surface2 text-muted hover:bg-surface hover:text-text hover:scale-105 border-transparent'
                                        }`}
                                >
                                    {level}
                                </button>
                            )
                        })}
                    </div>
                    <div className="text-sm">
                        <span className={`font-medium ${comfortLevel === 1 ? 'text-emerald-400' :
                            comfortLevel === 2 ? 'text-teal-400' :
                                comfortLevel === 3 ? 'text-blue-400' :
                                    comfortLevel === 4 ? 'text-amber-400' :
                                        'text-red-400'
                            }`}>
                            {{
                                1: 'Economy',
                                2: 'Balanced',
                                3: 'Neutral',
                                4: 'Priority',
                                5: 'Maximum'
                            }[comfortLevel]}
                        </span>
                        <span className="text-muted"> mode active</span>
                    </div>
                </Card>
                <Card className="p-5">
                    <div className="text-sm text-muted mb-3">Risk Strategy</div>
                    <div className="text-[10px] text-muted mb-2 uppercase tracking-wide">Risk Appetite</div>
                    <div className="flex gap-1 mb-2">
                        {[1, 2, 3, 4, 5].map((level) => {
                            const colorMap: Record<number, string> = {
                                1: 'bg-emerald-500/30 text-emerald-300 border-emerald-500/50 ring-emerald-500/20',
                                2: 'bg-teal-500/30 text-teal-300 border-teal-500/50 ring-teal-500/20',
                                3: 'bg-blue-500/30 text-blue-300 border-blue-500/50 ring-blue-500/20',
                                4: 'bg-amber-500/30 text-amber-300 border-amber-500/50 ring-amber-500/20',
                                5: 'bg-red-500/30 text-red-300 border-red-500/50 ring-red-500/20'
                            }
                            return (
                                <button
                                    key={level}
                                    onClick={async () => {
                                        setRiskAppetite(level)
                                        await Api.configSave({ s_index: { risk_appetite: level } })
                                    }}
                                    className={`w-8 h-8 rounded text-xs font-medium transition-all duration-300 border active:scale-95 ${riskAppetite === level
                                        ? `${colorMap[level]} ring-2 soft-glow`
                                        : 'bg-surface2 text-muted hover:bg-surface hover:text-text hover:scale-105 border-transparent'
                                        }`}
                                >
                                    {level}
                                </button>
                            )
                        })}
                    </div>
                    <div className="text-sm">
                        <span className={`font-medium ${riskAppetite === 1 ? 'text-emerald-400' :
                            riskAppetite === 2 ? 'text-teal-400' :
                                riskAppetite === 3 ? 'text-blue-400' :
                                    riskAppetite === 4 ? 'text-amber-400' :
                                        'text-red-400'
                            }`}>
                            {{
                                1: 'Safety',
                                2: 'Conservative',
                                3: 'Neutral',
                                4: 'Aggressive',
                                5: 'Gambler'
                            }[riskAppetite]}
                        </span>
                        <span className="text-muted"> mode active</span>
                    </div>
                </Card>
                <Card className="p-5">
                    <div className="text-sm text-muted mb-3">Today's Stats</div>
                    <div className="space-y-3">
                        {/* Group 1: Grid & Financial */}
                        <div className="p-2.5 rounded-lg bg-surface2/20 space-y-2 border border-line/20">
                            {/* Net Cost */}
                            <div className="flex items-center justify-between">
                                <div className="flex items-center gap-2">
                                    <span className="text-base">💰</span>
                                    <span className="text-xs text-muted">Net</span>
                                </div>
                                <div className="text-right">
                                    <span className={`text-sm font-semibold ${(todayStats?.netCost ?? 0) <= 0 ? 'text-emerald-300' : 'text-red-300'}`}>
                                        {todayStats?.netCost != null ? todayStats.netCost.toFixed(2) : '—'}
                                    </span>
                                    <span className="text-xs text-muted ml-1">kr</span>
                                </div>
                            </div>
                            {/* Grid: Import ↓ / Export ↑ */}
                            <div className="flex items-center justify-between">
                                <div className="flex items-center gap-2">
                                    <span className="text-base">🔌</span>
                                    <span className="text-xs text-muted">Grid</span>
                                </div>
                                <div className="text-right">
                                    <span className="text-sm font-semibold text-red-300">↓{todayStats?.gridImport?.toFixed(1) ?? '—'}</span>
                                    <span className="text-muted mx-0.5">/</span>
                                    <span className="text-sm font-semibold text-emerald-300">↑{todayStats?.gridExport?.toFixed(1) ?? '—'}</span>
                                </div>
                            </div>
                        </div>

                        {/* Group 2: Home Energy */}
                        <div className="p-2.5 rounded-lg bg-surface2/20 space-y-3 border border-line/20">
                            {/* PV: Actual / Forecast */}
                            <div className="flex flex-col gap-1">
                                <div className="flex items-center justify-between">
                                    <div className="flex items-center gap-2">
                                        <span className="text-base">☀️</span>
                                        <span className="text-xs text-muted">PV</span>
                                    </div>
                                    <div className="text-right">
                                        <span className="text-sm font-semibold text-amber-300">
                                            {todayStats?.pvProduction?.toFixed(1) ?? '—'}
                                        </span>
                                        <span className="text-xs text-muted mx-0.5">/</span>
                                        <span className="text-xs text-muted">{todayStats?.pvForecast?.toFixed(1) ?? '—'}</span>
                                    </div>
                                </div>
                                {/* Progress Bar */}
                                <div className="h-1 w-full bg-surface rounded-full overflow-hidden flex">
                                    <div
                                        className="h-full bg-amber-400 rounded-full transition-all duration-1000"
                                        style={{ width: `${Math.min(100, ((todayStats?.pvProduction ?? 0) / (todayStats?.pvForecast || 1)) * 100)}%` }}
                                    />
                                </div>
                            </div>

                            {/* Load: Actual / Average */}
                            <div className="flex flex-col gap-1">
                                <div className="flex items-center justify-between">
                                    <div className="flex items-center gap-2">
                                        <span className="text-base">⚡</span>
                                        <span className="text-xs text-muted">Load</span>
                                    </div>
                                    <div className="text-right">
                                        <span className="text-sm font-semibold text-purple-300">
                                            {todayStats?.loadConsumption?.toFixed(1) ?? '—'}
                                        </span>
                                        <span className="text-xs text-muted mx-0.5">/</span>
                                        <span className="text-xs text-muted">{avgLoad?.dailyKwh?.toFixed(0) ?? '—'}</span>
                                    </div>
                                </div>
                                {/* Progress Bar */}
                                <div className="h-1 w-full bg-surface rounded-full overflow-hidden flex">
                                    <div
                                        className="h-full bg-purple-400 rounded-full transition-all duration-1000"
                                        style={{ width: `${Math.min(100, ((todayStats?.loadConsumption ?? 0) / (avgLoad?.dailyKwh || 1)) * 100)}%` }}
                                    />
                                </div>
                            </div>

                            {/* Battery Cycles */}
                            <div className="flex items-center justify-between pt-1">
                                <div className="flex items-center gap-2">
                                    <span className="text-base">🔋</span>
                                    <span className="text-xs text-muted">Cycles</span>
                                </div>
                                <div className="text-right">
                                    <span className="text-sm font-semibold text-cyan-300">
                                        {todayStats?.batteryCycles != null ? todayStats.batteryCycles.toFixed(2) : '—'}
                                    </span>
                                </div>
                            </div>

                            {/* Water Heating */}
                            <div className="flex items-center justify-between">
                                <div className="flex items-center gap-2">
                                    <span className="text-base">🔥</span>
                                    <span className="text-xs text-muted">Water</span>
                                </div>
                                <div className="text-right">
                                    <span className="text-sm font-semibold text-orange-300">
                                        {waterToday?.kwh !== undefined ? waterToday.kwh.toFixed(1) : '—'}
                                    </span>
                                    <span className="text-xs text-muted ml-1">kWh</span>
                                </div>
                            </div>
                        </div>
                    </div>
                </Card>
            </div >
        </main >
    )
}
