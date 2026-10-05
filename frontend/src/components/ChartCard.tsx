import Card from './Card'
import { useEffect, useMemo, useRef, useState } from 'react'
import { Chart as ChartJS, ChartConfiguration, ChartDataset, Plugin, ScriptableContext } from 'chart.js/auto'
import type { Chart, Scale, Tick, ChartData } from 'chart.js/auto'
import zoomPlugin from 'chartjs-plugin-zoom'
ChartJS.register(zoomPlugin)
import { sampleChart } from '../lib/sample'
import { Api, type ConfigResponse } from '../lib/api'
import type { ScheduleSlot } from '../lib/types'
import { formatHour, DaySel, isToday, isTomorrow, wallClockParts } from '../lib/time'
import { hourLabelStep, hourOfLabel } from '../lib/chartTicks'
import { transferFeeAt, transferFeeConfigFromPricing, type TransferFeeConfig } from '../pages/settings/transferFees'
import { gridAlpha, isDarkTheme, token, type ChartToken } from '../lib/chartTokens'
import {
    ACTION_TOKEN,
    buildCompactLine,
    buildSlotInfo,
    estimatedRanges,
    isEstimatedSlot,
    type PriceSourceFields,
    priceAxisMax,
    slotMarkKinds,
    splitActualPlan,
    type ActionKind,
    type ActionSeries,
    type Series,
    type SlotSeries,
} from './ChartCard.logic'
// Note: We use a custom plugin for the NOW marker to support zooming.
// CSS overlays don't work well with pan/zoom.

// Fixed bar height for the "EV standby" band — keep-on slots carry no planned
// energy, so this is a presence indicator, not a real kW value.
const EV_STANDBY_BAND_KW = 0.3

// Hook: returns true when viewport is below Tailwind's `md` breakpoint (768px)
const EV_AWAITING_PLUG_IN_LABEL = 'EV Planned — Awaiting Plug-in'

function useIsMobile(): boolean {
    const [isMobile, setIsMobile] = useState(() => {
        if (typeof window === 'undefined') return false
        return window.matchMedia('(max-width: 767px)').matches
    })
    useEffect(() => {
        const mq = window.matchMedia('(max-width: 767px)')
        const handler = (e: MediaQueryListEvent) => setIsMobile(e.matches)
        mq.addEventListener('change', handler)
        return () => mq.removeEventListener('change', handler)
    }, [])
    return isMobile
}

/** Pricing inputs needed to split an import price into spot and fees+VAT. */
export interface PricingBreakdownConfig {
    vat: number
    energyTax: number
    transferFee: TransferFeeConfig
    /** Configured IANA timezone (`config.timezone`); the backend matches rules in this zone. */
    timezone: string
}

/** Backend fallback when `timezone` is unset in config. */
const DEFAULT_TIMEZONE = 'Europe/Stockholm'

/** Breakdown inputs from `/api/config`; `null` when the config has no `pricing` section. */
// eslint-disable-next-line react-refresh/only-export-components -- pure helper, tested directly
export function pricingBreakdownFromConfig(config: ConfigResponse): PricingBreakdownConfig | null {
    const p = config.pricing
    if (!p) return null
    return {
        vat: p.vat_percent ?? 25,
        energyTax: p.energy_tax_sek ?? 0,
        transferFee: transferFeeConfigFromPricing(p),
        timezone: config.timezone || DEFAULT_TIMEZONE,
    }
}

/** Splits a total SEK/kWh price into spot and fees+VAT parts.
 * Total = (Spot + Fees) * (1 + VAT/100); Spot = (Total / (1 + VAT/100)) - Fees.
 * Fees = energy tax + the transfer fee for the slot. In time-of-use mode the fee
 * is resolved from `slotStartIso` (wall-clock in the configured timezone); without a
 * slot time the flat fee is used, like the backend. */
// eslint-disable-next-line react-refresh/only-export-components -- pure helper, tested directly
export function splitPriceBreakdown(
    value: number,
    pricing?: PricingBreakdownConfig,
    slotStartIso?: string | null,
): { spot: number; feesAndVat: number } | null {
    if (!pricing) return null
    const vatMul = 1 + pricing.vat / 100
    // Avoid division by zero
    const basePrice = vatMul > 0 ? value / vatMul : value
    const transferFee = transferFeeAt(
        pricing.transferFee,
        slotStartIso ? wallClockParts(slotStartIso, pricing.timezone) : null,
    )
    const spot = Math.max(0, basePrice - (pricing.energyTax + transferFee))
    const feesAndVat = value - spot
    return { spot, feesAndVat }
}

// Full-hour ticks in the visible (zoomed) range, counted once per tick array
// rather than once per tick label.
const hourCountCache = new WeakMap<Tick[], number>()
function visibleHourCount(scale: Scale, ticks: Tick[]): number {
    let count = hourCountCache.get(ticks)
    if (count === undefined) {
        count = ticks.filter((t) => hourOfLabel(scale.getLabelForValue(t.value)) !== null).length
        hourCountCache.set(ticks, count)
    }
    return count
}

/** Height of the action strip drawn between the plot and the hour labels. */
const STRIP_HEIGHT = 12
const STRIP_GAP = 3

/** Dash pattern of every plan line; actual lines are solid. */
const PLAN_DASH = [6, 4]
const ESTIMATED_LABEL = 'Estimated prices'

const axisTick = {
    color: () => token('muted'),
    font: { family: 'monospace', size: 10 },
}

const chartOptions: ChartConfiguration['options'] = {
    maintainAspectRatio: false,
    animation: false,
    // Hover details live in the info panel above the chart (no floating tooltip).
    interaction: { mode: 'index', intersect: false, axis: 'x' },
    layout: { padding: { top: 16 } },
    plugins: {
        legend: { display: false },
        tooltip: { enabled: false },
        zoom: {
            pan: {
                enabled: true,
                mode: 'x',
            },
            zoom: {
                wheel: {
                    enabled: true,
                },
                pinch: {
                    enabled: true,
                },
                mode: 'x',
            },
        },
    },
    scales: {
        x: {
            offset: true,
            // Faint vertical line at every full hour
            grid: {
                display: true,
                drawTicks: false,
                color: (ctx) => {
                    const label = ctx.chart.data.labels?.[ctx.index]
                    return hourOfLabel(label) !== null ? token('line', gridAlpha('hour', isDarkTheme())) : 'transparent'
                },
            },
            ticks: {
                ...axisTick,
                // Leave room under the plot for the action strip
                padding: STRIP_HEIGHT + STRIP_GAP * 2,
                maxRotation: 0,
                autoSkip: false,
                // Hour labels only (24h); thinned to every 3rd (6th, 12th) hour when a label per
                // hour does not fit the scale width.
                callback: function (this: Scale, value: string | number, index: number, ticks: Tick[]) {
                    // The plot runs edge to edge, so the leftmost label would be cut in half
                    if (index === 0) return ''
                    const hh = hourOfLabel(this.getLabelForValue(value as number))
                    if (hh === null) return ''
                    const step = hourLabelStep(this.width, visibleHourCount(this, ticks))
                    return Number(hh) % step === 0 ? hh : ''
                },
            },
            border: { display: false },
            // The hour axis reserves side room for its edge labels; drop it so the plot
            // spans the full card width, matching the info panel above.
            afterFit(scale: Scale) {
                scale.paddingLeft = 0
                scale.paddingRight = 0
            },
        },
        // Import price (left)
        y: {
            position: 'left',
            beginAtZero: true,
            grid: { display: false },
            border: { display: false },
            // Headroom keeps the price area in the lower half; exact values are in the info panel
            afterDataLimits(scale: Scale) {
                scale.max = priceAxisMax(scale.max)
            },
            ticks: { display: false },
            // Hidden labels still reserve width; collapse it so the plot spans the card
            afterFit(scale: Scale) {
                scale.width = 0
            },
        },
        // Power axes share a scale but are not shown
        y1: { display: false, min: 0, max: 9 },
        y2: { display: false, min: 0, max: 9 },
        y4: { display: false, min: 0, max: 9 },
        // Battery SoC (right)
        y3: {
            position: 'right',
            min: 0,
            max: 100,
            // The 25 % grid lines stay; the % labels are in the info panel
            grid: { display: true, drawTicks: false, color: () => token('line', gridAlpha('soc', isDarkTheme())) },
            border: { display: false },
            ticks: { display: false, stepSize: 25 },
            afterFit(scale: Scale) {
                scale.width = 0
            },
        },
    },
}

