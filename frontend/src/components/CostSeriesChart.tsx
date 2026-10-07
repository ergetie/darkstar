import { useState } from 'react'
import type { CostSeriesResponse } from '../lib/api'

interface Props {
    series: CostSeriesResponse | null
    loading: boolean
}

export interface CostChartGeometry {
    slots: number
    bars: { index: number; importH: number; exportH: number }[]
    line: { x: number; y: number }[]
    /** "Without Darkstar" line on the same kr scale as `line`; null when no comparison amounts exist.
     * `pointIndex` is the matching index in `series.points`. Stops where the comparison stops. */
    without: { x: number; y: number; pointIndex: number }[] | null
    /** Without-Darkstar running total per series point (null where the comparison has no bucket). */
    withoutValues: (number | null)[]
    /** Shading between the actual and without lines, split per bucket pair and at line crossings
     * (linear interpolation). `good` = Darkstar cheaper than without; `bad` = dearer. Empty without a without line. */
    saving: { tone: 'good' | 'bad'; points: { x: number; y: number }[] }[]
    zeroY: number
}

const BAR_ZONE = 0.35 // bars use the bottom 35% of the chart, the net line the full height

/** Only comparisons with usable amounts feed the dotted line. */
function usableComparisonPoints(series: CostSeriesResponse) {
    const c = series.battery_comparison
    if (!c || (c.status !== 'available' && c.status !== 'estimated')) return []
    const pts = c.points ?? []
    return pts.every(
        (p) =>
            Number.isFinite(Date.parse(p.start)) &&
            Number.isFinite(p.darkstar_cumulative_comparison_cost_sek) &&
            Number.isFinite(p.self_use_cumulative_comparison_cost_sek),
    )
        ? pts
        : []
}

/** Positions in a 0..100 box: one slot per hour of the day (or per day of the
 * period), faint import/export bars on their own scale and the running net cost
 * as a line scaled to its own range, with zero always inside it. The without-Darkstar
 * running total (actual + self-use comparison - Darkstar comparison, per matching
 * bucket) shares that range so the two lines are comparable. */
