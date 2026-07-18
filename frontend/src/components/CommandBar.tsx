/* eslint-disable @typescript-eslint/no-explicit-any */
import { useState, useEffect } from 'react'
import { Play, Pause, Loader2, Rocket, Flame, BatteryCharging, ChevronLeft, ChevronRight, Palmtree } from 'lucide-react'
import Card from './Card'
import { Api, type ExecutorStatusResponse, type PlannerSIndex } from '../lib/api'
import { useSocket } from '../lib/hooks'
import { useToast } from '../lib/useToast'

type PlannerMeta = {
    planned_at?: string
    planner_version?: string
    s_index?: PlannerSIndex
} | null

const TOP_UP_SOC_OPTIONS = [30, 50, 80, 100]
const BOOST_MINUTES_OPTIONS = [30, 60, 120]
const VACATION_DAYS_OPTIONS = [1, 3, 7, 14, 30]

interface CommandBarProps {
    riskAppetite: number
    comfortLevel: number
    executorStatus: {
        shadow_mode?: boolean
        paused?: { paused_at?: string; paused_minutes?: number } | null
        quick_action?: ExecutorStatusResponse['quick_action']
    } | null
    automationConfig: {
        enable_scheduler?: boolean
        every_minutes?: number | null
    } | null
    automationSaving: boolean
    schedulerStatus: {
        last_run_at?: string | null
        last_run_status?: string | null
        next_run_at?: string | null
    } | null
    vacationMode: boolean
    vacationModeHA: boolean
    waterBoostActive: {
        boost: boolean
        expires_at?: string
        remaining_seconds?: number
    } | null
    soc: number | null
    plannerMeta: PlannerMeta
    onSetRiskAppetite: (level: number) => void
    onSetComfortLevel: (level: number) => void
    onToggleScheduler: () => void
    onRefresh: () => void
}

type PlannerProgress = { phase: string; elapsed_ms: number }

function formatLocalIso(d: Date | null): string {
    if (!d) return '—'
    const year = d.getFullYear()
    const month = String(d.getMonth() + 1).padStart(2, '0')
    const day = String(d.getDate()).padStart(2, '0')
    const hours = String(d.getHours()).padStart(2, '0')
    const minutes = String(d.getMinutes()).padStart(2, '0')
    return `${year}-${month}-${day} ${hours}:${minutes}`
}

