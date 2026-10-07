import React, { useState, useEffect, useCallback } from 'react'
import {
    ArrowDownToLine,
    ArrowUpFromLine,
    Sun,
    Zap,
    Activity,
    DollarSign,
    Droplets,
    BatteryCharging,
    Loader2,
} from 'lucide-react'
import Card from './Card'
import {
    Api,
    type EVChargerState,
    type ConfigResponse,
    type LoadBalancerStatusResponse,
    type CostSeriesResponse,
} from '../lib/api'
import { useSocket } from '../lib/hooks'
import EVChargerCard from './EVChargingCard'
import CostSeriesChart from './CostSeriesChart'

// --- Types ---
interface GridCardProps {
    netCost: number | null
    importKwh: number | null
    exportKwh: number | null
    hasEvCharger?: boolean
}

interface ResourcesCardProps {
    pvActual: number | null
    pvForecast: number | null
    pvSourceLabel?: string | null
    pvSourceActive?: boolean
    loadActual: number | null
    loadAvg: number | null
    waterKwh: number | null
    evChargingKwh?: number | null
    hasSolar?: boolean
    hasBattery?: boolean
    hasWaterHeater?: boolean
    hasEvCharger?: boolean
    batteryCapacity?: number | null
    config?: ConfigResponse | null
}

// --- Helper Components ---
const ProgressBar = ({ value, total, colorClass }: { value: number; total: number; colorClass: string }) => {
    const pct = total > 0 ? Math.min(100, (value / total) * 100) : 0
    return (
        <div className="h-1.5 w-full bg-surface2 rounded-full overflow-hidden flex">
            <div
                className={`h-full rounded-full transition-all duration-1000 ${colorClass}`}
                style={{ width: `${pct}%` }}
            />
        </div>
    )
}

type PeriodSel = 'today' | 'yesterday' | 'week' | 'month' | 'custom'

/** Computes the default {start, end} date-picker values for a given period, relative to `now`. */
// eslint-disable-next-line react-refresh/only-export-components -- pure helper, tested directly
export function getDefaultDatesForPeriod(
    prevPeriod: PeriodSel,
    now: Date = new Date(),
): { start: string; end: string } {
    const today = now
    const todayStr = today.toISOString().split('T')[0]

    switch (prevPeriod) {
        case 'today': {
            // Use yesterday to today
            const yesterday = new Date(today)
            yesterday.setDate(yesterday.getDate() - 1)
            return {
                start: yesterday.toISOString().split('T')[0],
                end: todayStr,
            }
        }
        case 'yesterday': {
            // Single day - yesterday
            const yesterdayOnly = new Date(today)
            yesterdayOnly.setDate(yesterdayOnly.getDate() - 1)
            return {
                start: yesterdayOnly.toISOString().split('T')[0],
                end: yesterdayOnly.toISOString().split('T')[0],
            }
        }
        case 'week': {
            // 7 days ago to today
            const weekAgo = new Date(today)
            weekAgo.setDate(weekAgo.getDate() - 7)
            return {
                start: weekAgo.toISOString().split('T')[0],
                end: todayStr,
            }
        }
        case 'month': {
            // 30 days ago to today
            const monthAgo = new Date(today)
            monthAgo.setDate(monthAgo.getDate() - 30)
            return {
                start: monthAgo.toISOString().split('T')[0],
                end: todayStr,
            }
        }
        default: {
            // Default to 7 days
            const defaultStart = new Date(today)
            defaultStart.setDate(defaultStart.getDate() - 7)
            return {
                start: defaultStart.toISOString().split('T')[0],
                end: todayStr,
            }
        }
    }
}

/** Pure predicate for a custom date range: both dates present and end >= start. */
// eslint-disable-next-line react-refresh/only-export-components -- pure helper, tested directly
export function isValidDateRange(start: string, end: string): boolean {
    if (!start || !end) return false
    return new Date(end) >= new Date(start)
}

// --- Domain Cards ---

