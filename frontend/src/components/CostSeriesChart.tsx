import { useMemo, useState } from 'react'
import type { CostSeriesPoint, CostSeriesResponse, GridOnlyBucketPoint } from '../lib/api'

interface Props {
    series: CostSeriesResponse | null
    loading: boolean
    seriesError?: boolean
}

type PlotPoint = { x: number; y: number; value: number; time: number }
type SavingShape = { tone: 'good' | 'bad'; points: { x: number; y: number }[] }
type Bar = {
    index: number
    left: number
    width: number
    importH: number
    exportH: number
    importCost: number
    exportRevenue: number
    dsRunning: number | null
    gridRunning: number | null
    actualRunning: number | null
    start: string
    end: string
}
type AxisTick = { x: number; label: string; row: 0 | 1; align: 'start' | 'center' | 'end' }

export interface CostChartGeometry {
    slots: number
    bars: Bar[]
    actualSegments: PlotPoint[][]
    dsSegments: { tone: 'good' | 'bad'; points: PlotPoint[] }[]
    gridSegments: PlotPoint[][]
    saving: SavingShape[]
    ticks: AxisTick[]
    zeroY: number
    hasComparison: boolean
}

const BAR_ZONE = 30
const PAD = 8

function localParts(timestamp: number, timezone: string) {
    const parts = new Intl.DateTimeFormat('en-CA', {
        timeZone: timezone,
        year: 'numeric',
        month: '2-digit',
        day: '2-digit',
        hour: '2-digit',
        minute: '2-digit',
        hourCycle: 'h23',
    }).formatToParts(new Date(timestamp))
    const get = (key: string) => Number(parts.find((part) => part.type === key)?.value ?? 0)
    return { year: get('year'), month: get('month'), day: get('day'), hour: get('hour'), minute: get('minute') }
}

function localMidnightEpoch(timestamp: number, timezone: string, addDays = 0): number {
    const local = localParts(timestamp, timezone)
    const targetDate = new Date(Date.UTC(local.year, local.month - 1, local.day + addDays))
    const target = Date.UTC(targetDate.getUTCFullYear(), targetDate.getUTCMonth(), targetDate.getUTCDate())
    let candidate = target
    for (let attempt = 0; attempt < 5; attempt += 1) {
        const represented = localParts(candidate, timezone)
        const representedAsUtc = Date.UTC(
            represented.year,
            represented.month - 1,
            represented.day,
            represented.hour,
            represented.minute,
        )
        const delta = target - representedAsUtc
        if (delta === 0) return candidate
        candidate += delta
    }
    return candidate
}

function offsetLabel(timestamp: number, timezone: string): string {
    const local = localParts(timestamp, timezone)
    const localAsUtc = Date.UTC(local.year, local.month - 1, local.day, local.hour, local.minute)
    const minutes = Math.round((localAsUtc - timestamp) / 60_000)
    const sign = minutes < 0 ? '−' : '+'
    const absolute = Math.abs(minutes)
    return `${sign}${String(Math.floor(absolute / 60)).padStart(2, '0')}:${String(absolute % 60).padStart(2, '0')}`
}

function hourKey(timestamp: number, timezone: string): string {
    const local = localParts(timestamp, timezone)
    return `${local.year}-${local.month}-${local.day}T${local.hour}`
}

function formatHour(timestamp: number, timezone: string, includeOffset: boolean): string {
    const local = localParts(timestamp, timezone)
    const time = `${String(local.hour).padStart(2, '0')}:${String(local.minute).padStart(2, '0')}`
    return includeOffset ? `${time} ${offsetLabel(timestamp, timezone)}` : time
}

function formatDay(timestamp: number, timezone: string): string {
    const parts = localParts(timestamp, timezone)
    const date = new Date(Date.UTC(parts.year, parts.month - 1, parts.day))
    return new Intl.DateTimeFormat('en-GB', { timeZone: 'UTC', day: '2-digit', month: '2-digit' }).format(date)
}

