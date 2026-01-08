/**
 * AdvisorCard.tsx
 *
 * Wrapper that toggles between Aurora Advisor and Power Flow views.
 */

import { useState } from 'react'
import Card from './Card'
import SmartAdvisor from './SmartAdvisor'
import PowerFlowCard, { type PowerFlowData } from './PowerFlowCard'

interface AdvisorCardProps {
    powerFlowData?: PowerFlowData
    isLoading?: boolean
}

function Skeleton() {
    return (
        <div className="animate-pulse space-y-4 p-2">
            <div className="h-4 bg-surface2/50 rounded w-3/4" />
            <div className="h-32 bg-surface2/30 rounded-lg" />
            <div className="space-y-2">
                <div className="h-3 bg-surface2/40 rounded w-full" />
                <div className="h-3 bg-surface2/40 rounded w-5/6" />
            </div>
        </div>
    )
}

export default function AdvisorCard({ powerFlowData, isLoading }: AdvisorCardProps) {
    const [view] = useState<'advisor' | 'powerflow'>('powerflow')

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
            {/* Header removed to save space */}

            {/* Content */}
            <div className="flex-1 min-h-0">
                {isLoading ? (
                    <Skeleton />
                ) : view === 'advisor' ? (
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
