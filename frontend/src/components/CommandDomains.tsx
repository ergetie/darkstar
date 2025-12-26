import { ArrowDownToLine, ArrowUpFromLine, Sun, Zap, Battery, Activity, DollarSign, Droplets, Gauge } from 'lucide-react'
import Card from './Card'

// --- Types ---
interface GridCardProps {
    netCost: number | null
    importKwh: number | null
    exportKwh: number | null
}

interface ResourcesCardProps {
    pvActual: number | null
    pvForecast: number | null
    loadActual: number | null
    loadAvg: number | null
    waterKwh: number | null
}

interface StrategyCardProps {
    soc: number | null
    socTarget: number | null
    sIndex: number | null
    cycles: number | null
    riskLabel?: string
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
    const isPositive = (netCost ?? 0) <= 0 // Negative cost is good (profit/savings) or zero
    // Note: Darkstar convention might be "Cost" = positive. 
    // If netCost is "Cost", then positive is bad. 
    // Let's assume net_cost_kr: positive = you pay, negative = you earn.

    return (
        <Card className="p-4 flex flex-col justify-between h-full relative overflow-hidden group">
            <div className={`absolute inset-0 opacity-[0.03] ${isPositive ? 'bg-emerald-500' : 'bg-red-500'}`} />
            
            {/* Header */}
            <div className="flex items-center gap-2 mb-3 relative z-10">
                <div className={`p-1.5 rounded-lg ${isPositive ? 'bg-emerald-500/10 text-emerald-400' : 'bg-red-500/10 text-red-400'}`}>
                    <DollarSign className="h-4 w-4" />
                </div>
                <span className="text-sm font-medium text-text">Grid & Financial</span>
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
                        <span className={`text-[10px] ml-2 px-1.5 py-0.5 rounded ${isPositive ? 'bg-emerald-500/10 text-emerald-400' : 'bg-red-500/10 text-red-400'}`}>
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

export function ResourcesDomain({ pvActual, pvForecast, loadActual, loadAvg, waterKwh }: ResourcesCardProps) {
    return (
        <Card className="p-4 flex flex-col h-full relative overflow-hidden">
            <div className="absolute inset-0 bg-amber-500/[0.01]" />
            
            {/* Header */}
            <div className="flex items-center gap-2 mb-4 relative z-10">
                <div className="p-1.5 rounded-lg bg-amber-500/10 text-amber-400">
                    <Zap className="h-4 w-4" />
                </div>
                <span className="text-sm font-medium text-text">Energy Resources</span>
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
                    <Battery className={`h-8 w-8 ${
                        (soc ?? 0) > 50 ? 'text-emerald-400' : (soc ?? 0) > 20 ? 'text-amber-400' : 'text-red-400'
                    }`} />
                    <div>
                        <div className="text-2xl font-bold text-text">
                            {soc?.toFixed(0) ?? '—'}%
                        </div>
                        <div className="text-[10px] text-muted">
                            {socTarget != null ? `Targeting ${socTarget.toFixed(0)}%` : 'Current SoC'}
                        </div>
                    </div>
                </div>

                {/* S-Index */}
                <div>
                    <div className="text-[10px] text-muted uppercase tracking-wider mb-1">S-Index</div>
                    <div className="text-lg font-semibold text-text">
                        {sIndex ? `x${sIndex.toFixed(2)}` : '—'}
                    </div>
                    <div className="text-[10px] text-blue-300/80">
                        Strategy Factor
                    </div>
                </div>

                {/* Cycles / Risk */}
                <div>
                    <div className="text-[10px] text-muted uppercase tracking-wider mb-1">Cycles</div>
                    <div className="text-lg font-semibold text-text">
                        {cycles?.toFixed(1) ?? '—'}
                    </div>
                    <div className="text-[10px] text-muted">
                        {riskLabel ? riskLabel : 'Daily usage'}
                    </div>
                </div>
            </div>
        </Card>
    )
}
