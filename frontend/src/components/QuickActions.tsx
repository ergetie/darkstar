import React, { useState, useEffect } from 'react'
import { Play, Pause, Loader2, Rocket } from 'lucide-react'
import { Api } from '../lib/api'

interface QuickActionsProps {
    status: string | null
    onRefresh?: () => void
}

export default function QuickActions({ status, onRefresh }: QuickActionsProps) {
    const [loading, setLoading] = useState<'pause' | null>(null)
    const [plannerPhase, setPlannerPhase] = useState<'idle' | 'planning' | 'executing' | 'done'>('idle')
    const [feedback, setFeedback] = useState<{ type: 'success' | 'error'; message: string } | null>(null)
    const [isPaused, setIsPaused] = useState(false)

    // Sync paused state with status prop if needed
    useEffect(() => {
        setIsPaused(status === 'paused' || status === 'idle')
    }, [status])

    const handleRunPlanner = async () => {
        setPlannerPhase('planning')
        setFeedback(null)
        try {
            // Planner run
            await Api.runPlanner()
            setPlannerPhase('executing')

            // Executor run
            await Api.executor.run()
            setPlannerPhase('done')

            if (onRefresh) setTimeout(onRefresh, 500)
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
                setFeedback({ type: 'success', message: 'Executor resumed' })
                onRefresh?.()
            } else {
                await Api.executor.pause()
                setIsPaused(true)
                setFeedback({ type: 'success', message: 'Executor paused - idle mode' })
                onRefresh?.()
            }
            setTimeout(() => setFeedback(null), 3000)
        } catch (err) {
            setFeedback({ type: 'error', message: err instanceof Error ? err.message : 'Failed' })
        } finally {
            setLoading(null)
        }
    }

    const getPlannerButtonText = () => {
        switch (plannerPhase) {
            case 'planning':
                return 'Planning...'
            case 'executing':
                return 'Executing...'
            case 'done':
                return 'Done ✓'
            default:
                return 'Run Planner'
        }
    }

    return (
        <div className="relative">
            {/* Buttons grid */}
            <div className="grid grid-cols-2 gap-3">
                {/* 1. Run Planner */}
                <button
                    className={`relative overflow-hidden flex items-center justify-center gap-2 rounded-xl px-3 py-2.5 text-[11px] font-semibold transition btn-glow-primary
                        ${
                            plannerPhase !== 'idle'
                                ? 'bg-surface border border-accent/50 text-accent cursor-wait'
                                : 'bg-accent hover:bg-accent2 text-[#100f0e]'
                        }`}
                    onClick={handleRunPlanner}
                    disabled={plannerPhase !== 'idle'}
                    title="Run planner and execute"
                >
                    {/* Progress Bar Background */}
                    <div
                        className={`absolute left-0 top-0 bottom-0 transition-all duration-[2000ms] ease-out pointer-events-none ${
                            plannerPhase === 'idle' ? 'bg-transparent' : 'bg-accent/50'
                        }`}
                        style={{
                            width: plannerPhase === 'idle' ? '0%' : plannerPhase === 'done' ? '100%' : '90%',
                        }}
                    />

                    <div className="relative z-10 flex items-center gap-2">
                        {plannerPhase === 'planning' || plannerPhase === 'executing' ? (
                            <Loader2 className="h-4 w-4 animate-spin" />
                        ) : (
                            <Rocket className="h-4 w-4" />
                        )}
                        <span>{getPlannerButtonText()}</span>
                    </div>
                </button>

                {/* 2. Executor Toggle (Pause/Resume) */}
                <button
                    className={`flex items-center justify-center gap-2 rounded-xl px-3 py-2.5 text-[11px] font-semibold transition
                        ${
                            isPaused
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
                        </>
                    ) : (
                        <>
                            <Pause className="h-4 w-4" />
                            <span>Pause</span>
                        </>
                    )}
                </button>
            </div>

            {/* Floating toast - doesn't shift layout */}
            {feedback && (
                <div
                    className={`absolute -bottom-8 left-0 right-0 text-center text-[10px] py-1 px-2 rounded-md transition-opacity animate-in fade-in slide-in-from-bottom-1 duration-300 ${
                        feedback.type === 'success' ? 'text-green-400' : 'text-red-400'
                    }`}
                >
                    {feedback.message}
                </div>
            )}
        </div>
    )
}