export function GridDomain({ netCost, importKwh, exportKwh, hasEvCharger = false }: GridCardProps) {
    const [period, setPeriod] = useState<'today' | 'yesterday' | 'week' | 'month' | 'custom'>('today')
    const [previousPeriod, setPreviousPeriod] = useState<'today' | 'yesterday' | 'week' | 'month'>('today')
    const [startDate, setStartDate] = useState<string>('')
    const [endDate, setEndDate] = useState<string>('')
    const [dateError, setDateError] = useState<string | null>(null)
    const [fetchError, setFetchError] = useState<string | null>(null)
    const [rangeData, setRangeData] = useState<{
        import_cost_sek: number
        export_revenue_sek: number
        grid_charge_cost_sek: number
        self_consumption_savings_sek: number
        net_cost_sek: number
        battery_wear_cost_sek: number
        net_cost_incl_wear_sek: number
        grid_import_kwh: number
        grid_export_kwh: number
        ev_charging_kwh: number
        ev_cost_sek: number
        ev_solar_share: number | null
        slot_count: number
    } | null>(null)
    const [loading, setLoading] = useState(true)
    const [costSeries, setCostSeries] = useState<CostSeriesResponse | null>(null)
    const [comparisonInfoOpen, setComparisonInfoOpen] = useState(false)
    const comparisonInfoRef = React.useRef<HTMLDivElement>(null)
    useEffect(() => {
        if (!comparisonInfoOpen) return
        const onPointer = (e: PointerEvent) => {
            if (!comparisonInfoRef.current?.contains(e.target as Node)) setComparisonInfoOpen(false)
        }
        const onKey = (e: KeyboardEvent) => {
            if (e.key === 'Escape') setComparisonInfoOpen(false)
        }
        document.addEventListener('pointerdown', onPointer)
        document.addEventListener('keydown', onKey)
        return () => {
            document.removeEventListener('pointerdown', onPointer)
            document.removeEventListener('keydown', onKey)
        }
    }, [comparisonInfoOpen])

    // Validation helper for custom date range: pure predicate lives in isValidDateRange,
    // this wrapper only adds the setDateError side effect.
    const validateDateRange = (start: string, end: string): boolean => {
        if (!start || !end) return false
        const valid = isValidDateRange(start, end)
        setDateError(valid ? null : 'End date must be after start date')
        return valid
    }

    // Fetch data when period changes
    useEffect(() => {
        let cancelled = false

        const fetchData = async () => {
            if (period === 'custom' && (!startDate || !endDate)) {
                // Wait for both dates to be set
                setLoading(false)
                return
            }

            if (period === 'custom' && !validateDateRange(startDate, endDate)) {
                setLoading(false)
                return
            }

            setCostSeries(null)
            try {
                setFetchError(null)
                const [seriesResult, rangeResult] = await Promise.allSettled([
                    Api.energyCostSeries(period, startDate, endDate),
                    Api.energyRange(period, startDate, endDate),
                ])
                if (cancelled) return
                setCostSeries(seriesResult.status === 'fulfilled' ? seriesResult.value : null)
                if (rangeResult.status === 'rejected') throw rangeResult.reason
                const data = rangeResult.value
                if (!cancelled) {
                    setRangeData({
                        import_cost_sek: data.import_cost_sek,
                        export_revenue_sek: data.export_revenue_sek,
                        grid_charge_cost_sek: data.grid_charge_cost_sek,
                        self_consumption_savings_sek: data.self_consumption_savings_sek,
                        net_cost_sek: data.net_cost_sek,
                        battery_wear_cost_sek: data.battery_wear_cost_sek,
                        net_cost_incl_wear_sek: data.net_cost_incl_wear_sek,
                        grid_import_kwh: data.grid_import_kwh,
                        grid_export_kwh: data.grid_export_kwh,
                        ev_charging_kwh: data.ev_charging_kwh ?? 0,
                        ev_cost_sek: data.ev_cost_sek ?? 0,
                        ev_solar_share: data.ev_solar_share ?? null,
                        slot_count: data.slot_count,
                    })
                }
            } catch (err) {
                if (!cancelled) {
                    setRangeData(null)
                    setFetchError(err instanceof Error ? err.message : 'Failed to fetch energy data')
                }
            } finally {
                if (!cancelled) setLoading(false)
            }
        }

        fetchData()

        return () => {
            cancelled = true
        }
    }, [period, startDate, endDate])

    // Use range data for display, fallback to props for "today"
    const displayNetCost = rangeData?.net_cost_sek ?? netCost
    const displayImport = rangeData?.grid_import_kwh ?? importKwh
    const displayExport = rangeData?.grid_export_kwh ?? exportKwh
    const isPositive = (displayNetCost ?? 0) <= 0

    const candidateComparison = costSeries?.battery_comparison
    const comparison =
        candidateComparison &&
        ((candidateComparison.status === 'available' && candidateComparison.basis !== 'configured_losses') ||
            (candidateComparison.status === 'estimated' && candidateComparison.basis !== 'calibrated')) &&
        candidateComparison.darkstar &&
        candidateComparison.self_use &&
        typeof candidateComparison.saving_sek === 'number' &&
        Number.isFinite(candidateComparison.saving_sek) &&
        [candidateComparison.darkstar, candidateComparison.self_use].every((side) =>
            [
                side.grid_cost_sek,
                side.wear_cost_sek,
                side.stored_energy_change_kwh,
                side.stored_energy_value_sek,
                side.comparison_cost_sek,
            ].every(Number.isFinite),
        )
            ? {
                  ...candidateComparison,
                  saving_sek: candidateComparison.saving_sek,
                  darkstar: candidateComparison.darkstar,
                  self_use: candidateComparison.self_use,
              }
            : null
    const coverage = comparison?.coverage
    const partialCoverage =
        coverage &&
        Number.isFinite(coverage.covered_slots) &&
        Number.isFinite(coverage.total_slots) &&
        coverage.total_slots > 0 &&
        coverage.excluded_slots > 0
            ? {
                  ...coverage,
                  // Never rounds up to 100% while slots are excluded.
                  percent: Math.min(99, Math.max(1, Math.floor((coverage.covered_slots / coverage.total_slots) * 100))),
              }
            : null
    // Older available responses came only from the strict fitted path.
    const comparisonVerified = comparison?.status === 'available' && comparison.basis !== 'configured_losses'

    const periods = [
        { key: 'today', label: 'Today' },
        { key: 'yesterday', label: 'Yesterday' },
        { key: 'week', label: '7d' },
        { key: 'month', label: '30d' },
        { key: 'custom', label: 'Custom' },
    ] as const

    return (
        <Card className="p-4 flex flex-col h-full relative overflow-hidden group">
            <div className={`absolute inset-0 opacity-[0.03] ${isPositive ? 'bg-good' : 'bg-bad'}`} />

            {/* Header */}
            <div className="flex items-center gap-2 mb-2 relative z-10">
                <div className={`p-1.5 rounded-lg ${isPositive ? 'bg-good/10 text-good' : 'bg-bad/10 text-bad'}`}>
                    <DollarSign className="h-4 w-4" />
                </div>
                <span className="text-sm font-medium text-text">Grid & Financial</span>
            </div>

            {/* Period Toggle */}
            <div className="flex w-full mb-2 relative z-10 rounded-ds-sm border border-line/30 bg-surface2/50 p-0.5 gap-0.5">
                {periods.map((p) => (
                    <button
                        key={p.key}
                        onClick={() => {
                            // Store previous period before switching (for Custom default dates)
                            if (p.key === 'custom') {
                                setPreviousPeriod(period === 'custom' ? previousPeriod : period)
                                const defaults = getDefaultDatesForPeriod(period === 'custom' ? previousPeriod : period)
                                setStartDate(defaults.start)
                                setEndDate(defaults.end)
                                setDateError(null)
                                setFetchError(null)
                            } else {
                                setStartDate('')
                                setEndDate('')
                                setDateError(null)
                                setFetchError(null)
                            }
                            setPeriod(p.key)
                            setLoading(true)
                        }}
                        className={`flex-auto whitespace-nowrap px-2 py-1 text-[10px] font-medium rounded-ds-sm transition ${
                            period === p.key
                                ? 'bg-accent/20 text-accent'
                                : 'text-muted hover:text-text hover:bg-surface2'
                        }`}
                    >
                        {p.label}
                    </button>
                ))}
            </div>

            {/* Custom Date Range Inputs */}
            {period === 'custom' && (
                <div className="flex items-center gap-2 mb-2 relative z-10">
                    <input
                        type="date"
                        value={startDate}
                        onChange={(e) => {
                            setStartDate(e.target.value)
                            if (endDate) validateDateRange(e.target.value, endDate)
                        }}
                        className="bg-surface2/50 border border-line/30 rounded px-2 py-0.5 text-[9px] text-text focus:outline-none focus:ring-1 focus:ring-accent"
                    />
                    <span className="text-muted text-[9px]">to</span>
                    <input
                        type="date"
                        value={endDate}
                        onChange={(e) => {
                            setEndDate(e.target.value)
                            if (startDate) validateDateRange(startDate, e.target.value)
                        }}
                        className="bg-surface2/50 border border-line/30 rounded px-2 py-0.5 text-[9px] text-text focus:outline-none focus:ring-1 focus:ring-accent"
                    />
                </div>
            )}
            {dateError && <div className="text-[9px] text-bad mb-2 relative z-10">{dateError}</div>}
            {fetchError && <div className="text-[9px] text-bad mb-2 relative z-10">Error: {fetchError}</div>}

            {/* Big Metric: Net Cost */}
            <div className={`mb-3 relative ${comparisonInfoOpen ? 'z-30' : 'z-10'}`}>
                <div className="text-[10px] text-muted uppercase tracking-wider mb-0.5">
                    {period === 'custom'
                        ? 'Actual electricity cost · Custom Period'
                        : `Actual electricity cost · ${
                              period === 'today'
                                  ? 'Today'
                                  : period === 'yesterday'
                                    ? 'Yesterday'
                                    : period === 'week'
                                      ? '7 Days'
                                      : '30 Days'
                          }`}
                </div>
                <div className="flex items-baseline gap-1">
                    <span
                        className={`text-2xl font-bold ${loading ? 'opacity-50' : ''} ${isPositive ? 'text-good' : 'text-bad'}`}
                    >
                        {displayNetCost != null
                            ? `${displayNetCost > 0 ? '-' : '+'}${Math.abs(displayNetCost).toFixed(2)}`
                            : '—'}
                    </span>
                    <span className="text-xs text-muted">kr</span>
                </div>
                {rangeData != null && (
                    <div className="flex items-baseline gap-1 mt-0.5">
                        <span
                            className={`text-sm font-medium ${rangeData.net_cost_incl_wear_sek <= 0 ? 'text-good' : 'text-bad'} opacity-70`}
                        >
                            {rangeData.net_cost_incl_wear_sek > 0 ? '-' : '+'}
                            {Math.abs(rangeData.net_cost_incl_wear_sek).toFixed(2)}
                        </span>
                        <span className="text-[9px] text-muted">kr incl. battery wear</span>
                    </div>
                )}
                {comparison && (
                    <div ref={comparisonInfoRef} className="mt-2 relative z-30 text-[10px]">
                        <div className="flex flex-wrap items-baseline gap-x-2 gap-y-1">
                            <span className="text-muted">
                                {comparison.saving_sek >= 0 ? 'Darkstar saved you' : 'Darkstar cost you extra'}
                            </span>
                            <span
                                className={`text-sm font-semibold tabular-nums ${comparison.saving_sek >= 0 ? 'text-good' : 'text-bad'}`}
                            >
                                {Math.abs(comparison.saving_sek).toFixed(2)} kr
                            </span>
                            {partialCoverage && (
                                <span className="text-muted tabular-nums">
                                    · {partialCoverage.percent}% of the period
                                </span>
                            )}
                            <button
                                type="button"
                                aria-expanded={comparisonInfoOpen}
                                aria-label="How this is calculated"
                                onClick={() => setComparisonInfoOpen((open) => !open)}
                                className={`px-1.5 py-0.5 rounded-ds-sm border border-line/30 text-[9px] ${
                                    comparisonVerified ? 'text-good' : 'text-muted'
                                } hover:bg-surface2`}
                            >
                                {comparisonVerified ? 'Verified' : 'Estimate'} ⓘ
                            </button>
                        </div>
                        {comparisonInfoOpen && (
                            <div
                                role="dialog"
                                className="absolute left-0 top-full z-30 mt-1 w-full max-w-full rounded-ds-sm border border-line bg-surface p-2 shadow-float text-muted"
                            >
                                <div>
                                    An estimate against a plain self-use inverter with the same battery and the same
                                    EV/water timing. EV and water scheduling savings are not included.
                                </div>
                                {comparison.through && (
                                    <div className="mt-1">
                                        Completed through{' '}
                                        {(() => {
                                            const d = new Date(comparison.through)
                                            const p = (n: number) => String(n).padStart(2, '0')
                                            return `${d.getFullYear()}-${p(d.getMonth() + 1)}-${p(d.getDate())} ${p(d.getHours())}:${p(d.getMinutes())}`
                                        })()}
                                    </div>
                                )}
                                {partialCoverage && (
                                    <div className="mt-1">
                                        Based on {partialCoverage.covered_slots} of {partialCoverage.total_slots}{' '}
                                        completed 15-minute slots ({partialCoverage.excluded_slots} left out because
                                        they are missing or could not be compared reliably).
                                    </div>
                                )}
                                {!comparisonVerified && (
                                    <div className="mt-1">
                                        {comparison.calibration_status === 'unreliable_model'
                                            ? 'Calibration checks did not pass; configured battery losses are used.'
                                            : comparison.calibration_status === 'insufficient_data'
                                              ? 'Not enough reliable history to verify; configured battery losses are used.'
                                              : 'Not yet verified; configured battery losses are used.'}
                                    </div>
                                )}
                                {!comparisonVerified &&
                                    comparison.input_assumptions &&
                                    (comparison.input_assumptions.legacy_recording_slots > 0 ||
                                        comparison.input_assumptions.legacy_soc_mapping_slots > 0) && (
                                        <div className="mt-1">
                                            Older readings use assumed measurement sources and state-of-charge mapping.
                                        </div>
                                    )}
                                {comparisonVerified && (
                                    <div className="mt-1">Verified: the model passed its accuracy checks.</div>
                                )}
                                <details className="mt-1">
                                    <summary className="cursor-pointer">Cost adjustments and assumptions</summary>
                                    <div className="mt-1 pl-2">
                                        Comparison cost = grid + wear − stored energy value.
                                    </div>
                                    <div className="grid grid-cols-1 sm:grid-cols-2 gap-x-3 gap-y-0.5 mt-1 pl-2">
                                        <span>Common energy price</span>
                                        <span className="tabular-nums">
                                            {comparison.reference_price_sek_kwh?.toFixed(3)} kr/kWh
                                        </span>
                                        <span>Darkstar grid / wear / stored energy</span>
                                        <span className="tabular-nums">
                                            {comparison.darkstar.grid_cost_sek.toFixed(2)} /{' '}
                                            {comparison.darkstar.wear_cost_sek.toFixed(2)} /{' '}
                                            {comparison.darkstar.stored_energy_value_sek.toFixed(2)} kr
                                        </span>
                                        <span>Self-use grid / wear / stored energy</span>
                                        <span className="tabular-nums">
                                            {comparison.self_use.grid_cost_sek.toFixed(2)} /{' '}
                                            {comparison.self_use.wear_cost_sek.toFixed(2)} /{' '}
                                            {comparison.self_use.stored_energy_value_sek.toFixed(2)} kr
                                        </span>
                                    </div>
                                </details>
                            </div>
                        )}
                    </div>
                )}
                {costSeries?.battery_comparison &&
                    costSeries.battery_comparison.status !== 'available' &&
                    costSeries.battery_comparison.status !== 'estimated' &&
                    costSeries.battery_comparison.status !== 'no_battery' && (
                        <div className="mt-2 text-[10px] text-muted" role="status">
                            {costSeries.battery_comparison.status === 'insufficient_data'
                                ? 'Battery comparison needs more reliable history to estimate battery losses, even when viewing today.'
                                : costSeries.battery_comparison.status === 'unreliable_model'
                                  ? 'The battery comparison estimate did not pass its accuracy checks.'
                                  : costSeries.battery_comparison.status === 'incomplete_period'
                                    ? costSeries.battery_comparison.reason === 'unsupported_period_measurements'
                                        ? 'This period includes measurements that cannot be compared reliably.'
                                        : 'Battery comparison unavailable because the selected period has missing or incomplete observations.'
                                    : 'No completed observations are available for a battery comparison.'}
                        </div>
                    )}
            </div>

            {/* Financial Breakdown: one row per figure, label left, amount right */}
            {rangeData && (
                <div className="flex flex-col gap-1 mb-2 relative z-10 text-[11px]">
                    <div className="p-1.5 rounded bg-surface2/30">
                        <div className="flex items-baseline justify-between gap-2">
                            <span className="text-muted">Grid Import</span>
                            <span className="text-bad font-medium tabular-nums whitespace-nowrap">
                                {`-${rangeData.import_cost_sek.toFixed(1)} kr`}
                            </span>
                        </div>
                        {/* EV sub-row: the EV's share of Grid Import. Shown whenever an EV charger is
                            configured (0 kr · 0 kWh on idle ranges); also kept when historical EV
                            energy exists after the charger was removed. */}
                        {(hasEvCharger || rangeData.ev_charging_kwh > 0) && (
                            <div
                                className="flex items-baseline justify-between gap-2 mt-1 pl-3"
                                title="Grid import cost of EV charging in this period. Part of Grid Import above, not added to Net. Solar energy used by the EV is not given a price."
                            >
                                <span className="text-muted whitespace-nowrap">↳ of which EV</span>
                                <span className="flex items-baseline justify-end gap-1.5 min-w-0 flex-wrap">
                                    {rangeData.ev_charging_kwh > 0 ? (
                                        <>
                                            <span className="text-bad font-medium tabular-nums whitespace-nowrap">
                                                {`-${rangeData.ev_cost_sek.toFixed(1)} kr`}
                                            </span>
                                            <span className="text-muted tabular-nums whitespace-nowrap">
                                                {`${rangeData.ev_charging_kwh.toFixed(1)} kWh`}
                                            </span>
                                        </>
                                    ) : (
                                        <>
                                            <span className="text-muted font-medium tabular-nums whitespace-nowrap">
                                                0 kr
                                            </span>
                                            <span className="text-muted tabular-nums whitespace-nowrap">0 kWh</span>
                                        </>
                                    )}
                                    {rangeData.ev_charging_kwh > 0 && rangeData.ev_solar_share != null && (
                                        <span
                                            className="text-good cursor-help whitespace-nowrap"
                                            title="Share of EV energy that came from solar. For information only; solar energy has no cost in the EV figure."
                                        >
                                            {`${Math.round(rangeData.ev_solar_share * 100)}% solar`}
                                        </span>
                                    )}
                                </span>
                            </div>
                        )}
                    </div>
                    <div className="flex items-baseline justify-between gap-2 p-1.5 rounded bg-surface2/30">
                        <span className="text-muted">Export Rev</span>
                        <span className="text-good font-medium tabular-nums whitespace-nowrap">
                            {`+${rangeData.export_revenue_sek.toFixed(1)} kr`}
                        </span>
                    </div>
                    <div className="flex items-baseline justify-between gap-2 p-1.5 rounded bg-surface2/30">
                        <span className="text-muted">Battery Charge</span>
                        <span className="text-bad font-medium tabular-nums whitespace-nowrap">
                            {`-${rangeData.grid_charge_cost_sek.toFixed(1)} kr`}
                        </span>
                    </div>
                    <div className="flex items-baseline justify-between gap-2 p-1.5 rounded bg-surface2/30">
                        <span
                            className="text-muted cursor-help"
                            title="House use covered by solar/battery instead of the grid, valued at the import price."
                        >
                            Self-Use Saved
                        </span>
                        <span className="text-accent font-medium tabular-nums whitespace-nowrap">
                            {`${rangeData.self_consumption_savings_sek.toFixed(1)} kr`}
                        </span>
                    </div>
                    <div className="flex items-baseline justify-between gap-2 p-1.5 rounded bg-surface2/30">
                        <span className="text-muted">Battery Wear</span>
                        <span className="text-bad font-medium tabular-nums whitespace-nowrap">
                            {`-${rangeData.battery_wear_cost_sek.toFixed(1)} kr`}
                        </span>
                    </div>
                </div>
            )}

            {/* Cost chart: fills the remaining card height */}
            <div className="flex-1 flex flex-col relative z-10 mb-2">
                <CostSeriesChart series={costSeries} loading={loading} />
            </div>

            {/* Grid Flow Stats */}
            <div className="grid grid-cols-2 gap-2 relative z-10">
                <div className="p-2 rounded-lg bg-surface2/40 border border-line/30">
                    <div className="flex items-center gap-1.5 text-bad mb-1">
                        <ArrowDownToLine className="h-3 w-3" />
                        <span className="text-[10px]">Import</span>
                    </div>
                    <div className={`text-lg font-semibold text-text ${loading ? 'opacity-50' : ''}`}>
                        {displayImport?.toFixed(1) ?? '—'}{' '}
                        <span className="text-[10px] text-muted font-normal">kWh</span>
                    </div>
                </div>
                <div className="p-2 rounded-lg bg-surface2/40 border border-line/30">
                    <div className="flex items-center gap-1.5 text-good mb-1">
                        <ArrowUpFromLine className="h-3 w-3" />
                        <span className="text-[10px]">Export</span>
                    </div>
                    <div className={`text-lg font-semibold text-text ${loading ? 'opacity-50' : ''}`}>
                        {displayExport?.toFixed(1) ?? '—'}{' '}
                        <span className="text-[10px] text-muted font-normal">kWh</span>
                    </div>
                </div>
            </div>
        </Card>
    )
}