type ChartValues = SlotSeries & {
    labels: string[]
    price: Series
    pv: Series
    load: Series
    waterBoost?: (boolean | null)[]
    socTarget?: Series
    hasNoData?: boolean
    day?: DaySel
    nowPct?: number | null
    /** Measured series take the full-weight role before "now" (the Actual overlay). */
    showActual?: boolean
}

interface ExtendedChartData extends ChartData {
    nowIndex?: number | null
    nowPct?: number | null
    hasNoData?: boolean
    pricingConfig?: PricingBreakdownConfig
    /** ISO start time per chart index (live data only), for per-slot fee breakdown. */
    slotStarts?: string[]
    /** Per-slot arrays behind the info panel. */
    series?: SlotSeries
}

/** Dataset fields the action strip plugin reads (such datasets are never drawn by Chart.js). */
type ActionDatasetFields = { actionKind?: ActionKind; actionSource?: 'planned' | 'actual' }

const hatchPatterns = new WeakMap<CanvasRenderingContext2D, { color: string; pattern: CanvasPattern }>()

/** Diagonal-line pattern in `color`; falls back to a flat tint where offscreen canvases are unavailable. */
function hatchPattern(ctx: CanvasRenderingContext2D, color: string): CanvasPattern | string {
    const cached = hatchPatterns.get(ctx)
    if (cached && cached.color === color) return cached.pattern
    if (typeof document === 'undefined') return color
    const tile = document.createElement('canvas')
    tile.width = 8
    tile.height = 8
    const tctx = tile.getContext('2d')
    if (!tctx) return color
    tctx.strokeStyle = color
    tctx.lineWidth = 1
    tctx.beginPath()
    tctx.moveTo(-1, 9)
    tctx.lineTo(9, -1)
    tctx.moveTo(-1, 1)
    tctx.lineTo(1, -1)
    tctx.moveTo(7, 9)
    tctx.lineTo(9, 7)
    tctx.stroke()
    const pattern = ctx.createPattern(tile, 'repeat')
    if (!pattern) return color
    hatchPatterns.set(ctx, { color, pattern })
    return pattern
}

const createChartData = (
    values: ChartValues,
    _themeColors: Record<string, string> = {}, // Deprecated - colours come from design tokens
    pricing?: PricingBreakdownConfig,
): ExtendedChartData => {
    // One colour per series: actual = solid line, plan = dashed line. Before "now" the solid
    // actual runs beside the dashed plan; after "now" only the dashed plan is drawn.
    // Every action (charge/discharge/export/water/EV) is a mark on the strip (see actionStripPlugin).
    // Colours are tokens resolved at draw time, so light/dark both work.
    const empty: Series = values.labels.map(() => null)
    const nowIdx = values.nowIndex ?? null
    const estimated = values.estimated
    const knownPrice = estimated ? values.price.map((p, i) => (estimated[i] ? null : p)) : values.price
    const estimatedPrice = estimated ? values.price.map((p, i) => (estimated[i] ? p : null)) : empty

    /** Dashed plan line: same colour as its actual counterpart. */
    const planLine = (tk: ChartToken, alpha: number) => ({
        borderColor: () => token(tk, alpha),
        borderDash: PLAN_DASH,
    })

    const softFill = (tk: ChartToken, top: number) => (context: ScriptableContext<'line'>) => {
        const area = context.chart.chartArea
        if (!area) return 'transparent'
        const gradient = context.chart.ctx.createLinearGradient(0, area.top, 0, area.bottom)
        gradient.addColorStop(0, token(tk, top))
        gradient.addColorStop(1, token(tk, 0))
        return gradient
    }

    /** Diagonal hatch over the estimated price area, drawn in the muted token. */
    const hatchFill = (context: ScriptableContext<'line'>) => hatchPattern(context.chart.ctx, token('grid', 0.4))

    const actionDs = (
        label: string,
        data: Series,
        kind: ActionKind,
        yAxisID: string,
        source: 'planned' | 'actual' = 'planned',
    ) =>
        ({
            type: 'line',
            label,
            data,
            yAxisID,
            actionKind: kind,
            actionSource: source,
            borderColor: () => token(ACTION_TOKEN[kind]),
            borderWidth: 0,
            pointRadius: 0,
            pointHoverRadius: 0,
            order: 8,
        }) as unknown as ChartDataset

    const actualLine = (
        label: string,
        data: Series,
        tk: ChartToken,
        yAxisID: string,
        stepped: boolean,
        width: number,
        glow = false,
    ) =>
        ({
            type: 'line',
            label,
            data: splitActualPlan(data, nowIdx),
            borderColor: () => token(tk),
            borderWidth: width,
            glow: glow ? tk : undefined,
            pointRadius: 0,
            pointHoverRadius: 0,
            yAxisID,
            ...(stepped ? { stepped: 'middle' } : { tension: 0.4 }),
            order: 2,
        }) as unknown as ChartDataset

    const baseData: ExtendedChartData = {
        labels: values.labels,
        datasets: [
            // 0: import price (published prices), a soft area behind everything
            {
                type: 'line',
                label: 'Import Price (SEK/kWh)',
                data: knownPrice,
                borderColor: () => token('grid', 0.55),
                backgroundColor: softFill('grid', 0.3),
                fill: true,
                yAxisID: 'y',
                stepped: 'middle',
                pointRadius: 0,
                pointHoverRadius: 0,
                borderWidth: 1.25,
                order: 9,
            } as ChartDataset,
            // 1: PV plan, dashed gold line over a soft vertical gradient
            {
                type: 'line',
                label: 'PV Forecast (kW)',
                data: values.pv,
                ...planLine('accent', 0.95),
                glow: 'accent',
                backgroundColor: softFill('accent', 0.3),
                fill: true,
                yAxisID: 'y4',
                tension: 0.4,
                pointRadius: 0,
                pointHoverRadius: 0,
                borderWidth: 1.5,
                order: 6,
            } as unknown as ChartDataset,
            // 2: load plan, dashed stepped outline
            {
                type: 'line',
                label: 'Load (kW)',
                data: values.load,
                ...planLine('house', 0.9),
                yAxisID: 'y1',
                stepped: 'middle',
                pointRadius: 0,
                pointHoverRadius: 0,
                borderWidth: 1.5,
                order: 5,
            } as unknown as ChartDataset,
            // 3-10: planned actions, drawn as strip marks
            actionDs('Charge (kW)', values.charge ?? empty, 'charge', 'y1'),
            actionDs('Discharge (kW)', values.discharge ?? empty, 'discharge', 'y1'),
            actionDs('Export (kW)', values.export ?? empty, 'export', 'y2'),
            actionDs('Water Heating (kW)', values.water ?? empty, 'water', 'y1'),
            actionDs(
                'Water Heating Boost (kW)',
                values.waterBoost?.map((b, i) =>
                    b && values.water && i < values.water.length ? values.water[i] : null,
                ) ?? empty,
                'waterBoost',
                'y1',
            ),
            actionDs('EV Charging (kW)', values.evCharging ?? empty, 'ev', 'y1'),
            actionDs('EV Surplus Charging (kW)', values.evSurplus ?? empty, 'evSurplus', 'y1'),
            actionDs('Excess PV Sink (kW)', values.customEntityActive ?? empty, 'excess', 'y1'),
            // 11: SoC target, faint dotted
            {
                type: 'line',
                label: 'SoC Target (%)',
                data: values.socTarget ?? empty,
                borderColor: () => token('night', 0.55),
                borderDash: [2, 4],
                yAxisID: 'y3',
                pointRadius: 0,
                pointHoverRadius: 0,
                borderWidth: 1.25,
                stepped: 'middle',
                order: 4,
            } as ChartDataset,
            // 12: planned SoC, dashed, as strong as the actual line
            {
                type: 'line',
                label: 'SoC Projected (%)',
                data: values.socProjected ?? empty,
                ...planLine('night', 1),
                glow: 'night',
                yAxisID: 'y3',
                pointRadius: 0,
                pointHoverRadius: 0,
                borderWidth: 3,
                tension: 0.3,
                order: 1,
            } as unknown as ChartDataset,
            // 13: measured SoC, solid, before "now"
            {
                type: 'line',
                label: 'SoC Actual (%)',
                data: splitActualPlan(values.socActual ?? empty, nowIdx),
                borderColor: () => token('night'),
                glow: 'night',
                yAxisID: 'y3',
                pointRadius: 0,
                pointHoverRadius: 0,
                borderWidth: 3,
                tension: 0.3,
                order: 0,
            } as ChartDataset,
            // 14-15: measured PV / load lines
            actualLine('Actual PV (kW)', values.actualPv ?? empty, 'accent', 'y4', false, 2, true),
            actualLine('Actual Load (kW)', values.actualLoad ?? empty, 'house', 'y1', true, 2),
            // 16-20: measured actions replace the plan on the strip before "now"
            actionDs('Actual Charge (kW)', values.actualCharge ?? empty, 'charge', 'y1', 'actual'),
            actionDs('Actual Discharge (kW)', values.actualDischarge ?? empty, 'discharge', 'y1', 'actual'),
            actionDs('Actual EV (kW)', values.actualEvCharging ?? empty, 'ev', 'y1', 'actual'),
            actionDs('Actual Export (kW)', values.actualExport ?? empty, 'export', 'y2', 'actual'),
            actionDs('Actual Water (kW)', values.actualWater ?? empty, 'water', 'y1', 'actual'),
            // 21-22: EV standby and planned-while-unplugged marks
            actionDs('EV Standby', values.evKeepOn ?? empty, 'evStandby', 'y1'),
            actionDs(EV_AWAITING_PLUG_IN_LABEL, values.evAwaitingPlugIn ?? empty, 'evPlanned', 'y1'),
            // 23: price rests on a forecast (Nordpool not published): lighter, hatched, dashed
            {
                type: 'line',
                label: 'Estimated Price (SEK/kWh)',
                data: estimatedPrice,
                borderColor: () => token('grid', 0.45),
                borderDash: [3, 3],
                backgroundColor: hatchFill,
                fill: true,
                yAxisID: 'y',
                stepped: 'middle',
                pointRadius: 0,
                pointHoverRadius: 0,
                borderWidth: 1.25,
                order: 9,
            } as unknown as ChartDataset,
        ],
    }

    // Preserve nowIndex on the returned object so runtime
    // logic can position the "NOW" marker.
    return {
        ...baseData,
        nowIndex: values.nowIndex ?? null,
        nowPct: values.nowPct ?? null,
        hasNoData: !!values.hasNoData,
        pricingConfig: pricing,
        series: values,
    }
}

