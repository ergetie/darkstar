/**
 * Pure helpers for the Schedule Overview chart: slot info panel values, the
 * past/future split and the action strip marks. No Chart.js, no DOM.
 */
import type { ChartToken } from '../lib/chartTokens'

export type Series = (number | null)[]

/** Per-slot arrays the chart is built from (all aligned to `labels`). */
export interface SlotSeries {
    labels: string[]
    /** ISO start time per slot (live data only). */
    slotStarts?: string[]
    resolutionMinutes?: number
    nowIndex?: number | null
    price?: Series
    /** True for slots whose price rests on a forecast (Nordpool not published yet). */
    estimated?: (boolean | null)[]
    pv?: Series
    load?: Series
    charge?: Series
    discharge?: Series
    export?: Series
    gridImport?: Series
    water?: Series
    customEntityActive?: Series
    evCharging?: Series
    evSurplus?: Series
    evKeepOn?: Series
    evAwaitingPlugIn?: Series
    socProjected?: Series
    socActual?: Series
    actualPv?: Series
    actualLoad?: Series
    actualCharge?: Series
    actualDischarge?: Series
    actualExport?: Series
    actualWater?: Series
    actualEvCharging?: Series
}

const DISPLAY_TZ = 'Europe/Stockholm'

/** Below this a power value counts as "off" (noise from the planner/recorder). */
export const ACTIVE_KW = 0.05

const pad2 = (n: number) => String(n).padStart(2, '0')

/** "HH:MM" in 24h clock for an instant in the display timezone. */
export function formatClock(date: Date, tz: string = DISPLAY_TZ): string {
    const parts = new Intl.DateTimeFormat('en-GB', {
        hour: '2-digit',
        minute: '2-digit',
        hourCycle: 'h23',
        timeZone: tz,
    }).formatToParts(date)
    const get = (type: string) => parts.find((p) => p.type === type)?.value ?? '00'
    return `${get('hour')}:${get('minute')}`
}

/** "14:15–14:30" for a slot start (ISO) and length; 24h clock, never AM/PM. */
export function formatTimeRange(startIso: string, minutes: number, tz: string = DISPLAY_TZ): string {
    const start = new Date(startIso)
    if (Number.isNaN(start.getTime())) return ''
    const end = new Date(start.getTime() + minutes * 60_000)
    return `${formatClock(start, tz)}–${formatClock(end, tz)}`
}

/** Time range from an "HH:MM" axis label, for data without slot start times. */
export function formatRangeFromLabel(label: string, minutes: number): string {
    const m = /^(\d{1,2}):(\d{2})$/.exec(label)
    if (!m) return label
    const startMin = Number(m[1]) * 60 + Number(m[2])
    const endMin = (startMin + minutes) % (24 * 60)
    return `${pad2(Number(m[1]))}:${m[2]}–${pad2(Math.floor(endMin / 60))}:${pad2(endMin % 60)}`
}

export function slotTimeRange(series: SlotSeries, index: number): string {
    const minutes = series.resolutionMinutes ?? 15
    const iso = series.slotStarts?.[index]
    if (iso) {
        const range = formatTimeRange(iso, minutes)
        if (range) return range
    }
    return formatRangeFromLabel(series.labels[index] ?? '', minutes)
}

export const EMPTY_VALUE = '—'

const isNum = (v: number | null | undefined): v is number => typeof v === 'number' && Number.isFinite(v)

export function formatKw(v: number | null | undefined): string {
    return isNum(v) ? `${v.toFixed(1)} kW` : EMPTY_VALUE
}

export function formatPercent(v: number | null | undefined): string {
    return isNum(v) ? `${v.toFixed(0)} %` : EMPTY_VALUE
}

export function formatPrice(v: number | null | undefined): string {
    return isNum(v) ? `${v.toFixed(2)} SEK/kWh` : EMPTY_VALUE
}

export type SlotPhase = 'past' | 'now' | 'future'

const isEstimatedAt = (series: SlotSeries, index: number): boolean => series.estimated?.[index] === true

/** Badge text: Now / Past / Plan, or Estimated for a plan slot priced from a forecast. */
export function phaseBadge(phase: SlotPhase, estimated: boolean): string {
    if (estimated && phase !== 'past') return 'Estimated'
    return phase === 'now' ? 'Now' : phase === 'past' ? 'Past' : 'Plan'
}