// eslint-disable-next-line react-refresh/only-export-components -- pure helper, tested directly
export function computeCostChartGeometry(series: CostSeriesResponse): CostChartGeometry {
    const indexOf = (iso: string) => {
        const d = new Date(iso)
        if (series.bucket === 'hour') return d.getHours()
        const start = new Date(`${series.start_date}T00:00:00`)
        return Math.round((d.getTime() - start.getTime()) / 86_400_000)
    }
    const days =
        series.start_date && series.end_date
            ? Math.round(
                  (new Date(`${series.end_date}T00:00:00`).getTime() -
                      new Date(`${series.start_date}T00:00:00`).getTime()) /
                      86_400_000,
              ) + 1
            : series.points.length
    const slots = series.bucket === 'hour' ? 24 : Math.max(1, days)

    const delta = new Map<number, number>()
    for (const p of usableComparisonPoints(series)) {
        delta.set(
            Date.parse(p.start),
            p.self_use_cumulative_comparison_cost_sek - p.darkstar_cumulative_comparison_cost_sek,
        )
    }
    // Buckets inside excluded stretches of the comparison carry the last known
    // difference forward, so the line stays continuous; it still stops at the last
    // comparison point and does not start before the first one.
    const lastComparisonTime = Math.max(-Infinity, ...delta.keys())
    let carriedDelta: number | undefined
    const withoutValues = series.points.map((p) => {
        const time = Date.parse(p.start)
        const d = delta.get(time)
        if (d !== undefined) carriedDelta = d
        if (carriedDelta === undefined || time > lastComparisonTime) return null
        return p.cumulative_net_cost_sek + carriedDelta
    })

    const barMax = Math.max(1e-6, ...series.points.map((p) => Math.max(p.import_cost_sek, p.export_revenue_sek)))
    const cum = series.points.map((p) => p.cumulative_net_cost_sek)
    const scale = [...cum, ...withoutValues.filter((v): v is number => v != null)]
    const hi = Math.max(0, ...scale)
    const lo = Math.min(0, ...scale)
    const span = hi - lo || 1
    const pad = 8
    const yOf = (v: number) => pad + ((hi - v) / span) * (100 - 2 * pad)

    const bars = series.points.map((p) => ({
        index: indexOf(p.start),
        importH: (p.import_cost_sek / barMax) * BAR_ZONE * 100,
        exportH: (p.export_revenue_sek / barMax) * BAR_ZONE * 100,
    }))
    const xOf = (p: { start: string }) => ((indexOf(p.start) + 1) / slots) * 100
    const line = series.points.map((p) => ({ x: xOf(p), y: yOf(p.cumulative_net_cost_sek) }))
    if (line.length > 0) line.unshift({ x: (bars[0].index / slots) * 100, y: yOf(0) })

    let without: CostChartGeometry['without'] = null
    const matched = series.points.flatMap((p, i) =>
        withoutValues[i] == null ? [] : [{ x: xOf(p), y: yOf(withoutValues[i] as number), pointIndex: i }],
    )
    if (matched.length > 0) {
        without = matched
        // Start from zero at the left edge only when the comparison covers the first bucket.
        if (matched[0].pointIndex === 0) {
            without = [{ x: (bars[0].index / slots) * 100, y: yOf(0), pointIndex: 0 }, ...matched]
        }
    }

    // Pair each without point with the actual line at the same x (y grows with cost, so
    // the without line sitting higher on the chart means a saving).
    const saving: CostChartGeometry['saving'] = []
    if (without) {
        const pairs = without.map((w, k) => ({
            x: w.x,
            wy: w.y,
            ay: k === 0 && matched[0].pointIndex === 0 ? line[0].y : line[w.pointIndex + 1].y,
        }))
        const push = (tone: 'good' | 'bad', points: { x: number; y: number }[]) => saving.push({ tone, points })
        for (let k = 1; k < pairs.length; k++) {
            const a = pairs[k - 1]
            const b = pairs[k]
            const d0 = a.ay - a.wy
            const d1 = b.ay - b.wy
            if (d0 === 0 && d1 === 0) continue
            if (d0 * d1 < 0) {
                const t = d0 / (d0 - d1)
                const cx = a.x + (b.x - a.x) * t
                const cy = a.ay + (b.ay - a.ay) * t
                push(d0 > 0 ? 'good' : 'bad', [
                    { x: a.x, y: a.ay },
                    { x: cx, y: cy },
                    { x: a.x, y: a.wy },
                ])
                push(d1 > 0 ? 'good' : 'bad', [
                    { x: cx, y: cy },
                    { x: b.x, y: b.ay },
                    { x: b.x, y: b.wy },
                ])
            } else {
                push(d0 + d1 > 0 ? 'good' : 'bad', [
                    { x: a.x, y: a.ay },
                    { x: b.x, y: b.ay },
                    { x: b.x, y: b.wy },
                    { x: a.x, y: a.wy },
                ])
            }
        }
    }

    return { slots, bars, line, without, withoutValues, saving, zeroY: yOf(0) }
}

function formatKr(v: number): string {
    return `${v > 0 ? '-' : '+'}${Math.abs(v).toFixed(2)} kr`
}