/** Pixel x of "now" (interpolated inside its slot), or null when not on the chart. */
function nowPixel(chart: Chart): number | null {
    const data = chart.data as ExtendedChartData
    const x = chart.scales.x
    const total = data.labels?.length ?? 0
    const pct = data.nowPct
    if (!x || typeof pct !== 'number' || pct < 0 || pct > 1 || total < 2) return null
    // Slot i is centred on tick i (offset axis), so a fractional slot position f sits at f - 0.5
    const slotWidth = x.getPixelForValue(1) - x.getPixelForValue(0)
    return x.getPixelForValue(0) + (pct * total - 0.5) * slotWidth
}

// "Now": past is tinted, a solid line marks the present with a small NOW label.
const nowLinePlugin: Plugin = {
    id: 'nowLine',
    beforeDatasetsDraw(chart) {
        const xPos = nowPixel(chart)
        const { left, right, top, bottom } = chart.chartArea
        if (xPos === null || xPos <= left) return
        const { ctx } = chart
        ctx.save()
        ctx.fillStyle = token('muted', isDarkTheme() ? 0.07 : 0.035)
        ctx.fillRect(left, top, Math.min(xPos, right) - left, bottom - top)
        ctx.restore()
    },
    afterDatasetsDraw(chart) {
        const xPos = nowPixel(chart)
        const { left, right, top, bottom } = chart.chartArea
        if (xPos === null || xPos < left || xPos > right) return
        const { ctx } = chart

        ctx.save()
        ctx.beginPath()
        ctx.strokeStyle = token('accent', 0.9)
        ctx.lineWidth = 1.25
        ctx.moveTo(xPos, top)
        ctx.lineTo(xPos, bottom)
        ctx.stroke()

        // Small pill label above the plot
        ctx.font = 'bold 9px monospace'
        const width = ctx.measureText('NOW').width + 10
        const height = 12
        const pillX = Math.min(Math.max(xPos - width / 2, left), right - width)
        const pillY = top - height - 2
        ctx.fillStyle = token('accent')
        ctx.beginPath()
        ctx.roundRect(pillX, pillY, width, height, 6)
        ctx.fill()
        ctx.fillStyle = token('canvas')
        ctx.textAlign = 'center'
        ctx.textBaseline = 'middle'
        ctx.fillText('NOW', pillX + width / 2, pillY + height / 2 + 0.5)
        ctx.restore()
    },
}

// Soft glow on datasets tagged with `glow: <token>`; dark mode only (light mode stays flat).
const lineGlowPlugin: Plugin = {
    id: 'lineGlow',
    beforeDatasetDraw(chart, args) {
        const tk = (chart.data.datasets[args.index] as unknown as { glow?: ChartToken }).glow
        if (!tk || !isDarkTheme()) return
        chart.ctx.save()
        chart.ctx.shadowColor = token(tk, 0.6)
        chart.ctx.shadowBlur = 8
    },
    afterDatasetDraw(chart, args) {
        const tk = (chart.data.datasets[args.index] as unknown as { glow?: ChartToken }).glow
        if (!tk || !isDarkTheme()) return
        chart.ctx.restore()
    },
}

// Estimated prices: a faint band over the slots priced from a forecast, with a small label at its top.
const estimatedBandPlugin: Plugin = {
    id: 'estimatedBand',
    beforeDatasetsDraw(chart) {
        const x = chart.scales.x
        const flags = (chart.data as ExtendedChartData).series?.estimated
        if (!x || !flags) return
        const { left, right, top, bottom } = chart.chartArea
        const half = Math.abs(x.getPixelForValue(1) - x.getPixelForValue(0)) / 2
        const { ctx } = chart
        for (const range of estimatedRanges(flags)) {
            const from = Math.max(left, x.getPixelForValue(range.from) - half)
            const to = Math.min(right, x.getPixelForValue(range.to) + half)
            if (to <= from) continue
            ctx.save()
            ctx.fillStyle = token('muted', 0.06)
            ctx.fillRect(from, top, to - from, bottom - top)
            ctx.strokeStyle = token('muted', 0.45)
            ctx.lineWidth = 1
            ctx.setLineDash([3, 3])
            ctx.beginPath()
            ctx.moveTo(from, top)
            ctx.lineTo(from, bottom)
            ctx.stroke()
            ctx.setLineDash([])
            ctx.font = '9px monospace'
            ctx.fillStyle = token('muted')
            ctx.textAlign = 'left'
            ctx.textBaseline = 'top'
            const label = ESTIMATED_LABEL.toUpperCase()
            if (ctx.measureText(label).width + 10 <= to - from) ctx.fillText(label, from + 5, top + 4)
            ctx.restore()
        }
    },
}

// Hover/tap guide: a vertical line (and faint band) on the slot shown in the info panel.
// Per-instance plugin options (chart.options.plugins.slotGuide) keep instances independent.
const slotGuidePlugin: Plugin = {
    id: 'slotGuide',
    afterDatasetsDraw(chart) {
        // eslint-disable-next-line @typescript-eslint/no-explicit-any
        const opts = (chart.options.plugins as any)?.slotGuide as { index?: number | null } | undefined
        const idx = opts?.index
        const x = chart.scales.x
        if (idx === null || idx === undefined || !x) return
        const { left, right, top, bottom } = chart.chartArea
        const xPos = x.getPixelForValue(idx)
        if (xPos < left || xPos > right) return
        const slotWidth = Math.abs(x.getPixelForValue(1) - x.getPixelForValue(0))
        const { ctx } = chart
        ctx.save()
        ctx.fillStyle = token('text', 0.06)
        ctx.fillRect(xPos - slotWidth / 2, top, slotWidth, bottom - top)
        ctx.beginPath()
        ctx.strokeStyle = token('text', 0.55)
        ctx.lineWidth = 1
        ctx.moveTo(xPos, top)
        ctx.lineTo(xPos, bottom)
        ctx.stroke()
        ctx.restore()
    },
}

