import { useState, useCallback } from 'react'
import { ArrowRight, Gauge } from 'lucide-react'
import Card from './Card'
import { type PlannerSIndex, type PriceOutlookResponse } from '../lib/api'

type PlannerMeta = {
    planned_at?: string
    planner_version?: string
    s_index?: PlannerSIndex
} | null

interface BatteryStrategyCardProps {
    soc: number | null
    socTarget: number
    batteryCapacity: number
    plannerMeta: PlannerMeta
    batteryCycles: number | null
    priceOutlook: PriceOutlookResponse | undefined
    currentAction?: string
}

interface TooltipState {
    text: string
    x: number
    y: number
}

/** Normalizes sparkline prices to a min/max/range, guarding the single-value
 * (or all-equal) case where max - min would otherwise be 0. */
// eslint-disable-next-line react-refresh/only-export-components -- pure helper, tested directly
export function computeSparklineRange(prices: number[]): {
    minPrice: number
    maxPrice: number
    range: number
    maxTopPercent: number
} {
    const minPrice = Math.min(...prices)
    const maxPrice = Math.max(...prices)
    const range = maxPrice - minPrice || 1

    // Container is 100px (from CSS), with py-1 (4px top + 4px bottom padding)
    // Available for block top: 4px to 86px (100 - 8 - 10)
    // As percentage: 86/100 * 100 = 86%
    const containerHeight = 100
    const paddingY = 4 // py-1
    const blockHeight = 10
    const maxTopPx = paddingY + (containerHeight - 2 * paddingY - blockHeight) // 86px
    const maxTopPercent = (maxTopPx / containerHeight) * 100 // 86%

    return { minPrice, maxPrice, range, maxTopPercent }
}

/** Pure strategy-sentence logic for the SOC context line, decided from the
 * current battery action, SOC-vs-target, and the price outlook. */
// eslint-disable-next-line react-refresh/only-export-components -- pure helper, tested directly
export function computeSocContextMessage(params: {
    currentAction?: string
    soc: number | null
    socTarget: number
    priceOutlook: PriceOutlookResponse | undefined
}): string | null {
    const { currentAction, soc, socTarget, priceOutlook } = params
    if (!currentAction) return null

    const action = currentAction.toLowerCase()
    const isCharging = action.includes('charge')
    const isDischarging = action.includes('discharge') || action.includes('export')

    let message = ''

    if (isCharging && soc !== null && soc < socTarget) {
        // Find cheap windows in the outlook
        if (priceOutlook?.days?.length) {
            const cheapDays = priceOutlook.days
                .slice(0, 7)
                .map((d, i) => ({ ...d, index: i }))
                .filter((d) => d.level === 'cheap')
                .map((d) => d.index + 1)

            if (cheapDays.length > 0) {
                const start = cheapDays[0]
                const end = cheapDays[cheapDays.length - 1]
                message =
                    start === end ? `charging ahead of cheap D${start}` : `charging ahead of cheap D${start}→D${end}`
            } else {
                message = 'charging ahead of cheap window'
            }
        } else {
            message = 'charging'
        }
    } else if (isDischarging && soc !== null && soc > socTarget) {
        if (action.includes('export')) {
            // Find peak price days
            if (priceOutlook?.days?.length) {
                const peakDays = priceOutlook.days
                    .slice(0, 7)
                    .map((d, i) => ({ ...d, index: i }))
                    .filter((d) => d.level === 'expensive')
                    .map((d) => d.index + 1)

                if (peakDays.length > 0) {
                    message = `exporting into peak D${peakDays.join(', ')}`
                } else {
                    message = 'exporting into evening peak'
                }
            } else {
                message = 'exporting into price peak'
            }
        } else {
            // Find next charge window
            if (priceOutlook?.days?.length) {
                const nextCheap = priceOutlook.days.slice(0, 7).findIndex((d) => d.level === 'cheap')
                if (nextCheap >= 0) {
                    message = `discharging — next charge D${nextCheap + 1}`
                } else {
                    message = 'discharging — next charge D2'
                }
            } else {
                message = 'discharging — next charge D2'
            }
        }
    } else if (action.includes('hold')) {
        message = 'holding — price neutral'
    }

    return message || null
}

