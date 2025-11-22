import { useEffect, useState } from 'react'
import { cls } from '../theme'
import { Rocket, CloudDownload, Upload, RotateCcw } from 'lucide-react'
import { Api } from '../lib/api'
import type { ScheduleSlot } from '../lib/types'

interface QuickActionsProps {
    onDataRefresh?: () => void
    onPlanSourceChange?: (source: 'local' | 'server') => void
    onServerScheduleLoaded?: (schedule: ScheduleSlot[]) => void
}

export default function QuickActions({ onDataRefresh, onPlanSourceChange, onServerScheduleLoaded }: QuickActionsProps){
    const [loading, setLoading] = useState<string | null>(null)
    const [feedback, setFeedback] = useState<{ type: 'success' | 'error'; message: string } | null>(null)
    const [themeColors, setThemeColors] = useState<Record<string, string>>({})
    const [accentIndex, setAccentIndex] = useState<number | null>(null)

    useEffect(() => {
        Api.theme()
            .then(themeData => {
                const currentThemeInfo = themeData.themes.find(t => t.name === themeData.current)
                if (currentThemeInfo) {
                    const colorMap: Record<string, string> = {}
                    currentThemeInfo.palette.forEach((color, index) => {
                        colorMap[`palette = ${index}`] = color
                    })
                    setThemeColors(colorMap)
                    if (typeof themeData.accent_index === 'number') {
                        setAccentIndex(themeData.accent_index)
                    }
                }
            })
            .catch(err => {
                console.error('Failed to load theme colors for QuickActions:', err)
            })
    }, [])

    const getPaletteColor = (index: number, fallback: string) =>
        themeColors[`palette = ${index}`] || fallback

    const handleAction = async (action: string, apiCall: () => Promise<any>) => {
        setLoading(action)
        setFeedback(null)
        try {
            const result = await apiCall()
            setFeedback({ type: 'success', message: result.message || 'Success' })

            if (action === 'load-server' && onServerScheduleLoaded) {
                const schedule = Array.isArray(result.schedule) ? result.schedule : []
                onServerScheduleLoaded(schedule)
            }
            
            // Handle plan source changes
            if (onPlanSourceChange) {
                if (action === 'load-server') {
                    onPlanSourceChange('server')
                } else if (action === 'run-planner' || action === 'reset') {
                    onPlanSourceChange('local')
                }
                // push-db doesn't change what user is viewing, so no plan source change
            }
            
            // Trigger data refresh after successful action with appropriate delay for backend processing
            if (onDataRefresh) {
                // Longer delay for load-server since it needs to update status metadata
                const delay = action === 'load-server' ? 2000 : 1000
                setTimeout(() => onDataRefresh(), delay)
            }
        } catch (error) {
            setFeedback({ type: 'error', message: error instanceof Error ? error.message : 'Failed' })
        } finally {
            setLoading(null)
            // Clear feedback after 3 seconds
            setTimeout(() => setFeedback(null), 3000)
        }
    }

    return (
        <div className="space-y-3">
            {feedback && (
                <div
                    className={`rounded-lg px-3 py-2 text-sm ${
                        feedback.type === 'success'
                            ? 'bg-green-500/20 text-green-300 border border-green-500/30'
                            : 'bg-red-500/20 text-red-300 border border-red-500/30'
                    }`}
                >
                    {feedback.message}
                </div>
            )}

            <div className="grid grid-cols-2 gap-3">
                {/*
                  Run planner: accent index from theme (fallback to palette 14 / yellow-ish).
                */}
                <button
                    className={`flex items-center justify-center gap-2 rounded-xl px-3 py-2 text-[11px] font-semibold transition hover:opacity-90 ${
                        loading === 'run-planner' ? 'cursor-not-allowed opacity-60' : ''
                    }`}
                    style={{
                        backgroundColor: getPaletteColor(
                            accentIndex ?? 14,
                            '#facc15' // warm yellow fallback
                        ),
                        color: '#000000',
                    }}
                    onClick={() => handleAction('run-planner', () => Api.runPlanner())}
                    disabled={loading === 'run-planner'}
                    title="Run planner"
                >
                    <Rocket className="h-4 w-4" />
                    <span>Run planner</span>
                </button>
                {/*
                  Load DB plan: palette 4 (typically blue/cyan).
                */}
                <button
                    className={`flex items-center justify-center gap-2 rounded-xl px-3 py-2 text-[11px] font-semibold border border-line/70 transition hover:opacity-90 ${
                        loading === 'load-server' ? 'cursor-not-allowed opacity-60' : ''
                    }`}
                    style={{
                        backgroundColor: getPaletteColor(4, '#38bdf8'),
                        color: '#000000',
                    }}
                    onClick={() => handleAction('load-server', () => Api.loadServerPlan())}
                    disabled={loading === 'load-server'}
                    title="Load server plan"
                >
                    <CloudDownload className="h-4 w-4" />
                    <span>Load DB plan</span>
                </button>
                {/*
                  Push to DB: palette 2 (typically green).
                */}
                <button
                    className={`flex items-center justify-center gap-2 rounded-xl px-3 py-2 text-[11px] font-semibold transition hover:opacity-90 ${
                        loading === 'push-db' ? 'cursor-not-allowed opacity-60' : ''
                    }`}
                    style={{
                        backgroundColor: getPaletteColor(2, '#22c55e'),
                        color: '#000000',
                    }}
                    onClick={() => handleAction('push-db', () => Api.pushToDb())}
                    disabled={loading === 'push-db'}
                    title="Push to DB"
                >
                    <Upload className="h-4 w-4" />
                    <span>Push to DB</span>
                </button>
                {/*
                  Reset optimal: palette 1 (typically red).
                */}
                <button
                    className={`flex items-center justify-center gap-2 rounded-xl px-3 py-2 text-[11px] font-semibold transition hover:opacity-90 ${
                        loading === 'reset' ? 'cursor-not-allowed opacity-60' : ''
                    }`}
                    style={{
                        backgroundColor: getPaletteColor(1, '#ef4444'),
                        color: '#000000',
                    }}
                    onClick={() => handleAction('reset', () => Api.resetToOptimal())}
                    disabled={loading === 'reset'}
                    title="Reset to optimal"
                >
                    <RotateCcw className="h-4 w-4" />
                    <span>Reset optimal</span>
                </button>
            </div>
        </div>
    )
}
