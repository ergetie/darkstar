import { useEffect, useState, useCallback, useRef } from 'react'
import { Rocket, Pause, Play, Palmtree, Flame, ChevronLeft, ChevronRight } from 'lucide-react'
import { Api } from '../lib/api'
import type { ScheduleSlot } from '../lib/types'

interface QuickActionsProps {
    onDataRefresh?: () => void
    onPlanSourceChange?: (source: 'local' | 'server') => void
    onServerScheduleLoaded?: (schedule: ScheduleSlot[]) => void
    onVacationModeChange?: (enabled: boolean) => void
}

type PlannerPhase = 'idle' | 'planning' | 'executing' | 'done'

const VACATION_DAYS_OPTIONS = [3, 7, 14, 21, 28]
const BOOST_MINUTES_OPTIONS = [30, 60, 120]

export default function QuickActions({ onDataRefresh, onPlanSourceChange, onVacationModeChange }: QuickActionsProps) {
    // Planner state
    const [plannerPhase, setPlannerPhase] = useState<PlannerPhase>('idle')

    // Executor pause state
    const [isPaused, setIsPaused] = useState(false)
    const [pausedMinutes, setPausedMinutes] = useState<number | null>(null)

    // Vacation state
    const [vacationDaysIndex, setVacationDaysIndex] = useState(1) // Default to 7 days
    const [vacationActive, setVacationActive] = useState(false)
    const [vacationEndDate, setVacationEndDate] = useState<string | null>(null)

    // Water boost state - use local countdown for smooth updates
    const [boostMinutesIndex, setBoostMinutesIndex] = useState(1) // Default to 60 min
    const [boostActive, setBoostActive] = useState(false)
    const [boostExpiresAt, setBoostExpiresAt] = useState<Date | null>(null)
    const [boostSecondsRemaining, setBoostSecondsRemaining] = useState<number>(0)

    // Feedback
    const [feedback, setFeedback] = useState<{ type: 'success' | 'error'; message: string } | null>(null)
    const [loading, setLoading] = useState<string | null>(null)

    // Refs for cleanup
    const countdownRef = useRef<ReturnType<typeof setInterval> | null>(null)

    // Fetch initial state (called once on mount and every 60s for sync)
    const fetchStatus = useCallback(async () => {
        try {
            const [execStatus, waterStatus, configData] = await Promise.all([
                Api.executor.status(),
                Api.waterBoost.status(),
                Api.config(),
            ])

            // Executor pause status
            if (execStatus.paused) {
                setIsPaused(true)
                setPausedMinutes(execStatus.paused.paused_minutes || null)
            } else {
                setIsPaused(false)
                setPausedMinutes(null)
            }

            // Water boost status - sync with server
            if (waterStatus.water_boost) {
                const expires = new Date(waterStatus.water_boost.expires_at)
                setBoostActive(true)
                setBoostExpiresAt(expires)
                // Calculate remaining seconds immediately
                const now = new Date()
                const remaining = Math.max(0, Math.floor((expires.getTime() - now.getTime()) / 1000))
                setBoostSecondsRemaining(remaining)
            } else {
                setBoostActive(false)
                setBoostExpiresAt(null)
                setBoostSecondsRemaining(0)
            }

            // Vacation mode from config
            const vacationCfg = configData.water_heating?.vacation_mode
            if (vacationCfg?.enabled) {
                setVacationActive(true)
                setVacationEndDate(vacationCfg.end_date || null)
            } else {
                setVacationActive(false)
                setVacationEndDate(null)
            }
        } catch (err) {
            console.error('Failed to fetch quick action status:', err)
        }
    }, [])

    // Initial fetch and periodic sync (every 60 seconds - not aggressive)
    useEffect(() => {
        fetchStatus()
        const interval = setInterval(fetchStatus, 60000) // Sync every 60 seconds
        return () => clearInterval(interval)
    }, [fetchStatus])

    // Local countdown timer for smooth updates (only when boost is active)
    useEffect(() => {
        // Clear any existing interval
        if (countdownRef.current) {
            clearInterval(countdownRef.current)
            countdownRef.current = null
        }

        if (!boostActive || !boostExpiresAt) return

        // Update countdown every second locally
        countdownRef.current = setInterval(() => {
            const now = new Date()
            const remaining = Math.floor((boostExpiresAt.getTime() - now.getTime()) / 1000)

            if (remaining <= 0) {
                // Boost expired
                setBoostActive(false)
                setBoostExpiresAt(null)
                setBoostSecondsRemaining(0)
                if (countdownRef.current) {
                    clearInterval(countdownRef.current)
                    countdownRef.current = null
                }
            } else {
                setBoostSecondsRemaining(remaining)
            }
        }, 1000)

        return () => {
            if (countdownRef.current) {
                clearInterval(countdownRef.current)
                countdownRef.current = null
            }
        }
    }, [boostActive, boostExpiresAt])

    // --- Handlers ---

    const handleRunPlanner = async () => {
        setPlannerPhase('planning')
        setFeedback(null)
        try {
            await Api.runPlanner()
            setPlannerPhase('executing')
            await Api.executor.run()
            setPlannerPhase('done')

            if (onPlanSourceChange) onPlanSourceChange('local')
            if (onDataRefresh) setTimeout(onDataRefresh, 500)

            setTimeout(() => setPlannerPhase('idle'), 2000)
        } catch (err) {
            setFeedback({ type: 'error', message: err instanceof Error ? err.message : 'Failed' })
            setPlannerPhase('idle')
        }
    }

    const handleTogglePause = async () => {
        setFeedback(null)
        setLoading('pause')
        try {
            if (isPaused) {
                await Api.executor.resume()
                setIsPaused(false)
                setPausedMinutes(null)
                setFeedback({ type: 'success', message: 'Executor resumed' })
            } else {
                await Api.executor.pause()
                setIsPaused(true)
                setFeedback({ type: 'success', message: 'Executor paused - idle mode' })
            }
            setTimeout(() => setFeedback(null), 3000)
        } catch (err) {
            setFeedback({ type: 'error', message: err instanceof Error ? err.message : 'Failed' })
        } finally {
            setLoading(null)
        }
    }

    const handleToggleVacation = async () => {
        setFeedback(null)
        setLoading('vacation')
        try {
            if (vacationActive) {
                // Deactivate
                await Api.configSave({ water_heating: { vacation_mode: { enabled: false, end_date: null } } })
                setVacationActive(false)
                setVacationEndDate(null)
                setFeedback({ type: 'success', message: 'Vacation mode disabled' })
            } else {
                // Activate with selected days
                const days = VACATION_DAYS_OPTIONS[vacationDaysIndex]
                const endDate = new Date()
                endDate.setDate(endDate.getDate() + days)
                const endDateStr = endDate.toISOString().split('T')[0]

                await Api.configSave({ water_heating: { vacation_mode: { enabled: true, end_date: endDateStr } } })
                setVacationActive(true)
                setVacationEndDate(endDateStr)
                setFeedback({ type: 'success', message: `Vacation mode active until ${endDateStr}` })
            }

            // Notify Dashboard to update banner instantly
            window.dispatchEvent(new Event('config-updated'))
            onVacationModeChange?.(!vacationActive)

            setTimeout(() => setFeedback(null), 3000)
        } catch (err) {
            setFeedback({ type: 'error', message: err instanceof Error ? err.message : 'Failed' })
        } finally {
            setLoading(null)
        }
    }

    const handleToggleBoost = async () => {
        setFeedback(null)
        setLoading('boost')
        try {
            if (boostActive) {
                // Cancel boost
                const result = await Api.waterBoost.cancel()
                if (result.success) {
                    setBoostActive(false)
                    setBoostExpiresAt(null)
                    setBoostSecondsRemaining(0)
                    setFeedback({ type: 'success', message: 'Water boost cancelled' })
                }
            } else {
                // Start boost
                const minutes = BOOST_MINUTES_OPTIONS[boostMinutesIndex]
                const result = await Api.waterBoost.start(minutes)
                if (result.success && result.expires_at) {
                    const expires = new Date(result.expires_at)
                    setBoostActive(true)
                    setBoostExpiresAt(expires)
                    setBoostSecondsRemaining(minutes * 60)
                    setFeedback({ type: 'success', message: `Water boost started (${minutes}min)` })
                }
            }
            setTimeout(() => setFeedback(null), 3000)
        } catch (err) {
            setFeedback({ type: 'error', message: err instanceof Error ? err.message : 'Failed' })
        } finally {
            setLoading(null)
        }
    }

    // --- Render helpers ---

    const getPlannerButtonText = () => {
        switch (plannerPhase) {
            case 'planning': return 'Planning...'
            case 'executing': return 'Executing...'
            case 'done': return 'Done ✓'
            default: return 'Run Planner'
        }
    }

    const formatSecondsRemaining = (secs: number) => {
        const m = Math.floor(secs / 60)
        const s = secs % 60
        return `${m}:${s.toString().padStart(2, '0')}`
    }

    return (
        <div className="relative">
            {/* Buttons grid */}
            <div className="grid grid-cols-2 gap-3">
                {/* 1. Run Planner */}
                <button
                    className={`flex items-center justify-center gap-2 rounded-xl px-3 py-2.5 text-[11px] font-semibold transition btn-glow-primary
                        ${plannerPhase !== 'idle'
                            ? 'bg-accent text-[#100f0e] cursor-wait'
                            : 'bg-accent hover:bg-accent2 text-[#100f0e]'
                        }`}
                    onClick={handleRunPlanner}
                    disabled={plannerPhase !== 'idle'}
                    title="Run planner and execute"
                >
                    <Rocket className={`h-4 w-4 ${plannerPhase !== 'idle' ? 'animate-pulse' : ''}`} />
                    <span>{getPlannerButtonText()}</span>
                </button>

                {/* 2. Executor Toggle (Pause/Resume) */}
                <button
                    className={`flex items-center justify-center gap-2 rounded-xl px-3 py-2.5 text-[11px] font-semibold transition
                        ${isPaused
                            ? 'bg-bad/80 text-white ring-2 ring-bad shadow-[0_0_20px_rgba(241,81,50,0.5)] animate-pulse'
                            : 'bg-good hover:bg-good/80 text-white btn-glow-green'
                        } ${loading === 'pause' ? 'opacity-60 cursor-wait' : ''}`}
                    onClick={handleTogglePause}
                    disabled={loading === 'pause'}
                    title={isPaused ? 'Resume executor' : 'Pause executor (idle mode)'}
                >
                    {isPaused ? (
                        <>
                            <Play className="h-4 w-4" />
                            <span>RESUME</span>
                            {pausedMinutes !== null && (
                                <span className="text-[9px] opacity-80">({Math.round(pausedMinutes)}m)</span>
                            )}
                        </>
                    ) : (
                        <>
                            <Pause className="h-4 w-4" />
                            <span>Pause</span>
                        </>
                    )}
                </button>

                {/* 3. Vacation Mode */}
                <div className={`flex items-center rounded-xl px-2 py-1.5 text-[11px] font-semibold transition
                    ${vacationActive
                        ? 'bg-amber-500/30 border border-amber-500/50 ring-2 ring-amber-400/50 shadow-[0_0_15px_rgba(245,158,11,0.4)]'
                        : 'bg-surface2 border border-line/50'
                    } ${loading === 'vacation' ? 'opacity-60' : ''}`}
                >
                    {!vacationActive && (
                        <>
                            <button
                                onClick={() => setVacationDaysIndex(i => Math.max(0, i - 1))}
                                className="px-0.5 hover:text-accent"
                                disabled={vacationDaysIndex === 0 || loading === 'vacation'}
                            >
                                <ChevronLeft className="h-3 w-3" />
                            </button>
                            <span className="mx-0.5 min-w-[24px] text-center text-muted">
                                {VACATION_DAYS_OPTIONS[vacationDaysIndex]}d
                            </span>
                            <button
                                onClick={() => setVacationDaysIndex(i => Math.min(VACATION_DAYS_OPTIONS.length - 1, i + 1))}
                                className="px-0.5 hover:text-accent"
                                disabled={vacationDaysIndex === VACATION_DAYS_OPTIONS.length - 1 || loading === 'vacation'}
                            >
                                <ChevronRight className="h-3 w-3" />
                            </button>
                        </>
                    )}
                    <button
                        onClick={handleToggleVacation}
                        disabled={loading === 'vacation'}
                        className={`flex-1 flex items-center justify-center gap-1 py-1 px-2 rounded-lg transition
                            ${vacationActive
                                ? 'bg-amber-500/50 text-amber-100'
                                : 'bg-amber-500/20 hover:bg-amber-500/30 text-amber-300/80 hover:text-amber-300'
                            }`}
                    >
                        <Palmtree className="h-3.5 w-3.5" />
                        {vacationActive ? (
                            <span className="truncate">
                                {vacationEndDate ? `→ ${vacationEndDate.slice(5)}` : 'ON'}
                            </span>
                        ) : (
                            <span>Vacation</span>
                        )}
                    </button>
                </div>

                {/* 4. Water Boost */}
                <div className={`flex items-center rounded-xl px-2 py-1.5 text-[11px] font-semibold transition
                    ${boostActive
                        ? 'bg-red-500/30 border border-red-500/50 ring-2 ring-red-400/50 shadow-[0_0_15px_rgba(239,68,68,0.4)]'
                        : 'bg-surface2 border border-line/50'
                    } ${loading === 'boost' ? 'opacity-60' : ''}`}
                >
                    {!boostActive && (
                        <>
                            <button
                                onClick={() => setBoostMinutesIndex(i => Math.max(0, i - 1))}
                                className="px-0.5 hover:text-accent"
                                disabled={boostMinutesIndex === 0 || loading === 'boost'}
                            >
                                <ChevronLeft className="h-3 w-3" />
                            </button>
                            <span className="mx-0.5 min-w-[24px] text-center text-muted">
                                {BOOST_MINUTES_OPTIONS[boostMinutesIndex] === 120 ? '2h' :
                                    BOOST_MINUTES_OPTIONS[boostMinutesIndex] === 60 ? '1h' : '30m'}
                            </span>
                            <button
                                onClick={() => setBoostMinutesIndex(i => Math.min(BOOST_MINUTES_OPTIONS.length - 1, i + 1))}
                                className="px-0.5 hover:text-accent"
                                disabled={boostMinutesIndex === BOOST_MINUTES_OPTIONS.length - 1 || loading === 'boost'}
                            >
                                <ChevronRight className="h-3 w-3" />
                            </button>
                        </>
                    )}
                    <button
                        onClick={handleToggleBoost}
                        disabled={loading === 'boost'}
                        className={`flex-1 flex items-center justify-center gap-1 py-1 px-2 rounded-lg transition
                            ${boostActive
                                ? 'bg-red-500/50 text-red-100'
                                : 'bg-red-500/20 hover:bg-red-500/30 text-red-300/80 hover:text-red-300'
                            }`}
                    >
                        <Flame className={`h-3.5 w-3.5 ${boostActive ? 'animate-pulse' : ''}`} />
                        {boostActive ? (
                            <span className="font-mono">{formatSecondsRemaining(boostSecondsRemaining)}</span>
                        ) : (
                            <span>Boost</span>
                        )}
                    </button>
                </div>
            </div>

            {/* Floating toast - doesn't shift layout */}
            {feedback && (
                <div
                    className={`absolute -bottom-8 left-0 right-0 text-center text-[10px] py-1 px-2 rounded-md transition-opacity animate-in fade-in slide-in-from-bottom-1 duration-300 ${feedback.type === 'success'
                        ? 'text-green-400'
                        : 'text-red-400'
                        }`}
                >
                    {feedback.message}
                </div>
            )}
        </div>
    )
}
