import { useState, useCallback } from 'react'
import { ArrowRight, Gauge, ShieldCheck } from 'lucide-react'
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

/** Smallest bar height (percent of the plot) so the cheapest day stays visible. */
export const SPARKLINE_MIN_BAR_PERCENT = 14

/** Bar geometry for the price outlook: one height per price, scaled between a
 * visible minimum (cheapest day) and 100% (dearest day). Also positions the
 * reference-average line on the same scale. All values are percent of plot height. */
// eslint-disable-next-line react-refresh/only-export-components -- pure helper, tested directly
export function computeSparklineBars(
    prices: number[],
    referenceAvg?: number | null,
): {
    minPrice: number
    maxPrice: number
    range: number
    heights: number[]
    refPercent: number | null
} {
    if (prices.length === 0) return { minPrice: 0, maxPrice: 0, range: 1, heights: [], refPercent: null }
    const minPrice = Math.min(...prices)
    const maxPrice = Math.max(...prices)
    const range = maxPrice - minPrice || 1
    const span = 100 - SPARKLINE_MIN_BAR_PERCENT
    const scale = (price: number) => {
        const pct = SPARKLINE_MIN_BAR_PERCENT + ((price - minPrice) / range) * span
        return Math.max(SPARKLINE_MIN_BAR_PERCENT, Math.min(100, pct))
    }
    // All-equal prices: show mid-height bars rather than all-minimum
    const heights = maxPrice === minPrice ? prices.map(() => 60) : prices.map(scale)
    const refPercent = referenceAvg != null && Number.isFinite(referenceAvg) ? scale(referenceAvg) : null
    return { minPrice, maxPrice, range, heights, refPercent }
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

type SafetyFloor = NonNullable<PlannerSIndex['safety_floor']>

export type FloorZoneKey = 'min' | 'deficit' | 'weather' | 'price' | 'tradable'

export interface FloorZone {
    key: FloorZoneKey
    label: string
    kwh: number
}

export interface FloorBreakdown {
    zones: FloorZone[]
    floorKwh: number
    capacityKwh: number
}

/** Splits the battery into the layers the planner holds back, in stacking order.
 * The deficit and weather layers are the capped values (they sum to the
 * deficit floor), and the price layer is only the part the price reserve adds
 * on top of it: the planner combines the two with max(), never adds them. */
// eslint-disable-next-line react-refresh/only-export-components -- pure helper, tested directly
export function computeFloorBreakdown(floor: SafetyFloor | undefined, capacityKwh: number): FloorBreakdown | null {
    if (!floor || floor.min_soc_kwh == null || floor.calculated_floor_kwh == null || !(capacityKwh > 0)) {
        return null
    }
    const minKwh = floor.min_soc_kwh
    const deficitFloor = floor.calculated_floor_kwh
    const finalFloor = floor.final_floor_kwh ?? deficitFloor

    const buffer = Math.max(0, deficitFloor - minKwh)
    const reserve = floor.effective_reserve_kwh ?? floor.base_reserve_kwh ?? 0
    const deficitKwh = Math.min(Math.max(0, reserve), buffer)
    const weatherKwh = buffer - deficitKwh
    const priceKwh = Math.max(0, finalFloor - deficitFloor)

    return {
        zones: [
            { key: 'min', label: 'Min SoC', kwh: minKwh },
            { key: 'deficit', label: 'Deficit', kwh: deficitKwh },
            { key: 'weather', label: 'Weather', kwh: weatherKwh },
            { key: 'price', label: 'Price', kwh: priceKwh },
            { key: 'tradable', label: 'Tradable', kwh: Math.max(0, capacityKwh - finalFloor) },
        ],
        floorKwh: finalFloor,
        capacityKwh,
    }
}

function weekdayOf(iso: string | null | undefined): string | null {
    if (!iso) return null
    const date = new Date(iso.replace(' ', 'T'))
    if (Number.isNaN(date.getTime())) return null
    return date.toLocaleDateString('en-GB', { weekday: 'long' })
}

function ore(sekPerKwh: number | null | undefined): string | null {
    return sekPerKwh == null ? null : `${Math.round(sekPerKwh * 100)} öre`
}

/** Plain-words explanation of the price reserve decision. */
// eslint-disable-next-line react-refresh/only-export-components -- pure helper, tested directly
export function describePriceReserve(floor: SafetyFloor | undefined): { title: string; detail: string | null } | null {
    if (!floor?.price_reserve_reason) return null
    const day = weekdayOf(floor.unseen_window_start) ?? 'the next unknown day'
    const now = ore(floor.known_cost_sek_kwh)
    const later = ore(floor.own_day_cost_sek_kwh)
    const compare = now && later ? `charging now ~${now} vs ~${later} on ${day}` : null

    switch (floor.price_reserve_reason) {
        case 'active': {
            const applied = floor.price_reserve_applied_kwh ?? 0
            const sized = floor.price_reserve_kwh ?? applied
            const cap =
                floor.price_reserve_capped_by === 'usable_capacity'
                    ? ' (limited by battery size)'
                    : floor.price_reserve_capped_by === 'known_window_charge'
                      ? ' (limited by charging time left)'
                      : ''
            const title =
                applied > 0.05
                    ? `Holding ${applied.toFixed(1)} kWh extra for ${day}`
                    : `${sized.toFixed(1)} kWh wanted for ${day}, already covered by the safety buffer`
            return { title, detail: compare ? `Cheaper to store it: ${compare}${cap}` : cap.trim() || null }
        }
        case 'own_day_cheaper':
            return {
                title: `No extra reserve: ${day} looks cheaper to charge`,
                detail: compare && `Compared ${compare}`,
            }
        case 'below_threshold':
            return {
                title: 'No extra reserve: price gap too small to pay off',
                detail: compare && `Compared ${compare}`,
            }
        case 'no_net_load':
            return { title: `No extra reserve: solar should cover ${day}`, detail: null }
        case 'no_charge_capacity':
            return { title: `No extra reserve: no charging time left before ${day}`, detail: null }
        case 'disabled':
            return { title: 'Price reserve is turned off', detail: null }
        default:
            return { title: 'No extra reserve: price forecast unavailable', detail: null }
    }
}

const SKELETON_HEIGHTS = [45, 70, 35, 60, 80, 50, 40]

const ZONE_COLOR: Record<FloorZoneKey, string> = {
    min: 'var(--color-muted)',
    deficit: 'var(--color-warn)',
    weather: 'var(--color-night)',
    price: 'var(--color-ai)',
    tradable: 'var(--color-good)',
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

    const breakdown = computeFloorBreakdown(safetyFloor, batteryCapacity)
    const reserve = describePriceReserve(safetyFloor)
    const reservePriceKwh = breakdown?.zones.find((z) => z.key === 'price')?.kwh ?? 0
    const socKwh = soc != null && batteryCapacity ? (soc / 100) * batteryCapacity : null
    const targetPct = socTarget != null ? Math.max(0, Math.min(100, socTarget)) : null
    const zoneStart = (key: FloorZoneKey) => {
        let start = 0
        for (const zone of breakdown?.zones ?? []) {
            if (zone.key === key) break
            start += zone.kwh
        }
        return start
    }

    // 3.1 Pixel sparkline logic
    const renderSparkline = () => {
        if (!priceOutlook || !priceOutlook.days || priceOutlook.days.length === 0) {
            return (
                <div className="flex-1 flex flex-col gap-1" aria-busy="true" aria-label="Loading price outlook">
                    <div className="price-sparkline price-sparkline-fill flex items-end justify-around gap-2 px-3 py-3">
                        {SKELETON_HEIGHTS.map((h, i) => (
                            <div
                                key={i}
                                className="skeleton w-full rounded-ds-sm"
                                style={{ height: `${h}%`, animationDelay: `${i * 120}ms` }}
                            />
                        ))}
                    </div>
                    <div className="skeleton h-5 w-full rounded-ds-sm" />
                </div>
            )
        }

        const days = priceOutlook.days.slice(0, 7)
        const prices = days.map((d) => d.avg_spot_p50 ?? 0)
        const { heights, refPercent } = computeSparklineBars(prices, priceOutlook.reference_avg)

        return (
            <div className="flex-1 flex flex-col gap-1">
                <div className="price-sparkline price-sparkline-fill">
                    <div className="price-sparkline-plot">
                        {refPercent != null && (
                            <div className="price-sparkline-ref" style={{ bottom: `${refPercent}%` }} />
                        )}
                        <div className="price-sparkline-bars">
                            {days.map((day, i) => {
                                const price = day.avg_spot_p50 ?? 0
                                const colorClass =
                                    {
                                        cheap: 'bg-good',
                                        normal: 'bg-warn',
                                        expensive: 'bg-bad',
                                        unknown: 'bg-muted',
                                    }[day.level] || 'bg-muted'

                                // Build tooltip with each value on separate line
                                const tooltipLines = [`${day.day_label}: ${price.toFixed(1)} öre`]
                                if (day.avg_spot_p10 != null)
                                    tooltipLines.push(`Min: ${day.avg_spot_p10.toFixed(1)} öre`)
                                if (day.avg_spot_p90 != null)
                                    tooltipLines.push(`Max: ${day.avg_spot_p90.toFixed(1)} öre`)
                                const tooltipText = tooltipLines.join('\n')

                                return (
                                    <div
                                        key={i}
                                        className="price-sparkline-col"
                                        onMouseEnter={(e) => showTooltip(e, tooltipText)}
                                        onMouseLeave={hideTooltip}
                                    >
                                        <div
                                            className={`price-sparkline-bar ${colorClass}`}
                                            style={{ height: `${heights[i]}%` }}
                                        />
                                    </div>
                                )
                            })}
                        </div>
                    </div>
                </div>
                <div className="price-sparkline-labels text-[10px] text-muted uppercase tracking-tighter">
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
        return <div className="text-xs text-muted">{message}</div>
    }

    return (
        <Card className="p-ds-4 flex flex-col h-full bg-surface">
            {/* Header */}
            <div className="flex items-center gap-2 mb-ds-3">
                <div className="p-1.5 rounded-ds-sm bg-ai/10 text-ai">
                    <Gauge className="h-4 w-4" />
                </div>
                <span className="text-sm font-medium text-text">Battery & Strategy</span>
                <span className="ml-auto text-xs text-muted tabular-nums">
                    {batteryCycles != null ? `${batteryCycles.toFixed(1)} cycles today` : ''}
                </span>
            </div>

            {/* SOC Section */}
            <div className="mb-ds-4">
                <div className="flex items-center gap-3 text-5xl font-bold leading-none tabular-nums">
                    <span className={`${(soc ?? 0) > 50 ? 'text-good' : (soc ?? 0) > 20 ? 'text-warn' : 'text-bad'}`}>
                        {soc?.toFixed(0) ?? '—'}%
                    </span>
                    <ArrowRight className="w-10 h-10 text-muted" strokeWidth={3} />
                    <span className="text-text">{socTarget?.toFixed(0) ?? '—'}%</span>
                </div>
                <div className="flex items-baseline justify-between gap-2 mt-ds-2">
                    {renderSocContext() ?? <span />}
                    <span className="text-sm text-muted tabular-nums shrink-0">
                        {socKwh != null ? socKwh.toFixed(1) : '—'} / {batteryCapacity?.toFixed(1) ?? '—'} kWh
                    </span>
                </div>
            </div>

            {/* Battery stack */}
            {breakdown ? (
                <div className="mb-ds-3">
                    <div className="battery-stack">
                        <div className="battery-stack-track">
                            {breakdown.zones
                                .filter((z) => z.kwh > 0.01)
                                .map((zone) => {
                                    const start = zoneStart(zone.key)
                                    const fillPct =
                                        socKwh == null ? 0 : Math.max(0, Math.min(1, (socKwh - start) / zone.kwh)) * 100
                                    return (
                                        <div
                                            key={zone.key}
                                            className="battery-stack-zone"
                                            style={
                                                {
                                                    width: `${(zone.kwh / breakdown.capacityKwh) * 100}%`,
                                                    '--zone-color': ZONE_COLOR[zone.key],
                                                } as React.CSSProperties
                                            }
                                            onMouseEnter={(e) =>
                                                showTooltip(e, `${zone.label}: ${zone.kwh.toFixed(1)} kWh`)
                                            }
                                            onMouseLeave={hideTooltip}
                                        >
                                            <div className="battery-stack-fill" style={{ width: `${fillPct}%` }} />
                                        </div>
                                    )
                                })}
                        </div>
                        {targetPct != null && (
                            <div className="battery-stack-marker bg-accent" style={{ left: `${targetPct}%` }} />
                        )}
                        <div
                            className="battery-stack-marker bg-text"
                            style={{ left: `${(breakdown.floorKwh / breakdown.capacityKwh) * 100}%` }}
                        />
                    </div>

                    <div className="flex justify-between items-baseline mt-ds-2">
                        <span className="text-xs text-muted uppercase tracking-wider">Held back</span>
                        <span className="text-base font-semibold text-text tabular-nums">
                            {breakdown.floorKwh.toFixed(1)} kWh
                            <span className="text-xs font-normal text-muted">
                                {' '}
                                · {((breakdown.floorKwh / breakdown.capacityKwh) * 100).toFixed(0)}%
                            </span>
                        </span>
                    </div>
                    <div className="grid grid-cols-2 gap-x-ds-4 gap-y-1 mt-1">
                        {breakdown.zones.map((zone) => (
                            <div
                                key={zone.key}
                                className={`flex items-center gap-1.5 text-xs ${
                                    zone.kwh > 0.01 ? 'text-text' : 'text-muted/60'
                                } ${zone.key === 'tradable' ? 'col-span-2 pt-1 mt-0.5 border-t border-line/30' : ''}`}
                            >
                                <span
                                    className="battery-stack-swatch"
                                    style={{ '--zone-color': ZONE_COLOR[zone.key] } as React.CSSProperties}
                                />
                                <span className="text-muted">{zone.label}</span>
                                <span className="ml-auto tabular-nums">{zone.kwh.toFixed(1)} kWh</span>
                            </div>
                        ))}
                    </div>
                </div>
            ) : (
                <div className="skeleton h-7 w-full mb-ds-3" />
            )}

            {/* Price reserve */}
            {reserve && (
                <div
                    className={`flex gap-2 mb-ds-3 p-ds-2 rounded-ds-sm ${
                        reservePriceKwh > 0.01 ? 'bg-ai/10 text-ai' : 'bg-surface2 text-muted'
                    }`}
                >
                    <ShieldCheck className="h-4 w-4 shrink-0 mt-px" />
                    <div className="flex flex-col min-w-0">
                        <span className={`text-xs font-medium ${reservePriceKwh > 0.01 ? 'text-text' : ''}`}>
                            {reserve.title}
                        </span>
                        {reserve.detail && <span className="text-xs text-muted">{reserve.detail}</span>}
                    </div>
                </div>
            )}

            {/* S-Index */}
            <div className="flex items-baseline gap-2 mb-ds-3 pb-ds-3 border-b border-line/30">
                <span className="text-xs text-muted uppercase tracking-wider">S-Index</span>
                <span className="text-base font-semibold text-text tabular-nums">
                    {sIndex?.effective_load_margin != null || sIndex?.risk_factor != null
                        ? `×${(sIndex?.effective_load_margin ?? sIndex?.risk_factor ?? 1).toFixed(2)}`
                        : '—'}
                </span>
                {sIndex?.avg_deficit != null && (
                    <span className="ml-auto text-xs text-muted tabular-nums truncate">
                        base {sIndex.base_factor?.toFixed(2) ?? '1.00'} · deficit +
                        {sIndex.avg_deficit?.toFixed(2) ?? '0.00'} · cold +
                        {sIndex.temp_adjustment?.toFixed(2) ?? '0.00'}
                    </span>
                )}
            </div>

            {/* Price Sparkline Section: grows into the remaining card height */}
            <div className="flex-1 flex flex-col min-h-[140px]">
                <div className="flex justify-between items-center mb-1">
                    <span className="text-xs text-muted uppercase tracking-wider">7-Day Price Outlook</span>
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