export default function CommandBar({
    riskAppetite,
    comfortLevel,
    executorStatus,
    automationConfig,
    automationSaving,
    schedulerStatus,
    vacationMode,
    vacationModeHA,
    waterBoostActive,
    plannerMeta,
    onSetRiskAppetite,
    onSetComfortLevel,
    onToggleScheduler,
    onRefresh,
}: CommandBarProps) {
    const { toast } = useToast()

    const [plannerProgress, setPlannerProgress] = useState<PlannerProgress | null>(null)
    const [quickActionLoading, setQuickActionLoading] = useState<string | null>(null)
    const [vacationDaysIdx, setVacationDaysIdx] = useState(1)
    const [boostMinutesIdx, setBoostMinutesIdx] = useState(1)
    const [topUpSocIdx, setTopUpSocIdx] = useState(1)
    const [loadingVacation, setLoadingVacation] = useState(false)
    const [loadingBoost, setLoadingBoost] = useState(false)
    const [now, setNow] = useState(() => Date.now())

    useEffect(() => {
        if (!waterBoostActive?.boost || !waterBoostActive.expires_at) return
        const id = setInterval(() => setNow(Date.now()), 1000)
        return () => clearInterval(id)
    }, [waterBoostActive?.boost, waterBoostActive?.expires_at])

    useSocket('planner_progress', (data: any) => {
        if (data.phase === 'failed') {
            setPlannerProgress(data)
            setTimeout(() => setPlannerProgress(null), 3000)
        } else {
            setPlannerProgress(data)
        }
    })

    useSocket('schedule_updated', () => {
        setPlannerProgress({ phase: 'complete', elapsed_ms: 0 })
        setTimeout(() => setPlannerProgress(null), 2000)
    })

    useSocket('water_boost_updated', () => {
        onRefresh()
    })

    const handleRunPlanner = async () => {
        setPlannerProgress({ phase: 'starting', elapsed_ms: 0 })
        try {
            await Api.runPlanner()
            await Api.executor.run()
        } catch (err) {
            toast({ message: err instanceof Error ? err.message : 'Failed', variant: 'error' })
            setPlannerProgress(null)
        }
    }

    const handleTogglePause = async () => {
        setQuickActionLoading('pause')
        try {
            if (executorStatus?.paused) {
                await Api.executor.resume()
                toast({ message: 'Executor resumed', variant: 'success' })
                onRefresh()
            } else {
                await Api.executor.pause()
                toast({ message: 'Executor paused', variant: 'success' })
                onRefresh()
            }
        } catch (err) {
            toast({ message: err instanceof Error ? err.message : 'Failed', variant: 'error' })
        } finally {
            setQuickActionLoading(null)
        }
    }

    const handleToggleTopUp = async () => {
        try {
            const activeQA = executorStatus?.quick_action
            if (activeQA?.type === 'force_charge') {
                await Api.executor.quickAction.clear()
                onRefresh()
                toast({ message: 'Top-Up Stopped', variant: 'success' })
            } else {
                const target = TOP_UP_SOC_OPTIONS[topUpSocIdx]
                await Api.executor.quickAction.set('force_charge', 60, { target_soc: target })
                onRefresh()
                toast({ message: `Top-Up to ${target}% started`, variant: 'success' })
            }
        } catch (e) {
            console.error('Top Up/Stop failed', e)
            toast({ message: 'Action failed', variant: 'error' })
        }
    }

    const handleToggleBoost = async () => {
        if (loadingBoost) return
        setLoadingBoost(true)
        try {
            if (waterBoostActive?.boost) {
                await Api.waterBoost.cancel()
                toast({ message: 'Water Boost Cancelled', variant: 'success' })
            } else {
                const duration = BOOST_MINUTES_OPTIONS[boostMinutesIdx]
                await Api.waterBoost.start(duration)
                toast({ message: `Water Boost Started (${duration}m)`, variant: 'success' })
            }
            onRefresh()
        } catch (e) {
            console.error('Failed to toggle boost', e)
            toast({ message: 'Action Failed', variant: 'error' })
        } finally {
            setLoadingBoost(false)
        }
    }

    const handleToggleVacation = async () => {
        setLoadingVacation(true)
        try {
            const vacationActive = vacationMode || vacationModeHA
            if (vacationActive) {
                await Api.configSave({ water_heating: { vacation_mode: { enabled: false, end_date: null } } })
                toast({ message: 'Vacation Mode Off', variant: 'success' })
            } else {
                const days = VACATION_DAYS_OPTIONS[vacationDaysIdx]
                const endDate = new Date()
                endDate.setDate(endDate.getDate() + days)
                const endDateStr = endDate.toISOString().split('T')[0]
                await Api.configSave({ water_heating: { vacation_mode: { enabled: true, end_date: endDateStr } } })
                toast({ message: `Vacation Active until ${endDateStr}`, variant: 'success' })
            }
            window.dispatchEvent(new Event('config-updated'))
            onRefresh()
        } catch {
            toast({ message: 'Vacation toggle failed', variant: 'error' })
        } finally {
            setLoadingVacation(false)
        }
    }

    const isPaused = executorStatus?.paused != null
    const isPlanning = plannerProgress !== null
    const isTopUpActive = executorStatus?.quick_action?.type === 'force_charge'
    const isBoostActive = waterBoostActive?.boost ?? false
    const isVacationActive = vacationMode || vacationModeHA

    const boostCountdown = (() => {
        if (!isBoostActive || !waterBoostActive?.expires_at) return null
        const rem = Math.max(0, Math.floor((new Date(waterBoostActive.expires_at).getTime() - now) / 1000))
        return `${Math.floor(rem / 60)}:${String(rem % 60).padStart(2, '0')}`
    })()

    const lastRunIso = schedulerStatus?.last_run_at || plannerMeta?.planned_at
    const lastRunDate = lastRunIso ? new Date(lastRunIso) : null
    const everyMinutes =
        automationConfig?.every_minutes && automationConfig.every_minutes > 0 ? automationConfig.every_minutes : null
    let nextRunDate: Date | null = null
    if (schedulerStatus?.next_run_at) {
        nextRunDate = new Date(schedulerStatus.next_run_at)
    } else if (automationConfig?.enable_scheduler && lastRunDate && everyMinutes) {
        nextRunDate = new Date(lastRunDate.getTime() + everyMinutes * 60 * 1000)
    }

    let planBadge = 'Local Plan'
    if (plannerMeta?.planned_at) {
        const planned = new Date(plannerMeta.planned_at)
        const timeStr = planned.toLocaleTimeString([], { hour: '2-digit', minute: '2-digit' })
        planBadge = `Plan: ${timeStr}`
    }

    const riskLabel =
        ({ 1: 'Safety', 2: 'Conservative', 3: 'Neutral', 4: 'Aggressive', 5: 'Gambler' } as Record<number, string>)[
            riskAppetite
        ] || 'Neutral'

    const comfortLabel =
        ({ 1: 'Economy', 2: 'Balanced', 3: 'Neutral', 4: 'Priority', 5: 'Maximum' } as Record<number, string>)[
            comfortLevel
        ] || 'Unknown'

    const riskPillColorMap: Record<number, string> = {
        1: 'bg-good text-[#100f0e] border-good',
        2: 'bg-night text-[#100f0e] border-night',
        3: 'bg-water text-[#100f0e] border-water',
        4: 'bg-warn text-[#100f0e] border-warn',
        5: 'bg-ai text-[#100f0e] border-ai',
    }
    const riskPills = (
        <div className="flex items-center gap-1.5" title={`Risk Appetite: ${riskLabel}`}>
            <span className="text-[10px] text-muted whitespace-nowrap">Risk</span>
            <div className="flex gap-0.5 h-5">
                {[1, 2, 3, 4, 5].map((level) => {
                    const isActive = riskAppetite === level
                    return (
                        <button
                            key={level}
                            onClick={() => onSetRiskAppetite(level)}
                            className={`w-4 rounded-sm text-[9px] font-medium transition border ${
                                isActive
                                    ? `${riskPillColorMap[level]} ring-1 ring-inset ring-white/5`
                                    : 'bg-surface2/50 text-muted hover:bg-surface2 border-transparent'
                            }`}
                        >
                            {level}
                        </button>
                    )
                })}
            </div>
        </div>
    )

    const waterPillColorMap: Record<number, string> = {
        1: 'bg-good text-[#100f0e] border-good',
        2: 'bg-night text-[#100f0e] border-night',
        3: 'bg-water text-[#100f0e] border-water',
        4: 'bg-warn text-[#100f0e] border-warn',
        5: 'bg-bad text-[#100f0e] border-bad',
    }
    const waterPills = (
        <div className="flex items-center gap-1.5" title={`Water Comfort: ${comfortLabel}`}>
            <span className="text-[10px] text-muted whitespace-nowrap">Water</span>
            <div className="flex gap-0.5 h-5">
                {[1, 2, 3, 4, 5].map((level) => {
                    const isActive = comfortLevel === level
                    return (
                        <button
                            key={level}
                            onClick={() => onSetComfortLevel(level)}
                            className={`w-4 rounded-sm text-[9px] font-medium transition border ${
                                isActive
                                    ? `${waterPillColorMap[level]} ring-1 ring-inset ring-white/5`
                                    : 'bg-surface2/50 text-muted hover:bg-surface2 border-transparent'
                            }`}
                        >
                            {level}
                        </button>
                    )
                })}
            </div>
        </div>
    )

    const overrideButtons = (
        <div className="flex items-center gap-2">
            {/* Top Up */}
            <div
                className={`flex items-center rounded px-1.5 py-1 text-[10px] font-semibold transition-all ${
                    isTopUpActive
                        ? 'bg-good/40 border border-good/60 shadow-[0_0_10px_rgba(34,197,94,0.4)]'
                        : 'bg-surface2/50 border border-line/50 hover:border-accent/40'
                }`}
            >
                {!isTopUpActive && (
                    <div className="flex items-center mr-1">
                        <button
                            onClick={() => setTopUpSocIdx((i) => Math.max(0, i - 1))}
                            className="px-0.5 hover:text-accent"
                            disabled={topUpSocIdx === 0}
                        >
                            <ChevronLeft className="h-2.5 w-2.5" />
                        </button>
                        <span className="text-muted text-[9px] min-w-[16px] text-center">
                            {TOP_UP_SOC_OPTIONS[topUpSocIdx]}%
                        </span>
                        <button
                            onClick={() => setTopUpSocIdx((i) => Math.min(TOP_UP_SOC_OPTIONS.length - 1, i + 1))}
                            className="px-0.5 hover:text-accent"
                            disabled={topUpSocIdx === TOP_UP_SOC_OPTIONS.length - 1}
                        >
                            <ChevronRight className="h-2.5 w-2.5" />
                        </button>
                    </div>
                )}
                <button
                    onClick={handleToggleTopUp}
                    className={`flex items-center gap-1 ${isTopUpActive ? 'text-white' : 'text-good'}`}
                >
                    <BatteryCharging className={`h-3 w-3 ${isTopUpActive ? 'animate-pulse' : ''}`} />
                    <span>{isTopUpActive ? 'STOP' : 'Top Up'}</span>
                </button>
            </div>

            {/* Boost */}
            <div
                className={`flex items-center rounded px-1.5 py-1 text-[10px] font-semibold transition-all ${
                    isBoostActive
                        ? 'bg-water/40 border border-water/60 shadow-[0_0_10px_rgba(var(--color-water),0.4)]'
                        : 'bg-surface2/50 border border-line/50 hover:border-accent/40'
                }`}
            >
                {!isBoostActive && (
                    <div className="flex items-center mr-1">
                        <button
                            onClick={() => setBoostMinutesIdx((i) => Math.max(0, i - 1))}
                            className="px-0.5 hover:text-accent"
                            disabled={boostMinutesIdx === 0}
                        >
                            <ChevronLeft className="h-2.5 w-2.5" />
                        </button>
                        <span className="text-muted text-[9px] min-w-[16px] text-center">
                            {BOOST_MINUTES_OPTIONS[boostMinutesIdx] === 120
                                ? '2h'
                                : BOOST_MINUTES_OPTIONS[boostMinutesIdx] === 60
                                  ? '1h'
                                  : '30m'}
                        </span>
                        <button
                            onClick={() => setBoostMinutesIdx((i) => Math.min(BOOST_MINUTES_OPTIONS.length - 1, i + 1))}
                            className="px-0.5 hover:text-accent"
                            disabled={boostMinutesIdx === BOOST_MINUTES_OPTIONS.length - 1}
                        >
                            <ChevronRight className="h-2.5 w-2.5" />
                        </button>
                    </div>
                )}
                <button
                    onClick={handleToggleBoost}
                    disabled={loadingBoost}
                    className={`flex items-center gap-1 ${isBoostActive ? 'text-white' : 'text-water'}`}
                >
                    <Flame className={`h-3 w-3 ${isBoostActive ? 'animate-pulse' : ''}`} />
                    <span>{isBoostActive ? 'STOP' : 'Boost'}</span>
                    {boostCountdown && <span className="text-water/80">{boostCountdown}</span>}
                </button>
            </div>

            {/* Vacation */}
            <div
                className={`flex items-center rounded px-1.5 py-1 text-[10px] font-semibold transition-all ${
                    isVacationActive
                        ? 'bg-amber-500/30 border border-amber-500/50 shadow-[0_0_10px_rgba(245,158,11,0.3)]'
                        : 'bg-surface2/50 border border-line/50 hover:border-accent/40'
                }`}
            >
                {!isVacationActive && (
                    <div className="flex items-center mr-1">
                        <button
                            onClick={() => setVacationDaysIdx((i) => Math.max(0, i - 1))}
                            className="px-0.5 hover:text-accent"
                            disabled={vacationDaysIdx === 0}
                        >
                            <ChevronLeft className="h-2.5 w-2.5" />
                        </button>
                        <span className="text-muted text-[9px] min-w-[16px] text-center">
                            {VACATION_DAYS_OPTIONS[vacationDaysIdx]}d
                        </span>
                        <button
                            onClick={() => setVacationDaysIdx((i) => Math.min(VACATION_DAYS_OPTIONS.length - 1, i + 1))}
                            className="px-0.5 hover:text-accent"
                            disabled={vacationDaysIdx === VACATION_DAYS_OPTIONS.length - 1}
                        >
                            <ChevronRight className="h-2.5 w-2.5" />
                        </button>
                    </div>
                )}
                <button
                    onClick={handleToggleVacation}
                    disabled={loadingVacation}
                    className={`flex items-center gap-1 ${isVacationActive ? 'text-amber-100' : 'text-amber-400/80'}`}
                >
                    <Palmtree className="h-3 w-3" />
                    <span>{isVacationActive ? 'ON' : 'Vacay'}</span>
                </button>
            </div>
        </div>
    )

    return (
        <Card className="px-4 py-2 border-accent/20 bg-surface/80 backdrop-blur-md">
            <div className="flex flex-wrap items-center justify-between gap-4">
                {/* Left Group: Execution Controls */}
                <div className="flex items-center gap-3">
                    <div className="flex items-center gap-2">
                        <button
                            onClick={handleRunPlanner}
                            disabled={isPlanning}
                            className={`relative overflow-hidden flex items-center justify-center h-8 w-10 rounded-lg transition ${
                                isPlanning
                                    ? 'bg-surface border border-accent/50 text-accent cursor-wait'
                                    : 'bg-accent hover:bg-accent2 text-[#100f0e]'
                            }`}
                            title="Run Planner"
                        >
                            {isPlanning && plannerProgress?.phase !== 'complete' ? (
                                <Loader2 className="h-4 w-4 animate-spin" />
                            ) : (
                                <Rocket className="h-4 w-4" />
                            )}
                            {isPlanning && (
                                <div
                                    className="absolute bottom-0 left-0 h-0.5 bg-accent/40 pointer-events-none transition-all duration-500 ease-linear"
                                    style={{ width: plannerProgress?.phase === 'complete' ? '100%' : '30%' }}
                                />
                            )}
                        </button>
                        <button
                            onClick={handleTogglePause}
                            disabled={quickActionLoading === 'pause'}
                            className={`flex items-center justify-center h-8 w-10 rounded-lg transition ${
                                isPaused
                                    ? 'bg-bad hover:bg-bad/80 text-white ring-2 ring-bad shadow-md'
                                    : 'bg-good hover:bg-good/80 text-white'
                            } ${quickActionLoading === 'pause' ? 'opacity-60 cursor-wait' : ''}`}
                            title={isPaused ? 'Resume execution' : 'Pause execution'}
                        >
                            {isPaused ? <Play className="h-4 w-4" /> : <Pause className="h-4 w-4" />}
                        </button>
                    </div>

                    <div className="h-6 w-px bg-line/40 hidden sm:block" />

                    <div className="flex items-center gap-2">
                        <span
                            className={`h-2 w-2 rounded-full ${automationConfig?.enable_scheduler ? 'bg-good' : 'bg-muted'}`}
                        />
                        <button
                            onClick={onToggleScheduler}
                            disabled={automationSaving}
                            className="text-[10px] font-medium text-text hover:text-accent disabled:opacity-50"
                        >
                            Auto: {automationConfig?.enable_scheduler ? 'ON' : 'OFF'}
                        </button>
                    </div>
                </div>

                {/* Center Group: Parameters & Overrides */}
                <div className="flex flex-wrap items-center gap-4">
                    {riskPills}
                    {waterPills}
                    <div className="h-6 w-px bg-line/40 hidden md:block" />
                    {overrideButtons}
                </div>

                {/* Right Group: Status */}
                <div className="flex items-center">
                    <div
                        className="flex items-center gap-1.5 text-[10px] bg-surface2/40 px-2 py-1 rounded text-text"
                        title={`Last run: ${formatLocalIso(lastRunDate)}\nNext run: ${automationConfig?.enable_scheduler ? formatLocalIso(nextRunDate) : '—'}`}
                    >
                        <span className="text-good">✅</span>
                        <span>{planBadge}</span>
                    </div>
                </div>
            </div>
        </Card>
    )
}
