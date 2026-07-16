/* eslint-disable @typescript-eslint/no-explicit-any */
import { useEffect, useState, useCallback, useRef } from 'react'
import Card from '../components/Card'
import ChartCard from '../components/ChartCard'
import { Flame, BatteryCharging } from 'lucide-react'
import { motion } from 'framer-motion'
import {
    Api,
    type PlannerSIndex,
    type ExecutorStatusResponse,
    type LearningStatusResponse,
    type ConfigResponse,
} from '../lib/api'
import type { ScheduleSlot } from '../lib/types'
import { isToday, isTomorrow } from '../lib/time'
import SmartAdvisor from '../components/SmartAdvisor'
import PowerFlowCard from '../components/PowerFlowCard'
import CommandBar from '../components/CommandBar'
import BatteryStrategyCard from '../components/BatteryStrategyCard'
import { GridDomain, ResourcesDomain } from '../components/CommandDomains'
import { useSocket, useSocketStatus } from '../lib/hooks'
import { useToast } from '../lib/useToast'

type PlannerMeta = {
    planned_at?: string
    planner_version?: string
    s_index?: PlannerSIndex
} | null

export default function Dashboard() {
    const [soc, setSoc] = useState<number | null>(null)
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
        evCharging: number | null
        waterHeating: number | null
    } | null>(null)
    const [systemFlags, setSystemFlags] = useState<{
        hasSolar: boolean
        hasBattery: boolean
        hasWaterHeater: boolean
        hasEvCharger: boolean
    }>({ hasSolar: true, hasBattery: true, hasWaterHeater: true, hasEvCharger: false })
    const [waterBoostActive, setWaterBoostActive] = useState<{
        boost: boolean
        expires_at?: string
    } | null>(null)

    const [plannerLocalMeta, setPlannerLocalMeta] = useState<PlannerMeta>(null)
    const [plannerMeta, setPlannerMeta] = useState<PlannerMeta>(null)
    const [batteryCapacity, setBatteryCapacity] = useState<number>(0)
    const [avgLoad, setAvgLoad] = useState<{ kw: number; dailyKwh: number } | null>(null)
    const [currentSlotTarget, setCurrentSlotTarget] = useState<number>(0)
    const [currentAction, setCurrentAction] = useState<string | undefined>(undefined)
    const [waterToday] = useState<{ kwh: number; source: string } | null>(null)
    const [comfortLevel, setComfortLevel] = useState<number>(0)
    const [vacationMode, setVacationMode] = useState<boolean>(false)
    const [vacationModeHA, setVacationModeHA] = useState<boolean>(false)
    const [vacationEntityId, setVacationEntityId] = useState<string>('')
    const [riskAppetite, setRiskAppetite] = useState<number>(1.0)
    const [livePower, setLivePower] = useState<{
        pv_kw?: number
        load_kw?: number
        battery_kw?: number
        grid_kw?: number
        water_kw?: number
        ev_kw?: number
        ev_plugged_in?: boolean
        ev_soc?: number
        ev_chargers?: Array<{ name: string; kw: number; soc: number | null; pluggedIn: boolean }>
    }>({})

    const [executorHealth, setExecutorHealth] = useState<import('../lib/api').ExecutorHealthResponse | null>(null)
    const [config, setConfig] = useState<ConfigResponse | null>(null)

    const [priceOutlook, setPriceOutlook] = useState<import('../lib/api').PriceOutlookResponse | undefined>(undefined)
    const [priceAdvice, setPriceAdvice] = useState<import('../lib/api').AdviceItem[]>([])
    const [learningStatus, setLearningStatus] = useState<LearningStatusResponse | null>(null)

    const { toast } = useToast()

    useSocket('live_metrics', (data: any) => {
        if (data.soc !== undefined) setSoc(data.soc)
        setLivePower((prev) => ({
            ...prev,
            pv_kw: data.pv_kw ?? prev.pv_kw,
            load_kw: data.load_kw ?? prev.load_kw,
            battery_kw: data.battery_kw ?? prev.battery_kw,
            grid_kw: data.grid_kw ?? prev.grid_kw,
            water_kw: data.water_kw ?? prev.water_kw,
            ev_kw: data.ev_kw ?? prev.ev_kw,
            ev_plugged_in: data.ev_plugged_in !== undefined ? data.ev_plugged_in : prev.ev_plugged_in,
            ev_soc: data.ev_soc !== undefined ? data.ev_soc : prev.ev_soc,
            ev_chargers: data.ev_chargers
                ? data.ev_chargers.map((ev: { name: string; kw: number; soc: number | null; plugged_in: boolean }) => ({
                      ...ev,
                      pluggedIn: ev.plugged_in,
                  }))
                : prev.ev_chargers,
        }))
    })

    useSocket('schedule_updated', (data: any) => {
        toast({
            message: 'Schedule updated',
            description: `${data.slot_count ?? 0} slots generated`,
            variant: 'success',
        })
        Promise.all([Api.schedule(), Api.scheduleTodayWithHistory()])
            .then(([scheduleData, historyData]) => {
                if (scheduleData.schedule) setLocalSchedule(scheduleData.schedule)
                if (scheduleData.meta) {
                    setPlannerLocalMeta({
                        planned_at: scheduleData.meta.planned_at as string | undefined,
                        planner_version: scheduleData.meta.planner_version as string | undefined,
                        s_index: scheduleData.meta.s_index as PlannerSIndex | undefined,
                    })
                }
                if (historyData.slots) setHistorySlots(historyData.slots)
            })
            .catch((err) => console.error('Failed to refresh after schedule update:', err))
    })

    useSocket('executor_status', (data: any) => {
        setExecutorStatus({
            shadow_mode: data.shadow_mode ?? false,
            paused: data.paused ?? null,
            quick_action: data.quick_action ?? null,
        })
    })

    useSocket('executor_error', (data: any) => {
        toast({
            message: `Executor Error: ${data.type}`,
            description: data.message,
            variant: 'error',
        })
    })

    useSocket('ha_entity_change', (data: any) => {
        if (data.entity_id === vacationEntityId) {
            setVacationModeHA(data.state === 'on')
        }
    })

    useEffect(() => {
        const handleConfigUpdate = async () => {
            try {
                const data = await Api.config()
                if (data) {
                    setConfig(data)
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
        try {
            const bundle = await Api.dashboardBundle()

            if (bundle.status) {
                const data = bundle.status
                if (data.soc_percent != null) setSoc(data.soc_percent)
                else if (data.current_soc?.value != null) setSoc(data.current_soc.value)

                setLivePower((prev) => ({
                    ...prev,
                    pv_kw: data.pv_power_kw ?? prev.pv_kw,
                    load_kw: data.load_power_kw ?? prev.load_kw,
                    battery_kw: data.battery_power_kw ?? prev.battery_kw,
                    grid_kw: data.grid_power_kw ?? prev.grid_kw,
                    ev_kw: data.ev_kw ?? prev.ev_kw,
                    ev_plugged_in: data.ev_plugged_in !== undefined ? data.ev_plugged_in : prev.ev_plugged_in,
                    ev_chargers: data.ev_chargers
                        ? data.ev_chargers.map(
                              (ev: { name: string; kw: number; soc: number | null; plugged_in: boolean }) => ({
                                  name: ev.name,
                                  kw: ev.kw,
                                  soc: ev.soc,
                                  pluggedIn: ev.plugged_in,
                              }),
                          )
                        : prev.ev_chargers,
                }))
            }

            if (bundle.config) {
                const data = bundle.config
                setConfig(data)
                const sIndex = (data as Record<string, unknown>).s_index as Record<string, unknown> | undefined
                if (typeof sIndex?.risk_appetite === 'number') setRiskAppetite(sIndex.risk_appetite)

                const systemConfig = data.system || {}
                setSystemFlags({
                    hasSolar: systemConfig.has_solar ?? true,
                    hasBattery: systemConfig.has_battery ?? true,
                    hasWaterHeater: systemConfig.has_water_heater ?? true,
                    hasEvCharger: systemConfig.has_ev_charger ?? false,
                })

                if (data.battery?.capacity_kwh != null) setBatteryCapacity(data.battery.capacity_kwh)
                else if (data.system?.battery?.capacity_kwh != null)
                    setBatteryCapacity(data.system.battery.capacity_kwh)

                if (data.automation) {
                    setAutomationConfig({
                        enable_scheduler: data.automation.enable_scheduler,
                        every_minutes: data.automation.schedule?.every_minutes ?? null,
                    })
                } else setAutomationConfig(null)

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
            }

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
                    let action = 'Hold'
                    if ((currentSlot.charge_kw || 0) > 0.1) action = 'Charge'
                    else if ((currentSlot.discharge_kw || 0) > 0.1) action = 'Discharge'
                    else if ((currentSlot.export_kwh || 0) > 0.1) action = 'Export'
                    setCurrentAction(action)
                }
            }

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

            if (bundle.water_boost) {
                setWaterBoostActive(bundle.water_boost)
            }

            try {
                const historyData = await Api.scheduleTodayWithHistory()
                if (historyData.slots) setHistorySlots(historyData.slots)
            } catch (historyErr) {
                console.warn('Failed to fetch history slots in critical path:', historyErr)
            }
        } catch (error) {
            console.error('Error fetching dashboard bundle:', error)
        }
    }, [])

    const fetchDeferredData = useCallback(async () => {
        try {
            const [
                haAverageData,
                todayStatsData,
                auroraData,
                historyData,
                executorHealthData,
                priceOutlookData,
                adviceData,
                learningStatusData,
            ] = await Promise.allSettled([
                Api.haAverage(),
                Api.energyToday(),
                Api.aurora.dashboard(),
                Api.scheduleTodayWithHistory(),
                Api.executor.health(),
                Api.priceForecast.outlook(),
                Api.getAdvice(),
                Api.learningStatus(),
            ])

            if (executorHealthData.status === 'fulfilled') {
                setExecutorHealth(executorHealthData.value)
            }

            if (priceOutlookData.status === 'fulfilled') {
                setPriceOutlook(priceOutlookData.value)
            }

            if (adviceData.status === 'fulfilled' && adviceData.value?.advice) {
                const adviceList = Array.isArray(adviceData.value.advice) ? adviceData.value.advice : []
                const filteredAdvice = adviceList.filter(
                    (item: import('../lib/api').AdviceItem) => item.category === 'price',
                )
                setPriceAdvice(filteredAdvice)
            }

            if (learningStatusData.status === 'fulfilled') {
                setLearningStatus(learningStatusData.value)
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
                    netCost: data.net_cost_sek ?? data.net_cost_kr ?? null,
                    evCharging: data.ev_charging_kwh ?? null,
                    waterHeating: data.water_heating_kwh ?? null,
                })
            }

            if (historyData.status === 'fulfilled') {
                setHistorySlots(historyData.value.slots ?? [])
                if (pvForecastTotal === 0 && historyData.value.slots) {
                    const todayStart = new Date()
                    todayStart.setHours(0, 0, 0, 0)
                    const tomorrowStart = new Date(todayStart)
                    tomorrowStart.setDate(tomorrowStart.getDate() + 1)
                    let dailyTotal = 0
                    historyData.value.slots.forEach((s) => {
                        const sTime = new Date(s.start_time)
                        if (sTime >= todayStart && sTime < tomorrowStart) {
                            dailyTotal += s.pv_forecast_kwh ?? 0
                        }
                    })
                    if (dailyTotal > 0) {
                        setTodayStats((prev) =>
                            prev ? { ...prev, pvForecast: parseFloat(dailyTotal.toFixed(1)) } : null,
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
        setTimeout(() => fetchDeferredData(), 100)
    }, [fetchCriticalData, fetchDeferredData])

    useEffect(() => {
        setPlannerMeta(plannerLocalMeta)
    }, [plannerLocalMeta])

    const pvPersonalization = learningStatus?.pv_personalization
    const pvPersonalized = (pvPersonalization?.weight ?? 0) > 0
    const pvSourceLabel = pvPersonalized ? 'Open-Meteo + tuned' : 'Open-Meteo baseline'

    const handleSetComfortLevel = async (l: number) => {
        setComfortLevel(l)
        await Api.configSave({ water_heating: { comfort_level: l } })
    }

    const handleSetRiskAppetite = async (l: number) => {
        setRiskAppetite(l)
        await Api.configSave({ s_index: { risk_appetite: l } })
    }

    useEffect(() => {
        fetchAllData()
    }, [fetchAllData])

    const socketConnected = useSocketStatus()
    const wasConnectedBefore = useRef(false)
    useEffect(() => {
        if (socketConnected === 'connected') {
            if (wasConnectedBefore.current) {
                // Reconnect after a drop (not the initial mount connect) — refetch.
                fetchAllData()
            }
            wasConnectedBefore.current = true
        }
    }, [socketConnected, fetchAllData])

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

    const todaySummary = (() => {
        if (!slotsOverride || slotsOverride.length === 0) return null
        const todayStart = new Date()
        todayStart.setHours(0, 0, 0, 0)
        const tomorrowStart = new Date(todayStart)
        tomorrowStart.setDate(tomorrowStart.getDate() + 1)
        const todaySlots = slotsOverride.filter((s) => {
            const t = new Date(s.start_time)
            return t >= todayStart && t < tomorrowStart
        })
        if (todaySlots.length === 0) return null

        interface Phase {
            action: string
            start: string
            end: string
            extra?: string
        }
        const phases: Phase[] = []
        const fmt = (iso: string) => iso.slice(11, 16)

        todaySlots.forEach((s) => {
            const start = fmt(s.start_time)
            const endTime = new Date(new Date(s.start_time).getTime() + 30 * 60 * 1000)
            const end = endTime.toISOString().slice(11, 16)
            if ((s.charge_kw || 0) > 0.1) {
                const price = s.import_price_sek_kwh ? `${s.import_price_sek_kwh.toFixed(2)} kr` : null
                phases.push({ action: 'Charge', start, end, extra: price ? price : undefined })
            } else if ((s.discharge_kw || 0) > 0.1) {
                const price = s.import_price_sek_kwh ? `${s.import_price_sek_kwh.toFixed(2)} kr` : null
                phases.push({ action: 'Discharge', start, end, extra: price ? price : undefined })
            } else if ((s.export_kwh || 0) > 0.1) {
                const price = s.import_price_sek_kwh ? `${s.import_price_sek_kwh.toFixed(2)} kr` : null
                phases.push({ action: 'Export', start, end, extra: price ? price : undefined })
            }
        })
        if (phases.length === 0) return null

        const merged: Phase[] = []
        phases.forEach((p) => {
            const last = merged[merged.length - 1]
            if (last && last.action === p.action) {
                last.end = p.end
                if (p.extra) last.extra = p.extra
            } else {
                merged.push({ ...p })
            }
        })
        return merged
            .map((p) => {
                let text = `${p.action} ${p.start}-${p.end}`
                if (p.extra) text += ` (${p.extra})`
                return text
            })
            .join(' → ')
    })()

    return (
        <main className="mx-auto max-w-[1400px] px-4 pb-24 pt-6 sm:px-6 lg:pt-8 space-y-4">
            {/* Banners */}
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
                        >
                            ✕
                        </button>
                    </div>
                </motion.div>
            )}

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

            {executorHealth?.has_error && (
                <motion.div
                    initial={{ opacity: 0, y: -10 }}
                    animate={{ opacity: 1, y: 0 }}
                    className="banner banner-error px-4 py-3 flex items-center justify-between"
                >
                    <div className="flex items-center gap-2">
                        <span>🚨</span>
                        <span className="font-medium">Executor Error: {executorHealth.last_run_status}</span>
                        <span className="opacity-70 text-xs">— {executorHealth.error}</span>
                    </div>
                    <div className="flex items-center gap-2 text-[10px] opacity-60">
                        {executorHealth.last_run_at && new Date(executorHealth.last_run_at).toLocaleTimeString()}
                    </div>
                </motion.div>
            )}

            {executorHealth?.warnings && executorHealth.warnings.length > 0 && (
                <div className="space-y-2">
                    {executorHealth.warnings.map((warning, idx) => (
                        <motion.div
                            key={`executor-warning-${idx}`}
                            initial={{ opacity: 0, y: -10 }}
                            animate={{ opacity: 1, y: 0 }}
                            className="banner banner-warning px-4 py-3 flex items-center gap-2"
                        >
                            <span>⚠️</span>
                            <span className="font-medium">{warning}</span>
                            <span className="opacity-70 text-xs">— Action skipped. Configure in Settings.</span>
                        </motion.div>
                    ))}
                </div>
            )}

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
                                — Expires at{' '}
                                {new Date(waterBoostActive.expires_at).toLocaleTimeString([], {
                                    hour: '2-digit',
                                    minute: '2-digit',
                                })}
                            </span>
                        )}
                    </div>
                    <button
                        onClick={async () => {
                            try {
                                await Api.waterBoost.cancel()
                                fetchAllData()
                                toast({ message: 'Boost Cancelled', variant: 'success' })
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
                            — Charging {soc ?? '?'}% →{' '}
                            {(executorStatus.quick_action.params?.target_soc as number) ?? 60}%
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

            {/* Row 1: Chart */}
            <motion.div initial={{ opacity: 0, y: 8 }} animate={{ opacity: 1, y: 0 }}>
                <ChartCard useHistoryForToday={true} refreshToken={chartRefreshToken} slotsOverride={slotsOverride} />
            </motion.div>

            {/* Row 2: Unified Command Bar */}
            <motion.div initial={{ opacity: 0, y: 8 }} animate={{ opacity: 1, y: 0 }}>
                <CommandBar
                    riskAppetite={riskAppetite}
                    comfortLevel={comfortLevel}
                    executorStatus={executorStatus}
                    automationConfig={automationConfig}
                    automationSaving={automationSaving}
                    schedulerStatus={schedulerStatus}
                    vacationMode={vacationMode}
                    vacationModeHA={vacationModeHA}
                    waterBoostActive={waterBoostActive}
                    soc={soc}
                    plannerMeta={plannerMeta}
                    onSetRiskAppetite={handleSetRiskAppetite}
                    onSetComfortLevel={handleSetComfortLevel}
                    onToggleScheduler={toggleAutomationScheduler}
                    onRefresh={fetchAllData}
                />
            </motion.div>

            {/* Row 3: Bento Grid */}
            <div className="grid grid-cols-1 lg:grid-cols-3 gap-6">
                {/* Cell 1: SmartAdvisor (row 1, col 1) */}
                <motion.div className="h-full" initial={{ opacity: 0, y: 8 }} animate={{ opacity: 1, y: 0 }}>
                    <SmartAdvisor todaySummary={todaySummary} priceAdvice={priceAdvice} />
                </motion.div>

                {/* Cell 2: PowerFlowCard (row 1, col 2) */}
                <motion.div className="h-full" initial={{ opacity: 0, y: 8 }} animate={{ opacity: 1, y: 0 }}>
                    <Card className="h-full flex flex-col overflow-hidden">
                        <div className="flex-1 flex items-center justify-center overflow-hidden">
                            <PowerFlowCard
                                systemConfig={config}
                                data={{
                                    solar: {
                                        kw: livePower.pv_kw ?? 0,
                                        todayKwh: todayStats?.pvProduction ?? undefined,
                                    },
                                    battery: { kw: livePower.battery_kw ?? 0, soc: soc ?? 50 },
                                    grid: {
                                        kw: livePower.grid_kw ?? 0,
                                        importKwh: todayStats?.gridImport ?? undefined,
                                        exportKwh: todayStats?.gridExport ?? undefined,
                                    },
                                    house: {
                                        kw: livePower.load_kw ?? 0,
                                        todayKwh: todayStats?.loadConsumption ?? undefined,
                                    },
                                    water: { kw: livePower.water_kw ?? 0, todayKwh: waterToday?.kwh },
                                    ev: { kw: livePower.ev_kw ?? 0 },
                                    evPluggedIn: livePower.ev_plugged_in,
                                    evSoc: livePower.ev_soc,
                                    evChargers: livePower.ev_chargers,
                                }}
                            />
                        </div>
                    </Card>
                </motion.div>

                {/* Cell 3: BatteryStrategyCard (rows 1-2, col 3) */}
                <motion.div
                    className="h-full lg:row-span-2"
                    initial={{ opacity: 0, y: 8 }}
                    animate={{ opacity: 1, y: 0 }}
                >
                    <BatteryStrategyCard
                        soc={soc}
                        socTarget={currentSlotTarget}
                        batteryCapacity={batteryCapacity}
                        plannerMeta={plannerMeta}
                        batteryCycles={todayStats?.batteryCycles ?? null}
                        priceOutlook={priceOutlook}
                        currentAction={currentAction}
                    />
                </motion.div>

                {/* Cell 4: GridDomain (row 2, col 1) */}
                <motion.div className="h-full" initial={{ opacity: 0, y: 8 }} animate={{ opacity: 1, y: 0 }}>
                    <GridDomain
                        netCost={todayStats?.netCost ?? null}
                        importKwh={todayStats?.gridImport ?? null}
                        exportKwh={todayStats?.gridExport ?? null}
                    />
                </motion.div>

                {/* Cell 5: ResourcesDomain (row 2, col 2) */}
                <motion.div className="h-full" initial={{ opacity: 0, y: 8 }} animate={{ opacity: 1, y: 0 }}>
                    <ResourcesDomain
                        pvActual={todayStats?.pvProduction ?? null}
                        pvForecast={todayStats?.pvForecast ?? null}
                        pvSourceLabel={pvSourceLabel}
                        pvSourceActive={pvPersonalized}
                        loadActual={todayStats?.loadConsumption ?? null}
                        loadAvg={avgLoad?.dailyKwh ?? null}
                        waterKwh={todayStats?.waterHeating ?? null}
                        evChargingKwh={todayStats?.evCharging ?? null}
                        hasSolar={systemFlags.hasSolar}
                        hasBattery={systemFlags.hasBattery}
                        hasWaterHeater={systemFlags.hasWaterHeater}
                        hasEvCharger={systemFlags.hasEvCharger}
                        batteryCapacity={batteryCapacity}
                        config={config}
                    />
                </motion.div>
            </div>
        </main>
    )
}
