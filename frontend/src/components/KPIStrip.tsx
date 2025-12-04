import { TrendingDown, TrendingUp, Target, Zap, DollarSign, Activity } from 'lucide-react'
import Card from './Card'

interface KPIStripProps {
    metrics?: {
        mae_pv_aurora?: number | null
        mae_load_aurora?: number | null
        max_price_spread?: number | null
    }
    perfData?: {
        cost_series: Array<{
            date: string
            planned: number
            realized: number
        }>
    }
}

export default function KPIStrip({ metrics, perfData }: KPIStripProps) {
    // 1. Calculate Cost Drift (7-day)
    let totalPlanned = 0
    let totalRealized = 0

    if (perfData?.cost_series) {
        perfData.cost_series.forEach(d => {
            totalPlanned += d.planned
            totalRealized += d.realized
        })
    }

    const costDrift = totalRealized - totalPlanned
    const costDriftLabel = costDrift <= 0
        ? `Saved ${Math.abs(costDrift).toFixed(1)} SEK`
        : `Overspent ${costDrift.toFixed(1)} SEK`

    const isSaving = costDrift <= 0

    // 2. Forecast Accuracy
    const pvMae = metrics?.mae_pv_aurora?.toFixed(2) ?? 'N/A'
    const loadMae = metrics?.mae_load_aurora?.toFixed(2) ?? 'N/A'

    // 3. Max Price Spread
    const maxSpread = metrics?.max_price_spread
    const spreadLabel = maxSpread != null ? `${maxSpread.toFixed(2)} SEK` : 'N/A'
    const isProfitable = maxSpread != null && maxSpread > 0

    return (
        <div className="grid gap-4 grid-cols-1 md:grid-cols-2 lg:grid-cols-4">
            {/* Cost Drift */}
            <Card className="p-4 flex items-center justify-between relative overflow-hidden group">
                <div className={`absolute inset-0 opacity-[0.03] ${isSaving ? 'bg-emerald-500' : 'bg-rose-500'}`} />
                <div className="flex items-center gap-3 relative z-10">
                    <div className={`p-2 rounded-full ${isSaving ? 'bg-emerald-500/10 text-emerald-400' : 'bg-rose-500/10 text-rose-400'}`}>
                        <DollarSign className="h-5 w-5" />
                    </div>
                    <div>
                        <div className="text-[10px] text-muted uppercase tracking-wider font-medium">7-Day Cost Drift</div>
                        <div className={`text-lg font-semibold ${isSaving ? 'text-emerald-400' : 'text-rose-400'}`}>
                            {costDriftLabel}
                        </div>
                    </div>
                </div>
                <div className="text-right relative z-10">
                    <div className="text-[10px] text-muted">vs Plan</div>
                    {isSaving ? (
                        <TrendingDown className="h-4 w-4 text-emerald-500 ml-auto" />
                    ) : (
                        <TrendingUp className="h-4 w-4 text-rose-500 ml-auto" />
                    )}
                </div>
            </Card>

            {/* Max Price Spread */}
            <Card className="p-4 flex items-center justify-between relative overflow-hidden">
                <div className={`absolute inset-0 opacity-[0.03] ${isProfitable ? 'bg-emerald-500' : 'bg-rose-500'}`} />
                <div className="flex items-center gap-3 relative z-10">
                    <div className={`p-2 rounded-full ${isProfitable ? 'bg-emerald-500/10 text-emerald-400' : 'bg-rose-500/10 text-rose-400'}`}>
                        <Activity className="h-5 w-5" />
                    </div>
                    <div>
                        <div className="text-[10px] text-muted uppercase tracking-wider font-medium">Max Price Spread</div>
                        <div className={`text-lg font-semibold ${isProfitable ? 'text-emerald-400' : 'text-rose-400'}`}>
                            {spreadLabel}
                        </div>
                    </div>
                </div>
                <div className="text-right relative z-10">
                    <div className="text-[10px] text-muted">Arbitrage</div>
                    {isProfitable ? (
                        <TrendingUp className="h-4 w-4 text-emerald-500 ml-auto" />
                    ) : (
                        <TrendingDown className="h-4 w-4 text-rose-500 ml-auto" />
                    )}
                </div>
            </Card>

            {/* PV Accuracy */}
            <Card className="p-4 flex items-center justify-between relative overflow-hidden">
                <div className="absolute inset-0 bg-amber-500/[0.02]" />
                <div className="flex items-center gap-3 relative z-10">
                    <div className="p-2 rounded-full bg-amber-500/10 text-amber-400">
                        <Zap className="h-5 w-5" />
                    </div>
                    <div>
                        <div className="text-[10px] text-muted uppercase tracking-wider font-medium">PV Forecast Error</div>
                        <div className="text-lg font-semibold text-text">
                            {pvMae} <span className="text-xs font-normal text-muted">kWh</span>
                        </div>
                    </div>
                </div>
                <div className="text-right relative z-10">
                    <div className="text-[10px] text-muted">MAE (7d)</div>
                    <Target className="h-4 w-4 text-amber-500/50 ml-auto" />
                </div>
            </Card>

            {/* Load Accuracy */}
            <Card className="p-4 flex items-center justify-between relative overflow-hidden">
                <div className="absolute inset-0 bg-blue-500/[0.02]" />
                <div className="flex items-center gap-3 relative z-10">
                    <div className="p-2 rounded-full bg-blue-500/10 text-blue-400">
                        <Activity className="h-5 w-5" />
                    </div>
                    <div>
                        <div className="text-[10px] text-muted uppercase tracking-wider font-medium">Load Forecast Error</div>
                        <div className="text-lg font-semibold text-text">
                            {loadMae} <span className="text-xs font-normal text-muted">kWh</span>
                        </div>
                    </div>
                </div>
                <div className="text-right relative z-10">
                    <div className="text-[10px] text-muted">MAE (7d)</div>
                    <Target className="h-4 w-4 text-blue-500/50 ml-auto" />
                </div>
            </Card>
        </div>
    )
}
