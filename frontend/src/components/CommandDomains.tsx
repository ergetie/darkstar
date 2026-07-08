/* eslint-disable @typescript-eslint/no-explicit-any */
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
import { Api } from '../lib/api'
import { useSocket } from '../lib/hooks'
import EVChargerCard from './EVChargingCard'

// --- Types ---
interface GridCardProps {
    netCost: number | null
    importKwh: number | null
    exportKwh: number | null
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
    config?: any | null
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

// --- Domain Cards ---

export function GridDomain({ netCost, importKwh, exportKwh }: GridCardProps) {
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
        slot_count: number
    } | null>(null)
    const [loading, setLoading] = useState(true)

    // Helper to calculate default dates based on previous period
    const getDefaultDatesForPeriod = (prevPeriod: typeof previousPeriod) => {
        const today = new Date()
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

    // Validation helper for custom date range
    const validateDateRange = (start: string, end: string): boolean => {
        if (!start || !end) return false
        const startDate = new Date(start)
        const endDate = new Date(end)
        if (endDate < startDate) {
            setDateError('End date must be after start date')
            return false
        }
        setDateError(null)
        return true
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

            try {
                setFetchError(null)
                const data = await Api.energyRange(period, startDate, endDate)
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

    const periods = [
        { key: 'today', label: 'Today' },
        { key: 'yesterday', label: 'Yesterday' },
        { key: 'week', label: '7 Days' },
        { key: 'month', label: '30 Days' },
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
            <div className="flex gap-1 mb-2 relative z-10">
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
                        className={`px-2 py-0.5 text-[9px] font-medium rounded-full transition ${
                            period === p.key
                                ? 'bg-accent/20 text-accent border border-accent/30'
                                : 'bg-surface2/50 text-muted border border-line/30 hover:border-accent/50'
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
            <div className="mb-3 relative z-10">
                <div className="text-[10px] text-muted uppercase tracking-wider mb-0.5">
                    {period === 'custom'
                        ? 'Custom Period'
                        : `Net ${
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
            </div>

            {/* Financial Breakdown */}
            {rangeData && (
                <div className="grid grid-cols-2 gap-1.5 mb-2 relative z-10 text-[10px]">
                    <div className="flex justify-between p-1.5 rounded bg-surface2/30">
                        <span className="text-muted">Grid Import</span>
                        <span className="text-bad font-medium">-{rangeData.import_cost_sek.toFixed(1)} kr</span>
                    </div>
                    <div className="flex justify-between p-1.5 rounded bg-surface2/30">
                        <span className="text-muted">Export Rev</span>
                        <span className="text-good font-medium">+{rangeData.export_revenue_sek.toFixed(1)} kr</span>
                    </div>
                    <div className="flex justify-between p-1.5 rounded bg-surface2/30">
                        <span className="text-muted">Battery Charge</span>
                        <span className="text-bad font-medium">-{rangeData.grid_charge_cost_sek.toFixed(1)} kr</span>
                    </div>
                    <div className="flex justify-between p-1.5 rounded bg-surface2/30">
                        <span className="text-muted">Self-Use Saved</span>
                        <span className="text-accent font-medium">
                            {rangeData.self_consumption_savings_sek.toFixed(1)} kr
                        </span>
                    </div>
                    <div className="flex justify-between p-1.5 rounded bg-surface2/30">
                        <span className="text-muted">Battery Wear</span>
                        <span className="text-bad font-medium">-{rangeData.battery_wear_cost_sek.toFixed(1)} kr</span>
                    </div>
                </div>
            )}

            {/* Grid Flow Stats */}
            <div className="grid grid-cols-2 gap-2 mt-auto relative z-10">
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
    hasBattery = true,
    hasWaterHeater = true,
    hasEvCharger = false,
    batteryCapacity,
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
                    {hasBattery && batteryCapacity != null && batteryCapacity > 0 && (
                        <span className="text-[9px] text-muted opacity-60 ml-2">({batteryCapacity} kWh Cap)</span>
                    )}
                </div>
                {hasEvCharger && (
                    <div className="flex items-center bg-surface-elevated rounded-lg p-0.5 text-[10px] font-medium border border-line/20">
                        <button
                            onClick={() => handleTabChange('metrics')}
                            className={`px-2 py-1 rounded-md transition-all ${
                                activeTab === 'metrics'
                                    ? 'bg-accent text-surface-elevated font-semibold'
                                    : 'text-muted hover:text-text'
                            }`}
                        >
                            Metrics
                        </button>
                        <button
                            onClick={() => handleTabChange('ev')}
                            className={`px-2 py-1 rounded-md transition-all ${
                                activeTab === 'ev'
                                    ? 'bg-accent text-surface-elevated font-semibold'
                                    : 'text-muted hover:text-text'
                            }`}
                        >
                            EV
                        </button>
                    </div>
                )}
            </div>

            {activeTab === 'metrics' ? (
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
                <EVTabContent config={config} />
            )}
        </Card>
    )
}

function EVTabContent({ config }: { config: any }) {
    const [chargers, setChargers] = useState<any[]>([])
    const [loading, setLoading] = useState(false)
    const [error, setError] = useState<string | null>(null)

    const fetchChargers = useCallback(() => {
        setLoading(true)
        Api.ev
            .chargers()
            .then(setChargers)
            .catch((err) => {
                console.error('Failed to fetch EV chargers', err)
                setError('Failed to load chargers')
            })
            .finally(() => setLoading(false))
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

    useSocket('schedule_updated', () => {
        fetchChargers()
    })

    const [loadBalancing, setLoadBalancing] = useState<any>(null)

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

    useSocket('live_metrics', (data: any) => {
        if (data?.load_balancing) {
            setLoadBalancing(data.load_balancing)
        }
    })

    if (loading && chargers.length === 0) {
        return (
            <div className="flex flex-col items-center justify-center py-12 text-muted text-xs relative z-10">
                <Loader2 className="h-6 w-6 animate-spin mb-2 text-accent" />
                <span>Loading chargers…</span>
            </div>
        )
    }

    const visibleChargers = chargers.filter((c: any) => !c.externally_controlled)

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
        <div className="space-y-4 overflow-y-auto max-h-[360px] pr-1 relative z-10 custom-scrollbar">
            {visibleChargers.map((charger) => (
                <EVChargerCard
                    key={charger.id}
                    charger={charger}
                    config={config}
                    loadBalancing={loadBalancing}
                    onRefresh={fetchChargers}
                />
            ))}
        </div>
    )
}
