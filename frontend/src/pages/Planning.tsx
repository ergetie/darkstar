import { useEffect, useMemo, useState } from 'react'
import Card from '../components/Card'
import PillButton from '../components/PillButton'
import { Api } from '../lib/api'
import type { ScheduleSlot } from '../lib/types'
import { isToday, isTomorrow } from '../lib/time'
import PlanningTimeline from '../components/PlanningTimeline'

type LaneId = 'battery' | 'water' | 'export' | 'hold'

type PlanningLane = {
    id: LaneId
    label: string
    color: string
}

type PlanningBlock = {
    id: string
    lane: LaneId
    start: Date
    end: Date
    source: 'schedule'
}

const planningLanes: PlanningLane[] = [
    { id: 'battery', label: 'Battery', color: '#AAB6C4' },
    { id: 'water',   label: 'Water',   color: '#FF7A7A' },
    { id: 'export',  label: 'Export',  color: '#9BF6A3' },
    { id: 'hold',    label: 'Hold',    color: '#FFD966' },
]

function classifyBlocks(slots: ScheduleSlot[]): PlanningBlock[] {
    const blocks: PlanningBlock[] = []

    slots.forEach((slot, index) => {
        if (!isToday(slot.start_time) && !isTomorrow(slot.start_time)) return

        const start = new Date(slot.start_time)
        const end = new Date(start.getTime() + 30 * 60 * 1000)

        const laneCandidates: LaneId[] = []

        const charge = slot.battery_charge_kw ?? slot.charge_kw ?? 0
        const discharge = slot.battery_discharge_kw ?? slot.discharge_kw ?? 0
        const water = slot.water_heating_kw ?? 0
        const exp = slot.export_kwh ?? 0

        if (charge > 0 || discharge > 0) laneCandidates.push('battery')
        if (water > 0) laneCandidates.push('water')
        if (exp > 0) laneCandidates.push('export')
        if (!laneCandidates.length) laneCandidates.push('hold')

        laneCandidates.forEach((lane, laneIdx) => {
            blocks.push({
                id: `${index}-${lane}-${laneIdx}`,
                lane,
                start,
                end,
                source: 'schedule',
            })
        })
    })

    return blocks
}

export default function Planning(){
    const [schedule, setSchedule] = useState<ScheduleSlot[] | null>(null)
    const [blocks, setBlocks] = useState<PlanningBlock[]>([])
    const [error, setError] = useState<string | null>(null)
    const [loading, setLoading] = useState(false)

    useEffect(() => {
        let cancelled = false
        setLoading(true)
        setError(null)
        Api.schedule()
            .then(res => {
                if (cancelled) return
                const sched = res.schedule ?? []
                setSchedule(sched)
                setBlocks(classifyBlocks(sched))
            })
            .catch(err => {
                if (cancelled) return
                console.error('Failed to load schedule for Planning:', err)
                setError('Failed to load schedule')
            })
            .finally(() => {
                if (cancelled) return
                setLoading(false)
            })

        return () => { cancelled = true }
    }, [])

    const planningBlocks = useMemo(
        () => blocks,
        [blocks],
    )

    const handleBlockMove = ({ id, start, lane }: { id: string; start: Date; lane: LaneId }) => {
        setBlocks(prev =>
            prev.map(b => {
                if (b.id !== id) return b
                const duration = b.end.getTime() - b.start.getTime()
                const newEnd = new Date(start.getTime() + duration)
                return { ...b, start, end: newEnd, lane }
            }),
        )
    }

    const handleBlockResize = ({ id, start, end }: { id: string; start: Date; end: Date }) => {
        setBlocks(prev =>
            prev.map(b => (b.id === id ? { ...b, start, end } : b)),
        )
    }

    const handleAddBlock = (lane: LaneId) => {
        const base = new Date()
        const start = new Date(base)
        start.setMinutes(start.getMinutes() < 30 ? 0 : 30, 0, 0)
        const end = new Date(start.getTime() + 60 * 60 * 1000) // 1 hour
        const id = `manual-${Date.now()}-${lane}`
        setBlocks(prev => [
            ...prev,
            {
                id,
                lane,
                start,
                end,
                source: 'schedule',
            },
        ])
    }

    return (
        <main className="mx-auto max-w-7xl px-6 pb-24 pt-10 lg:pt-12">
        <Card className="p-4 md:p-6">
        <div className="flex items-baseline justify-between pb-4">
        <div className="text-sm text-muted">Planning Timeline</div>
        <div className="text-[11px] text-muted">
            {loading && 'Loading schedule…'}
            {!loading && error && error}
            {!loading && !error && 'today → tomorrow'}
        </div>
        </div>

        <div className="rounded-xl2 border border-line/60 bg-surface2 overflow-hidden">
        <PlanningTimeline
            lanes={planningLanes}
            blocks={planningBlocks}
            onBlockMove={handleBlockMove}
            onBlockResize={handleBlockResize}
        />
        </div>

        <div className="mt-4 flex gap-3 justify-between">
        <div className="flex gap-3">
        {planningLanes.map((lane) => (
            <PillButton
            key={lane.id}
            label={
                lane.id==='battery' ? '+ chg' :
                lane.id==='water'   ? '+ wtr' :
                lane.id==='export'  ? '+ exp' : '+ hld'
            }
            color={lane.color}
            onClick={() => handleAddBlock(lane.id)}
            />
        ))}
        </div>

        <button className="rounded-pill bg-accent text-canvas px-5 py-2.5 font-semibold" disabled>
            Apply manual changes
        </button>
        <button className="rounded-pill border border-line/70 px-5 py-2.5 text-text hover:border-accent" disabled>
            Reset
        </button>
        </div>
        </Card>
        </main>
    )
}