export function slotPhase(index: number, nowIndex: number | null | undefined): SlotPhase {
    if (nowIndex === null || nowIndex === undefined || nowIndex < 0) return 'future'
    if (index < nowIndex) return 'past'
    return index === nowIndex ? 'now' : 'future'
}

/**
 * Measured values that may be drawn as the solid "actual" line: everything up to and
 * including the current slot. Later slots show the dashed plan only, so a stray measurement
 * after "now" is dropped. Without a "now" in view the series is returned unchanged.
 */
export function splitActualPlan(actual: Series, nowIndex: number | null | undefined): Series {
    if (nowIndex === null || nowIndex === undefined || nowIndex < 0) return actual
    return actual.map((v, i) => (i <= nowIndex ? v : null))
}

/** Slot fields that tell whether the slot's price is a forecast rather than a published one. */
export interface PriceSourceFields {
    price_source?: string | null
}

/**
 * True when the slot's price is estimated. The backend names forecast-based prices
 * `price_source: "forecast"` (see backend/core/prices.py); published ones are `"nordpool"`.
 */
export function isEstimatedSlot(slot: PriceSourceFields): boolean {
    return slot.price_source === 'forecast'
}

/** Inclusive index ranges of consecutive estimated slots. */
export function estimatedRanges(flags: (boolean | null)[] | undefined): { from: number; to: number }[] {
    const ranges: { from: number; to: number }[] = []
    if (!flags) return ranges
    let from = -1
    flags.forEach((flag, i) => {
        if (flag && from < 0) from = i
        if (!flag && from >= 0) {
            ranges.push({ from, to: i - 1 })
            from = -1
        }
    })
    if (from >= 0) ranges.push({ from, to: flags.length - 1 })
    return ranges
}

/** Upper bound for the price axis: headroom so the price area stays in the lower half. */
export function priceAxisMax(dataMax: number): number {
    if (!Number.isFinite(dataMax) || dataMax <= 0) return 1
    return dataMax * 2
}

// ---------------------------------------------------------------------------
// Action strip
// ---------------------------------------------------------------------------

export type ActionKind =
    | 'charge'
    | 'discharge'
    | 'export'
    | 'water'
    | 'waterBoost'
    | 'ev'
    | 'evSurplus'
    | 'evPlanned'
    | 'evStandby'
    | 'excess'

/** Strip row order, top to bottom. */
export const ACTION_ORDER: ActionKind[] = [
    'charge',
    'discharge',
    'export',
    'water',
    'waterBoost',
    'ev',
    'evSurplus',
    'evPlanned',
    'evStandby',
    'excess',
]

export const ACTION_TOKEN: Record<ActionKind, ChartToken> = {
    charge: 'bad',
    discharge: 'peak',
    export: 'good',
    water: 'water',
    waterBoost: 'water',
    ev: 'ai',
    evSurplus: 'ai',
    evPlanned: 'ai',
    evStandby: 'ai',
    excess: 'warn',
}

export type ActionSeries = Partial<Record<ActionKind, Series>>

/**
 * Action kinds to mark for one slot. `planned` holds the visible planned series,
 * `actual` the visible measured ones; before "now" a measured value replaces the plan.
 * Water boost is the stronger form of water heating, so it replaces the plain water mark.
 */
export function slotMarkKinds(
    index: number,
    nowIndex: number | null | undefined,
    planned: ActionSeries,
    actual: ActionSeries = {},
): ActionKind[] {
    const past = slotPhase(index, nowIndex) === 'past'
    const kinds: ActionKind[] = []
    for (const kind of ACTION_ORDER) {
        const plan = planned[kind]
        if (!plan) continue
        const measured = past ? actual[kind]?.[index] : null
        const value = isNum(measured) ? measured : plan[index]
        if (isNum(value) && value >= ACTIVE_KW) kinds.push(kind)
    }
    return kinds.includes('waterBoost') ? kinds.filter((k) => k !== 'water') : kinds
}

// ---------------------------------------------------------------------------
// Planned action text
// ---------------------------------------------------------------------------

const at = (s: Series | undefined, i: number): number | null => {
    const v = s?.[i]
    return isNum(v) ? v : null
}
const on = (s: Series | undefined, i: number): boolean => (at(s, i) ?? 0) >= ACTIVE_KW

