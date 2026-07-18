import { useState, useEffect } from 'react'
import { Brain, RotateCw, AlertTriangle, CheckCircle2, Play, CalendarClock } from 'lucide-react'
import Card from '../Card'
import { Api } from '../../lib/api'
import type { TrainingStatusResponse, TrainingHistoryResponse } from '../../lib/api'
import { useSocket } from '../../lib/hooks'

export default function ModelTrainingCard() {
    const [status, setStatus] = useState<TrainingStatusResponse | null>(null)
    const [history, setHistory] = useState<TrainingHistoryResponse | null>(null)
    const [scheduler, setScheduler] = useState<{ next_run_at?: string; next_training_at?: string } | null>(null)
    const [loading, setLoading] = useState(false)
    const [triggering, setTriggering] = useState(false)
    const [progress, setProgress] = useState<{
        status: string
        stage: string
        message: string
        progress: number
    } | null>(null)

    const fetchData = async () => {
        setLoading(true)
        try {
            const [statusRes, historyRes, schedulerRes] = await Promise.all([
                Api.learningTrainingStatus(),
                Api.learningTrainingHistory(3),
                Api.schedulerStatus(),
            ])
            setStatus(statusRes)
            setHistory(historyRes)
            setScheduler(schedulerRes)
        } catch (err) {
            console.error('Failed to fetch training data:', err)
        } finally {
            setLoading(false)
        }
    }

    // Listen for real-time progress
    useSocket('training_progress', (data: unknown) => {
        const payload = data as { status: string; stage: string; message: string; progress: number }
        // console.log('Training progress:', payload)
        setProgress(payload)
        if (payload.status === 'success' || payload.status === 'error') {
            // Refresh main data on completion
            fetchData()
        }
    })

    useEffect(() => {
        // eslint-disable-next-line react-hooks/set-state-in-effect -- mount IO fetch, not derivable
        fetchData()
        // Poll status if training is active
        const interval = setInterval(() => {
            Api.learningTrainingStatus().then(setStatus).catch(console.error)
        }, 5000)
        return () => clearInterval(interval)
    }, [])

    const handleTrain = async () => {
        setTriggering(true)
        try {
            await Api.learningTrain()
            // After trigger, fetch status immediately
            setTimeout(fetchData, 500)
        } catch (err) {
            alert('Training failed to start: ' + String(err))
        } finally {
            setTriggering(false)
        }
    }

    const mainModel = status?.models
        ? Object.values(status.models).find((m) => !m.last_modified.includes('error'))
        : null
    const correctorModel = status?.models
        ? Object.entries(status.models).find(([filename]) => filename.includes('error'))?.[1]
        : null

    // Helper to format age
    const formatAge = (seconds: number) => {
        const hours = Math.floor(seconds / 3600)
        const days = Math.floor(hours / 24)
        if (days > 0) return `${days}d ago`
        return `${hours}h ago`
    }

    // Stale lock detection using backend provided status (or fallback)
    // ARC11 Fix: Replace existing lock detection with robust check
    const isTrainingLocked = status?.lock_status?.locked && !status?.lock_status?.stale

    // Use either API status or realtime progress status
    // If backend says is_training=false (because stale), we respect that.
    const isTraining = isTrainingLocked || progress?.status === 'busy'

    // Helper for button state
    // const canTrain = !isTrainingLocked && !isTraining // Used in render

    return (
        <Card className="p-4 md:p-5 flex flex-col h-full">
            <div className="flex items-center justify-between mb-4">
                <div className="flex items-center gap-2">
                    <Brain className="h-4 w-4 text-accent" />
                    <span className="text-xs font-medium text-text">Model Training</span>
                </div>
                {isTraining && (
                    <div className="flex items-center gap-1.5 px-2 py-0.5 rounded-full bg-accent/10 border border-accent/20">
                        <RotateCw className="h-3 w-3 text-accent animate-spin" />
                        <span className="text-[10px] font-medium text-accent">Running</span>
                    </div>
                )}
                {scheduler?.next_training_at && !isTraining && (
                    <div className="flex items-center gap-1.5 text-[10px] text-muted">
                        <CalendarClock className="h-3 w-3" />
                        <span>
                            Next:{' '}
                            {new Date(scheduler.next_training_at).toLocaleString('sv-SE', {
                                hour: '2-digit',
                                minute: '2-digit',
                                hour12: false,
                            })}
                        </span>
                    </div>
                )}
            </div>

            <div className="flex-1 space-y-4">
                {/* Status Grid */}
                <div className="grid grid-cols-2 gap-2">
                    <div className="p-2.5 rounded-lg bg-surface2/50 border border-line/50">
                        <div className="text-[10px] text-muted mb-1">Main Models</div>
                        <div className="flex items-center gap-1.5">
                            <div className={`h-2 w-2 rounded-full ${mainModel ? 'bg-emerald-400' : 'bg-red-400'}`} />
                            <span className="text-sm font-medium text-text">{mainModel ? 'Ready' : 'Missing'}</span>
                        </div>
                        {mainModel && (
                            <div className="text-[10px] text-muted mt-1">{formatAge(mainModel.age_seconds)}</div>
                        )}
                    </div>

                    <div className="p-2.5 rounded-lg bg-surface2/50 border border-line/50">
                        <div className="text-[10px] text-muted mb-1">Corrector</div>
                        <div className="flex items-center gap-1.5">
                            <div
                                className={`h-2 w-2 rounded-full ${correctorModel ? 'bg-emerald-400' : 'bg-slate-500'}`}
                            />
                            <span className="text-sm font-medium text-text">
                                {correctorModel ? 'Ready' : 'Inactive'}
                            </span>
                        </div>
                        {correctorModel && (
                            <div className="text-[10px] text-muted mt-1">{formatAge(correctorModel.age_seconds)}</div>
                        )}
                    </div>
                </div>

                {/* Recent History */}
                <div className="space-y-2">
                    <div className="text-[10px] font-medium text-muted uppercase tracking-wider">Recent Training</div>
                    <div className="space-y-1">
                        {loading && !history ? (
                            <div className="text-[10px] text-muted italic">Loading history...</div>
                        ) : history?.runs.length === 0 ? (
                            <div className="text-[10px] text-muted italic">No recent training</div>
                        ) : (
                            history?.runs.slice(0, 3).map((run) => (
                                <div
                                    key={run.id}
                                    className="flex items-center justify-between text-[11px] p-1.5 rounded bg-surface2/30"
                                >
                                    <div className="flex items-center gap-2">
                                        {run.status === 'success' ? (
                                            <CheckCircle2 className="h-3 w-3 text-emerald-400" />
                                        ) : (
                                            <AlertTriangle className="h-3 w-3 text-amber-400" />
                                        )}
                                        <span className="text-text">
                                            {new Date(run.run_date).toLocaleString('sv-SE', {
                                                year: 'numeric',
                                                month: '2-digit',
                                                day: '2-digit',
                                                hour: '2-digit',
                                                minute: '2-digit',
                                                hour12: false,
                                            })}
                                        </span>
                                    </div>
                                    <span className="text-muted">{Math.round(run.training_duration_seconds)}s</span>
                                </div>
                            ))
                        )}
                    </div>
                </div>
            </div>

            <div className="mt-4 pt-3 border-t border-line/30 space-y-2">
                {isTraining && progress?.status === 'busy' && (
                    <div className="space-y-1.5">
                        <div className="flex justify-between text-[11px]">
                            <span className="text-accent font-medium animate-pulse">{progress.message}</span>
                            <span className="text-muted">{Math.round(progress.progress * 100)}%</span>
                        </div>
                        <div className="h-1.5 w-full bg-surface1 rounded-full overflow-hidden">
                            <div
                                className="h-full bg-accent transition-all duration-500 ease-in-out"
                                style={{ width: `${Math.max(5, progress.progress * 100)}%` }}
                            />
                        </div>
                    </div>
                )}

                <button
                    onClick={handleTrain}
                    disabled={isTraining || triggering}
                    className="w-full flex items-center justify-center gap-2 py-2 rounded-lg bg-accent text-[#0F1216] text-[11px] font-semibold transition-all hover:bg-accent/90 disabled:opacity-50 disabled:cursor-not-allowed"
                >
                    {triggering || isTraining ? (
                        <>
                            <div className="h-3 w-3 border-2 border-[#0F1216]/20 border-t-[#0F1216] rounded-full animate-spin" />
                            <span>{triggering ? 'Starting...' : 'Training in Progress...'}</span>
                        </>
                    ) : (
                        <>
                            <Play className="h-3.5 w-3.5" />
                            <span>Run Full Training</span>
                        </>
                    )}
                </button>
            </div>
        </Card>
    )
}