// Action strip: charge / discharge / export / water / EV as small coloured marks in a thin
// lane under the plot. Datasets tagged with an `actionKind` hold the values (so overlays and
// the info panel keep working) but are never drawn by Chart.js itself.
const actionStripPlugin: Plugin = {
    id: 'actionStrip',
    beforeDatasetDraw(chart, args) {
        const ds = chart.data.datasets[args.index] as unknown as ActionDatasetFields
        if (ds.actionKind) return false
    },
    afterDatasetsDraw(chart) {
        const x = chart.scales.x
        const total = chart.data.labels?.length ?? 0
        if (!x || total < 2) return
        const { left, right, bottom } = chart.chartArea

        const planned: ActionSeries = {}
        const actual: ActionSeries = {}
        chart.data.datasets.forEach((raw, i) => {
            const ds = raw as unknown as ActionDatasetFields & { data: Series }
            if (!ds.actionKind || !chart.isDatasetVisible(i)) return
            ;(ds.actionSource === 'actual' ? actual : planned)[ds.actionKind] = ds.data
        })
        const nowIndex = (chart.data as ExtendedChartData).nowIndex

        const top = bottom + STRIP_GAP
        const slotWidth = Math.abs(x.getPixelForValue(1) - x.getPixelForValue(0))
        const markWidth = Math.max(1, slotWidth - Math.min(1.5, slotWidth * 0.2))
        const { ctx } = chart

        ctx.save()
        ctx.beginPath()
        ctx.rect(left, top - 1, right - left, STRIP_HEIGHT + 2)
        ctx.clip()
        // Lane track
        ctx.fillStyle = token('muted', 0.1)
        ctx.fillRect(left, top, right - left, STRIP_HEIGHT)

        const first = Math.max(0, Math.floor(x.min))
        const last = Math.min(total - 1, Math.ceil(x.max))
        for (let i = first; i <= last; i++) {
            const kinds = slotMarkKinds(i, nowIndex, planned, actual)
            if (!kinds.length) continue
            const rowHeight = (STRIP_HEIGHT - (kinds.length - 1)) / kinds.length
            const markX = x.getPixelForValue(i) - markWidth / 2
            kinds.forEach((kind, row) => {
                const y = top + row * (rowHeight + 1)
                const color = ACTION_TOKEN[kind]
                if (kind === 'evPlanned') {
                    ctx.strokeStyle = token(color, 0.9)
                    ctx.lineWidth = 1
                    ctx.strokeRect(markX + 0.5, y + 0.5, Math.max(0, markWidth - 1), Math.max(0, rowHeight - 1))
                    return
                }
                ctx.fillStyle = token(color, kind === 'evStandby' ? 0.45 : 0.95)
                ctx.fillRect(markX, y, markWidth, rowHeight)
            })
        }
        ctx.restore()
    },
}

// Chart configuration helpers removed and consolidated into applyData

const DETAILS_KEY = 'darkstar-chart-details'

function readDetailsPref(): boolean {
    try {
        return localStorage.getItem(DETAILS_KEY) === 'true'
    } catch {
        return false
    }
}

function writeDetailsPref(value: boolean): void {
    try {
        localStorage.setItem(DETAILS_KEY, String(value))
    } catch {
        // Storage unavailable (private window): the choice just does not persist
    }
}

type ChartCardProps = {
    day?: DaySel
    refreshToken?: number
    useHistoryForToday?: boolean
    slotsOverride?: ScheduleSlot[]
    /** Chargers planned while unplugged; their slots render as "awaiting plug-in" */
    evAwaitingPlugInIds?: string[]
}