function buildTicks(axisStart: number, axisEnd: number, hourly: boolean, timezone: string): AxisTick[] {
    const duration = axisEnd - axisStart
    const position = (time: number) => ((time - axisStart) / duration) * 100
    if (!hourly) {
        return [
            { x: 0, label: formatDay(axisStart, timezone), row: 1, align: 'start' },
            { x: 100, label: formatDay(axisEnd - 1, timezone), row: 1, align: 'end' },
        ]
    }

    const ticks: { time: number; elapsedHours: number; key: string }[] = []
    for (let time = axisStart, elapsedHours = 0; time <= axisEnd; time += 3_600_000, elapsedHours += 1) {
        ticks.push({ time: Math.min(time, axisEnd), elapsedHours, key: hourKey(Math.min(time, axisEnd), timezone) })
        if (time + 3_600_000 > axisEnd) break
    }
    const keyCounts = new Map<string, number>()
    for (const tick of ticks) keyCounts.set(tick.key, (keyCounts.get(tick.key) ?? 0) + 1)
    const totalHours = duration / 3_600_000
    const repeatedIndexes = new Map<string, number>()
    return ticks
        .filter(
            (tick, index) =>
                index === 0 ||
                tick.time === axisEnd ||
                tick.elapsedHours % 6 === 0 ||
                (keyCounts.get(tick.key) ?? 0) > 1,
        )
        .map((tick) => {
            const repeated = (keyCounts.get(tick.key) ?? 0) > 1
            const repeatedIndex = repeatedIndexes.get(tick.key) ?? 0
            repeatedIndexes.set(tick.key, repeatedIndex + 1)
            const label = tick.time === axisEnd ? String(totalHours) : formatHour(tick.time, timezone, repeated)
            return {
                x: position(tick.time),
                label,
                row: repeated ? ((repeatedIndex % 2) as 0 | 1) : tick.time === axisEnd && totalHours > 24 ? 0 : 1,
                align:
                    repeated && repeatedIndex === 1
                        ? 'start'
                        : tick.time === axisStart
                          ? 'start'
                          : tick.time === axisEnd
                            ? 'end'
                            : 'center',
            }
        })
}

function compactAxisLabel(label: string): string {
    const repeatedHour = /^(\d{2}):\d{2} ([+−-])(\d{2}):(\d{2})$/.exec(label)
    if (!repeatedHour) return label
    const [, hour, sign, offsetHour, offsetMinute] = repeatedHour
    return `${hour}${sign}${offsetMinute === '00' ? Number(offsetHour) : `${Number(offsetHour)}:${offsetMinute}`}`
}

function splitDsAtZero(points: PlotPoint[]): { tone: 'good' | 'bad'; points: PlotPoint[] }[] {
    const result: { tone: 'good' | 'bad'; points: PlotPoint[] }[] = []
    const append = (tone: 'good' | 'bad', segment: PlotPoint[]) => {
        const previous = result[result.length - 1]
        if (previous?.tone === tone && previous.points[previous.points.length - 1]?.time === segment[0]?.time) {
            previous.points.push(...segment.slice(1))
        } else {
            result.push({ tone, points: segment })
        }
    }
    for (let index = 1; index < points.length; index += 1) {
        const a = points[index - 1]
        const b = points[index]
        const toneFor = (value: number): 'good' | 'bad' => (value <= 0 ? 'good' : 'bad')
        if (a.value * b.value < 0) {
            const t = a.value / (a.value - b.value)
            const cross: PlotPoint = {
                time: a.time + (b.time - a.time) * t,
                x: a.x + (b.x - a.x) * t,
                y: a.y + (b.y - a.y) * t,
                value: 0,
            }
            append(toneFor(a.value), [a, cross])
            append(toneFor(b.value), [cross, b])
        } else {
            append(toneFor((a.value + b.value) / 2), [a, b])
        }
    }
    if (points.length === 1) append(points[0].value <= 0 ? 'good' : 'bad', points)
    return result
}

