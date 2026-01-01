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
    const isPositive = (netCost ?? 0) <= 0 // Negative cost is good (profit/savings) or zero
    // Note: Darkstar convention might be "Cost" = positive.
    // If netCost is "Cost", then positive is bad.
    // Let's assume net_cost_kr: positive = you pay, negative = you earn.

    return (
        <Card className="p-4 flex flex-col justify-between h-full relative overflow-hidden group">
            <div className={`absolute inset-0 opacity-[0.03] ${isPositive ? 'bg-emerald-500' : 'bg-red-500'}`} />

            {/* Header */}
            <div className="flex items-center gap-2 mb-3 relative z-10">
                <div
                    className={`p-1.5 rounded-lg ${isPositive ? 'bg-emerald-500/10 text-emerald-400' : 'bg-red-500/10 text-red-400'}`}
                >
                    <DollarSign className="h-4 w-4" />
                </div>
                <span className="text-sm font-medium text-text">Grid & Financial</span>
                {exportGuard && (
                    <span className="ml-auto text-[9px] bg-emerald-500/20 text-emerald-400 px-1.5 py-0.5 rounded border border-emerald-500/20 animate-pulse">
                        Guard
                    </span>
                )}
            </div>

            {/* Big Metric: Net Cost */}
            <div className="mb-4 relative z-10">
                <div className="text-[10px] text-muted uppercase tracking-wider mb-0.5">Net Daily Cost</div>
                <div className="flex items-baseline gap-1">
                    <span className={`text-2xl font-bold ${isPositive ? 'text-emerald-400' : 'text-red-400'}`}>
                        {netCost != null ? Math.abs(netCost).toFixed(2) : '—'}
                    </span>
                    <span className="text-xs text-muted">kr</span>
                    {netCost !== null && (
                        <span
                            className={`text-[10px] ml-2 px-1.5 py-0.5 rounded ${isPositive ? 'bg-emerald-500/10 text-emerald-400' : 'bg-red-500/10 text-red-400'}`}
                        >
                            {netCost > 0 ? 'COST' : 'EARNING'}
                        </span>
                    )}
                </div>
            </div>

            {/* Grid Flow Stats */}
            <div className="grid grid-cols-2 gap-2 mt-auto relative z-10">
                <div className="p-2 rounded-lg bg-surface2/40 border border-line/30">
                    <div className="flex items-center gap-1.5 text-red-300 mb-1">
                        <ArrowDownToLine className="h-3 w-3" />
                        <span className="text-[10px]">Import</span>
                    </div>
                    <div className="text-lg font-semibold text-text">
                        {importKwh?.toFixed(1) ?? '—'} <span className="text-[10px] text-muted font-normal">kWh</span>
                    </div>
                </div>
                <div className="p-2 rounded-lg bg-surface2/40 border border-line/30">
                    <div className="flex items-center gap-1.5 text-emerald-300 mb-1">
                        <ArrowUpFromLine className="h-3 w-3" />
                        <span className="text-[10px]">Export</span>
                    </div>
                    <div className="text-lg font-semibold text-text">
                        {exportKwh?.toFixed(1) ?? '—'} <span className="text-[10px] text-muted font-normal">kWh</span>
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
                <div className="p-1.5 rounded-lg bg-amber-500/10 text-amber-400">
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
                        <div className="flex items-center gap-1.5 text-[11px] text-amber-300">
                            <Sun className="h-3 w-3" />
                            <span>Solar Production</span>
                        </div>
                        <div className="text-[10px] text-muted">
                            <span className="text-text font-medium">{pvActual?.toFixed(1) ?? '—'}</span>
                            <span className="mx-1">/</span>
                            {pvForecast?.toFixed(1) ?? '—'} kWh
                        </div>
                    </div>
                    <ProgressBar value={pvActual ?? 0} total={pvForecast ?? 1} colorClass="bg-amber-400" />
                </div>

                {/* Load Section */}
                <div>
                    <div className="flex items-center justify-between mb-1">
                        <div className="flex items-center gap-1.5 text-[11px] text-purple-300">
                            <Activity className="h-3 w-3" />
                            <span>House Load</span>
                        </div>
                        <div className="text-[10px] text-muted">
                            <span className="text-text font-medium">{loadActual?.toFixed(1) ?? '—'}</span>
                            <span className="mx-1">/</span>
                            {loadAvg?.toFixed(1) ?? '—'} kWh
                        </div>
                    </div>
                    <ProgressBar value={loadActual ?? 0} total={loadAvg ?? 1} colorClass="bg-purple-400" />
                </div>

                {/* Water Section */}
                <div className="flex items-center justify-between pt-2 border-t border-line/30">
                    <div className="flex items-center gap-1.5 text-[11px] text-sky-300">
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
            <div className="absolute inset-0 bg-blue-500/[0.01]" />

            {/* Header */}
            <div className="flex items-center gap-2 mb-4 relative z-10">
                <div className="p-1.5 rounded-lg bg-blue-500/10 text-blue-400">
                    <Gauge className="h-4 w-4" />
                </div>
                <span className="text-sm font-medium text-text">Battery & Strategy</span>
            </div>

            <div className="grid grid-cols-2 gap-4 relative z-10">
                {/* SoC Big Display */}
                <div className="col-span-2 flex items-center gap-3 p-3 rounded-xl bg-surface2/30 border border-line/30">
                    <Battery
                        className={`h-8 w-8 ${
                            (soc ?? 0) > 50 ? 'text-emerald-400' : (soc ?? 0) > 20 ? 'text-amber-400' : 'text-red-400'
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
                    <div className="text-[10px] text-blue-300/80">Strategy Factor</div>
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
            {/* Connective Line (Left) */}
            <div className="absolute left-[19px] top-6 bottom-6 w-[1px] bg-line/30 z-0" />

            <div className="space-y-3 relative z-10">
                {/* 1. Risk Appetite Panel */}
                <div className="bg-surface2/30 rounded-xl p-3 border border-line/50 relative overflow-hidden group">
                    <div className="absolute left-0 top-0 bottom-0 w-1 bg-gradient-to-b from-blue-500/50 to-purple-500/50" />
                    <div className="flex justify-between items-baseline mb-2 pl-3">
                        <div className="text-[10px] text-muted uppercase tracking-wider flex items-center gap-2">
                            <span>Market Strategy</span>
                            {/* LED Indicator */}
                            <div
                                className={`h-1.5 w-1.5 rounded-full transition-colors ${
                                    riskAppetite > 3
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
                                1: 'bg-emerald-500/20 text-emerald-300 border-emerald-500/40 shadow-[0_0_10px_rgba(16,185,129,0.2)]',
                                2: 'bg-teal-500/20 text-teal-300 border-teal-500/40 shadow-[0_0_10px_rgba(20,184,166,0.2)]',
                                3: 'bg-blue-500/20 text-blue-300 border-blue-500/40 shadow-[0_0_10px_rgba(59,130,246,0.2)]',
                                4: 'bg-amber-500/20 text-amber-300 border-amber-500/40 shadow-[0_0_10px_rgba(245,158,11,0.2)]',
                                5: 'bg-purple-500/20 text-purple-300 border-purple-500/40 shadow-[0_0_10px_rgba(168,85,247,0.2)]',
                            }
                            const isActive = riskAppetite === level
                            return (
                                <button
                                    key={level}
                                    onClick={() => setRiskAppetite(level)}
                                    className={`flex-1 rounded transition-all duration-300 border text-xs font-medium ${
                                        isActive
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
                <div className="bg-surface2/30 rounded-xl p-3 border border-line/50 relative overflow-hidden">
                    <div className="absolute left-0 top-0 bottom-0 w-1 bg-gradient-to-b from-amber-500/50 to-red-500/50" />

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
                                1: 'bg-emerald-500/20 text-emerald-300 border-emerald-500/40 shadow-[0_0_10px_rgba(16,185,129,0.2)]',
                                2: 'bg-teal-500/20 text-teal-300 border-teal-500/40 shadow-[0_0_10px_rgba(20,184,166,0.2)]',
                                3: 'bg-blue-500/20 text-blue-300 border-blue-500/40 shadow-[0_0_10px_rgba(59,130,246,0.2)]',
                                4: 'bg-amber-500/20 text-amber-300 border-amber-500/40 shadow-[0_0_10px_rgba(245,158,11,0.2)]',
                                5: 'bg-red-500/20 text-red-300 border-red-500/40 shadow-[0_0_10px_rgba(239,68,68,0.2)]',
                            }
                            const isActive = comfortLevel === level
                            return (
                                <button
                                    key={level}
                                    onClick={() => setComfortLevel(level)}
                                    className={`flex-1 rounded transition-all duration-300 border text-xs font-medium ${
                                        isActive
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
                <div className="bg-surface2/30 rounded-xl p-2 border border-line/50 flex gap-2 relative">
                    <div className="absolute left-0 top-0 bottom-0 w-1 bg-line/50" />
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
                        <div className="p-1 rounded-full bg-emerald-500/10 text-emerald-400 group-hover:bg-emerald-500/20 transition-colors">
                            <BatteryCharging className="h-3.5 w-3.5" />
                        </div>
                        <span className="text-[10px] font-medium text-text">Top Up 50%</span>
                    </button>
                </div>
            </div>
        </Card>
    )
}
