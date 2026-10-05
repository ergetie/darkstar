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
    zeroY: number
}

const BAR_ZONE = 0.35 // bars use the bottom 35% of the chart, the net line the full height

/** Positions in a 0..100 box: one slot per hour of the day (or per day of the
 * period), faint import/export bars on their own scale and the running net cost
 * as a line scaled to its own range, with zero always inside it. */
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

    const barMax = Math.max(1e-6, ...series.points.map((p) => Math.max(p.import_cost_sek, p.export_revenue_sek)))
    const cum = series.points.map((p) => p.cumulative_net_cost_sek)
    const hi = Math.max(0, ...cum)
    const lo = Math.min(0, ...cum)
    const span = hi - lo || 1
    const pad = 8
    const yOf = (v: number) => pad + ((hi - v) / span) * (100 - 2 * pad)

    const bars = series.points.map((p) => ({
        index: indexOf(p.start),
        importH: (p.import_cost_sek / barMax) * BAR_ZONE * 100,
        exportH: (p.export_revenue_sek / barMax) * BAR_ZONE * 100,
    }))
    const line = series.points.map((p) => ({
        x: ((indexOf(p.start) + 1) / slots) * 100,
        y: yOf(p.cumulative_net_cost_sek),
    }))
    if (line.length > 0) line.unshift({ x: (bars[0].index / slots) * 100, y: yOf(0) })

    return { slots, bars, line, zeroY: yOf(0) }
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
    const last = geo.line[geo.line.length - 1]
    const area = `${path} L${last.x},${geo.zeroY} L${geo.line[0].x},${geo.zeroY} Z`
    const finalNet = series.points[series.points.length - 1].cumulative_net_cost_sek
    // Full class names so Tailwind can see them
    const tone =
        finalNet <= 0
            ? { bg: 'bg-good', text: 'text-good', stroke: 'stroke-good' }
            : { bg: 'bg-bad', text: 'text-bad', stroke: 'stroke-bad' }
    const hovered = hover != null ? series.points[hover] : null

    const labels =
        series.bucket === 'hour'
            ? ['00', '06', '12', '18', '24']
            : [series.start_date?.slice(5), series.end_date?.slice(5)].filter(Boolean)

    return (
        <div className={`flex-1 flex flex-col min-h-[120px] ${loading ? 'opacity-60' : ''} transition-opacity`}>
            <div className="flex items-baseline justify-between text-xs mb-1 h-4">
                <span className="text-muted uppercase tracking-wider">
                    {series.bucket === 'hour' ? 'Cost so far' : 'Cost per day'}
                </span>
                {hovered ? (
                    <span className="tabular-nums text-muted">
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
                    </span>
                ) : (
                    <span className="flex items-center gap-3 text-muted">
                        <span className="flex items-center gap-1">
                            <span className="h-2 w-2 rounded-sm bg-bad/60" /> import
                        </span>
                        <span className="flex items-center gap-1">
                            <span className="h-2 w-2 rounded-sm bg-good/60" /> export
                        </span>
                        <span className="flex items-center gap-1">
                            <span className={`h-0.5 w-3 rounded-full ${tone.bg}`} /> net
                        </span>
                    </span>
                )}
            </div>

            <div
                className="relative flex-1 rounded-ds-md bg-surface2/30 overflow-hidden"
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
                    <path
                        d={path}
                        fill="none"
                        className={tone.stroke}
                        strokeWidth="2"
                        strokeLinejoin="round"
                        vectorEffect="non-scaling-stroke"
                    />
                </svg>
                {/* End-of-line dot, in HTML so it stays round on the stretched SVG */}
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
                            />
                        )
                    })}
                </div>
            </div>
            <div className="flex justify-between text-[10px] text-muted tabular-nums mt-1">
                {labels.map((l) => (
                    <span key={l}>{l}</span>
                ))}
            </div>
        </div>
    )
}
