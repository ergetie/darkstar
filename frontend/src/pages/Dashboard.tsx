/* eslint-disable @typescript-eslint/no-explicit-any */
import { useEffect, useState, useCallback } from 'react'
import Card from '../components/Card'
import ChartCard from '../components/ChartCard'
import QuickActions from '../components/QuickActions'
import { motion } from 'framer-motion'
import { Api, type PlannerSIndex } from '../lib/api'
import type { ScheduleSlot } from '../lib/types'
import { isToday, isTomorrow } from '../lib/time'
import AdvisorCard from '../components/AdvisorCard'
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
    // const [plannerDbMeta, setPlannerDbMeta] = useState<PlannerMeta>(null) // Unused
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
    const [serverSchedule, setServerSchedule] = useState<ScheduleSlot[]>([])

    // Live power metrics for PowerFlowCard
    const [livePower, setLivePower] = useState<{
        pv_kw?: number
        load_kw?: number
        battery_kw?: number
        grid_kw?: number
        water_kw?: number
    }>({})

    // --- WebSocket Event Handlers (Rev E1) ---
    useSocket('live_metrics', (data: any) => {
        console.log('📊 live_metrics received:', data)
        if (data.soc !== undefined) setSoc(data.soc)
        // Capture all power metrics for PowerFlowCard
        setLivePower((prev) => ({
            ...prev,
            pv_kw: data.pv_kw ?? prev.pv_kw,
            load_kw: data.load_kw ?? prev.load_kw,
            battery_kw: data.battery_kw ?? prev.battery_kw,
            grid_kw: data.grid_kw ?? prev.grid_kw,
            water_kw: data.water_kw ?? prev.water_kw,
        }))
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
                scheduleData, // learningStatusData unused
                ,
                schedulerStatusData,
                todayStatsData,
                waterData,
                auroraData,
                executorStatusData,
                historyData,
            ] = await Promise.allSettled([
                Api.status(),
                Api.config(),
                Api.haAverage(),
                Api.schedule(),
                Api.learningStatus(),
                Api.schedulerStatus(),
                Api.energyToday(),
                Api.haWaterToday(),
                Api.aurora.dashboard(),
                Api.executor.status(),
                Api.scheduleTodayWithHistory(),
            ])

            // Extract SoC from status API (flat structure: soc_percent)
            if (statusData.status === 'fulfilled') {
                const data = statusData.value
                if (data.soc_percent != null) {
                    setSoc(data.soc_percent)
                } else if (data.current_soc?.value != null) {
                    setSoc(data.current_soc.value) // Fallback for legacy format
                }
            }

            // Calculate PV Forecast for today from Aurora horizon
            let pvForecastTotal = 0
            if (auroraData.status === 'fulfilled' && auroraData.value?.horizon?.slots) {
                const now = new Date()
                const todayStr = now.toISOString().split('T')[0]
                pvForecastTotal = auroraData.value.horizon.slots
                    .filter((s) => s.slot_start.startsWith(todayStr))
                    .reduce((sum, s) => sum + (s.final?.pv_kwh || 0), 0)
            }

            // Process config data
            if (configData.status === 'fulfilled') {
                const data = configData.value
                // Read risk_appetite from s_index
                const sIndex = (data as Record<string, unknown>).s_index as Record<string, unknown> | undefined
                if (typeof sIndex?.risk_appetite === 'number') {
                    setRiskAppetite(sIndex.risk_appetite)
                }
                // Battery config is at config.battery, not config.system.battery
                if (data.battery?.capacity_kwh != null) {
                    setBatteryCapacity(data.battery.capacity_kwh)
                } else if (data.system?.battery?.capacity_kwh != null) {
                    setBatteryCapacity(data.system.battery.capacity_kwh) // Fallback
                }

                // Automation / scheduler config
                if (data.automation) {
                    setAutomationConfig({
                        enable_scheduler: data.automation.enable_scheduler,
                        write_to_mariadb: data.automation.write_to_mariadb,
                        external_executor_mode: data.automation.external_executor_mode,
                        every_minutes: data.automation.schedule?.every_minutes ?? null,
                    })
                } else {
                    setAutomationConfig(null)
                }

                if (data.water_heating) {
                    if (typeof data.water_heating.comfort_level === 'number') {
                        setComfortLevel(data.water_heating.comfort_level)
                    }
                    if (typeof data.water_heating.vacation_mode?.enabled === 'boolean') {
                        setVacationMode(data.water_heating.vacation_mode.enabled)
                    }
                }

                if (data.input_sensors?.vacation_mode) {
                    setVacationEntityId(data.input_sensors.vacation_mode)
                    Api.haEntityState(data.input_sensors.vacation_mode)
                        .then((entityData) => {
                            setVacationModeHA(entityData.state === 'on')
                        })
                        .catch(() => setVacationModeHA(false))
                }
            } else {
                console.error('Failed to load config:', configData.reason)
            }

            // Process HA average data
            if (haAverageData.status === 'fulfilled') {
                setAvgLoad({
                    kw: haAverageData.value.average_load_kw ?? 0,
                    dailyKwh: haAverageData.value.daily_kwh ?? 0,
                })
            }

            // Process schedule data
            if (scheduleData.status === 'fulfilled' && scheduleData.value) {
                const data = scheduleData.value
                setLocalSchedule(data.schedule ?? [])

                // Extract plannerMeta from schedule.meta for s-index display
                if (data.meta) {
                    setPlannerLocalMeta({
                        planned_at: data.meta.planned_at as string | undefined,
                        planner_version: data.meta.planner_version as string | undefined,
                        s_index: data.meta.s_index as PlannerSIndex | undefined,
                    })
                }

                if (data.meta?.last_error) {
                    setLastError({ message: data.meta.last_error, at: data.meta.last_error_at || '' })
                } else {
                    setLastError(null)
                }

                const now = new Date()
                const currentSlot = (data.schedule ?? []).find((slot) => {
                    const slotTime = new Date(slot.start_time || '')
                    const slotEnd = new Date(slotTime.getTime() + 30 * 60 * 1000)
                    return now >= slotTime && now < slotEnd
                })
                if (currentSlot?.soc_target_percent !== undefined) {
                    setCurrentSlotTarget(currentSlot.soc_target_percent)
                }
            }

            // Process water data
            if (waterData.status === 'fulfilled') {
                setWaterToday({
                    kwh: waterData.value.water_kwh_today ?? 0,
                    source: waterData.value.source ?? 'unknown',
                })
            }

            // Process scheduler status
            if (schedulerStatusData.status === 'fulfilled') {
                const data = schedulerStatusData.value
                setSchedulerStatus({
                    last_run_at: data.last_run_at ?? null,
                    last_run_status: data.last_run_status ?? null,
                    next_run_at: data.next_run_at ?? null,
                })
            }

            // Process history
            if (historyData.status === 'fulfilled') {
                setHistorySlots(historyData.value.slots ?? [])
                // Fallback for PV Forecast if Aurora missing
                if (pvForecastTotal === 0 && historyData.value.slots) {
                    const todayStart = new Date()
                    todayStart.setHours(0, 0, 0, 0)
                    historyData.value.slots.forEach((s) => {
                        if (new Date(s.start_time) >= todayStart) {
                            pvForecastTotal += s.pv_forecast_kwh ?? 0
                        }
                    })
                }
            }

            // Process executor status
            if (executorStatusData.status === 'fulfilled') {
                setExecutorStatus({
                    shadow_mode: executorStatusData.value.shadow_mode ?? false,
                    paused: executorStatusData.value.paused ?? null,
                })
            }

            // Process energy today
            if (todayStatsData.status === 'fulfilled') {
                const data = todayStatsData.value
                setTodayStats({
                    gridImport: data.grid_import_kwh ?? null,
                    gridExport: data.grid_export_kwh ?? null,
                    batteryCycles: data.battery_cycles ?? null,
                    pvProduction: data.pv_production_kwh ?? null,
                    pvForecast: pvForecastTotal > 0 ? parseFloat(pvForecastTotal.toFixed(1)) : null,
                    loadConsumption: data.load_consumption_kwh ?? null,
                    netCost: data.net_cost_kr ?? null,
                })
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
            nextMeta = null // plannerDbMeta was unused/always null
        } else {
            nextMeta = plannerLocalMeta
        }
        setPlannerMeta(nextMeta)
    }, [currentPlanSource, plannerLocalMeta])

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
    const lastRunIso = schedulerStatus?.last_run_at || plannerLocalMeta?.planned_at
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
                    {/* Advisor with Power Flow toggle */}
                    <div className="flex-1 min-h-0">
                        <AdvisorCard
                            powerFlowData={{
                                solar: {
                                    kw: livePower.pv_kw ?? 0,
                                    todayKwh: todayStats?.pvProduction ?? undefined,
                                },
                                battery: {
                                    kw: livePower.battery_kw ?? 0,
                                    soc: soc ?? 50,
                                },
                                grid: {
                                    kw: livePower.grid_kw ?? 0,
                                    importKwh: todayStats?.gridImport ?? undefined,
                                    exportKwh: todayStats?.gridExport ?? undefined,
                                },
                                house: {
                                    kw: livePower.load_kw ?? 0,
                                    todayKwh: todayStats?.loadConsumption ?? undefined,
                                },
                                water: {
                                    kw: livePower.water_kw ?? 0,
                                },
                            }}
                        />
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
                    sIndex={
                        plannerMeta?.s_index?.effective_load_margin ??
                        plannerMeta?.s_index?.risk_factor ??
                        plannerMeta?.s_index?.factor ??
                        null
                    }
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