function makeSavingShapes(ds: PlotPoint[][], grid: PlotPoint[][]): SavingShape[] {
    const shapes: SavingShape[] = []
    const pushPair = (a: PlotPoint, b: PlotPoint, gridA: PlotPoint, gridB: PlotPoint) => {
        const differenceA = gridA.value - a.value
        const differenceB = gridB.value - b.value
        if (differenceA === 0 && differenceB === 0) return
        const polygon = (ds0: PlotPoint, ds1: PlotPoint, grid0: PlotPoint, grid1: PlotPoint, toneValue: number) => {
            const tone = toneValue >= 0 ? 'good' : 'bad'
            shapes.push({ tone, points: [ds0, ds1, grid1, grid0].map(({ x, y }) => ({ x, y })) })
        }
        if (differenceA * differenceB < 0) {
            const t = differenceA / (differenceA - differenceB)
            const crossDs: PlotPoint = {
                ...a,
                x: a.x + (b.x - a.x) * t,
                y: a.y + (b.y - a.y) * t,
                value: a.value + (b.value - a.value) * t,
                time: a.time + (b.time - a.time) * t,
            }
            const crossGrid: PlotPoint = {
                ...gridA,
                x: gridA.x + (gridB.x - gridA.x) * t,
                y: gridA.y + (gridB.y - gridA.y) * t,
                value: gridA.value + (gridB.value - gridA.value) * t,
                time: gridA.time + (gridB.time - gridA.time) * t,
            }
            polygon(a, crossDs, gridA, crossGrid, differenceA)
            polygon(crossDs, b, crossGrid, gridB, differenceB)
        } else {
            polygon(a, b, gridA, gridB, differenceA + differenceB)
        }
    }
    ds.forEach((segment, index) => {
        const gridSegment = grid[index]
        if (!gridSegment || segment.length !== gridSegment.length) return
        for (let point = 1; point < segment.length; point += 1) {
            pushPair(segment[point - 1], segment[point], gridSegment[point - 1], gridSegment[point])
        }
    })
    return shapes
}

