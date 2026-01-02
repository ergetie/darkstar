import React from 'react'
import {
    ArrowDownToLine,
    ArrowUpFromLine,
    Sun,
    Zap,
    Battery,
    Activity,
    DollarSign,
    Droplets,
    Gauge,
    Flame,
    BatteryCharging,
} from 'lucide-react'
import Card from './Card'

// --- Types ---
interface GridCardProps {
    netCost: number | null
    importKwh: number | null
    exportKwh: number | null
    exportGuard?: boolean | null
}

interface ResourcesCardProps {
    pvActual: number | null
    pvForecast: number | null
    loadActual: number | null
    loadAvg: number | null
    waterKwh: number | null
    batteryCapacity?: number | null
}

interface StrategyCardProps {
    soc: number | null
    socTarget: number | null
    sIndex: number | null
    cycles: number | null
    riskLabel?: string
}

interface ControlParametersProps {
    comfortLevel: number
    setComfortLevel: (level: number) => void
    riskAppetite: number
    setRiskAppetite: (level: number) => void
    vacationMode: boolean
    onWaterBoost?: () => void
    onBatteryTopUp?: () => void
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

export function GridDomain({ netCost, importKwh, exportKwh, exportGuard }: GridCardProps) {
    const [period, setPeriod] = React.useState<'today' | 'yesterday' | 'week' | 'month'>('today')
    const [rangeData, setRangeData] = React.useState<{
        import_cost_sek: number
        export_revenue_sek: number
        grid_charge_cost_sek: number
        self_consumption_savings_sek: number
        net_cost_sek: number
        grid_import_kwh: number
        grid_export_kwh: number
        slot_count: number
    } | null>(null)
    const [loading, setLoading] = React.useState(false)

    // Fetch data when period changes
    React.useEffect(() => {
        let cancelled = false
        setLoading(true)

        import('../lib/api').then(({ Api }) => {
            Api.energyRange(period)
                .then((data) => {
                    if (!cancelled) {
                        setRangeData({
                            import_cost_sek: data.import_cost_sek,
                            export_revenue_sek: data.export_revenue_sek,
                            grid_charge_cost_sek: data.grid_charge_cost_sek,
                            self_consumption_savings_sek: data.self_consumption_savings_sek,
                            net_cost_sek: data.net_cost_sek,
                            grid_import_kwh: data.grid_import_kwh,
                            grid_export_kwh: data.grid_export_kwh,
                            slot_count: data.slot_count,
                        })
                    }
                })
                .catch(() => {
                    if (!cancelled) setRangeData(null)
                })
                .finally(() => {
                    if (!cancelled) setLoading(false)
                })
        })

        return () => { cancelled = true }
    }, [period])

    // Use range data for display, fallback to props for "today"
    const displayNetCost = rangeData?.net_cost_sek ?? netCost
    const displayImport = rangeData?.grid_import_kwh ?? importKwh
    const displayExport = rangeData?.grid_export_kwh ?? exportKwh
    const isPositive = (displayNetCost ?? 0) <= 0

    const periods = [
        { key: 'today', label: 'Today' },
        { key: 'yesterday', label: 'Yesterday' },
        { key: 'week', label: 'Week' },
        { key: 'month', label: 'Month' },
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
                {exportGuard && (
                    <span className="ml-auto text-[9px] bg-good/20 text-good px-1.5 py-0.5 rounded border border-good/20 animate-pulse">
                        Guard
                    </span>
                )}
            </div>

            {/* Period Toggle */}
            <div className="flex gap-1 mb-2 relative z-10">
                {periods.map((p) => (
                    <button
                        key={p.key}
                        onClick={() => setPeriod(p.key)}
                        className={`px-2 py-0.5 text-[9px] font-medium rounded-full transition ${period === p.key
                                ? 'bg-accent/20 text-accent border border-accent/30'
                                : 'bg-surface2/50 text-muted border border-line/30 hover:border-accent/50'
                            }`}
                    >
                        {p.label}
                    </button>
                ))}
            </div>

            {/* Big Metric: Net Cost */}
            <div className="mb-3 relative z-10">
                <div className="text-[10px] text-muted uppercase tracking-wider mb-0.5">
                    Net {period === 'today' ? 'Daily' : period === 'yesterday' ? 'Yesterday' : period === 'week' ? 'Weekly' : 'Monthly'} Cost
                </div>
                <div className="flex items-baseline gap-1">
                    <span className={`text-2xl font-bold ${loading ? 'opacity-50' : ''} ${isPositive ? 'text-good' : 'text-bad'}`}>
                        {displayNetCost != null ? Math.abs(displayNetCost).toFixed(2) : '—'}
                    </span>
                    <span className="text-xs text-muted">kr</span>
                    {displayNetCost !== null && !loading && (
                        <span className={`text-[10px] ml-2 px-1.5 py-0.5 rounded ${isPositive ? 'bg-good/10 text-good' : 'bg-bad/10 text-bad'}`}>
                            {displayNetCost > 0 ? 'COST' : 'EARNING'}
                        </span>
                    )}
                </div>
            </div>

            {/* Financial Breakdown */}
            {rangeData && (
                <div className="grid grid-cols-2 gap-1.5 mb-2 relative z-10 text-[10px]">
                    <div className="flex justify-between p-1.5 rounded bg-surface2/30">
                        <span className="text-muted">Import Cost</span>
                        <span className="text-bad font-medium">{rangeData.import_cost_sek.toFixed(1)} kr</span>
                    </div>
                    <div className="flex justify-between p-1.5 rounded bg-surface2/30">
                        <span className="text-muted">Export Rev</span>
                        <span className="text-good font-medium">{rangeData.export_revenue_sek.toFixed(1)} kr</span>
                    </div>
                    <div className="flex justify-between p-1.5 rounded bg-surface2/30">
                        <span className="text-muted">Grid Charge</span>
                        <span className="text-bad font-medium">{rangeData.grid_charge_cost_sek.toFixed(1)} kr</span>
                    </div>
                    <div className="flex justify-between p-1.5 rounded bg-surface2/30">
                        <span className="text-muted">Self-Use Saved</span>
                        <span className="text-accent font-medium">{rangeData.self_consumption_savings_sek.toFixed(1)} kr</span>
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
                        {displayImport?.toFixed(1) ?? '—'} <span className="text-[10px] text-muted font-normal">kWh</span>
                    </div>
                </div>
                <div className="p-2 rounded-lg bg-surface2/40 border border-line/30">
                    <div className="flex items-center gap-1.5 text-good mb-1">
                        <ArrowUpFromLine className="h-3 w-3" />
                        <span className="text-[10px]">Export</span>
                    </div>
                    <div className={`text-lg font-semibold text-text ${loading ? 'opacity-50' : ''}`}>
                        {displayExport?.toFixed(1) ?? '—'} <span className="text-[10px] text-muted font-normal">kWh</span>
                    </div>
                </div>
            </div>
        </Card>
    )
}

export function ResourcesDomain({
    pvActual,
    pvForecast,
    loadActual,
    loadAvg,
    waterKwh,
    batteryCapacity,
}: ResourcesCardProps) {
    return (
        <Card className="p-4 flex flex-col h-full relative overflow-hidden">
            <div className="absolute inset-0 bg-amber-500/[0.01]" />

            {/* Header */}
            <div className="flex items-center gap-2 mb-4 relative z-10">
                <div className="p-1.5 rounded-lg bg-accent/10 text-accent">
                    <Zap className="h-4 w-4" />
                </div>
                <span className="text-sm font-medium text-text">Energy Resources</span>
                {batteryCapacity != null && batteryCapacity > 0 && (
                    <span className="ml-auto text-[9px] text-muted opacity-60">{batteryCapacity} kWh Cap</span>
                )}
            </div>

            <div className="space-y-4 relative z-10">
                {/* PV Section */}
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
                    <ProgressBar value={pvActual ?? 0} total={pvForecast ?? 1} colorClass="bg-accent" />
                </div>

                {/* Load Section */}
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

                {/* Water Section */}
                <div className="flex items-center justify-between pt-2 border-t border-line/30">
                    <div className="flex items-center gap-1.5 text-[11px] text-water">
                        <Droplets className="h-3 w-3" />
                        <span>Water Heating</span>
                    </div>
                    <div className="text-sm font-medium text-text">
                        {waterKwh?.toFixed(1) ?? '—'} <span className="text-[10px] text-muted font-normal">kWh</span>
                    </div>
                </div>
            </div>
        </Card>
    )
}

export function StrategyDomain({ soc, socTarget, sIndex, cycles, riskLabel }: StrategyCardProps) {
    return (
        <Card className="p-4 flex flex-col h-full relative overflow-hidden">
            <div className="absolute inset-0 bg-ai/[0.01]" />

            {/* Header */}
            <div className="flex items-center gap-2 mb-4 relative z-10">
                <div className="p-1.5 rounded-lg bg-ai/10 text-ai">
                    <Gauge className="h-4 w-4" />
                </div>
                <span className="text-sm font-medium text-text">Battery & Strategy</span>
            </div>

            <div className="grid grid-cols-2 gap-4 relative z-10">
                {/* SoC Big Display */}
                <div className="col-span-2 flex items-center gap-3 p-3 rounded-xl bg-surface2/30 border border-line/30">
                    <Battery
                        className={`h-8 w-8 ${(soc ?? 0) > 50 ? 'text-good' : (soc ?? 0) > 20 ? 'text-warn' : 'text-bad'
                            }`}
                    />
                    <div>
                        <div className="text-2xl font-bold text-text">{soc?.toFixed(0) ?? '—'}%</div>
                        <div className="text-[10px] text-muted">
                            {socTarget != null ? `Targeting ${socTarget.toFixed(0)}%` : 'Current SoC'}
                        </div>
                    </div>
                </div>

                {/* S-Index */}
                <div>
                    <div className="text-[10px] text-muted uppercase tracking-wider mb-1">S-Index</div>
                    <div className="text-lg font-semibold text-text">{sIndex ? `x${sIndex.toFixed(2)}` : '—'}</div>
                    <div className="text-[10px] text-ai/80">Strategy Factor</div>
                </div>

                {/* Cycles / Risk */}
                <div>
                    <div className="text-[10px] text-muted uppercase tracking-wider mb-1">Cycles</div>
                    <div className="text-lg font-semibold text-text">{cycles?.toFixed(1) ?? '—'}</div>
                    <div className="text-[10px] text-muted">{riskLabel ? riskLabel : 'Daily usage'}</div>
                </div>
            </div>
        </Card>
    )
}

export function ControlParameters({
    comfortLevel,
    setComfortLevel,
    riskAppetite,
    setRiskAppetite,
    vacationMode,
    onWaterBoost,
    onBatteryTopUp,
}: ControlParametersProps) {
    return (
        <Card className="p-4 flex flex-col h-full relative overflow-hidden">
            <div className="space-y-3 relative z-10">
                {/* 1. Risk Appetite Panel */}
                <div className="metric-card-border metric-card-border-house bg-surface2/30 p-3 overflow-hidden group">
                    <div className="flex justify-between items-baseline mb-2 pl-3">
                        <div className="text-[10px] text-muted uppercase tracking-wider flex items-center gap-2">
                            <span>Market Strategy</span>
                            {/* LED Indicator */}
                            <div
                                className={`h-1.5 w-1.5 rounded-full transition-colors ${riskAppetite > 3
                                    ? 'bg-purple-400 shadow-[0_0_5px_rgba(192,132,252,0.8)]'
                                    : riskAppetite < 2
                                        ? 'bg-emerald-400'
                                        : 'bg-blue-400'
                                    }`}
                            />
                        </div>
                        <div className="text-xs font-medium text-text">
                            {{
                                1: 'Safety',
                                2: 'Conservative',
                                3: 'Neutral',
                                4: 'Aggressive',
                                5: 'Gambler',
                            }[riskAppetite] || 'Unknown'}
                        </div>
                    </div>

                    <div className="flex gap-1 h-8 pl-3">
                        {[1, 2, 3, 4, 5].map((level) => {
                            const colorMap: Record<number, string> = {
                                1: 'bg-good text-[#100f0e] border-good shadow-[0_0_10px_rgba(var(--color-good),0.4)]',
                                2: 'bg-night text-[#100f0e] border-night shadow-[0_0_10px_rgba(var(--color-night),0.4)]',
                                3: 'bg-water text-[#100f0e] border-water shadow-[0_0_10px_rgba(var(--color-water),0.4)]',
                                4: 'bg-warn text-[#100f0e] border-warn shadow-[0_0_10px_rgba(var(--color-warn),0.4)]',
                                5: 'bg-ai text-[#100f0e] border-ai shadow-[0_0_10px_rgba(var(--color-ai),0.4)]',
                            }
                            const isActive = riskAppetite === level
                            return (
                                <button
                                    key={level}
                                    onClick={() => setRiskAppetite(level)}
                                    className={`flex-1 rounded transition-all duration-300 border text-xs font-medium ${isActive
                                        ? `${colorMap[level]} ring-1 ring-inset ring-white/5`
                                        : 'bg-surface2/50 text-muted hover:bg-surface2 hover:text-text border-transparent hover:border-line/50'
                                        }`}
                                >
                                    {level}
                                </button>
                            )
                        })}
                    </div>
                </div>

                {/* 2. Water Comfort Panel */}
                <div className="metric-card-border metric-card-border-water bg-surface2/30 p-3 overflow-hidden">
                    <div className="flex justify-between items-center mb-2 pl-3">
                        <div className="text-[10px] text-muted uppercase tracking-wider flex items-center gap-2">
                            <span>Water Comfort</span>
                            {vacationMode && (
                                <span className="text-[9px] text-amber-300 bg-amber-500/20 px-1.5 rounded animate-pulse">
                                    Vacation
                                </span>
                            )}
                        </div>
                        <div className="text-xs font-medium text-text">
                            {{
                                1: 'Economy',
                                2: 'Balanced',
                                3: 'Neutral',
                                4: 'Priority',
                                5: 'Maximum',
                            }[comfortLevel] || 'Unknown'}
                        </div>
                    </div>

                    <div className="flex gap-1 h-8 pl-3">
                        {[1, 2, 3, 4, 5].map((level) => {
                            const colorMap: Record<number, string> = {
                                1: 'bg-good text-[#100f0e] border-good shadow-[0_0_10px_rgba(var(--color-good),0.4)]',
                                2: 'bg-night text-[#100f0e] border-night shadow-[0_0_10px_rgba(var(--color-night),0.4)]',
                                3: 'bg-water text-[#100f0e] border-water shadow-[0_0_10px_rgba(var(--color-water),0.4)]',
                                4: 'bg-warn text-[#100f0e] border-warn shadow-[0_0_10px_rgba(var(--color-warn),0.4)]',
                                5: 'bg-bad text-[#100f0e] border-bad shadow-[0_0_10px_rgba(var(--color-bad),0.4)]',
                            }
                            const isActive = comfortLevel === level
                            return (
                                <button
                                    key={level}
                                    onClick={() => setComfortLevel(level)}
                                    className={`flex-1 rounded transition-all duration-300 border text-xs font-medium ${isActive
                                        ? `${colorMap[level]} ring-1 ring-inset ring-white/5`
                                        : 'bg-surface2/50 text-muted hover:bg-surface2 hover:text-text border-transparent hover:border-line/50'
                                        }`}
                                >
                                    {level}
                                </button>
                            )
                        })}
                    </div>
                </div>

                {/* 3. Overrides Panel */}
                <div className="metric-card-border metric-card-border-muted bg-surface2/30 p-2 flex gap-2">
                    {/* Water Boost */}
                    <button
                        onClick={onWaterBoost}
                        className="flex-1 flex items-center justify-center gap-2 py-2 rounded-lg bg-surface hover:bg-surface2 border border-line/30 transition-all group ml-3"
                    >
                        <div className="p-1 rounded-full bg-orange-500/10 text-orange-400 group-hover:bg-orange-500/20 transition-colors">
                            <Flame className="h-3.5 w-3.5" />
                        </div>
                        <span className="text-[10px] font-medium text-text">Boost Water (1h)</span>
                    </button>
                    {/* Battery Top Up */}
                    <button
                        onClick={onBatteryTopUp}
                        className="flex-1 flex items-center justify-center gap-2 py-2 rounded-lg bg-surface hover:bg-surface2 border border-line/30 transition-all group"
                    >
                        <div className="p-1 rounded-full bg-good/10 text-good group-hover:bg-good/20 transition-colors">
                            <BatteryCharging className="h-3.5 w-3.5" />
                        </div>
                        <span className="text-[10px] font-medium text-text">Top Up 50%</span>
                    </button>
                </div>
            </div>
        </Card>
    )
}
