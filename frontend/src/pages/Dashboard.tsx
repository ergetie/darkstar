/* eslint-disable @typescript-eslint/no-explicit-any */
import { useEffect, useState, useCallback } from 'react'
import Card from '../components/Card'
import ChartCard from '../components/ChartCard'
import QuickActions from '../components/QuickActions'
import { Flame, BatteryCharging } from 'lucide-react'
import { motion } from 'framer-motion'
import {
    Api, type PlannerSIndex, type HealthResponse, type AuroraDashboardResponse,
    ExecutorStatusResponse,
} from '../lib/api'
import type { ScheduleSlot, AuroraRiskProfile } from '../lib/types'
import { isToday, isTomorrow } from '../lib/time'
import AdvisorCard from '../components/AdvisorCard'
import { GridDomain, ResourcesDomain, StrategyDomain, ControlParameters } from '../components/CommandDomains'
import { useSocket } from '../lib/hooks'
import { useToast } from '../lib/useToast'
import { SystemAlert } from '../components/SystemAlert'

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
        quick_action?: ExecutorStatusResponse['quick_action']
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
    const [waterBoostActive, setWaterBoostActive] = useState<{
        boost: boolean
        expires_at?: string
    } | null>(null)

    // --- Missing State Variables Restored ---
    const [plannerLocalMeta, setPlannerLocalMeta] = useState<PlannerMeta>(null)
    const [plannerMeta, setPlannerMeta] = useState<PlannerMeta>(null)
    const [batteryCapacity, setBatteryCapacity] = useState<number>(0)
    const [avgLoad, setAvgLoad] = useState<{ kw: number; dailyKwh: number } | null>(null)
    const [currentSlotTarget, setCurrentSlotTarget] = useState<number>(0)
    const [waterToday, setWaterToday] = useState<{ kwh: number; source: string } | null>(null)
    const [comfortLevel, setComfortLevel] = useState<number>(0)
    const [vacationMode, setVacationMode] = useState<boolean>(false)
    const [vacationModeHA, setVacationModeHA] = useState<boolean>(false)
    const [vacationEntityId, setVacationEntityId] = useState<string>('')
    const [riskAppetite, setRiskAppetite] = useState<number>(1.0)
    const [plannerStatus, setPlannerStatus] = useState<string | null>(null)

    // Live power metrics for PowerFlowCard
    const [livePower, setLivePower] = useState<{
        pv_kw?: number
        load_kw?: number
        battery_kw?: number
        grid_kw?: number
        water_kw?: number
    }>({})

    // REV LCL01: Health status for config validation banners
    const [healthStatus, setHealthStatus] = useState<HealthResponse | null>(null)

    const { toast } = useToast()

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

    useSocket('schedule_updated', (data: any) => {
        console.log('📅 Schedule updated via push:', data)
        // Show toast notification (Rev ARC8)
        toast({
            message: 'Schedule updated',
            description: `${data.slot_count ?? 0} slots generated`,
            variant: 'success',
        })
        // Targeted refresh - only fetch schedule, not everything
        Api.schedule().then((data) => {
            if (data.schedule) setLocalSchedule(data.schedule)
            if (data.meta) {
                setPlannerLocalMeta({
                    planned_at: data.meta.planned_at as string | undefined,
                    planner_version: data.meta.planner_version as string | undefined,
                    s_index: data.meta.s_index as PlannerSIndex | undefined,
                })
            }
        })
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

    const fetchCriticalData = useCallback(async () => {
        setIsRefreshing(true)
        try {
            const bundle = await Api.dashboardBundle()

            // Process critical data: Status
            if (bundle.status) {
                const data = bundle.status
                if (data.soc_percent != null) setSoc(data.soc_percent)
                else if (data.current_soc?.value != null) setSoc(data.current_soc.value)
                setPlannerStatus(data.status || null)
            }

            // Process critical data: Config
            if (bundle.config) {
                const data = bundle.config
                // Risk appetite
                const sIndex = (data as Record<string, unknown>).s_index as Record<string, unknown> | undefined
                if (typeof sIndex?.risk_appetite === 'number') setRiskAppetite(sIndex.risk_appetite)

                // Battery capacity
                if (data.battery?.capacity_kwh != null) setBatteryCapacity(data.battery.capacity_kwh)
                else if (data.system?.battery?.capacity_kwh != null)
                    setBatteryCapacity(data.system.battery.capacity_kwh)

                // Automation config
                if (data.automation) {
                    setAutomationConfig({
                        enable_scheduler: data.automation.enable_scheduler,
                        every_minutes: data.automation.schedule?.every_minutes ?? null,
                    })
                } else setAutomationConfig(null)

                // Water/Vacation config
                if (data.water_heating) {
                    if (typeof data.water_heating.comfort_level === 'number')
                        setComfortLevel(data.water_heating.comfort_level)
                    if (typeof data.water_heating.vacation_mode?.enabled === 'boolean')
                        setVacationMode(data.water_heating.vacation_mode.enabled)
                }

                if (data.input_sensors?.vacation_mode) {
                    setVacationEntityId(data.input_sensors.vacation_mode)
                    Api.haEntityState(data.input_sensors.vacation_mode)
                        .then((entityData) => setVacationModeHA(entityData.state === 'on'))
                        .catch(() => setVacationModeHA(false))
                }
            } else {
                console.error('Failed to load critical config from bundle')
            }

            // Schedule Data
            if (bundle.schedule) {
                const data = bundle.schedule
                setLocalSchedule(data.schedule ?? [])

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

            // Executor & Scheduler Status
            if (bundle.executor_status) {
                setExecutorStatus({
                    shadow_mode: bundle.executor_status.shadow_mode ?? false,
                    paused: bundle.executor_status.paused ?? null,
                    quick_action: bundle.executor_status.quick_action ?? null,
                })
            }

            if (bundle.scheduler_status) {
                const data = bundle.scheduler_status
                setSchedulerStatus({
                    last_run_at: data.last_run_at ?? null,
                    last_run_status: data.last_run_status ?? null,
                    next_run_at: data.next_run_at ?? null,
                })
            }

            // Water Boost Status
            if (bundle.water_boost) {
                setWaterBoostActive(bundle.water_boost)
            }

            setLastRefresh(new Date())
        } catch (error) {
            console.error('Error fetching dashboard bundle:', error)
        } finally {
            setIsRefreshing(false)
        }
    }, [])

    const fetchDeferredData = useCallback(async () => {
        try {
            const [
                haAverageData,
                todayStatsData,
                waterData,
                auroraData,
                historyData,
                healthData, // REV LCL01: Fetch health for config validation banners
            ] = await Promise.allSettled([
                Api.haAverage(), // Cached for 60s
                Api.energyToday(),
                Api.haWaterToday(),
                Api.aurora.dashboard(),
                Api.scheduleTodayWithHistory(),
                Api.health(), // REV LCL01
            ])

            // REV LCL01: Update health status for banners
            if (healthData.status === 'fulfilled') {
                setHealthStatus(healthData.value)
            }

            if (haAverageData.status === 'fulfilled') {
                setAvgLoad({
                    kw: haAverageData.value.average_load_kw ?? 0,
                    dailyKwh: haAverageData.value.daily_kwh ?? 0,
                })
            }

            let pvForecastTotal = 0
            if (auroraData.status === 'fulfilled' && auroraData.value?.horizon?.slots) {
                const now = new Date()
                const todayStr = now.toISOString().split('T')[0]
                pvForecastTotal = auroraData.value.horizon.slots
                    .filter((s) => s.slot_start.startsWith(todayStr))
                    .reduce((sum, s) => sum + (s.final?.pv_kwh || 0), 0)
            }

            if (todayStatsData.status === 'fulfilled') {
                const data = todayStatsData.value
                setTodayStats({
                    gridImport: data.grid_import_kwh ?? null,
                    gridExport: data.grid_export_kwh ?? null,
                    batteryCycles: data.battery_cycles ?? null,
                    pvProduction: data.pv_production_kwh ?? null,
                    pvForecast: pvForecastTotal >= 0 ? parseFloat(pvForecastTotal.toFixed(1)) : null,
                    loadConsumption: data.load_consumption_kwh ?? null,
                    netCost: data.net_cost_kr ?? null,
                })
            }

            if (waterData.status === 'fulfilled') {
                setWaterToday({
                    kwh: waterData.value.water_kwh_today ?? 0,
                    source: waterData.value.source ?? 'unknown',
                })
            }

            if (historyData.status === 'fulfilled') {
                setHistorySlots(historyData.value.slots ?? [])
                // Fallback PV Total logic - sum the WHOLE day from history
                if (historyData.value.slots) {
                    const todayStart = new Date()
                    todayStart.setHours(0, 0, 0, 0)
                    let dailyTotal = 0
                    historyData.value.slots.forEach((s) => {
                        const sTime = new Date(s.start_time)
                        if (sTime >= todayStart) {
                            dailyTotal += s.pv_forecast_kwh ?? 0
                        }
                    })

                    if (dailyTotal > 0 || pvForecastTotal === 0) {
                        setTodayStats((prev) =>
                            prev
                                ? {
                                    ...prev,
                                    pvForecast: parseFloat(dailyTotal.toFixed(1)),
                                }
                                : null,
                        )
                    }
                }
            }
        } catch (error) {
            console.error('Error fetching deferred data:', error)
        } finally {
            setChartRefreshToken((token) => token + 1)
        }
    }, [])

    const fetchAllData = useCallback(async () => {
        await fetchCriticalData()
        // 100ms delay for deferred data
        setTimeout(() => fetchDeferredData(), 100)
    }, [fetchCriticalData, fetchDeferredData])

    // Keep displayed plannerMeta aligned with stored metadata.
    useEffect(() => {
        setPlannerMeta(plannerLocalMeta)
    }, [plannerLocalMeta])

    const handleSetComfortLevel = async (l: number) => {
        setComfortLevel(l)
        await Api.configSave({ water_heating: { comfort_level: l } })
    }

    const handleSetRiskAppetite = async (l: number) => {
        setRiskAppetite(l)
        await Api.configSave({ s_index: { risk_appetite: l } })
    }

    const handleBatteryTopUp = async (targetSoc: number = 60) => {
        try {
            // Check if force_charge is already active
            const activeQA = executorStatus?.quick_action
            if (activeQA?.type === 'force_charge') {
                await Api.executor.quickAction.clear()
                await fetchAllData()
                toast({ message: 'Top-Up Stopped', description: 'Battery charging override cleared', variant: 'success' })
            } else {
                await Api.executor.quickAction.set('force_charge', 60, { target_soc: targetSoc })
                await fetchAllData()
                toast({ message: 'Charging Started', description: `Battery top-up to ${targetSoc}% initiated`, variant: 'success' })
            }
        } catch (e) {
            console.error('Top Up/Stop failed', e)
            toast({ message: 'Action failed', variant: 'error' })
        }
    }

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
                every_minutes: prev?.every_minutes ?? null,
            }))
        } catch (err) {
            console.error('Failed to toggle planner automation:', err)
        } finally {
            setAutomationSaving(false)
        }
    }

    // Build slotsOverride for the chart (and badge)
    let slotsOverride: ScheduleSlot[] | undefined
    if (localSchedule && localSchedule.length > 0) {
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
    let freshnessText = 'Local Plan'
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

            {/* REV LCL01: Config Validation Health Banners */}
            <SystemAlert health={healthStatus} />

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

            {/* Water Boost Banner */}
            {waterBoostActive?.boost && (
                <motion.div
                    initial={{ opacity: 0, y: -10 }}
                    animate={{ opacity: 1, y: 0 }}
                    className="banner banner-error px-4 py-3 flex items-center justify-between"
                >
                    <div className="flex items-center gap-2">
                        <Flame className="h-4 w-4 text-red-400 animate-pulse" />
                        <span className="font-medium">Water Heater Boost Active</span>
                        {waterBoostActive.expires_at && (
                            <span className="opacity-70 text-xs ml-2">
                                — Expires at {new Date(waterBoostActive.expires_at).toLocaleTimeString([], { hour: '2-digit', minute: '2-digit' })}
                            </span>
                        )}
                    </div>
                    <button
                        onClick={async () => {
                            try {
                                await Api.waterBoost.cancel()
                                fetchAllData()
                                toast({
                                    message: 'Boost Cancelled',
                                    description: 'Water heater boost has been stopped.',
                                    variant: 'success'
                                })
                            } catch (e) {
                                console.error('Failed to cancel boost', e)
                            }
                        }}
                        className="bg-white/10 hover:bg-white/20 px-3 py-1 rounded-md text-[10px] font-semibold transition"
                    >
                        STOP BOOST
                    </button>
                </motion.div>
            )}

            {/* Top-Up Active Banner */}
            {executorStatus?.quick_action?.type === 'force_charge' && (
                <motion.div
                    initial={{ opacity: 0, y: -10 }}
                    animate={{ opacity: 1, y: 0 }}
                    className="banner banner-success px-4 py-3 flex items-center justify-between"
                >
                    <div className="flex items-center gap-2">
                        <BatteryCharging className="h-4 w-4 text-green-600 animate-pulse" />
                        <span className="font-medium text-green-800">Battery Top-Up Active</span>
                        <span className="opacity-70 text-green-700 text-xs ml-2">
                            — Charging {soc ?? '?'}% → {executorStatus.quick_action.params?.target_soc ?? 60}%
                        </span>
                    </div>
                    <button
                        onClick={async () => {
                            try {
                                await Api.executor.quickAction.clear()
                                await fetchAllData()
                                toast({ message: 'Top-Up Stopped', variant: 'success' })
                            } catch (e) {
                                console.error('Failed to stop top-up', e)
                                toast({ message: 'Failed to stop top-up', variant: 'error' })
                            }
                        }}
                        className="px-2 py-1 bg-green-600/20 hover:bg-green-600/30 text-green-800 rounded text-xs transition border border-green-600/20"
                    >
                        STOP TOP-UP
                    </button>
                </motion.div>
            )}

            {/* Row 1: Schedule Overview (24h / 48h) */}
            <motion.div initial={{ opacity: 0, y: 8 }} animate={{ opacity: 1, y: 0 }}>
                <ChartCard
                    useHistoryForToday={true}
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
                            isLoading={isRefreshing}
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
                        setComfortLevel={handleSetComfortLevel}
                        riskAppetite={riskAppetite}
                        setRiskAppetite={handleSetRiskAppetite}
                        vacationMode={vacationMode || vacationModeHA}
                        boostActive={waterBoostActive?.boost}
                        activeQuickAction={executorStatus?.quick_action}
                        currentSoc={soc ?? 0}
                        onBatteryTopUp={handleBatteryTopUp}
                        onStatusRefresh={fetchAllData}
                    />
                </motion.div>

                {/* Right Column: Quick Actions */}
                <motion.div className="h-full" initial={{ opacity: 0, y: 8 }} animate={{ opacity: 1, y: 0 }}>
                    <div className="flex h-full flex-col gap-6">
                        <Card className="flex-1 p-4 md:p-5">
                            <QuickActions
                                status={plannerStatus}
                                onRefresh={fetchAllData}
                            />
                        </Card>
                        <Card className="flex-1 p-4 md:p-5">
                            <div className="flex items-baseline justify-between mb-4">
                                <div className="text-sm font-medium text-text">Planner Automation</div>
                                <div className="flex items-center gap-2">
                                    <div className="flex items-center gap-2 text-[10px] text-muted">
                                        <span
                                            className={`inline-flex h-2 w-2 rounded-full ${automationConfig?.enable_scheduler
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
                                    className={`rounded-full p-1 transition ${isRefreshing ? 'bg-surface2 text-muted' : 'text-muted hover:text-accent'
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
                                <div className="flex justify-between pt-1 border-t border-line/30 mt-1">
                                    <span>Dashboard Sync:</span>
                                    <span>{lastRefresh ? lastRefresh.toLocaleTimeString() : '—'}</span>
                                </div>
                            </div>
                        </Card>
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