/** Pure geometry uses the full installation-local period and elapsed UTC time. */
// eslint-disable-next-line react-refresh/only-export-components -- pure helper, tested directly
export function computeCostChartGeometry(series: CostSeriesResponse): CostChartGeometry {
    const comparison = series.grid_only_comparison
    const axis = comparison?.time_axis
    const timezone = axis?.timezone ?? 'UTC'
    const axisStart = axis ? Date.parse(axis.start) : Math.min(...series.points.map((point) => Date.parse(point.start)))
    const fallbackEnd = axisStart + (series.bucket === 'hour' ? 24 : 86_400) * 3_600_000
    const axisEnd = axis ? Date.parse(axis.end) : fallbackEnd
    const duration = Math.max(1, axisEnd - axisStart)
    const hasComparison = !!comparison && (comparison.status === 'available' || comparison.status === 'partial')
    const comparisonPoints = hasComparison && comparison && 'points' in comparison ? comparison.points : []
    const dataBars: (GridOnlyBucketPoint | CostSeriesPoint)[] = hasComparison ? comparisonPoints : series.points
    const barMax = Math.max(
        1e-6,
        ...dataBars.flatMap((point) => [Math.abs(point.import_cost_sek), Math.abs(point.export_revenue_sek)]),
    )
    const bars: Bar[] = dataBars.map((point, index) => {
        const start = Date.parse(point.start)
        const end =
            'end' in point
                ? Date.parse(point.end)
                : series.bucket === 'hour'
                  ? start + 3_600_000
                  : localMidnightEpoch(start, timezone, 1)
        const left = ((start - axisStart) / duration) * 100
        const width = Math.max(0, ((end - start) / duration) * 100)
        const importH = (Math.abs(point.import_cost_sek) / barMax) * BAR_ZONE
        const exportH = (Math.abs(point.export_revenue_sek) / barMax) * BAR_ZONE
        return {
            index,
            left,
            width,
            importH,
            exportH,
            importCost: point.import_cost_sek,
            exportRevenue: point.export_revenue_sek,
            dsRunning: 'cumulative_ds_cost_sek' in point ? point.cumulative_ds_cost_sek : null,
            gridRunning: 'cumulative_grid_only_cost_sek' in point ? point.cumulative_grid_only_cost_sek : null,
            actualRunning: 'cumulative_net_cost_sek' in point ? point.cumulative_net_cost_sek : null,
            start: point.start,
            end: 'end' in point ? point.end : new Date(end).toISOString(),
        }
    })

    const values: number[] = [0]
    let actualSegments: PlotPoint[][] = []
    const dsRawSegments: PlotPoint[][] = []
    const gridRawSegments: PlotPoint[][] = []
    const xOf = (time: number) => ((time - axisStart) / duration) * 100

    if (hasComparison && comparison) {
        for (const segment of comparison.segments) {
            const ds: PlotPoint[] = []
            const grid: PlotPoint[] = []
            for (const point of segment.points) {
                const time = Date.parse(point.at)
                const dsValue = point.cumulative_ds_cost_sek
                const gridValue = point.cumulative_grid_only_cost_sek
                values.push(dsValue, gridValue)
                ds.push({ x: xOf(time), y: 0, value: dsValue, time })
                grid.push({ x: xOf(time), y: 0, value: gridValue, time })
            }
            dsRawSegments.push(ds)
            gridRawSegments.push(grid)
        }
    } else if (series.points.length > 0) {
        let actual = 0
        const points: PlotPoint[] = [{ x: xOf(axisStart), y: 0, value: 0, time: axisStart }]
        for (const point of series.points) {
            actual = point.cumulative_net_cost_sek
            const start = Date.parse(point.start)
            const end = series.bucket === 'hour' ? start + 3_600_000 : localMidnightEpoch(start, timezone, 1)
            values.push(actual)
            points.push({ x: xOf(end), y: 0, value: actual, time: end })
        }
        actualSegments = [points]
    }

    const high = Math.max(0, ...values)
    const low = Math.min(0, ...values)
    const span = high - low || 1
    const yOf = (value: number) => PAD + ((high - value) / span) * (100 - 2 * PAD)
    const withY = (points: PlotPoint[][]) =>
        points.map((segment) => segment.map((point) => ({ ...point, y: yOf(point.value) })))
    const actualWithY = withY(actualSegments)
    const dsSegments = withY(dsRawSegments).flatMap((segment) => splitDsAtZero(segment))
    const gridSegments = withY(gridRawSegments)
    const saving = makeSavingShapes(withY(dsRawSegments), gridSegments)
    const zeroY = yOf(0)

    if (!hasComparison && actualWithY.length > 0) {
        const final = actualWithY[0][actualWithY[0].length - 1]?.value ?? 0
        const areaStart = actualWithY[0][0]
        const areaEnd = actualWithY[0][actualWithY[0].length - 1]
        if (areaStart && areaEnd) {
            saving.push({
                tone: final <= 0 ? 'good' : 'bad',
                points: [
                    { x: areaStart.x, y: zeroY },
                    ...actualWithY[0].map(({ x, y }) => ({ x, y })),
                    { x: areaEnd.x, y: zeroY },
                ],
            })
        }
    }

    return {
        slots: duration / (series.bucket === 'hour' ? 3_600_000 : 86_400_000),
        bars,
        actualSegments: actualWithY,
        dsSegments,
        gridSegments,
        saving,
        ticks: buildTicks(axisStart, axisEnd, series.bucket === 'hour', timezone),
        zeroY,
        hasComparison,
    }
}

function formatKr(value: number): string {
    return `${value > 0 ? '−' : value < 0 ? '+' : ''}${Math.abs(value).toFixed(2)} kr`
}

function pathOf(points: Pick<PlotPoint, 'x' | 'y'>[]): string {
    return points.map((point, index) => `${index === 0 ? 'M' : 'L'}${point.x},${point.y}`).join(' ')
}

