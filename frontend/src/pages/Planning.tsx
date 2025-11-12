import { useEffect, useState } from 'react'
import Card from '../components/Card'
import ChartCard from '../components/ChartCard'
import PillButton from '../components/PillButton'
import { lanes, blocks } from '../lib/sample'
import { Api, Sel } from '../lib/api'
import type { DaySel } from '../lib/time'

const laneHeight = 64  // px
const hours = Array.from({length:24}, (_,i)=>i)

export default function Planning(){
    const [soc, setSoc] = useState<number | null>(null)
    const [horizon, setHorizon] = useState<{pvDays?: number; weatherDays?: number} | null>(null)
    const [day, setDay] = useState<DaySel>('today')

    useEffect(() => {
        Api.status()
            .then((d) => setSoc(Sel.socValue(d) ?? null))
            .catch(() => {})
        Api.horizon()
            .then((d) =>
                setHorizon({
                    pvDays: Sel.pvDays(d) ?? undefined,
                    weatherDays: Sel.wxDays(d) ?? undefined,
                }),
            )
            .catch(() => {})
    }, [])

    const socDisplay = soc !== null ? `${soc.toFixed(1)}%` : '—'
    const pvDays = horizon?.pvDays ?? '—'
    const weatherDays = horizon?.weatherDays ?? '—'

    return (
        <main className="mx-auto max-w-7xl px-6 pb-24 pt-10 lg:pt-12">
        <Card className="p-4 md:p-6">
        <div className="flex items-baseline justify-between pb-4">
        <div className="text-sm text-muted">Planning Timeline</div>
        <div className="text-[11px] text-muted">today → tomorrow</div>
        </div>
        <div className="flex flex-wrap gap-6 pb-4 text-[11px] uppercase tracking-wider text-muted">
        <div className="text-text">SoC now: {socDisplay}</div>
        <div className="text-text">Horizon: PV {pvDays}d · Weather {weatherDays}d</div>
        </div>

        <div className="relative rounded-xl2 border border-line/60 bg-surface2 overflow-hidden">
        {/* hour grid */}
        <div className="absolute left-28 right-2 top-0 h-[16px] flex items-center gap-2 px-2 text-[10px] text-muted">
        {hours.map(h => (
            <div key={h} className="flex-1 text-center">{String(h).padStart(2,'0')}</div>
        ))}
        </div>

        {/* vertical grid lines */}
        <div className="absolute left-28 right-2 bottom-2 top-6 grid"
        style={{ gridTemplateColumns: 'repeat(24,minmax(0,1fr))' }}>
        {hours.map(h => (
            <div key={h} className="border-l border-line/60" />
        ))}
        </div>

        {/* lanes */}
        <div className="pl-2 pr-2 pt-6 pb-2">
        {lanes.map((lane, idx) => (
            <div key={lane.id} className="relative flex items-center" style={{ height: laneHeight }}>
            {/* floating add buttons column */}
            <div className="w-24 flex items-center justify-center">
            <div className="grid gap-2">
            {/* one pill that matches your screenshot per lane */}
            <PillButton
            label={
                lane.id==='battery' ? '+ chg' :
                lane.id==='water'   ? '+ wtr' :
                lane.id==='export'  ? '+ exp' : '+ hld'
            }
            color={lane.color}
            />
            </div>
            </div>

            {/* lane rail */}
            <div className="relative flex-1 h-12 rounded-xl2 border border-line/70 bg-surface shadow-inset1">
            {/* blocks */}
            {blocks.filter(b=>b.lane===lane.id).map((b, i) => {
                const leftPct = (b.start/24)*100
                const widthPct = (b.len/24)*100
                return (
                    <div key={i}
                    className="absolute top-1 bottom-1 rounded-pill shadow-float"
                    style={{ left: `${leftPct}%`, width: `${widthPct}%`, background: b.color }}
                    />
                )
            })}
            {/* "now" indicator */}
            <div className="absolute top-0 bottom-0 w-0.5 bg-[#ff6a6a] left-[66%] opacity-80" />
            </div>
            </div>
        ))}
        </div>
        </div>

        <div className="mt-4 flex gap-3 justify-end">
        <button className="rounded-pill bg-accent text-canvas px-5 py-2.5 font-semibold">Apply manual changes</button>
        <button className="rounded-pill border border-line/70 px-5 py-2.5 text-text hover:border-accent">Reset</button>
        </div>
        </Card>
        <div className="mt-6">
        <div className="flex gap-3">
        <button
            className={`rounded-pill px-4 py-2 text-[11px] font-semibold uppercase tracking-wide transition ${day === 'today' ? 'bg-accent text-canvas' : 'bg-surface border border-line/60 text-muted'}`}
            onClick={() => setDay('today')}
        >
            Today
        </button>
        <button
            className={`rounded-pill px-4 py-2 text-[11px] font-semibold uppercase tracking-wide transition ${day === 'tomorrow' ? 'bg-accent text-canvas' : 'bg-surface border border-line/60 text-muted'}`}
            onClick={() => setDay('tomorrow')}
        >
            Tomorrow
        </button>
        </div>
        <div className="mt-4">
        <ChartCard day={day} />
        </div>
        </div>
        </main>
    )
}