export function ResourcesDomain({
    pvActual,
    pvForecast,
    pvSourceLabel,
    pvSourceActive = false,
    loadActual,
    loadAvg,
    waterKwh,
    evChargingKwh,
    hasSolar = true,
    hasWaterHeater = true,
    hasEvCharger = false,
    config,
}: ResourcesCardProps) {
    const [activeTab, setActiveTab] = useState<'metrics' | 'ev'>(() => {
        try {
            const val = localStorage.getItem('darkstar-resources-tab')
            if (val === 'ev' || val === 'metrics') return val
        } catch (e) {
            console.error('Failed to read active tab from localStorage', e)
        }
        return 'metrics'
    })

    const handleTabChange = (tab: 'metrics' | 'ev') => {
        setActiveTab(tab)
        try {
            localStorage.setItem('darkstar-resources-tab', tab)
        } catch (e) {
            console.error('Failed to save active tab to localStorage', e)
        }
    }

    // A persisted 'ev' tab must never render when there's no EV charger to
    // show — guard at render time, not just by hiding the toggle button.
    const effectiveTab = hasEvCharger ? activeTab : 'metrics'

    return (
        <Card className="p-4 flex flex-col h-full relative overflow-hidden">
            <div className="absolute inset-0 bg-amber-500/[0.01]" />

            {/* Header */}
            <div className="flex items-center justify-between mb-4 relative z-10">
                <div className="flex items-center gap-2">
                    <div className="p-1.5 rounded-lg bg-accent/10 text-accent">
                        <Zap className="h-4 w-4" />
                    </div>
                    <span className="text-sm font-medium text-text">Energy Resources</span>
                </div>
                {hasEvCharger && (
                    <div className="flex items-center bg-surface-elevated rounded-lg p-0.5 text-[10px] font-medium border border-line/20">
                        <button
                            onClick={() => handleTabChange('metrics')}
                            className={`px-2 py-1 rounded-md transition-all ${
                                activeTab === 'metrics'
                                    ? 'bg-accent text-on-accent font-semibold'
                                    : 'text-muted hover:text-text'
                            }`}
                        >
                            Metrics
                        </button>
                        <button
                            onClick={() => handleTabChange('ev')}
                            className={`px-2 py-1 rounded-md transition-all ${
                                activeTab === 'ev'
                                    ? 'bg-accent text-on-accent font-semibold'
                                    : 'text-muted hover:text-text'
                            }`}
                        >
                            EV
                        </button>
                    </div>
                )}
            </div>

            {effectiveTab === 'metrics' ? (
                <div className="space-y-4 relative z-10">
                    {/* PV Section - conditional on hasSolar */}
                    {hasSolar && (
                        <div>
                            <div className="flex items-center justify-between mb-1">
                                <div className="flex items-center gap-1.5 text-[11px] text-accent">
                                    <Sun className="h-3 w-3" />
                                    <span>Solar Production</span>
                                </div>
                                <div className="text-[10px] text-muted">
                                    <span className="text-text font-medium">{pvActual?.toFixed(1) ?? '—'}</span>
                                    <span className="mx-1">/</span>
                                    {pvForecast?.toFixed(1) ?? '—'} kWh
                                </div>
                            </div>
                            {pvSourceLabel && (
                                <div className="mb-1 flex justify-end">
                                    <span
                                        className={`rounded-full border px-2 py-0.5 text-[9px] ${
                                            pvSourceActive
                                                ? 'border-emerald-400/30 bg-emerald-400/10 text-emerald-300'
                                                : 'border-sky-400/30 bg-sky-400/10 text-sky-300'
                                        }`}
                                    >
                                        {pvSourceLabel}
                                    </span>
                                </div>
                            )}
                            <ProgressBar value={pvActual ?? 0} total={pvForecast ?? 1} colorClass="bg-accent" />
                        </div>
                    )}

                    {/* Load Section - always displayed */}
                    <div>
                        <div className="flex items-center justify-between mb-1">
                            <div className="flex items-center gap-1.5 text-[11px] text-house">
                                <Activity className="h-3 w-3" />
                                <span>House Load</span>
                            </div>
                            <div className="text-[10px] text-muted">
                                <span className="text-text font-medium">{loadActual?.toFixed(1) ?? '—'}</span>
                                <span className="mx-1">/</span>
                                {loadAvg?.toFixed(1) ?? '—'} kWh
                            </div>
                        </div>
                        <ProgressBar value={loadActual ?? 0} total={loadAvg ?? 1} colorClass="bg-house" />
                    </div>

                    {/* EV Charging Section - conditional on hasEvCharger */}
                    {hasEvCharger && (
                        <div className="flex items-center justify-between pt-2 border-t border-line/30">
                            <div className="flex items-center gap-1.5 text-[11px] text-ev">
                                <BatteryCharging className="h-3 w-3" />
                                <span>EV Charging</span>
                            </div>
                            <div className="text-sm font-medium text-text">
                                {evChargingKwh?.toFixed(1) ?? '0.0'}{' '}
                                <span className="text-[10px] text-muted font-normal">kWh</span>
                            </div>
                        </div>
                    )}

                    {/* Water Section - conditional on hasWaterHeater */}
                    {hasWaterHeater && (
                        <div
                            className={`flex items-center justify-between pt-2${hasEvCharger ? '' : ' border-t border-line/30'}`}
                        >
                            <div className="flex items-center gap-1.5 text-[11px] text-water">
                                <Droplets className="h-3 w-3" />
                                <span>Water Heating</span>
                            </div>
                            <div className="text-sm font-medium text-text">
                                {waterKwh?.toFixed(1) ?? '—'}{' '}
                                <span className="text-[10px] text-muted font-normal">kWh</span>
                            </div>
                        </div>
                    )}
                </div>
            ) : (
                <div className="relative z-10 flex-1 flex flex-col min-h-0 lg:min-h-[320px]">
                    <EVTabContent config={config ?? null} />
                </div>
            )}
        </Card>
    )
}