export default function CostSeriesChart({ series, loading, seriesError = false }: Props) {
    const [hover, setHover] = useState<number | null>(null)
    const hasComparisonPoints =
        !!series?.grid_only_comparison &&
        (series.grid_only_comparison.status === 'available' || series.grid_only_comparison.status === 'partial') &&
        series.grid_only_comparison.points.length > 0
    const hasRenderablePoints = !!series && (series.points.length > 0 || hasComparisonPoints)
    const geometry = useMemo(
        () => (hasRenderablePoints && series ? computeCostChartGeometry(series) : null),
        [hasRenderablePoints, series],
    )

    if (loading && !series) {
        return <div className="skeleton flex-1 min-h-[120px] w-full rounded-ds-md" aria-busy="true" />
    }
    if (seriesError && !series) {
        return (
            <div
                className="flex-1 min-h-[120px] flex items-center justify-center rounded-ds-md bg-surface2/30 text-xs text-muted"
                role="status"
                data-testid="cost-chart-error"
            >
                Unable to load chart data for this period
            </div>
        )
    }
    if (!series || !hasRenderablePoints) {
        return (
            <div className="flex-1 min-h-[120px] flex items-center justify-center rounded-ds-md bg-surface2/30 text-xs text-muted">
                No recorded slots yet for this period
            </div>
        )
    }
    if (!geometry) return null

    const hovered = hover === null ? null : (geometry.bars[hover] ?? null)
    const comparison = series.grid_only_comparison
    const timezone = comparison?.time_axis.timezone ?? 'UTC'
    const repeatedHours = new Map<string, number>()
    const axis = comparison?.time_axis
    const hourStarts =
        axis && series.bucket === 'hour'
            ? Array.from(
                  { length: Math.ceil((Date.parse(axis.end) - Date.parse(axis.start)) / 3_600_000) },
                  (_, index) => Date.parse(axis.start) + index * 3_600_000,
              )
            : geometry.bars.map((bar) => Date.parse(bar.start))
    for (const start of hourStarts) {
        const key = hourKey(start, timezone)
        repeatedHours.set(key, (repeatedHours.get(key) ?? 0) + 1)
    }
    const hoveredLabel = hovered
        ? series.bucket === 'hour'
            ? formatHour(
                  Date.parse(hovered.start),
                  timezone,
                  (repeatedHours.get(hourKey(Date.parse(hovered.start), timezone)) ?? 0) > 1,
              )
            : formatDay(Date.parse(hovered.start), timezone)
        : null
    const lineTone = series.points[series.points.length - 1]?.cumulative_net_cost_sek ?? 0
    const actualTone = lineTone <= 0 ? 'stroke-good' : 'stroke-bad'
    const compareBarItems = geometry.bars

    return (
        <div className={`flex-1 flex flex-col min-h-[120px] ${loading ? 'opacity-60' : ''} transition-opacity`}>
            <div className="text-xs mb-1" data-testid="cost-chart-header">
                <div className="h-4 whitespace-nowrap text-muted uppercase tracking-wider">
                    {series.bucket === 'hour' ? 'Actual cost so far' : 'Actual cost per day'}
                </div>
                {hovered ? (
                    <div className="min-h-4 tabular-nums text-muted" data-testid="cost-chart-readout">
                        {hoveredLabel} · <span className="text-bad">{formatKr(hovered.importCost)}</span> import /{' '}
                        <span className="text-good">
                            {hovered.exportRevenue > 0 ? '+' : hovered.exportRevenue < 0 ? '−' : ''}
                            {Math.abs(hovered.exportRevenue).toFixed(2)} kr
                        </span>{' '}
                        export
                        {geometry.hasComparison ? (
                            <>
                                {' · DS '}
                                <span className="text-text">{formatKr(hovered.dsRunning ?? 0)}</span>
                                {' · Grid-only '}
                                <span className="text-text">{formatKr(hovered.gridRunning ?? 0)}</span>
                            </>
                        ) : (
                            <>
                                {' · Actual '}
                                <span className="text-text">{formatKr(hovered.actualRunning ?? 0)}</span>
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
                        {geometry.hasComparison ? (
                            <>
                                <span className="flex items-center gap-1 whitespace-nowrap">
                                    <span className="h-0.5 w-3 rounded-full bg-good" /> DS
                                </span>
                                <span className="flex items-center gap-1 whitespace-nowrap">
                                    <span className="w-3 border-t-2 border-dotted border-muted" /> Grid-only
                                </span>
                            </>
                        ) : (
                            <span className="flex items-center gap-1 whitespace-nowrap">
                                <span className="h-0.5 w-3 rounded-full bg-good" /> Actual
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
                    aria-hidden="true"
                >
                    <line
                        x1="0"
                        x2="100"
                        y1={geometry.zeroY}
                        y2={geometry.zeroY}
                        className="stroke-line"
                        strokeDasharray="1.5 1.5"
                        vectorEffect="non-scaling-stroke"
                    />
                    {geometry.bars.map((bar) => (
                        <g key={bar.index} className="cost-chart-bar" style={{ animationDelay: `${bar.index * 15}ms` }}>
                            <rect
                                x={bar.left + bar.width * 0.12}
                                width={bar.width * 0.35}
                                y={100 - bar.importH}
                                height={bar.importH}
                                className={`fill-bad ${hover === bar.index ? 'opacity-90' : 'opacity-40'}`}
                            />
                            <rect
                                x={bar.left + bar.width * 0.53}
                                width={bar.width * 0.35}
                                y={100 - bar.exportH}
                                height={bar.exportH}
                                className={`fill-good ${hover === bar.index ? 'opacity-90' : 'opacity-40'}`}
                            />
                        </g>
                    ))}
                    {geometry.saving.map((shape, index) => (
                        <path
                            key={`saving-${index}`}
                            data-testid="cost-chart-saving"
                            d={`${pathOf(shape.points)} Z`}
                            className={shape.tone === 'good' ? 'fill-good' : 'fill-bad'}
                            fillOpacity={geometry.hasComparison ? 0.18 : 0.1}
                        />
                    ))}
                    {geometry.hasComparison ? (
                        <>
                            {geometry.gridSegments.map((segment, index) => (
                                <path
                                    key={`grid-${index}`}
                                    data-testid="grid-only-line"
                                    d={pathOf(segment)}
                                    fill="none"
                                    className="stroke-muted"
                                    strokeWidth="1.5"
                                    strokeDasharray="1 3"
                                    strokeLinecap="round"
                                    vectorEffect="non-scaling-stroke"
                                />
                            ))}
                            {geometry.dsSegments.map((segment, index) => (
                                <path
                                    key={`ds-${index}`}
                                    data-testid="ds-line"
                                    d={pathOf(segment.points)}
                                    fill="none"
                                    className={segment.tone === 'good' ? 'stroke-good' : 'stroke-bad'}
                                    strokeWidth="2"
                                    strokeLinejoin="round"
                                    vectorEffect="non-scaling-stroke"
                                />
                            ))}
                        </>
                    ) : (
                        geometry.actualSegments.map((segment, index) => (
                            <path
                                key={`actual-${index}`}
                                data-testid="actual-line"
                                d={pathOf(segment)}
                                fill="none"
                                className={actualTone}
                                strokeWidth="2"
                                strokeLinejoin="round"
                                vectorEffect="non-scaling-stroke"
                            />
                        ))
                    )}
                </svg>
                <div className="absolute inset-0" aria-label="Cost-series chart buckets">
                    {compareBarItems.map((bar) => (
                        <button
                            key={bar.index}
                            type="button"
                            aria-label={`${series.bucket === 'hour' ? 'Hour' : 'Day'} ${series.bucket === 'hour' ? formatHour(Date.parse(bar.start), timezone, (repeatedHours.get(hourKey(Date.parse(bar.start), timezone)) ?? 0) > 1) : formatDay(Date.parse(bar.start), timezone)} cost details`}
                            className={`absolute top-0 h-full ${hover === bar.index ? 'bg-text/5' : ''}`}
                            style={{ left: `${bar.left}%`, width: `${Math.max(bar.width, 0.25)}%` }}
                            onMouseEnter={() => setHover(bar.index)}
                            onFocus={() => setHover(bar.index)}
                            onBlur={() => setHover(null)}
                            onClick={() => setHover((current) => (current === bar.index ? null : bar.index))}
                        />
                    ))}
                </div>
            </div>
            <div className="relative h-8 text-[10px] text-muted tabular-nums mt-1">
                {geometry.ticks.map((tick, index) => (
                    <span
                        key={`${tick.x}-${tick.label}-${index}`}
                        title={tick.label}
                        className="absolute whitespace-nowrap"
                        style={{
                            left: `${tick.x}%`,
                            top: `${tick.row * 16}px`,
                            transform:
                                tick.align === 'start'
                                    ? 'translateX(0)'
                                    : tick.align === 'end'
                                      ? 'translateX(-100%)'
                                      : 'translateX(-50%)',
                        }}
                    >
                        {compactAxisLabel(tick.label)}
                    </span>
                ))}
            </div>
        </div>
    )
}
