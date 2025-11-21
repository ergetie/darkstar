import { useEffect, useState, useCallback, useRef } from 'react'
import Card from '../components/Card'
import ChartCard from '../components/ChartCard'
import QuickActions from '../components/QuickActions'
import Kpi from '../components/Kpi'
import { motion } from 'framer-motion'
import { Api, Sel } from '../lib/api'
import type { ScheduleSlot } from '../lib/types'
import type { DaySel } from '../lib/time'
import SmartAdvisor from '../components/SmartAdvisor'

type PlannerMeta = { plannedAt?: string; version?: string } | null

export default function Dashboard(){
    const [soc, setSoc] = useState<number | null>(null)
    const [horizon, setHorizon] = useState<{pvDays?: number; weatherDays?: number} | null>(null)
    const [plannerLocalMeta, setPlannerLocalMeta] = useState<PlannerMeta>(null)
    const [plannerDbMeta, setPlannerDbMeta] = useState<PlannerMeta>(null)
    const [plannerMeta, setPlannerMeta] = useState<PlannerMeta>(null)
    const [currentPlanSource, setCurrentPlanSource] = useState<'local' | 'server'>('local')
    const [batteryCapacity, setBatteryCapacity] = useState<number | null>(null)
    const [pvToday, setPvToday] = useState<number | null>(null)
    const [avgLoad, setAvgLoad] = useState<{kw?: number; dailyKwh?: number} | null>(null)
    const [currentSlotTarget, setCurrentSlotTarget] = useState<number | null>(null)
    const [waterToday, setWaterToday] = useState<{kwh?: number; source?: string} | null>(null)
    const [learningStatus, setLearningStatus] = useState<{enabled?: boolean; status?: string; samples?: number} | null>(null)
    const [exportGuard, setExportGuard] = useState<{enabled?: boolean; mode?: string} | null>(null)
    const [serverSchedule, setServerSchedule] = useState<ScheduleSlot[] | null>(null)
    const [serverScheduleLoading, setServerScheduleLoading] = useState(false)
    const [serverScheduleError, setServerScheduleError] = useState<string | null>(null)
    const [isRefreshing, setIsRefreshing] = useState(false)
    const [lastRefresh, setLastRefresh] = useState<Date | null>(null)
    const [chartRefreshToken, setChartRefreshToken] = useState(0)
    const [statusMessage, setStatusMessage] = useState<string | null>(null)
    const [autoRefresh, setAutoRefresh] = useState(true)
    const pollingIntervalRef = useRef<NodeJS.Timeout | null>(null)

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
        setStatusMessage('Refreshing…')
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
                learningData
            ] = await Promise.allSettled([
                Api.status(),
                Api.horizon(),
                Api.config(),
                Api.haAverage(),
                Api.schedule(),
                Api.haWaterToday(),
                Api.learningStatus()
            ])

            // Process status data
            if (statusData.status === 'fulfilled') {
                const data = statusData.value
                setSoc(Sel.socValue(data) ?? null)

                const local = data.local ?? {}
                const db = (data.db && 'planned_at' in data.db) ? (data.db as any) : null

                const nextLocalMeta: PlannerMeta =
                    local?.planned_at || local?.planner_version
                        ? { plannedAt: local.planned_at, version: local.planner_version }
                        : null
                const nextDbMeta: PlannerMeta =
                    db?.planned_at || db?.planner_version
                        ? { plannedAt: db.planned_at, version: db.planner_version }
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

                // Initialize auto-refresh from dashboard config if present
                if (typeof data.dashboard?.auto_refresh_enabled === 'boolean') {
                    setAutoRefresh(data.dashboard.auto_refresh_enabled)
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
                // Calculate PV today from schedule data
                const today = new Date().toISOString().split('T')[0]
                const todaySlots = data.schedule?.filter(slot => 
                    slot.start_time?.startsWith(today)
                ) || []
                const pvTotal = todaySlots.reduce((sum, slot) => 
                    sum + (slot.pv_forecast_kwh || 0), 0
                )
                setPvToday(pvTotal)
                
                // Get current slot target
                const now = new Date()
                const currentSlot = data.schedule?.find(slot => {
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

    const socDisplay = soc !== null ? `${soc.toFixed(1)}%` : '—'
    const pvDays = horizon?.pvDays ?? '—'
    const weatherDays = horizon?.weatherDays ?? '—'
    const planBadge = `${currentPlanSource} plan`
    const planMeta = plannerMeta?.plannedAt || plannerMeta?.version ? ` · ${plannerMeta?.plannedAt ?? ''} ${plannerMeta?.version ?? ''}`.trim() : ''



    const slotsOverride =
        currentPlanSource === 'server' && serverSchedule && serverSchedule.length > 0
            ? serverSchedule
            : undefined

    return (
        <main className="mx-auto max-w-7xl px-4 pb-24 pt-8 sm:px-6 lg:pt-12 space-y-10">
        {/* Row 1: Schedule Overview (24h / 48h) */}
        <motion.div initial={{opacity:0, y:8}} animate={{opacity:1,y:0}}>
        <ChartCard
            useHistoryForToday={currentPlanSource === 'local'}
            refreshToken={chartRefreshToken}
            slotsOverride={slotsOverride}
            range="48h"
            showDayToggle={true}
        />
        </motion.div>

        {/* Row 2: Advisor + System Status + Quick Actions */}
        <div className="grid gap-6 lg:grid-cols-3 items-stretch">
        <motion.div className="h-full" initial={{opacity:0, y:8}} animate={{opacity:1,y:0}}>
        <SmartAdvisor />
        </motion.div>
        <motion.div initial={{opacity:0, y:8}} animate={{opacity:1,y:0}}>
        <Card className="p-4 md:p-5">
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
                className={`rounded-pill px-2 py-1 text-[10px] font-medium transition ${
                    isRefreshing 
                        ? 'bg-surface border border-line/60 text-muted cursor-not-allowed' 
                        : 'bg-surface border border-line/60 text-muted hover:border-accent hover:text-accent'
                }`}
                title="Refresh data"
            >
                {isRefreshing ? '⟳' : '↻'}
            </button>
            <button
                onClick={() => setAutoRefresh(!autoRefresh)}
                className={`rounded-pill px-2 py-1 text-[10px] font-medium transition ${
                    autoRefresh 
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
        <Kpi label="Current SoC" value={socDisplay} hint={currentSlotTarget !== null ? `target ${currentSlotTarget.toFixed(0)}%` : 'target —%'} />
        <Kpi label="Battery Cap" value={batteryCapacity !== null ? `${batteryCapacity.toFixed(1)} kWh` : '— kWh'} />
        <Kpi label="PV Today" value={pvToday !== null ? `${pvToday.toFixed(1)} kWh` : '— kWh'} hint={`PV ${pvDays}d · Weather ${weatherDays}d`} />
        <Kpi label="Avg Load" value={avgLoad?.kw !== undefined ? `${avgLoad.kw.toFixed(1)} kW` : '— kW'} hint={avgLoad?.dailyKwh !== undefined ? `HA ${avgLoad.dailyKwh.toFixed(1)} kWh/day` : ''} />
        </div>
        </Card>
        </motion.div>
        <motion.div initial={{opacity:0, y:8}} animate={{opacity:1,y:0}}>
        <Card className="p-4 md:p-5">
        <div className="text-sm text-muted mb-3">Quick Actions</div>
        <QuickActions
            onDataRefresh={fetchAllData}
            onPlanSourceChange={handlePlanSourceChange}
            onServerScheduleLoaded={handleServerScheduleLoaded}
        />
        </Card>
        </motion.div>
        </div>

        {/* Row 3: Context Cards */}
        <div className="grid grid-cols-1 gap-6 lg:grid-cols-3">
        <Card className="p-5">
        <div className="text-sm text-muted mb-3">Water heater</div>
        <div className="flex items-center justify-between">
        <div className="text-2xl">Eco mode</div>
        <div className="rounded-pill bg-surface2 border border-line/60 px-3 py-1 text-muted text-xs">
            today {waterToday?.kwh !== undefined ? `${waterToday.kwh.toFixed(1)} kWh` : '— kWh'}
        </div>
        </div>
        </Card>
        <Card className="p-5">
        <div className="text-sm text-muted mb-3">Export guard</div>
        <div className="text-2xl capitalize">
            {exportGuard?.enabled ? (exportGuard?.mode || 'passive') : 'disabled'}
        </div>
        </Card>
        <Card className="p-5">
        <div className="text-sm text-muted mb-3">Learning</div>
        <div className="text-2xl capitalize">
            {learningStatus?.enabled ? (learningStatus?.status || 'ready') : 'disabled'}
        </div>
        </Card>
        </div>
        </main>
    )
}