export default function CostSeriesChart({ series, loading }: Props) {
    const [hover, setHover] = useState<number | null>(null)

    if (loading && !series) {
        return <div className="skeleton flex-1 min-h-[120px] w-full rounded-ds-md" aria-busy="true" />
    }
    if (!series || series.points.length === 0) {
        return (
            <div className="flex-1 min-h-[120px] flex items-center justify-center rounded-ds-md bg-surface2/30 text-xs text-muted">
                No recorded slots yet for this period
            </div>
        )
    }

    const geo = computeCostChartGeometry(series)
    const slotW = 100 / geo.slots
    const path = geo.line.map((p, i) => `${i === 0 ? 'M' : 'L'}${p.x},${p.y}`).join(' ')
    const withoutPath = geo.without ? geo.without.map((p, i) => `${i === 0 ? 'M' : 'L'}${p.x},${p.y}`).join(' ') : null
    const withoutLast = geo.without ? geo.without[geo.without.length - 1] : null
    const last = geo.line[geo.line.length - 1]
    const area = `${path} L${last.x},${geo.zeroY} L${geo.line[0].x},${geo.zeroY} Z`
    const finalNet = series.points[series.points.length - 1].cumulative_net_cost_sek
    // Full class names so Tailwind can see them
    const tone =
        finalNet <= 0
            ? { bg: 'bg-good', text: 'text-good', stroke: 'stroke-good' }
            : { bg: 'bg-bad', text: 'text-bad', stroke: 'stroke-bad' }
    const hovered = hover != null ? series.points[hover] : null
    const hoveredWithout = hover != null ? (geo.withoutValues[hover] ?? null) : null

    const labels =
        series.bucket === 'hour'
            ? ['00', '06', '12', '18', '24']
            : [series.start_date?.slice(5), series.end_date?.slice(5)].filter(Boolean)

    return (
        <div className={`flex-1 flex flex-col min-h-[120px] ${loading ? 'opacity-60' : ''} transition-opacity`}>
            <div className="text-xs mb-1" data-testid="cost-chart-header">
                <div className="h-4 whitespace-nowrap text-muted uppercase tracking-wider">
                    {series.bucket === 'hour' ? 'Actual cost so far' : 'Actual cost per day'}
                </div>
                {/* Own row below the heading: the legend (or hover readout) is too long to share a line at card width */}
                {hovered ? (
                    <div className="min-h-4 tabular-nums text-muted">
                        {series.bucket === 'hour'
                            ? new Date(hovered.start).toLocaleTimeString([], {
                                  hour: '2-digit',
                                  minute: '2-digit',
                                  hour12: false,
                              })
                            : new Date(hovered.start).toLocaleDateString([], { weekday: 'short', day: 'numeric' })}
                        {' · '}
                        <span className="text-bad">-{hovered.import_cost_sek.toFixed(2)}</span>
                        {' / '}
                        <span className="text-good">+{hovered.export_revenue_sek.toFixed(2)}</span>
                        {' · total '}
                        <span className="text-text">{formatKr(hovered.cumulative_net_cost_sek)}</span>
                        {hoveredWithout != null && (
                            <>
                                {' · without '}
                                <span className="text-text">{formatKr(hoveredWithout)}</span>
                            </>
                        )}
                    </div>
                ) : (
                    <div className="flex min-h-4 flex-wrap items-center gap-x-3 gap-y-0.5 text-muted">
                        <span className="flex items-center gap-1 whitespace-nowrap">
                            <span className="h-2 w-2 rounded-sm bg-bad/60" /> import
                        </span>
                        <span className="flex items-center gap-1 whitespace-nowrap">
                            <span className="h-2 w-2 rounded-sm bg-good/60" /> export
                        </span>
                        <span className="flex items-center gap-1 whitespace-nowrap">
                            <span className={`h-0.5 w-3 rounded-full ${tone.bg}`} /> Actual
                        </span>
                        {geo.without && (
                            <span className="flex items-center gap-1 whitespace-nowrap">
                                <span className="w-3 border-t-2 border-dotted border-muted" /> Without Darkstar
                            </span>
                        )}
                    </div>
                )}
            </div>

            <div
                className="relative flex-1 min-h-[90px] rounded-ds-md bg-surface2/30 overflow-hidden"
                onMouseLeave={() => setHover(null)}
            >
                <svg
                    className="absolute inset-0 h-full w-full cost-chart-reveal"
                    viewBox="0 0 100 100"
                    preserveAspectRatio="none"
                >
                    <defs>
                        <linearGradient id="cost-area" x1="0" y1="0" x2="0" y2="1">
                            <stop offset="0%" className={tone.text} stopColor="currentColor" stopOpacity="0.25" />
                            <stop offset="100%" className={tone.text} stopColor="currentColor" stopOpacity="0" />
                        </linearGradient>
                    </defs>
                    {geo.bars.map((b, i) => (
                        <g key={i} className="cost-chart-bar" style={{ animationDelay: `${i * 15}ms` }}>
                            <rect
                                x={b.index * slotW + slotW * 0.15}
                                width={slotW * 0.35}
                                y={100 - b.importH}
                                height={b.importH}
                                className={`fill-bad ${hover === i ? 'opacity-90' : 'opacity-40'}`}
                            />
                            <rect
                                x={b.index * slotW + slotW * 0.5}
                                width={slotW * 0.35}
                                y={100 - b.exportH}
                                height={b.exportH}
                                className={`fill-good ${hover === i ? 'opacity-90' : 'opacity-40'}`}
                            />
                        </g>
                    ))}
                    <line
                        x1="0"
                        x2="100"
                        y1={geo.zeroY}
                        y2={geo.zeroY}
                        className="stroke-line"
                        strokeDasharray="1.5 1.5"
                        vectorEffect="non-scaling-stroke"
                    />
                    <path d={area} fill="url(#cost-area)" className="cost-chart-area" />
                    {geo.saving.map((seg, i) => (
                        <path
                            key={i}
                            data-testid="cost-chart-saving"
                            d={`${seg.points.map((p, j) => `${j === 0 ? 'M' : 'L'}${p.x},${p.y}`).join(' ')} Z`}
                            className={seg.tone === 'good' ? 'fill-good' : 'fill-bad'}
                            fillOpacity="0.3"
                        />
                    ))}
                    {withoutPath && (
                        <path
                            d={withoutPath}
                            fill="none"
                            className="stroke-muted"
                            strokeWidth="1.5"
                            strokeDasharray="1 3"
                            strokeLinecap="round"
                            vectorEffect="non-scaling-stroke"
                        />
                    )}
                    <path
                        d={path}
                        fill="none"
                        className={tone.stroke}
                        strokeWidth="2"
                        strokeLinejoin="round"
                        vectorEffect="non-scaling-stroke"
                    />
                </svg>
                {/* End-of-line dots, in HTML so they stay round on the stretched SVG */}
                {withoutLast && (
                    <span
                        className="absolute h-1.5 w-1.5 -translate-x-1/2 -translate-y-1/2 rounded-full bg-muted ring-2 ring-surface"
                        style={{ left: `${withoutLast.x}%`, top: `${withoutLast.y}%` }}
                    />
                )}
                <span
                    className={`absolute h-2 w-2 -translate-x-1/2 -translate-y-1/2 rounded-full ${tone.bg} ring-2 ring-surface`}
                    style={{ left: `${last.x}%`, top: `${last.y}%` }}
                />
                {/* Hover targets, one per bucket */}
                <div className="absolute inset-0 flex">
                    {Array.from({ length: geo.slots }, (_, slot) => {
                        const i = geo.bars.findIndex((b) => b.index === slot)
                        return (
                            <div
                                key={slot}
                                className={`h-full flex-1 ${i >= 0 && hover === i ? 'bg-text/5' : ''}`}
                                onMouseEnter={() => setHover(i >= 0 ? i : null)}
                                onClick={() => setHover(i >= 0 ? i : null)}
                            />
                        )
                    })}
                </div>
            </div>
            <div className="flex justify-between text-[10px] text-muted tabular-nums mt-1">
                {labels.map((l, index) => (
                    <span key={`${index}-${l}`}>{l}</span>
                ))}
            </div>
        </div>
    )
}