export default function BatteryStrategyCard({
    soc,
    socTarget,
    batteryCapacity,
    plannerMeta,
    batteryCycles,
    priceOutlook,
    currentAction,
}: BatteryStrategyCardProps) {
    const sIndex = plannerMeta?.s_index
    const safetyFloor = sIndex?.safety_floor
    const [tooltip, setTooltip] = useState<TooltipState | null>(null)

    const showTooltip = useCallback((e: React.MouseEvent, text: string) => {
        const rect = e.currentTarget.getBoundingClientRect()
        setTooltip({
            text,
            x: rect.left + rect.width / 2,
            y: rect.top,
        })
    }, [])

    const hideTooltip = useCallback(() => setTooltip(null), [])

    // 3.1 Pixel sparkline logic
    const renderSparkline = () => {
        if (!priceOutlook || !priceOutlook.days || priceOutlook.days.length === 0) {
            return (
                <div className="flex-1 flex items-center justify-center text-[11px] text-muted h-[100px]">
                    Price data loading...
                </div>
            )
        }

        const days = priceOutlook.days.slice(0, 7)
        const prices = days.map((d) => d.avg_spot_p50 ?? 0)
        const { minPrice, range, maxTopPercent } = computeSparklineRange(prices)

        return (
            <div className="flex flex-col gap-1">
                <div className="price-sparkline py-2">
                    {priceOutlook.reference_avg != null && (
                        <div
                            className="price-sparkline-ref"
                            style={{
                                top: `${Math.max(0, Math.min(maxTopPercent, (1 - (priceOutlook.reference_avg - minPrice) / range) * 100))}%`,
                            }}
                        />
                    )}
                    <div className="flex justify-around items-end h-full px-1">
                        {days.map((day, i) => {
                            const price = day.avg_spot_p50 ?? 0
                            const normalized = (price - minPrice) / range
                            const top = (1 - normalized) * 100
                            const colorClass =
                                {
                                    cheap: 'bg-good',
                                    normal: 'bg-warn',
                                    expensive: 'bg-bad',
                                    unknown: 'bg-muted',
                                }[day.level] || 'bg-muted'

                            // Build tooltip with each value on separate line
                            const tooltipLines = [`${day.day_label}: ${price.toFixed(1)} öre`]
                            if (day.avg_spot_p10 != null) tooltipLines.push(`Min: ${day.avg_spot_p10.toFixed(1)} öre`)
                            if (day.avg_spot_p90 != null) tooltipLines.push(`Max: ${day.avg_spot_p90.toFixed(1)} öre`)
                            const tooltipText = tooltipLines.join('\n')

                            return (
                                <div
                                    key={i}
                                    className="relative w-full flex justify-center h-full"
                                    onMouseEnter={(e) => showTooltip(e, tooltipText)}
                                    onMouseLeave={hideTooltip}
                                >
                                    <div
                                        className={`price-sparkline-block ${colorClass}`}
                                        style={{ top: `${Math.max(0, Math.min(maxTopPercent, top))}%` }}
                                    />
                                </div>
                            )
                        })}
                    </div>
                </div>
                <div className="flex justify-around text-[8px] text-muted uppercase tracking-tighter">
                    {days.map((day, i) => (
                        <div key={i} className="flex flex-col items-center">
                            <span>{day.day_label.slice(0, 2)}</span>
                            <span className="tabular-nums">
                                {day.avg_spot_p50?.toFixed(day.avg_spot_p50 < 10 ? 1 : 0) ?? '—'}
                            </span>
                        </div>
                    ))}
                </div>
            </div>
        )
    }

    // 3.5 SOC context line logic - dynamic based on price outlook
    const renderSocContext = () => {
        const message = computeSocContextMessage({ currentAction, soc, socTarget, priceOutlook })
        if (!message) return null
        return <div className="text-[10px] text-muted mt-0.5">{message}</div>
    }

    return (
        <Card className="p-ds-4 flex flex-col h-full bg-surface">
            {/* Header */}
            <div className="flex items-center gap-2 mb-ds-3">
                <div className="p-1.5 rounded-ds-sm bg-ai/10 text-ai">
                    <Gauge className="h-4 w-4" />
                </div>
                <span className="text-sm font-medium text-text">Battery & Strategy</span>
            </div>

            {/* SOC Section */}
            <div className="mb-ds-4">
                <div className="flex items-center gap-3 text-5xl font-bold leading-none">
                    <span className={`${(soc ?? 0) > 50 ? 'text-good' : (soc ?? 0) > 20 ? 'text-warn' : 'text-bad'}`}>
                        {soc?.toFixed(0) ?? '—'}%
                    </span>
                    <ArrowRight className="w-10 h-10 text-muted" strokeWidth={3} />
                    <span className="text-text">{socTarget?.toFixed(0) ?? '—'}%</span>
                </div>
                <div className="flex flex-col mt-1">
                    <div className="text-[11px] text-muted">
                        {soc != null && batteryCapacity != null ? ((soc / 100) * batteryCapacity).toFixed(1) : '—'} of{' '}
                        {batteryCapacity?.toFixed(1) ?? '—'} kWh
                    </div>
                    {renderSocContext()}
                </div>
            </div>

            {/* Metrics Stack */}
            <div className="flex flex-col gap-ds-3 mb-ds-4 pb-ds-4 border-b border-line/30">
                {/* S-Index */}
                <div className="flex flex-col">
                    <div className="flex justify-between items-baseline">
                        <span className="text-[9px] text-muted uppercase tracking-wider">S-Index</span>
                        <span className="text-base font-semibold text-text">
                            {sIndex?.effective_load_margin != null || sIndex?.risk_factor != null
                                ? `x${(sIndex?.effective_load_margin ?? sIndex?.risk_factor ?? 1).toFixed(2)}`
                                : '—'}
                        </span>
                    </div>
                    {sIndex?.avg_deficit != null && (
                        <div className="text-[10px] text-muted mt-0.5">
                            base {sIndex.base_factor?.toFixed(2) ?? '1.00'} · deficit +
                            {sIndex.avg_deficit?.toFixed(2) ?? '0.00'} · cold +
                            {sIndex.temp_adjustment?.toFixed(2) ?? '0.00'}
                        </div>
                    )}
                </div>

                {/* Safety Floor */}
                <div className="flex flex-col">
                    <div className="flex justify-between items-baseline">
                        <span className="text-[9px] text-muted uppercase tracking-wider">Safety Floor</span>
                        <span className="text-base font-semibold text-text">
                            {safetyFloor?.calculated_floor_kwh != null
                                ? `${safetyFloor.calculated_floor_kwh.toFixed(1)} kWh`
                                : '—'}
                        </span>
                    </div>
                    {safetyFloor?.min_soc_kwh != null && (
                        <div className="text-[10px] text-muted mt-0.5">
                            min {safetyFloor.min_soc_kwh?.toFixed(1) ?? '0.0'} · deficit{' '}
                            {safetyFloor.base_reserve_kwh?.toFixed(1) ?? '0.0'} · weather{' '}
                            {safetyFloor.weather_buffer_kwh?.toFixed(1) ?? '0.0'}
                        </div>
                    )}
                </div>

                {/* Cycles + Tradable */}
                <div className="flex justify-between gap-4">
                    <div className="flex flex-col">
                        <span className="text-[9px] text-muted uppercase tracking-wider">Cycles</span>
                        <span className="text-sm font-semibold text-text">{batteryCycles?.toFixed(1) ?? '—'}</span>
                    </div>
                    <div className="flex flex-col items-end">
                        <span className="text-[9px] text-muted uppercase tracking-wider">Tradable</span>
                        <span className="text-sm font-semibold text-text">
                            {safetyFloor?.calculated_floor_kwh != null && batteryCapacity != null
                                ? `${Math.max(0, batteryCapacity - safetyFloor.calculated_floor_kwh).toFixed(1)} kWh`
                                : '—'}
                        </span>
                    </div>
                </div>
            </div>

            {/* Price Sparkline Section */}
            <div className="mt-auto">
                <div className="flex justify-between items-center mb-1">
                    <span className="text-[9px] text-muted uppercase tracking-wider">7-Day Price Outlook</span>
                    {/* Removed "ref X¢" text - user requested removal */}
                </div>
                {renderSparkline()}
            </div>

            {/* React-based Tooltip */}
            {tooltip && (
                <div
                    className="fixed z-[9999] -translate-x-1/2 -translate-y-full px-2 py-1 bg-text text-canvas text-[10px] rounded-ds-sm whitespace-pre-line text-left"
                    style={{ left: tooltip.x, top: tooltip.y }}
                >
                    {tooltip.text}
                </div>
            )}
        </Card>
    )
}