/** What the plan does in this slot, e.g. "Charge battery 3.2 kW · Heat water". */
export function plannedActionText(series: SlotSeries, i: number): string {
    const parts: string[] = []
    if (on(series.charge, i)) parts.push(`Charge battery ${formatKw(at(series.charge, i))}`)
    if (on(series.discharge, i)) parts.push(`Discharge battery ${formatKw(at(series.discharge, i))}`)
    if (on(series.export, i)) parts.push(`Export ${formatKw(at(series.export, i))}`)
    if (on(series.water, i)) parts.push('Heat water')
    if (on(series.evCharging, i) || on(series.evSurplus, i)) parts.push('Charge EV')
    if (on(series.evAwaitingPlugIn, i)) parts.push('EV planned, awaiting plug-in')
    if (on(series.evKeepOn, i)) parts.push('EV switch held on')
    if (on(series.customEntityActive, i)) parts.push('Excess PV load on')
    return parts.length ? parts.join(' · ') : 'Hold · self-use'
}

// ---------------------------------------------------------------------------
// Info panel
// ---------------------------------------------------------------------------

export interface InfoRow {
    key: string
    label: string
    value: string
    /** Planned value shown beside a measured one ("plan 3.2 kW"), before "now" only. */
    plan?: string
    tone: ChartToken
}

export interface InfoGroup {
    title: string
    rows: InfoRow[]
    /** Small grey line under the rows (price spot/fee split). */
    note?: string
}

export interface SlotInfo {
    range: string
    phase: SlotPhase
    /** Price rests on a forecast; the badge reads "Estimated". */
    estimated: boolean
    action: string
    groups: InfoGroup[]
}

export interface SlotInfoOptions {
    /** Spot / fees+VAT split of the slot's import price, when pricing config is known. */
    breakdown?: { spot: number; feesAndVat: number } | null
}

/** Value for a slot: before "now" the measurement leads and the plan becomes the ghost. */
function lead(
    past: boolean,
    actual: number | null,
    planned: number | null,
    fmt: (v: number | null) => string,
): { value: string; plan?: string } {
    if (past && actual !== null) {
        return { value: fmt(actual), plan: planned !== null ? fmt(planned) : undefined }
    }
    return { value: fmt(planned) }
}

export function buildSlotInfo(series: SlotSeries, index: number, opts: SlotInfoOptions = {}): SlotInfo | null {
    if (index < 0 || index >= series.labels.length) return null
    const phase = slotPhase(index, series.nowIndex)
    const past = phase === 'past'
    const row = (
        key: string,
        label: string,
        tone: ChartToken,
        actual: Series | undefined,
        planned: Series | undefined,
        fmt: (v: number | null) => string,
    ): InfoRow => ({ key, label, tone, ...lead(past, at(actual, index), at(planned, index), fmt) })

    const price = at(series.price, index)
    const priceGroup: InfoGroup = {
        title: 'Price',
        rows: [{ key: 'price', label: 'Import', value: formatPrice(price), tone: 'grid' }],
        note:
            opts.breakdown && price !== null
                ? `Spot ${opts.breakdown.spot.toFixed(2)} + fees ${opts.breakdown.feesAndVat.toFixed(2)}`
                : undefined,
    }

    const battery: InfoGroup = {
        title: 'Battery',
        rows: [
            row('soc', 'SoC', 'night', series.socActual, series.socProjected, formatPercent),
            row('charge', 'Charge', 'bad', series.actualCharge, series.charge, formatKw),
            row('discharge', 'Discharge', 'peak', series.actualDischarge, series.discharge, formatKw),
        ],
    }

    const energy: InfoGroup = {
        title: 'Energy',
        rows: [
            row('pv', 'PV', 'accent', series.actualPv, series.pv, formatKw),
            row('load', 'Load', 'house', series.actualLoad, series.load, formatKw),
            row('import', 'Grid import', 'grid', undefined, series.gridImport, formatKw),
            row('export', 'Grid export', 'good', series.actualExport, series.export, formatKw),
        ],
    }

    const loadRows: InfoRow[] = []
    if (on(series.water, index) || on(series.actualWater, index)) {
        loadRows.push(row('water', 'Water heating', 'water', series.actualWater, series.water, formatKw))
    }
    const evPlanned = (at(series.evCharging, index) ?? 0) + (at(series.evSurplus, index) ?? 0)
    if (evPlanned >= ACTIVE_KW || on(series.actualEvCharging, index)) {
        const evSeries: Series = []
        evSeries[index] = evPlanned >= ACTIVE_KW ? evPlanned : null
        loadRows.push(row('ev', 'EV charging', 'ai', series.actualEvCharging, evSeries, formatKw))
    }
    if (on(series.evAwaitingPlugIn, index)) {
        loadRows.push(row('evPlanned', 'EV (awaiting plug-in)', 'ai', undefined, series.evAwaitingPlugIn, formatKw))
    }
    if (on(series.customEntityActive, index)) {
        loadRows.push(row('excess', 'Excess PV load', 'warn', undefined, series.customEntityActive, formatKw))
    }

    const groups = [priceGroup, battery, energy]
    if (loadRows.length) groups.push({ title: 'Loads', rows: loadRows })

    return {
        range: slotTimeRange(series, index),
        phase,
        estimated: isEstimatedAt(series, index),
        action: plannedActionText(series, index),
        groups,
    }
}

