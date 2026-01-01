/* eslint-disable @typescript-eslint/no-explicit-any */
import { useEffect, useState, useCallback } from 'react'
import Card from '../components/Card'
import ChartCard from '../components/ChartCard'
import QuickActions from '../components/QuickActions'
import { motion } from 'framer-motion'
import { Api, type PlannerSIndex } from '../lib/api'
import type { ScheduleSlot } from '../lib/types'
import { isToday, isTomorrow } from '../lib/time'
import SmartAdvisor from '../components/SmartAdvisor'
import { ArrowDownToLine, ArrowUpFromLine } from 'lucide-react'
import { GridDomain, ResourcesDomain, StrategyDomain, ControlParameters } from '../components/CommandDomains'
import { useSocket } from '../lib/hooks'

type PlannerMeta = {
    planned_at?: string
    planner_version?: string
    s_index?: PlannerSIndex
} | null

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
    const [isRefreshing, setIsRefreshing] = useState(false)
    const [lastRefresh, setLastRefresh] = useState<Date | null>(null)
    const [chartRefreshToken, setChartRefreshToken] = useState(0)

    const [automationConfig, setAutomationConfig] = useState<{
        enable_scheduler?: boolean
        write_to_mariadb?: boolean
        external_executor_mode?: boolean
        every_minutes?: number | null
    } | null>(null)
    const [automationSaving, setAutomationSaving] = useState(false)
    const [schedulerStatus, setSchedulerStatus] = useState<{
        last_run_at?: string | null
        last_run_status?: string | null
        next_run_at?: string | null
    } | null>(null)
    const [localSchedule, setLocalSchedule] = useState<ScheduleSlot[] | null>(null)
    const [historySlots, setHistorySlots] = useState<ScheduleSlot[] | null>(null)
    const [lastError, setLastError] = useState<{ message: string; at: string } | null>(null)
    const [executorStatus, setExecutorStatus] = useState<{
        shadow_mode?: boolean
        paused?: { paused_at?: string; paused_minutes?: number } | null
    } | null>(null)
    const [todayStats, setTodayStats] = useState<{
        gridImport: number | null
        gridExport: number | null
        batteryCycles: number | null
        pvProduction: number | null
        pvForecast: number | null
        loadConsumption: number | null
        netCost: number | null
    } | null>(null)

    // --- Missing State Variables Restored ---
    const [plannerLocalMeta, setPlannerLocalMeta] = useState<PlannerMeta>(null)
    const [plannerDbMeta, setPlannerDbMeta] = useState<PlannerMeta>(null)
    const [plannerMeta, setPlannerMeta] = useState<PlannerMeta>(null)
    const [currentPlanSource, setCurrentPlanSource] = useState<'local' | 'server'>('local')
    const [batteryCapacity, setBatteryCapacity] = useState<number>(0)
    const [avgLoad, setAvgLoad] = useState<{ kw: number; dailyKwh: number } | null>(null)
    const [currentSlotTarget, setCurrentSlotTarget] = useState<number>(0)
    const [waterToday, setWaterToday] = useState<{ kwh: number; source: string } | null>(null)
    const [comfortLevel, setComfortLevel] = useState<number>(0)
    const [vacationMode, setVacationMode] = useState<boolean>(false)
    const [vacationModeHA, setVacationModeHA] = useState<boolean>(false)
    const [vacationEntityId, setVacationEntityId] = useState<string>('')
    const [riskAppetite, setRiskAppetite] = useState<number>(1.0)
    const [exportGuard, setExportGuard] = useState<boolean>(false)
    const [serverSchedule, setServerSchedule] = useState<ScheduleSlot[]>([])

    // --- WebSocket Event Handlers (Rev E1) ---
    useSocket('live_metrics', (data: any) => {
        if (data.soc !== undefined) setSoc(data.soc)
        // Note: PV/Load today stats still come from fetchAllData because they are cumulative
    })

    useSocket('plan_updated', () => {
        console.log('📅 Plan updated! Refreshing data...')
        fetchAllData()
    })

    useSocket('executor_status', (data: any) => {
        setExecutorStatus({
            shadow_mode: data.shadow_mode ?? false,
            paused: data.paused ?? null,
        })
    })

    // WebSocket: HA entity state changes (instant vacation mode sync)
    useSocket('ha_entity_change', (data: any) => {
        // If this is the vacation mode entity, update state instantly
        if (data.entity_id === vacationEntityId) {
            const isActive = data.state === 'on'
            setVacationModeHA(isActive)
        }
    })

    // Listen for config updates from QuickActions
    useEffect(() => {
        const handleConfigUpdate = async () => {
            try {
                const data = await Api.config()
                if (data) {
                    const vacationCfg = data.water_heating?.vacation_mode
                    setVacationMode(vacationCfg?.enabled || false)
                }
            } catch (error) {
                console.log('Failed to reload vacation mode:', error)
            }
        }

        window.addEventListener('config-updated', handleConfigUpdate)
        return () => window.removeEventListener('config-updated', handleConfigUpdate)
    }, [])

    const handlePlanSourceChange = useCallback((source: 'local' | 'server') => {
        setCurrentPlanSource(source)
    }, [])

    const handleServerScheduleLoaded = useCallback((schedule: ScheduleSlot[]) => {
        if (!schedule || schedule.length === 0) {
            setServerSchedule([])
            return
        }

        Api.scheduleTodayWithHistory()
            .then((res) => {
                const historySlots = res.slots ?? []
                const byStart = new Map<string, ScheduleSlot>()
                historySlots.forEach((slot: ScheduleSlot) => {
                    if (slot.start_time) {
                        byStart.set(String(slot.start_time), slot)
                    }
                })

                const merged: ScheduleSlot[] = schedule.map((slot) => {
                    const key = slot.start_time
                    const hist = key ? byStart.get(String(key)) : undefined
                    if (!hist) return slot

                    const mergedSlot: ScheduleSlot = { ...slot }

                    if (hist.soc_actual_percent != null) {
                        mergedSlot.soc_actual_percent = hist.soc_actual_percent
                    }
                    if (hist.is_executed === true) {
                        mergedSlot.is_executed = true
                    }

                    return mergedSlot
                })

                setServerSchedule(merged)
            })
            .catch((err) => {
                console.error('Failed to merge history into server schedule:', err)
                setServerSchedule(schedule ?? [])
                // Removed setServerScheduleError
            })
            .finally(() => {})
    }, [])

    const fetchAllData = useCallback(async () => {
        setIsRefreshing(true)
        try {
            // Parallel fetch all data
            const [
                statusData,
                configData,
                haAverageData,
                scheduleData,
                waterData,
                schedulerStatusData,
                historyData,
                executorStatusData,
                energyTodayData,
            ] = await Promise.allSettled([
                Api.status(),
                Api.config(),
                Api.haAverage(),
                Api.schedule(),
                Api.haWaterToday(),
                Api.schedulerStatus(),
                Api.scheduleTodayWithHistory(),
                Api.executor.status(),
                Api.energyToday(),
            ])

            // Process status data
            if (statusData.status === 'fulfilled') {
                const data = statusData.value
                if (data.current_soc?.value !== undefined) setSoc(data.current_soc.value)
                if (data.local) setPlannerLocalMeta(data.local)
                if (data.db && !('error' in data.db)) {
                    setPlannerDbMeta(data.db as PlannerMeta)
                }
            }

            // Process config data
            if (configData.status === 'fulfilled') {
                const data = configData.value
                // Get export guard status from arbitrage config
                const arbitrage = data.arbitrage || {}
                setExportGuard(arbitrage.export_guard_enabled || false)
                if (typeof arbitrage.risk_appetite === 'number') {
                    setRiskAppetite(arbitrage.risk_appetite)
                }
                if (data.system?.battery?.capacity_kwh != null) {
                    setBatteryCapacity(data.system.battery.capacity_kwh)
                }

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

                // Auto-refresh was removed in UI2 - dashboard is now WebSocket-based

                // Load comfort level and vacation mode from water_heating config
                if (data.water_heating) {
                    if (typeof data.water_heating.comfort_level === 'number') {
                        setComfortLevel(data.water_heating.comfort_level)
                    }
                    if (typeof data.water_heating.vacation_mode?.enabled === 'boolean') {
                        setVacationMode(data.water_heating.vacation_mode.enabled)
                    }
                }

                // Load vacation mode HA entity ID
                if (data.input_sensors?.vacation_mode) {
                    setVacationEntityId(data.input_sensors.vacation_mode)
                    // Immediately fetch the HA entity state if configured
                    Api.haEntityState(data.input_sensors.vacation_mode)
                        .then((entityData) => {
                            const isActive = entityData.state === 'on'
                            setVacationModeHA(isActive)
                        })
                        .catch(() => {
                            // Entity not available, gracefully ignore
                            setVacationModeHA(false)
                        })
                }
            } else {
                console.error('Failed to load config for Dashboard:', configData.reason)
            }

            // Process HA average data
            if (haAverageData.status === 'fulfilled') {
                const data = haAverageData.value
                setAvgLoad({
                    kw: data.average_load_kw ?? 0,
                    dailyKwh: data.daily_kwh ?? 0,
                })
            } else {
                console.error('Failed to load HA average for Dashboard:', haAverageData.reason)
            }

            // Process schedule data
            if (scheduleData.status === 'fulfilled') {
                const data = scheduleData.value
                const sched = data.schedule ?? []
                setLocalSchedule(sched)
                // Removed todaySlots/pvTotal calculation as it was unused

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
                const currentSlot = sched.find((slot) => {
                    const slotTime = new Date(slot.start_time || '')
                    const slotEnd = new Date(slotTime.getTime() + 30 * 60 * 1000) // 30 min slots
                    return now >= slotTime && now < slotEnd
                })
                if (currentSlot?.soc_target_percent !== undefined) {
                    setCurrentSlotTarget(currentSlot.soc_target_percent)
                }
            } else {
                console.error('Failed to load schedule for Dashboard:', scheduleData.reason)
            }

            // Process water data
            if (waterData.status === 'fulfilled') {
                const data = waterData.value
                setWaterToday({
                    kwh: data.water_kwh_today ?? 0,
                    source: data.source ?? 'unknown',
                })
            } else {
                console.error('Failed to load water data for Dashboard:', waterData.reason)
            }

            // Process water data

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
                const todaySlots = historyData.value.slots.filter((s) => {
                    const slotTime = new Date(s.start_time)
                    return slotTime >= todayStart
                })
                todaySlots.forEach((s) => {
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
        } finally {
            setIsRefreshing(false)
            // Nudge the overview chart to reload its schedule data so that
            // planner runs / server-plan loads are reflected without manual
            // day toggling.
            setChartRefreshToken((token) => token + 1)
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

    const toggleAutomationScheduler = async () => {
        if (automationSaving) return
        const current = automationConfig?.enable_scheduler ?? false
        const next = !current
        setAutomationSaving(true)
        try {
            await Api.configSave({ automation: { enable_scheduler: next } })
            setAutomationConfig((prev) => ({
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

    // Build slotsOverride for the chart (and badge)
    let slotsOverride: ScheduleSlot[] | undefined
    if (currentPlanSource === 'server' && serverSchedule && serverSchedule.length > 0) {
        slotsOverride = serverSchedule
    } else if (currentPlanSource === 'local' && localSchedule && localSchedule.length > 0) {
        const todayAndTomorrow = localSchedule.filter((slot) => isToday(slot.start_time) || isTomorrow(slot.start_time))
        if (historySlots && historySlots.length > 0) {
            const tomorrowSlots = todayAndTomorrow.filter((slot) => isTomorrow(slot.start_time))
            slotsOverride = [...historySlots, ...tomorrowSlots]
        } else {
            slotsOverride = todayAndTomorrow
        }
    }

    // Badge Logic
    const now = new Date()
    let freshnessText = currentPlanSource === 'server' ? 'Server Plan' : 'Local Plan'
    if (plannerMeta?.planned_at) {
        const planned = new Date(plannerMeta.planned_at)
        const timeStr = planned.toLocaleTimeString([], { hour: '2-digit', minute: '2-digit' })
        freshnessText = `Generated ${timeStr}`
    }

    let nextActionText = ''
    if (slotsOverride) {
        const currentSlot = slotsOverride.find((s) => {
            const start = new Date(s.start_time)
            const end = new Date(start.getTime() + 30 * 60 * 1000)
            return now >= start && now < end
        })

        if (currentSlot) {
            const end = new Date(new Date(currentSlot.start_time).getTime() + 30 * 60 * 1000)
            const minutesLeft = Math.max(0, Math.floor((end.getTime() - now.getTime()) / 60000))

            let action = 'Idle'
            if ((currentSlot.charge_kw || 0) > 0.1) action = `Charge ${currentSlot.charge_kw?.toFixed(1)}kW`
            else if ((currentSlot.discharge_kw || 0) > 0.1)
                action = `Discharge ${currentSlot.discharge_kw?.toFixed(1)}kW`
            else if ((currentSlot.export_kwh || 0) > 0.1) action = `Export ${currentSlot.export_kwh?.toFixed(1)}kWh`
            else if ((currentSlot.water_heating_kw || 0) > 0.1) action = `Heat Water`

            nextActionText = ` · Next: ${action} (${minutesLeft}m)`
        }
    }
    const planBadge = `${freshnessText}${nextActionText}`

    // Derive last/next planner runs for automation card
    const lastRunIso = schedulerStatus?.last_run_at || plannerLocalMeta?.planned_at || plannerDbMeta?.planned_at
    const lastRunDate = lastRunIso ? new Date(lastRunIso) : null
    const everyMinutes =
        automationConfig?.every_minutes && automationConfig.every_minutes > 0 ? automationConfig.every_minutes : null
    let nextRunDate: Date | null = null
    if (schedulerStatus?.next_run_at) {
        nextRunDate = new Date(schedulerStatus.next_run_at)
    } else if (automationConfig?.enable_scheduler && lastRunDate && everyMinutes) {
        nextRunDate = new Date(lastRunDate.getTime() + everyMinutes * 60 * 1000)
    }

    // Base display variables
    // Rev DX1: Removed unused variables (socDisplay, pvDays, weatherDays, sIndexDisplay, termDisplay)

    return (
        <main className="mx-auto max-w-7xl px-4 pb-24 pt-6 sm:px-6 lg:pt-10 space-y-6">
            {/* Header Removed as per user request */}

            {/* Critical Error Banner */}
            {lastError && (
                <motion.div
                    initial={{ opacity: 0, y: -10 }}
                    animate={{ opacity: 1, y: 0 }}
                    className="banner banner-error p-4"
                >
                    <div className="flex items-start justify-between gap-4 w-full">
                        <div>
                            <div className="flex items-center gap-2 font-semibold text-sm mb-1">
                                <span>⚠️</span>
                                <span>Planner Error</span>
                            </div>
                            <div className="opacity-80 text-xs">{lastError.message}</div>
                            {lastError.at && (
                                <div className="opacity-60 text-[10px] mt-1">
                                    {new Date(lastError.at).toLocaleString()}
                                </div>
                            )}
                        </div>
                        <button
                            onClick={() => setLastError(null)}
                            className="opacity-60 hover:opacity-100 text-xs px-2 py-1"
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
                    className="banner banner-purple px-4 py-3"
                >
                    <span>👻</span>
                    <span className="font-medium">Shadow Mode Active</span>
                    <span className="opacity-70 text-xs ml-2">— Actions logged but not executed on Home Assistant</span>
                </motion.div>
            )}

            {/* Executor Paused Banner */}
            {executorStatus?.paused && (
                <motion.div
                    initial={{ opacity: 0, y: -10 }}
                    animate={{ opacity: 1, y: 0 }}
                    className="banner banner-warning px-4 py-3"
                >
                    <span>⏸️</span>
                    <span className="font-medium">Executor Paused (Idle Mode)</span>
                    {executorStatus.paused.paused_minutes !== undefined && (
                        <span className="opacity-70 text-xs ml-2">
                            — Paused for {executorStatus.paused.paused_minutes} minutes
                        </span>
                    )}
                </motion.div>
            )}

            {/* Vacation Mode Banner */}
            {(vacationMode || vacationModeHA) && (
                <motion.div
                    initial={{ opacity: 0, y: -10 }}
                    animate={{ opacity: 1, y: 0 }}
                    className="banner banner-warning px-4 py-3"
                >
                    <span>🏝️</span>
                    <span className="font-medium">Vacation Mode Active</span>
                    <span className="opacity-70 text-xs ml-2">— Water heating is disabled</span>
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

            {/* Row 2: Controls & Advisor & Quick Actions */}
            <div className="grid gap-6 lg:grid-cols-3 items-stretch">
                {/* Col 1: Toolbar + Advisor */}
                <motion.div
                    className="h-full flex flex-col gap-4"
                    initial={{ opacity: 0, y: 8 }}
                    animate={{ opacity: 1, y: 0 }}
                >
                    {/* Advisor */}
                    <div className="flex-1 min-h-0">
                        <SmartAdvisor />
                    </div>
                </motion.div>

                {/* Middle Column: Control Parameters (Comfort + Risk + Overrides) */}
                <motion.div className="h-full" initial={{ opacity: 0, y: 8 }} animate={{ opacity: 1, y: 0 }}>
                    <ControlParameters
                        comfortLevel={comfortLevel}
                        setComfortLevel={async (l) => {
                            setComfortLevel(l)
                            await Api.configSave({ water_heating: { comfort_level: l } })
                        }}
                        riskAppetite={riskAppetite}
                        setRiskAppetite={async (l) => {
                            setRiskAppetite(l)
                            await Api.configSave({ s_index: { risk_appetite: l } })
                        }}
                        vacationMode={vacationMode}
                        onWaterBoost={async () => {
                            try {
                                await Api.waterBoost.start(60)
                                fetchAllData()
                            } catch (e) {
                                console.error('Boost failed', e)
                            }
                        }}
                        onBatteryTopUp={async () => {
                            try {
                                await Api.executor.quickAction.set('force_charge', 60)
                                fetchAllData()
                            } catch (e) {
                                console.error('Top Up failed', e)
                            }
                        }}
                    />
                </motion.div>

                {/* Right Column: Quick Actions */}
                <motion.div className="h-full" initial={{ opacity: 0, y: 8 }} animate={{ opacity: 1, y: 0 }}>
                    <div className="flex h-full flex-col gap-6">
                        <Card className="flex-1 p-4 md:p-5">
                            <QuickActions
                                onDataRefresh={fetchAllData}
                                onPlanSourceChange={handlePlanSourceChange}
                                onServerScheduleLoaded={handleServerScheduleLoaded}
                                onVacationModeChange={(enabled) => setVacationMode(enabled)}
                            />
                        </Card>
                        <Card className="flex-1 p-4 md:p-5">
                            <div className="flex items-baseline justify-between mb-4">
                                <div className="text-sm font-medium text-text">Planner Automation</div>
                                <div className="flex items-center gap-2">
                                    <div className="flex items-center gap-2 text-[10px] text-muted">
                                        <span
                                            className={`inline-flex h-2 w-2 rounded-full ${
                                                automationConfig?.enable_scheduler
                                                    ? 'bg-good shadow-[0_0_0_2px_rgba(var(--color-good),0.4)]'
                                                    : 'bg-line'
                                            }`}
                                        />
                                        <span>{automationConfig?.enable_scheduler ? 'Active' : 'Disabled'}</span>
                                    </div>
                                    <button
                                        type="button"
                                        onClick={toggleAutomationScheduler}
                                        disabled={automationSaving}
                                        className="rounded-pill px-2 py-0.5 text-[10px] font-semibold border border-line/60 text-muted hover:border-accent hover:text-accent disabled:opacity-50 transition"
                                    >
                                        {automationConfig?.enable_scheduler ? 'Disable' : 'Enable'}
                                    </button>
                                </div>
                            </div>

                            {/* Plan Info Badge & Refresh */}
                            <div className="mb-4 p-2 rounded-lg bg-surface2/30 border border-line/30 flex items-center justify-between">
                                <div className="text-[10px] font-medium text-text">{planBadge}</div>
                                <button
                                    onClick={() => fetchAllData()}
                                    disabled={isRefreshing}
                                    className={`rounded-full p-1 transition ${
                                        isRefreshing ? 'bg-surface2 text-muted' : 'text-muted hover:text-accent'
                                    }`}
                                    title="Manual sync"
                                >
                                    <span className={`inline-block text-[10px] ${isRefreshing ? 'animate-spin' : ''}`}>
                                        {isRefreshing ? '⟳' : '↻'}
                                    </span>
                                </button>
                            </div>

                            <div className="space-y-1 text-[10px] text-muted">
                                <div className="flex justify-between">
                                    <span>Last plan run:</span>
                                    <span className="font-mono">{formatLocalIso(lastRunDate)}</span>
                                </div>
                                <div className="flex justify-between">
                                    <span>Next expected run:</span>
                                    <span className="font-mono">
                                        {automationConfig?.enable_scheduler ? formatLocalIso(nextRunDate) : '—'}
                                    </span>
                                </div>
                                <div className="flex justify-between">
                                    <span>DB sync:</span>
                                    <span>{automationConfig?.write_to_mariadb ? 'enabled' : 'disabled'}</span>
                                </div>
                                <div className="flex justify-between pt-1 border-t border-line/30 mt-1">
                                    <span>Dashboard Sync:</span>
                                    <span>{lastRefresh ? lastRefresh.toLocaleTimeString() : '—'}</span>
                                </div>
                            </div>
                        </Card>

                        {automationConfig?.external_executor_mode && (
                            <Card className="flex-1 p-4 md:p-5 flex flex-col">
                                <div className="flex items-baseline justify-between mb-3">
                                    <div className="text-sm text-muted">DB Sync</div>
                                    <div
                                        className={`text-[10px] ${dbSyncFeedback?.type === 'success' ? 'text-good' : 'text-bad'}`}
                                    >
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

            {/* Row 3: Grid + Resources + Strategy */}
            <div className="grid grid-cols-1 gap-6 lg:grid-cols-3">
                {/* Col 1: Grid Domain */}
                <GridDomain
                    netCost={todayStats?.netCost ?? null}
                    importKwh={todayStats?.gridImport ?? null}
                    exportKwh={todayStats?.gridExport ?? null}
                    exportGuard={exportGuard}
                />

                {/* Col 2: Resources Domain */}
                <ResourcesDomain
                    pvActual={todayStats?.pvProduction ?? null}
                    pvForecast={todayStats?.pvForecast ?? null}
                    loadActual={todayStats?.loadConsumption ?? null}
                    loadAvg={avgLoad?.dailyKwh ?? null}
                    waterKwh={waterToday?.kwh ?? null}
                    batteryCapacity={batteryCapacity}
                />

                {/* Col 3: Strategy Domain (Moved here) */}
                <StrategyDomain
                    soc={soc}
                    socTarget={currentSlotTarget}
                    sIndex={plannerMeta?.s_index?.effective_load_margin ?? null}
                    cycles={todayStats?.batteryCycles ?? null}
                    riskLabel={
                        (
                            {
                                1: 'Safety',
                                2: 'Conservative',
                                3: 'Neutral',
                                4: 'Aggressive',
                                5: 'Gambler',
                            } as Record<number, string>
                        )[riskAppetite] || 'Neutral'
                    }
                />
            </div>
        </main>
    )
}
