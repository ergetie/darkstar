import { useMemo } from 'react'
import { Brain, CloudRain, Zap, GraduationCap, Info, Upload, Shield, Coffee, TrendingUp, Battery } from 'lucide-react'

interface StrategyEvent {
    timestamp: string
    type: string
    message: string
    details?: Record<string, any>
}

interface ActivityLogProps {
    events: StrategyEvent[]
}

export default function ActivityLog({ events }: ActivityLogProps) {
    const sortedEvents = useMemo(() => {
        return [...events].sort((a, b) =>
            new Date(b.timestamp).getTime() - new Date(a.timestamp).getTime()
        )
    }, [events])

    const getIcon = (event: StrategyEvent) => {
        const text = (event.type + ' ' + event.message).toLowerCase()

        if (text.includes('charge') || text.includes('charging')) return <Zap className="h-4 w-4 text-amber-400" />
        if (text.includes('export') || text.includes('discharging')) return <Upload className="h-4 w-4 text-emerald-400" />
        if (text.includes('defensive') || text.includes('safety') || text.includes('hold')) return <Shield className="h-4 w-4 text-blue-400" />
        if (text.includes('idle') || text.includes('wait')) return <Coffee className="h-4 w-4 text-slate-400" />
        if (text.includes('weather')) return <CloudRain className="h-4 w-4 text-sky-400" />
        if (text.includes('learning') || text.includes('tune')) return <GraduationCap className="h-4 w-4 text-purple-400" />
        if (text.includes('price') || text.includes('cost')) return <TrendingUp className="h-4 w-4 text-emerald-400" />

        switch (event.type) {
            case 'STRATEGY_CHANGE':
                return <Brain className="h-4 w-4 text-purple-400" />
            case 'WEATHER_ADJUSTMENT':
                return <CloudRain className="h-4 w-4 text-blue-400" />
            case 'PRICE_VOLATILITY':
                return <Zap className="h-4 w-4 text-amber-400" />
            case 'LEARNING_EVENT':
                return <GraduationCap className="h-4 w-4 text-emerald-400" />
            default:
                return <Info className="h-4 w-4 text-slate-400" />
        }
    }

    const formatTime = (iso: string) => {
        return new Date(iso).toLocaleTimeString([], { hour: '2-digit', minute: '2-digit', hour12: false })
    }

    if (events.length === 0) {
        return (
            <div className="flex flex-col items-center justify-center h-48 text-muted text-xs">
                <Info className="h-6 w-6 mb-2 opacity-50" />
                No activity recorded yet.
            </div>
        )
    }

    return (
        <div className="relative space-y-4 pl-2">
            {/* Vertical Line */}
            <div className="absolute left-[19px] top-2 bottom-2 w-[1px] bg-line/50" />

            {sortedEvents.map((event, idx) => (
                <div key={idx} className="relative flex gap-3 items-start group">
                    {/* Icon Bubble */}
                    <div className="relative z-10 flex h-8 w-8 shrink-0 items-center justify-center rounded-full bg-surface border border-line/60 group-hover:border-accent/50 transition-colors">
                        {getIcon(event)}
                    </div>

                    {/* Content */}
                    <div className="flex-1 pt-1.5 min-w-0">
                        <div className="flex items-baseline justify-between gap-2">
                            <p className="text-xs font-medium text-text truncate">
                                {event.type.replace('_', ' ')}
                            </p>
                            <span className="text-[10px] text-muted shrink-0 font-mono">
                                {formatTime(event.timestamp)}
                            </span>
                        </div>
                        <p className="text-[11px] text-muted mt-0.5 leading-relaxed break-words">
                            {event.message}
                        </p>
                        {event.details && Object.keys(event.details).length > 0 && (
                            <div className="mt-1.5">
                                <details className="group/details">
                                    <summary className="cursor-pointer text-[10px] text-accent/80 hover:text-accent select-none list-none flex items-center gap-1">
                                        <span>Details</span>
                                        <span className="opacity-50 group-open/details:rotate-180 transition-transform">▼</span>
                                    </summary>
                                    <pre className="mt-1 p-2 rounded bg-surface2/50 text-[10px] text-muted overflow-x-auto font-mono">
                                        {JSON.stringify(event.details, null, 2)}
                                    </pre>
                                </details>
                            </div>
                        )}
                    </div>
                </div>
            ))}
        </div>
    )
}