export default function ChartCard({
    day = 'today',
    refreshToken = 0,
    slotsOverride,
    useHistoryForToday = false,
    evAwaitingPlugInIds,
}: ChartCardProps) {
    // Stable key so the data effect only re-runs when the set of ids changes.
    const evAwaitingKey = (evAwaitingPlugInIds ?? []).slice().sort().join(',')
    const isMobile = useIsMobile()
    const [hasNoDataMessage, setHasNoDataMessage] = useState(false)
    const [hasRealData, setHasRealData] = useState(false) // Track when real data has been loaded
    const currentDay = day || 'today'
    const ref = useRef<HTMLCanvasElement | null>(null)
    const chartRef = useRef<Chart | null>(null)
    const cardRef = useRef<HTMLDivElement | null>(null)
    const userHasZoomedRef = useRef(false) // Track if user has manually zoomed/panned
    const lastHadTomorrowPricesRef = useRef<boolean | null>(null) // Track tomorrow prices availability
    const [isZoomed, setIsZoomed] = useState(false) // UI state for reset button visibility
    const [themeColors, setThemeColors] = useState<Record<string, string>>({})
    // Mobile tap-to-select state
    const [selectedIndex, setSelectedIndex] = useState<number | null>(null)
    // Selection only applies on mobile; derived so the desktop transition clears it without an effect setState
    const effectiveSelectedIndex = isMobile ? selectedIndex : null
    // Snapshot of the latest chart data pushed to the chart instance — used by the
    // selection panel memo so it reads stable React state rather than a mutating ref (S2b)
    const [liveChartData, setLiveChartData] = useState<ExtendedChartData | null>(null)
    // Per-instance ref for current mobile state — kept in sync so the baked-in onClick
    // handler always reads the live value even after viewport crosses 768px (N1)
    const isMobileRef = useRef(isMobile)
    useEffect(() => {
        isMobileRef.current = isMobile
    }, [isMobile])

    // Click-away handler: tapping outside the card clears selection (mobile only)
    useEffect(() => {
        if (!isMobile) return
        const handler = (e: MouseEvent) => {
            if (cardRef.current && !cardRef.current.contains(e.target as Node)) {
                setSelectedIndex(null)
            }
        }
        document.addEventListener('click', handler, true)
        return () => document.removeEventListener('click', handler, true)
    }, [isMobile])

    // Desktop hover: slot under the cursor (null when the pointer is outside the plot)
    const [hoverIndex, setHoverIndex] = useState<number | null>(null)
    // Slot the info panel shows: tapped slot on mobile, hovered slot on desktop, else the current slot
    const pinnedIndex = isMobile ? effectiveSelectedIndex : hoverIndex
    const guideIndexRef = useRef(pinnedIndex)
    const infoSeries = liveChartData?.series
    const shownIndex = pinnedIndex ?? liveChartData?.nowIndex ?? null

    // Info panel content, built from stable React state (liveChartData is a snapshot of the
    // data pushed to the chart, never the mutating chart ref).
    const slotInfo = useMemo(() => {
        if (shownIndex === null || !infoSeries) return null
        const price = infoSeries.price?.[shownIndex]
        const breakdown =
            typeof price === 'number'
                ? splitPriceBreakdown(price, liveChartData?.pricingConfig, liveChartData?.slotStarts?.[shownIndex])
                : null
        return buildSlotInfo(infoSeries, shownIndex, { breakdown })
    }, [shownIndex, infoSeries, liveChartData?.pricingConfig, liveChartData?.slotStarts])
    const compact = useMemo(
        () => (shownIndex === null || !infoSeries ? null : buildCompactLine(infoSeries, shownIndex)),
        [shownIndex, infoSeries],
    )
    const hasEstimated = useMemo(() => estimatedRanges(infoSeries?.estimated).length > 0, [infoSeries])
    const [overlays, setOverlays] = useState(() => {
        // Load from localStorage if available, otherwise use defaults
        const STORAGE_KEY = 'darkstar-chart-overlays'
        const STORAGE_VERSION = 6 // Increment to force migration

        try {
            const saved = localStorage.getItem(STORAGE_KEY)
            if (saved) {
                const parsed = JSON.parse(saved)

                // Check version - if missing or old, use new defaults
                if (parsed._version !== STORAGE_VERSION) {
                    console.log(`Migrating overlay preferences from v${parsed._version || 1} to v${STORAGE_VERSION}`)
                    // Use new defaults, but preserve user's explicit customizations if they match new defaults
                    const newDefaults = {
                        _version: STORAGE_VERSION,
                        price: true,
                        pv: true,
                        load: true,
                        charge: true,
                        discharge: true,
                        export: true,
                        water: true,
                        ev: true,
                        evKeepOn: false,
                        excessPvSink: false,
                        socTarget: false,
                        socProjected: true,
                        socActual: true,
                        showActual: true,
                    }
                    // Save migrated version immediately
                    localStorage.setItem(STORAGE_KEY, JSON.stringify(newDefaults))
                    return newDefaults
                }

                return {
                    _version: STORAGE_VERSION,
                    price: parsed.price ?? true,
                    pv: parsed.pv ?? true,
                    load: parsed.load ?? true,
                    charge: parsed.charge ?? true,
                    discharge: parsed.discharge ?? true,
                    export: parsed.export ?? true,
                    water: parsed.water ?? false,
                    ev: parsed.ev ?? false,
                    evKeepOn: parsed.evKeepOn ?? false,
                    excessPvSink: parsed.excessPvSink ?? false,
                    socTarget: parsed.socTarget ?? false,
                    socProjected: parsed.socProjected ?? false,
                    socActual: parsed.socActual ?? true,
                    showActual: parsed.showActual ?? true,
                }
            }
        } catch (e) {
            console.warn('Failed to load overlay preferences:', e)
        }
        return {
            _version: STORAGE_VERSION,
            price: true,
            pv: true,
            load: true,
            charge: true,
            discharge: true,
            export: true,
            water: true,
            ev: true,
            evKeepOn: false,
            excessPvSink: false,
            socTarget: false,
            socProjected: true,
            socActual: true,
            showActual: true,
        }
    })
    const [showOverlayMenu, setShowOverlayMenu] = useState(false)
    const [showDetails, setShowDetails] = useState(readDetailsPref)
    const toggleDetails = () => {
        const next = !showDetails
        setShowDetails(next)
        writeDetailsPref(next)
    }
    const [pricingConfig, setPricingConfig] = useState<PricingBreakdownConfig | undefined>()
    const [excessPvPowerKw, setExcessPvPowerKw] = useState(1.0)
    const [scaling, setScaling] = useState({
        solarKwp: 10,
        gridMaxKw: 8,
        inverterMaxKw: 8,
    })

    // Persist overlay preferences to localStorage
    useEffect(() => {
        try {
            localStorage.setItem('darkstar-chart-overlays', JSON.stringify(overlays))
        } catch (e) {
            console.warn('Failed to save overlay preferences:', e)
        }
    }, [overlays])

    // Load scaling values from config and set default overlays for new users
    // All overlays are enabled by default - users can toggle them off via the chart controls
    useEffect(() => {
        const STORAGE_KEY = 'darkstar-chart-overlays'
        const hasStoredPreferences = localStorage.getItem(STORAGE_KEY) !== null

        Api.config()
            .then((config) => {
                // Scaling values - always apply
                const legacySolarKwp = config?.system?.solar_array?.kwp
                const solarArrays = config?.system?.solar_arrays
                let solarKwp = 10

                if (legacySolarKwp != null) {
                    solarKwp = Number(legacySolarKwp)
                } else if (Array.isArray(solarArrays) && solarArrays.length > 0) {
                    solarKwp = solarArrays.reduce((sum, arr) => sum + Number(arr.kwp || 0), 0)
                }

                const gridMaxKw = config?.system?.grid?.max_power_kw ?? 8
                const inverterMaxKw = config?.system?.inverter?.max_power_kw ?? 8
                setScaling({
                    solarKwp: Number(solarKwp),
                    gridMaxKw: Number(gridMaxKw),
                    inverterMaxKw: Number(inverterMaxKw),
                })

                // Parse pricing for tooltips - always apply
                const breakdownConfig = pricingBreakdownFromConfig(config)
                if (breakdownConfig) setPricingConfig(breakdownConfig)

                // Load custom entity power_kw for chart bar scaling
                const powerKw = config?.executor?.excess_pv?.custom_entity?.power_kw
                if (powerKw != null) {
                    setExcessPvPowerKw(Number(powerKw))
                }

                // For NEW users (no localStorage), enable all overlays by default
                if (!hasStoredPreferences) {
                    setOverlays({
                        _version: 6,
                        price: true,
                        pv: true,
                        load: true,
                        charge: true,
                        discharge: true,
                        export: true,
                        water: true,
                        ev: true,
                        evKeepOn: true,
                        excessPvSink: false,
                        socTarget: true,
                        socProjected: true,
                        socActual: true,
                        showActual: true,
                    })
                }
            })
            .catch((err) => console.error('Failed to load config:', err))
    }, []) // No dependencies - only run once on mount

    useEffect(() => {
        // Fetch theme colors on mount
        Api.theme()
            .then((themeData) => {
                const currentThemeInfo = themeData.themes.find((t) => t.name === themeData.current)
                if (currentThemeInfo) {
                    // Convert palette array to key-value format
                    const colorMap: Record<string, string> = {}
                    currentThemeInfo.palette.forEach((color, index) => {
                        colorMap[`palette = ${index}`] = color
                    })
                    colorMap['background'] = currentThemeInfo.background
                    colorMap['foreground'] = currentThemeInfo.foreground
                    setThemeColors(colorMap)
                }
            })
            .catch((err) => console.error('Failed to load theme colors:', err))
    }, [])

    // Chart initialization: only runs ONCE when canvas ref is available
    useEffect(() => {
        if (!ref.current || Object.keys(themeColors).length === 0) return
        // Skip re-initialization if real data has already been loaded
        if (hasRealData && chartRef.current) return

        const cfg: ChartConfiguration = {
            type: 'bar',
            data: createChartData(
                {
                    labels: sampleChart.labels,
                    price: sampleChart.price,
                    pv: sampleChart.pv,
                    load: sampleChart.load,
                    charge: sampleChart.charge,
                    discharge: sampleChart.discharge,
                },
                themeColors,
                pricingConfig,
            ),
            options: {
                ...chartOptions,
                plugins: {
                    ...chartOptions?.plugins,
                    zoom: {
                        ...chartOptions?.plugins?.zoom,
                        zoom: {
                            ...chartOptions?.plugins?.zoom?.zoom,
                            onZoomComplete: () => {
                                userHasZoomedRef.current = true
                                setIsZoomed(true)
                            },
                        },
                        pan: {
                            ...chartOptions?.plugins?.zoom?.pan,
                            onPanComplete: () => {
                                userHasZoomedRef.current = true
                                setIsZoomed(true)
                            },
                        },
                    },
                    // Per-instance guide line options; seeded from the current slot because the
                    // selection survives data refreshes, so a re-created chart must keep its guide
                    slotGuide: { index: guideIndexRef.current },
                    // eslint-disable-next-line @typescript-eslint/no-explicit-any
                } as any,
                // Desktop hover feeds the info panel; touch devices use tap-to-select instead
                onHover: (event, _elements, chart) => {
                    if (isMobileRef.current) return
                    const x = chart.scales.x
                    const area = chart.chartArea
                    const px = event.x
                    const py = event.y
                    if (
                        event.type === 'mouseout' ||
                        !x ||
                        px === null ||
                        py === null ||
                        px < area.left ||
                        px > area.right ||
                        py < area.top ||
                        py > area.bottom
                    ) {
                        setHoverIndex(null)
                        return
                    }
                    const idx = Math.round(x.getValueForPixel(px) ?? -1)
                    const slotCount = chart.data.labels?.length ?? 0
                    setHoverIndex(idx >= 0 && idx < slotCount ? idx : null)
                },
                // Always register onClick but guard on isMobileRef so crossing 768px mid-session
                // works without recreating the chart (N1).
                onClick: (_event, elements) => {
                    if (!isMobileRef.current) return
                    if (elements && elements.length > 0) {
                        const idx = elements[0].index
                        setSelectedIndex((prev) => (prev === idx ? null : idx))
                    } else {
                        setSelectedIndex(null)
                    }
                },
                scales: {
                    ...chartOptions?.scales,
                    y1: {
                        ...chartOptions?.scales?.y1,
                        max: Math.max(scaling.gridMaxKw, scaling.inverterMaxKw, scaling.solarKwp),
                    },
                    y2: {
                        ...chartOptions?.scales?.y2,
                        max: Math.max(scaling.gridMaxKw, scaling.inverterMaxKw, scaling.solarKwp),
                    },
                    y4: {
                        ...chartOptions?.scales?.y4,
                        max: Math.max(scaling.gridMaxKw, scaling.inverterMaxKw, scaling.solarKwp),
                    },
                },
            },
            plugins: [nowLinePlugin, estimatedBandPlugin, lineGlowPlugin, slotGuidePlugin, actionStripPlugin],
        }
        chartRef.current = new ChartJS(ref.current, cfg)

        return () => {
            if (chartRef.current) {
                chartRef.current.destroy()
                chartRef.current = null
            }
        }
    }, [themeColors, pricingConfig, hasRealData, scaling.gridMaxKw, scaling.inverterMaxKw, scaling.solarKwp]) // Re-create chart only for initial creation or theme/pricing changes (but not after real data loads)

    // Push the hovered/tapped slot into per-instance plugin options and redraw the guide line.
    // Also runs when the viewport crosses the mobile breakpoint, since that switches which
    // interaction (hover or tap) drives the guide.
    const guideIndex = pinnedIndex
    useEffect(() => {
        guideIndexRef.current = guideIndex
        if (!chartRef.current) return
        // eslint-disable-next-line @typescript-eslint/no-explicit-any
        const pluginsOpts = chartRef.current.options.plugins as any
        if (pluginsOpts) {
            pluginsOpts.slotGuide = { index: guideIndex }
        }
        chartRef.current.draw()
    }, [guideIndex])

    // Dynamically update chart scales when scaling configuration changes
    // This prevents chart re-initialization and preserves loaded data
    useEffect(() => {
        if (!chartRef.current || !hasRealData) return

        const chart = chartRef.current
        if (chart.options?.scales) {
            const sharedPowerMax = Math.max(scaling.gridMaxKw, scaling.inverterMaxKw, scaling.solarKwp)

            if (chart.options.scales.y1) {
                chart.options.scales.y1.max = sharedPowerMax
            }
            if (chart.options.scales.y2) {
                chart.options.scales.y2.max = sharedPowerMax
            }
            if (chart.options.scales.y4) {
                chart.options.scales.y4.max = sharedPowerMax
            }

            chart.update('none') // Update without animation for instant response
        }
    }, [scaling.gridMaxKw, scaling.inverterMaxKw, scaling.solarKwp, hasRealData])

    // Theme switch (`.dark` on <html>): colours are tokens resolved at draw time, so a redraw
    // is all it takes to repaint grid, tint, glow and lines with the new theme.
    useEffect(() => {
        const observer = new MutationObserver(() => {
            const chart = chartRef.current
            if (chart) chart.update('none')
        })
        observer.observe(document.documentElement, { attributes: true, attributeFilter: ['class'] })
        return () => observer.disconnect()
    }, [])

    const isChartUsable = (chartInstance: Chart | null) => {
        if (!chartInstance) return false
        const anyChart = chartInstance as unknown as { _destroyed?: boolean; _plugins?: unknown; $plugins?: unknown }
        if (anyChart._destroyed) return false
        if (anyChart._plugins === undefined && anyChart.$plugins === undefined) return false
        return true
    }

    useEffect(() => {
        const chartInstance = chartRef.current
        if (!isChartUsable(chartInstance) || Object.keys(themeColors).length === 0) return
        const applyData = (slots: ScheduleSlot[]) => {
            if (!isChartUsable(chartRef.current)) return
            const liveData = buildLiveData(
                slots,
                currentDay,
                themeColors,
                pricingConfig,
                excessPvPowerKw,
                evAwaitingKey ? evAwaitingKey.split(',') : [],
                overlays.showActual,
            )
            if (!liveData) return

            setHasNoDataMessage(!!liveData.hasNoData)

            const ds = liveData.datasets
            if (ds[0]) ds[0].hidden = !overlays.price
            if (ds[1]) ds[1].hidden = !overlays.pv
            if (ds[2]) ds[2].hidden = !overlays.load
            if (ds[3]) ds[3].hidden = !overlays.charge
            if (ds[4]) ds[4].hidden = !overlays.discharge
            if (ds[5]) ds[5].hidden = !overlays.export
            if (ds[6]) ds[6].hidden = !overlays.water
            if (ds[7]) ds[7].hidden = !overlays.water
            if (ds[8]) ds[8].hidden = !overlays.ev
            if (ds[9]) ds[9].hidden = !overlays.ev // EV Surplus
            if (ds[10]) ds[10].hidden = !overlays.excessPvSink
            if (ds[11]) ds[11].hidden = !overlays.socTarget
            if (ds[12]) ds[12].hidden = !overlays.socProjected
            if (ds[13]) ds[13].hidden = !overlays.socActual

            // Actual Overlays
            if (ds[14]) ds[14].hidden = !overlays.showActual || !overlays.pv
            if (ds[15]) ds[15].hidden = !overlays.showActual || !overlays.load
            if (ds[16]) ds[16].hidden = !overlays.showActual || !overlays.charge
            if (ds[17]) ds[17].hidden = !overlays.showActual || !overlays.discharge
            if (ds[18]) ds[18].hidden = !overlays.showActual || !overlays.ev
            if (ds[19]) ds[19].hidden = !overlays.showActual || !overlays.export
            if (ds[20]) ds[20].hidden = !overlays.showActual || !overlays.water
            if (ds[21]) ds[21].hidden = !overlays.evKeepOn // EV Standby
            if (ds[22]) ds[22].hidden = !overlays.ev // EV awaiting plug-in

            try {
                if (chartRef.current) {
                    chartRef.current.data = liveData
                    // Keep the selection while it still points at a slot in the new data
                    // (dismissal is the click-away / re-tap), and snapshot the new data so
                    // the panel memo reads stable React state, not a mutating ref (S2a/S2b)
                    const slotCount = liveData.labels?.length ?? 0
                    setSelectedIndex((prev) => (prev !== null && prev >= slotCount ? null : prev))
                    setLiveChartData(liveData)
                    chartRef.current.update()

                    // Check if tomorrow prices just became available
                    const tomorrowPricesJustArrived =
                        lastHadTomorrowPricesRef.current === false && liveData.hasTomorrowPrices

                    // Update tracking ref
                    lastHadTomorrowPricesRef.current = liveData.hasTomorrowPrices

                    // Only apply auto-zoom if user hasn't manually zoomed, or if tomorrow prices just arrived
                    if (tomorrowPricesJustArrived) {
                        // Tomorrow prices arrived - reset to full 48h view
                        chartRef.current.resetZoom()
                        userHasZoomedRef.current = false
                        setIsZoomed(false)
                    } else if (!userHasZoomedRef.current) {
                        // User hasn't zoomed yet - apply initial auto-zoom logic
                        if (!liveData.hasTomorrowPrices) {
                            // Zoom to show roughly first 24h (approx slots 0-96 for 15m resolution)
                            chartRef.current.zoomScale('x', { min: 0, max: 95 }, 'default')
                        } else {
                            chartRef.current.resetZoom()
                        }
                    }
                    // else: user has zoomed and tomorrow prices haven't changed - preserve zoom
                }
            } catch (err) {
                console.error('Chart update error:', err)
            }
        }

        if (slotsOverride && slotsOverride.length) {
            applyData(slotsOverride)
            return
        }

        const shouldLoadHistory = useHistoryForToday && currentDay === 'today'
        const loader = shouldLoadHistory
            ? Api.scheduleTodayWithHistory().then((res) => ({ schedule: res.slots }))
            : Api.schedule()

        loader
            .then((data) => {
                applyData(data.schedule ?? [])
                setHasRealData(true)
            })
            .catch((err) => {
                console.error('Failed to load schedule:', err)
                setHasNoDataMessage(true)
            })
    }, [
        currentDay,
        overlays,
        themeColors,
        refreshToken,
        slotsOverride,
        useHistoryForToday,
        pricingConfig,
        excessPvPowerKw,
        evAwaitingKey,
    ])

    // Memoize theme colors to prevent unnecessary re-computations
    return (
        // Outer wrapper holds ref for click-away detection (clears selection when tapping outside card on mobile)
        <div ref={cardRef}>
            <Card className="p-4 md:p-6">
                <div className="flex items-baseline justify-between pb-2">
                    <div className="flex min-w-0 flex-wrap items-baseline gap-x-3 gap-y-1">
                        <div className="text-sm text-muted">Schedule Overview</div>
                        <div className="sched-legend" aria-label="Solid line is actual, dashed line is plan">
                            <span className="sched-legend__item">
                                <span className="sched-legend__swatch" data-form="actual" />
                                actual
                            </span>
                            <span className="sched-legend__item">
                                <span className="sched-legend__swatch" data-form="plan" />
                                plan
                            </span>
                            {hasEstimated && (
                                <span className="sched-legend__item">
                                    <span className="sched-legend__swatch" data-form="estimated" />
                                    est. price
                                </span>
                            )}
                        </div>
                    </div>
                    <div className="flex items-center gap-2">
                        {isZoomed && (
                            <button
                                className="rounded-pill px-3 py-1 text-[11px] font-semibold uppercase tracking-wide border border-line/60 text-muted hover:border-accent hover:text-accent transition"
                                onClick={() => {
                                    if (chartRef.current) {
                                        chartRef.current.resetZoom()
                                        userHasZoomedRef.current = false
                                        setIsZoomed(false)
                                    }
                                }}
                            >
                                Reset Zoom
                            </button>
                        )}
                        <button
                            className="rounded-pill px-3 py-1 text-[11px] font-semibold uppercase tracking-wide border border-line/60 text-muted hover:border-accent hover:text-accent transition"
                            onClick={toggleDetails}
                            aria-pressed={showDetails}
                        >
                            Details
                        </button>
                        <button
                            className="rounded-pill px-3 py-1 text-[11px] font-semibold uppercase tracking-wide border border-line/60 text-muted hover:border-accent hover:text-accent transition"
                            onClick={() => setShowOverlayMenu((v) => !v)}
                        >
                            Overlays
                        </button>
                    </div>
                </div>
                {showOverlayMenu && (
                    <div className="mt-2 flex items-center justify-between gap-4">
                        {/* Main overlay toggles  */}
                        <div className="flex flex-wrap gap-1.5 text-[10px]">
                            {(
                                [
                                    ['Price', 'price', 'bg-grid/20 border-grid'],
                                    ['PV', 'pv', 'bg-accent/20 border-accent'],
                                    ['Load', 'load', 'bg-house/20 border-house'],
                                    ['Charge', 'charge', 'bg-bad/20 border-bad'],
                                    ['Discharge', 'discharge', 'bg-peak/20 border-peak'],
                                    ['EV', 'ev', 'bg-ai/20 border-ai'],
                                    ['EV Standby', 'evKeepOn', 'bg-ai/20 border-ai'],
                                    ['Export', 'export', 'bg-good/20 border-good'],
                                    ['Water', 'water', 'bg-water/20 border-water'],
                                    ['Excess PV', 'excessPvSink', 'bg-bad/20 border-good'],
                                    ['SoC Target', 'socTarget', 'bg-night/20 border-night'],
                                    ['SoC Proj', 'socProjected', 'bg-night/20 border-night'],
                                    ['SoC Act', 'socActual', 'bg-night/20 border-night'],
                                ] as const
                            ).map(([label, key, activeClass]) => (
                                <button
                                    key={key}
                                    onClick={(e) => {
                                        e.preventDefault()
                                        setOverlays((o) => ({ ...o, [key]: !o[key as keyof typeof o] }))
                                    }}
                                    className={`rounded-full px-2.5 py-0.5 border transition-all duration-150 font-medium ${
                                        overlays[key as keyof typeof overlays]
                                            ? `${activeClass} shadow-sm`
                                            : 'border-line/40 text-muted/60 hover:border-line hover:text-muted'
                                    }`}
                                >
                                    {label}
                                </button>
                            ))}
                        </div>
                        {/* Show Actual toggle - separated on right */}
                        <button
                            onClick={(e) => {
                                e.preventDefault()
                                setOverlays((o) => ({ ...o, showActual: !o.showActual }))
                            }}
                            className={`rounded-full px-3 py-1 border text-[10px] font-semibold transition-all duration-150 whitespace-nowrap ${
                                overlays.showActual
                                    ? 'bg-accent text-canvas border-accent shadow-md shadow-accent/30'
                                    : 'border-line/40 text-muted/60 hover:border-accent hover:text-accent'
                            }`}
                        >
                            📊 Actual
                        </button>
                    </div>
                )}
                {slotInfo && compact && (
                    <div
                        className="sched-panel mt-1"
                        data-slot-panel
                        data-phase={slotInfo.phase}
                        data-estimated={slotInfo.estimated ? 'true' : 'false'}
                        data-expanded={showDetails ? 'true' : 'false'}
                        data-pinned={pinnedIndex !== null ? 'true' : 'false'}
                        onClick={(e) => e.stopPropagation()}
                    >
                        <div className="sched-panel__head">
                            <span
                                className="sched-panel__phase"
                                data-phase={compact.estimated ? 'estimated' : compact.phase}
                            >
                                {compact.badge}
                            </span>
                            <span className="sched-panel__time">{slotInfo.range}</span>
                            {showDetails ? (
                                <span className="sched-panel__action">{slotInfo.action}</span>
                            ) : (
                                <span className="sched-panel__summary">{compact.parts.join(' · ')}</span>
                            )}
                        </div>
                        {showDetails && (
                            <div className="sched-panel__groups">
                                {slotInfo.groups.map((group) => (
                                    <div key={group.title} className="sched-panel__group">
                                        <div className="sched-panel__title">{group.title}</div>
                                        {group.rows.map((row) => (
                                            <div key={row.key} className="sched-panel__row">
                                                <span className="sched-panel__dot" data-tone={row.tone} />
                                                <span className="sched-panel__label">{row.label}</span>
                                                <span className="sched-panel__value">
                                                    {row.value}
                                                    {row.plan && (
                                                        <span className="sched-panel__plan"> plan {row.plan}</span>
                                                    )}
                                                </span>
                                            </div>
                                        ))}
                                        {group.note && <div className="sched-panel__note">{group.note}</div>}
                                    </div>
                                ))}
                            </div>
                        )}
                    </div>
                )}
                <div className="h-[300px] md:h-[320px] relative mt-2">
                    {hasNoDataMessage && (
                        <div className="absolute inset-0 flex items-center justify-center bg-surface/90 rounded-lg">
                            <div className="text-center">
                                <div className="text-lg font-semibold text-accent mb-2">No Price Data</div>
                                <div className="text-sm text-muted">
                                    Schedule data not available yet. Check back later for prices.
                                </div>
                            </div>
                        </div>
                    )}
                    <canvas ref={ref} style={{ display: hasNoDataMessage ? 'none' : 'block' }} />
                </div>
            </Card>
        </div>
    )
}