function EVTabContent({ config }: { config: ConfigResponse | null }) {
    const [chargers, setChargers] = useState<EVChargerState[]>([])
    const [loading, setLoading] = useState(false)
    const [error, setError] = useState<string | null>(null)
    const fetchSeqRef = React.useRef(0)

    const fetchChargers = useCallback(async () => {
        const seq = ++fetchSeqRef.current
        setLoading(true)
        try {
            const data = await Api.ev.chargers()
            if (seq !== fetchSeqRef.current) return // a newer request has since started/resolved
            setChargers(data)
            setError(null)
        } catch (err) {
            if (seq !== fetchSeqRef.current) return
            console.error('Failed to fetch EV chargers', err)
            setError('Failed to load chargers')
        } finally {
            if (seq === fetchSeqRef.current) setLoading(false)
        }
    }, [])

    useEffect(() => {
        let active = true
        const run = async () => {
            await Promise.resolve()
            if (active) {
                fetchChargers()
            }
        }
        run()
        return () => {
            active = false
        }
    }, [fetchChargers])

    useSocket('ev_schedule_changed', () => {
        fetchChargers()
    })

    useSocket('ev_manual_charge_updated', () => {
        fetchChargers()
    })

    useSocket('schedule_updated', () => {
        fetchChargers()
    })

    // A failed goal-triggered replan clears plan_pending server-side.
    useSocket('planner_error', () => {
        fetchChargers()
    })

    const [loadBalancing, setLoadBalancing] = useState<LoadBalancerStatusResponse | null>(null)

    useEffect(() => {
        let active = true
        const run = async () => {
            await Promise.resolve()
            if (!active) return
            try {
                const s = await Api.executor.loadBalancerStatus()
                if (active) setLoadBalancing(s)
            } catch (err) {
                console.error('Failed to fetch load balancer status', err)
            }
        }
        run()
        return () => {
            active = false
        }
    }, [])

    useSocket('live_metrics', (data: unknown) => {
        const payload = data as { load_balancing?: LoadBalancerStatusResponse }
        setLoadBalancing(payload.load_balancing ?? null)
    })

    if (loading && chargers.length === 0) {
        return (
            <div className="flex flex-col items-center justify-center py-12 text-muted text-xs relative z-10">
                <Loader2 className="h-6 w-6 animate-spin mb-2 text-accent" />
                <span>Loading chargers…</span>
            </div>
        )
    }

    const visibleChargers = chargers.filter((c) => !c.externally_controlled)

    if (error && visibleChargers.length === 0) {
        return <div className="text-center py-12 text-bad text-xs relative z-10">{error}</div>
    }

    if (visibleChargers.length === 0) {
        return (
            <div className="text-center py-12 text-muted text-xs relative z-10">
                No EV chargers enabled or configured.
            </div>
        )
    }

    return (
        // On desktop the list fills the grid cell without driving its height,
        // and scrolls when several chargers do not fit.
        <div className="flex flex-col gap-4 pr-1 custom-scrollbar max-h-[360px] overflow-y-auto lg:max-h-none lg:absolute lg:inset-0">
            {visibleChargers.map((charger) => (
                <EVChargerCard
                    key={charger.id}
                    fill={visibleChargers.length === 1}
                    charger={charger}
                    config={config}
                    loadBalancing={loadBalancing}
                    onRefresh={fetchChargers}
                />
            ))}
        </div>
    )
}