// ---------------------------------------------------------------------------
// Compact line
// ---------------------------------------------------------------------------

export interface CompactLine {
    range: string
    phase: SlotPhase
    estimated: boolean
    badge: string
    /** Summary parts after the time range, joined with " · " for display. */
    parts: string[]
}

const kwShort = (v: number) => `${v.toFixed(1)} kW`

/** Short action text for the compact line; past slots prefer the measured value over the plan. */
function compactAction(series: SlotSeries, i: number, past: boolean): string {
    const pick = (actual: Series | undefined, planned: Series | undefined): number | null =>
        (past ? at(actual, i) : null) ?? at(planned, i)
    const parts: string[] = []
    const charge = pick(series.actualCharge, series.charge)
    const discharge = pick(series.actualDischarge, series.discharge)
    const exported = pick(series.actualExport, series.export)
    if (charge !== null && charge >= ACTIVE_KW) parts.push(`Charge ${kwShort(charge)}`)
    if (discharge !== null && discharge >= ACTIVE_KW) parts.push(`Discharge ${kwShort(discharge)}`)
    if (exported !== null && exported >= ACTIVE_KW) parts.push(`Export ${kwShort(exported)}`)
    const water = pick(series.actualWater, series.water)
    if (water !== null && water >= ACTIVE_KW) parts.push('Water')
    const ev =
        (past ? at(series.actualEvCharging, i) : null) ??
        (at(series.evCharging, i) ?? 0) + (at(series.evSurplus, i) ?? 0)
    if (ev >= ACTIVE_KW) parts.push('EV')
    return parts.length ? parts.join(', ') : 'Hold'
}

/**
 * One-line summary of a slot: `14:15–14:30 · Charge 3.2 kW · 1.28 kr/kWh · SoC 64% · PV 2.1 kW · Load 0.8 kW`.
 * Before "now" the measured SoC / PV / load / actions are shown; otherwise the plan.
 */
export function buildCompactLine(series: SlotSeries, index: number): CompactLine | null {
    if (index < 0 || index >= series.labels.length) return null
    const phase = slotPhase(index, series.nowIndex)
    const past = phase === 'past'
    const estimated = isEstimatedAt(series, index)
    const lead = (actual: Series | undefined, planned: Series | undefined): number | null =>
        (past ? at(actual, index) : null) ?? at(planned, index)

    const price = at(series.price, index)
    const soc = lead(series.socActual, series.socProjected)
    const pv = lead(series.actualPv, series.pv)
    const load = lead(series.actualLoad, series.load)
    const parts = [compactAction(series, index, past)]
    if (price !== null) parts.push(`${price.toFixed(2)} kr/kWh`)
    if (soc !== null) parts.push(`SoC ${soc.toFixed(0)}%`)
    if (pv !== null) parts.push(`PV ${kwShort(pv)}`)
    if (load !== null) parts.push(`Load ${kwShort(load)}`)
    return { range: slotTimeRange(series, index), phase, estimated, badge: phaseBadge(phase, estimated), parts }
}