// eslint-disable-next-line react-refresh/only-export-components -- pure helper, tested directly
export function buildLiveData(
    slots: ScheduleSlot[],
    day: DaySel,
    themeColors: Record<string, string> = {},
    pricing?: PricingBreakdownConfig,
    excessPvPowerKw: number = 1.0,
    evAwaitingPlugInIds: string[] = [],
    showActual: boolean = false,
): (ExtendedChartData & { hasTomorrowPrices: boolean }) | null {
    const hasTomorrowPrices = slots.some((slot) => isTomorrow(slot.start_time) && slot.import_price_sek_kwh != null)
    const filtered = slots.filter((slot) => isToday(slot.start_time) || isTomorrow(slot.start_time))

    if (!filtered.length) {
        console.log('[buildLiveData] No slots found for 48h range, creating fallback')
        const labels = Array.from({ length: 48 }, (_, i) => {
            const hour = i % 24
            return `${String(hour).padStart(2, '0')}:00`
        })
        return {
            ...createChartData(
                {
                    labels,
                    price: Array(labels.length).fill(null),
                    pv: Array(labels.length).fill(null),
                    load: Array(labels.length).fill(null),
                    charge: Array(labels.length).fill(null),
                    discharge: Array(labels.length).fill(null),
                    export: Array(labels.length).fill(null),
                    water: Array(labels.length).fill(null),
                    socTarget: Array(labels.length).fill(null),
                    socProjected: Array(labels.length).fill(null),
                    hasNoData: true,
                    day,
                },
                themeColors,
            ),
            hasTomorrowPrices,
        }
    }

    const ordered = [...filtered].sort((a, b) => {
        const aTime = new Date(a.start_time).getTime()
        const bTime = new Date(b.start_time).getTime()
        return aTime - bTime
    })

    // Infer resolution from consecutive slots; default to 15 minutes.
    let resolutionMinutes = 15
    if (ordered.length >= 2) {
        const dt0 = new Date(ordered[0].start_time).getTime()
        const dt1 = new Date(ordered[1].start_time).getTime()
        const deltaMinutes = Math.max(1, Math.round((dt1 - dt0) / 60000))
        if (deltaMinutes === 15 || deltaMinutes === 30 || deltaMinutes === 60) {
            resolutionMinutes = deltaMinutes
        }
    }

    // Use the first slot's time as the anchor if available, otherwise fallback to today 00:00
    // This ensures we align with the actual data being returned, shielding against timezone/date mismatches
    const anchor = new Date()
    if (ordered.length > 0) {
        // Parse the ISO string to extract Date and Offset, resetting time to 00:00:00
        // Format: YYYY-MM-DDTHH:MM:SS+HH:MM or YYYY-MM-DDTHH:MM:SSZ
        // We want: YYYY-MM-DDT00:00:00+HH:MM
        const startStr = ordered[0].start_time
        try {
            // Assume ISO 8601 standard length for YYYY-MM-DD
            const datePart = startStr.substring(0, 10)

            // Robust offset extraction: match Z or +HH:MM or -HH:MM
            const offsetMatch = startStr.match(/(Z|[+-]\d{2}:?\d{2})$/)
            const offset = offsetMatch ? offsetMatch[0] : 'Z'

            const midnightIso = `${datePart}T00:00:00${offset}`
            anchor.setTime(new Date(midnightIso).getTime())
        } catch (e) {
            console.error('Failed to parse anchor time from string:', startStr, e)
            const d = new Date(startStr)
            d.setHours(0, 0, 0, 0)
            anchor.setTime(d.getTime())
        }
    } else {
        anchor.setHours(0, 0, 0, 0)
    }

    const stepMs = resolutionMinutes * 60 * 1000
    const steps = Math.round((48 * 60) / resolutionMinutes)

    const slotByTime = new Map<string, ScheduleSlot>()
    for (const s of ordered) {
        // Standardize on UTC ISO strings for keys to avoid timezone mess
        const iso = new Date(s.start_time).toISOString()
        slotByTime.set(iso, s)
    }

    const labels: string[] = []
    const slotStarts: string[] = []
    const price: (number | null)[] = []
    const estimated: boolean[] = []
    const pv: (number | null)[] = []
    const load: (number | null)[] = []
    const charge: (number | null)[] = []
    const discharge: (number | null)[] = []
    const exp: (number | null)[] = []
    const water: (number | null)[] = []
    const waterBoost: (boolean | null)[] = []
    const customEntityActive: (number | null)[] = []
    const evCharging: (number | null)[] = []
    const evSurplus: (number | null)[] = []
    const evKeepOn: (number | null)[] = []
    const evAwaitingPlugIn: (number | null)[] = []
    const awaitingIds = new Set(evAwaitingPlugInIds)
    const socTarget: (number | null)[] = []
    const socProjected: (number | null)[] = []
    const socActual: (number | null)[] = []
    const actualPv: (number | null)[] = []
    const actualLoad: (number | null)[] = []
    const actualCharge: (number | null)[] = []
    const actualDischarge: (number | null)[] = []
    const actualExport: (number | null)[] = []
    const actualWater: (number | null)[] = []
    const actualEvCharging: (number | null)[] = []
    const gridImport: (number | null)[] = []

    let nowIndex: number | null = null
    const now = new Date()

    for (let i = 0; i < steps; i++) {
        const bucketStart = new Date(anchor.getTime() + i * stepMs)
        const bucketEnd = new Date(bucketStart.getTime() + stepMs)
        const slot = slotByTime.get(bucketStart.toISOString())

        labels.push(formatHour(bucketStart.toISOString()))
        slotStarts.push(bucketStart.toISOString())

        if (slot) {
            const hourFraction = resolutionMinutes / 60

            price.push(slot.import_price_sek_kwh ?? null)
            estimated.push(isEstimatedSlot(slot as ScheduleSlot & PriceSourceFields))
            // Main bars: always show planned/forecasted values
            // Actuals are shown in overlay lines
            const rawPvKwh = slot.pv_forecast_kwh ?? null
            pv.push(rawPvKwh != null ? rawPvKwh / hourFraction : null)

            const rawLoadKwh = slot.load_forecast_kwh ?? null
            load.push(rawLoadKwh != null ? rawLoadKwh / hourFraction : null)

            // Main bars: always show planned/forecasted values
            charge.push(slot.battery_charge_kw ?? slot.charge_kw ?? null)
            discharge.push(slot.battery_discharge_kw ?? slot.discharge_kw ?? null)

            const rawExportKwh = slot.export_kwh ?? null
            exp.push(rawExportKwh != null ? rawExportKwh / hourFraction : null)

            water.push(slot.water_heating_kw ?? null)
            waterBoost.push(
                slot.water_heating_boost && Object.values(slot.water_heating_boost).some(Boolean) ? true : null,
            )
            customEntityActive.push(
                slot.custom_entity_active && Object.values(slot.custom_entity_active).some(Boolean)
                    ? excessPvPowerKw
                    : null,
            )
            const regularEv = slot.ev_charging_kw ?? 0
            // Split planned EV kW of assumed-plugged chargers into its own series.
            const awaitingEv = slot.ev_chargers
                ? Object.entries(slot.ev_chargers).reduce(
                      (sum, [id, kw]) => (awaitingIds.has(id) ? sum + (kw || 0) : sum),
                      0,
                  )
                : 0
            const actionableEv = Math.max(0, regularEv - awaitingEv)
            evCharging.push(actionableEv > 0.01 ? actionableEv : null)
            evAwaitingPlugIn.push(awaitingEv > 0.01 ? awaitingEv : null)

            const surplusEv = slot.ev_surplus_kw
                ? Object.values(slot.ev_surplus_kw).reduce((sum: number, val: number) => sum + (val || 0), 0)
                : 0
            evSurplus.push(surplusEv > 0.01 ? surplusEv : null)

            const keepOnActive = slot.ev_keep_on ? Object.values(slot.ev_keep_on).some(Boolean) : false
            evKeepOn.push(keepOnActive && regularEv <= 0.01 ? EV_STANDBY_BAND_KW : null)
            socTarget.push(slot.soc_target_percent ?? null)
            socProjected.push(slot.projected_soc_percent ?? null)
            socActual.push(slot.actual_soc != null ? slot.actual_soc : null)

            // Populate actual* arrays
            const hourFrac = resolutionMinutes / 60
            actualPv.push(slot.actual_pv_kwh != null ? slot.actual_pv_kwh / hourFrac : null)
            actualLoad.push(slot.actual_load_kwh != null ? slot.actual_load_kwh / hourFrac : null)
            actualCharge.push(slot.actual_charge_kw ?? null)
            actualDischarge.push(slot.actual_discharge_kw ?? null)
            actualExport.push(slot.actual_export_kw ?? null)
            actualWater.push(slot.actual_water_kw ?? null)
            actualEvCharging.push(slot.actual_ev_charging_kw ?? null)

            // Planned grid import: the backend writes it per slot but it is not in the ScheduleSlot type
            const { grid_import_kw: importKw, import_kwh: importKwh } = slot as ScheduleSlot & {
                grid_import_kw?: number
                import_kwh?: number
            }
            gridImport.push(importKw ?? (importKwh != null ? importKwh / hourFrac : null))
        } else {
            price.push(null)
            estimated.push(false)
            pv.push(null)
            load.push(null)
            charge.push(null)
            discharge.push(null)
            exp.push(null)
            evCharging.push(null)
            evSurplus.push(null)
            evKeepOn.push(null)
            evAwaitingPlugIn.push(null)
            water.push(null)
            waterBoost.push(null)
            customEntityActive.push(null)
            socTarget.push(null)
            socProjected.push(null)
            socActual.push(null)
            actualPv.push(null)
            actualLoad.push(null)
            actualCharge.push(null)
            actualDischarge.push(null)
            actualExport.push(null)
            actualWater.push(null)
            actualEvCharging.push(null)
            gridImport.push(null)
        }

        if (now >= bucketStart && now < bucketEnd) {
            nowIndex = i
        }
    }

    // Calculate precise time percentage for "Now Line"
    let nowPct: number | null = null
    const totalMs = steps * stepMs
    const elapsed = now.getTime() - anchor.getTime()
    // For 48h view, we show "now" if it's within the window (which starts at 00:00 today)
    if (elapsed >= 0 && elapsed <= totalMs) {
        nowPct = elapsed / totalMs
    }

    return {
        ...createChartData(
            {
                labels,
                price,
                estimated,
                pv,
                load,
                charge,
                discharge,
                export: exp,
                water,
                waterBoost,
                customEntityActive,
                evCharging,
                evSurplus,
                evKeepOn,
                evAwaitingPlugIn,
                socTarget,
                socProjected,
                socActual,
                nowIndex,
                actualPv,
                actualLoad,
                actualCharge,
                actualDischarge,
                actualExport,
                actualWater,
                actualEvCharging,
                gridImport,
                resolutionMinutes,
                slotStarts,
                nowPct,
                showActual,
            },
            themeColors,
            pricing,
        ),
        slotStarts,
        hasTomorrowPrices,
    }
}
