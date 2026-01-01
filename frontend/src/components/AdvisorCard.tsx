/**
 * AdvisorCard.tsx
 *
 * Wrapper that toggles between Aurora Advisor and Power Flow views.
 */

import { useState } from 'react'
import { Sparkles, Activity } from 'lucide-react'
import Card from './Card'
import SmartAdvisor from './SmartAdvisor'
import PowerFlowCard, { type PowerFlowData } from './PowerFlowCard'

interface AdvisorCardProps {
    powerFlowData?: PowerFlowData
}

export default function AdvisorCard({ powerFlowData }: AdvisorCardProps) {
    const [view, setView] = useState<'advisor' | 'powerflow'>('advisor')

    // Default data when no live metrics available
    const defaultData: PowerFlowData = {
        solar: { kw: 0, todayKwh: 0 },
        battery: { kw: 0, soc: 50 },
        grid: { kw: 0, importKwh: 0, exportKwh: 0 },
        house: { kw: 0, todayKwh: 0 },
        water: { kw: 0 },
    }

    const data = powerFlowData ?? defaultData

    return (
        <Card className="h-full p-4 md:p-5 flex flex-col">
            {/* Header with toggle */}
            <div className="flex items-center justify-between mb-3">
                <div className="flex items-center gap-1 p-0.5 rounded-lg bg-surface2/50 border border-line/30">
                    <button
                        onClick={() => setView('advisor')}
                        className={`flex items-center gap-1.5 px-2.5 py-1 rounded-md text-[10px] font-medium transition ${
                            view === 'advisor' ? 'bg-accent text-[#100f0e]' : 'text-muted hover:text-text'
                        }`}
                    >
                        <Sparkles className="h-3 w-3" />
                        <span>Advisor</span>
                    </button>
                    <button
                        onClick={() => setView('powerflow')}
                        className={`flex items-center gap-1.5 px-2.5 py-1 rounded-md text-[10px] font-medium transition ${
                            view === 'powerflow' ? 'bg-accent text-[#100f0e]' : 'text-muted hover:text-text'
                        }`}
                    >
                        <Activity className="h-3 w-3" />
                        <span>Power Flow</span>
                    </button>
                </div>
            </div>

            {/* Content */}
            <div className="flex-1 min-h-0">
                {view === 'advisor' ? (
                    <SmartAdvisorContent />
                ) : (
                    <div className="h-full flex items-center justify-center">
                        <PowerFlowCard data={data} />
                    </div>
                )}
            </div>
        </Card>
    )
}

/**
 * Embedded SmartAdvisor content (without the outer Card wrapper)
 * We extract just the inner content from SmartAdvisor.
 */
function SmartAdvisorContent() {
    // Re-use SmartAdvisor but it has its own Card wrapper, so we need to
    // render just the content. For now, we'll render SmartAdvisor as-is
    // but hide the card styling via CSS.
    return (
        <div className="[&>div]:p-0 [&>div]:shadow-none [&>div]:bg-transparent [&>div]:border-none">
            <SmartAdvisor />
        </div>
    )
}
