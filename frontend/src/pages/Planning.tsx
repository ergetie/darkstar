import { useEffect, useMemo, useState } from 'react'
import Card from '../components/Card'
import ChartCard from '../components/ChartCard'
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
    isHistorical?: boolean
}

type PlanningConstraints = {
    minSocPercent: number
    maxSocPercent: number
    maxChargeKw: number
    maxDischargeKw: number
}

const planningLanes: PlanningLane[] = [
    { id: 'battery', label: 'Battery', color: '#AAB6C4' },
    { id: 'water',   label: 'Water',   color: '#FF7A7A' },
    { id: 'export',  label: 'Export',  color: '#9BF6A3' },
    { id: 'hold',    label: 'Hold',    color: '#FFD966' },
]

function classifyBlocks(slots: ScheduleSlot[], caps?: PlanningConstraints | null): PlanningBlock[] {
    const filtered = slots.filter(
        (slot) => isToday(slot.start_time) || isTomorrow(slot.start_time),
    )

    if (!filtered.length) return []

    const sorted = [...filtered].sort(
        (a, b) =>
            new Date(a.start_time).getTime() - new Date(b.start_time).getTime(),
    )

    const merged: PlanningBlock[] = []
    const lastByLane: Partial<Record<LaneId, PlanningBlock>> = {}
    let blockCounter = 0

    for (const slot of sorted) {
        const start = new Date(slot.start_time)
        const end = slot.end_time
            ? new Date(slot.end_time)
            : new Date(start.getTime() + 30 * 60 * 1000)
        const isHistorical = slot.is_historical === true

        const laneCandidates: LaneId[] = []

        const charge = slot.battery_charge_kw ?? slot.charge_kw ?? 0
        const discharge = slot.battery_discharge_kw ?? slot.discharge_kw ?? 0
        const water = slot.water_heating_kw ?? 0
        const exp = slot.export_kwh ?? 0

        // Identify slots where the device cannot meaningfully act:
        // no controllable actions and SoC pinned to configured bounds.
        let isPinnedZeroCapacity = false
        if (caps) {
            const soc =
                (typeof slot.projected_soc_percent === 'number'
                    ? slot.projected_soc_percent
                    : typeof slot.soc_target_percent === 'number'
                      ? slot.soc_target_percent
                      : null)
            const noActions =
                (charge || 0) <= 0 &&
                (discharge || 0) <= 0 &&
                (water || 0) <= 0 &&
                (exp || 0) <= 0
            if (
                noActions &&
                typeof soc === 'number' &&
                (soc <= caps.minSocPercent + 0.01 ||
                    soc >= caps.maxSocPercent - 0.01)
            ) {
                isPinnedZeroCapacity = true
            }
        }

        // Battery lane represents explicit charging actions only
        if (charge > 0) laneCandidates.push('battery')
        if (water > 0) laneCandidates.push('water')
        if (exp > 0) laneCandidates.push('export')
        if (!laneCandidates.length) {
            // Only treat as a "hold" block if the device is actually free to act;
            // if SoC is pinned at bounds and there are no actions, leave a gap.
            if (!isPinnedZeroCapacity) laneCandidates.push('hold')
        }

        for (const lane of laneCandidates) {
            const last = lastByLane[lane]

            if (last && start.getTime() <= last.end.getTime()) {
                // Extend or merge overlapping/adjacent slots for this lane
                if (end.getTime() > last.end.getTime()) {
                    last.end = end
                }
            } else {
                const block: PlanningBlock = {
                    id: `auto-${blockCounter++}-${lane}`,
                    lane,
                    start,
                    end,
                    source: 'schedule',
                    isHistorical,
                }
                merged.push(block)
                lastByLane[lane] = block
            }
        }
    }

    return merged
}

export default function Planning(){
    const [schedule, setSchedule] = useState<ScheduleSlot[] | null>(null)
    const [blocks, setBlocks] = useState<PlanningBlock[]>([])
    const [selectedBlockId, setSelectedBlockId] = useState<string | null>(null)
    const [error, setError] = useState<string | null>(null)
    const [loading, setLoading] = useState(false)
    const [applying, setApplying] = useState(false)
    const [chartRefreshToken, setChartRefreshToken] = useState(0)
    const [historySlots, setHistorySlots] = useState<ScheduleSlot[] | null>(null)
    const [chartSlots, setChartSlots] = useState<ScheduleSlot[] | null>(null)
    const [constraints, setConstraints] = useState<PlanningConstraints | null>(null)

    useEffect(() => {
        let cancelled = false
        setLoading(true)
        setError(null)
        Promise.allSettled([Api.schedule(), Api.scheduleTodayWithHistory(), Api.config()])
            .then(([schedRes, histRes, configRes]) => {
                if (cancelled) return

                if (schedRes.status === 'fulfilled') {
                    const sched = schedRes.value.schedule ?? []
                    setSchedule(sched)
                    setBlocks(classifyBlocks(sched, constraints))
                    setSelectedBlockId(null)
                } else {
                    console.error('Failed to load schedule for Planning:', schedRes.reason)
                    setError('Failed to load schedule')
                }

                if (histRes.status === 'fulfilled') {
                    const histSlots = histRes.value.slots ?? []
                    setHistorySlots(histSlots)
                } else {
                    console.error('Failed to load execution history for Planning:', histRes.reason)
                }

                if (configRes.status === 'fulfilled') {
                    const cfg = configRes.value as any
                    const battery = cfg.battery || {}
                    const minSoc = Number(battery.min_soc_percent ?? 0)
                    const maxSoc = Number(battery.max_soc_percent ?? 100)
                    const maxChargeKw = Number(battery.max_charge_power_kw ?? 0)
                    const maxDischargeKw = Number(battery.max_discharge_power_kw ?? 0)
                    setConstraints({
                        minSocPercent: Number.isFinite(minSoc) ? minSoc : 0,
                        maxSocPercent: Number.isFinite(maxSoc) ? maxSoc : 100,
                        maxChargeKw: Number.isFinite(maxChargeKw) ? maxChargeKw : 0,
                        maxDischargeKw: Number.isFinite(maxDischargeKw) ? maxDischargeKw : 0,
                    })
                } else {
                    console.error('Failed to load config for Planning constraints:', configRes.reason)
                }
            })
            .finally(() => {
                if (cancelled) return
                setLoading(false)
            })

        return () => { cancelled = true }
    }, [])

    // Build merged chart slots when schedule or history changes
    useEffect(() => {
        if (!schedule) {
            setChartSlots(null)
            return
        }
        const todayAndTomorrow = schedule.filter(
            slot => isToday(slot.start_time) || isTomorrow(slot.start_time),
        )
        if (historySlots && historySlots.length) {
            const tomorrowSlots = todayAndTomorrow.filter(slot => isTomorrow(slot.start_time))
            setChartSlots([...historySlots, ...tomorrowSlots])
        } else {
            setChartSlots(todayAndTomorrow)
        }
    }, [schedule, historySlots, constraints])

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

    const handleBlockSelect = (id: string | null) => {
        setSelectedBlockId(id)
    }

    const handleDeleteSelected = () => {
        if (!selectedBlockId) return
        setBlocks(prev => prev.filter(b => b.id !== selectedBlockId))
        setSelectedBlockId(null)
    }

    const validateSimulatedSchedule = (
        sched: ScheduleSlot[],
        caps: PlanningConstraints | null,
    ): { ok: true } | { ok: false; message: string } => {
        if (!caps) return { ok: true }

        const violations: string[] = []
        for (const slot of sched) {
            const time = slot.start_time
            const soc =
                (typeof slot.projected_soc_percent === 'number'
                    ? slot.projected_soc_percent
                    : typeof slot.soc_target_percent === 'number'
                      ? slot.soc_target_percent
                      : null)

            if (typeof soc === 'number') {
                if (soc < caps.minSocPercent - 0.01) {
                    violations.push(
                        `${time}: SoC ${soc.toFixed(1)}% below min ${caps.minSocPercent}%`,
                    )
                } else if (soc > caps.maxSocPercent + 0.01) {
                    violations.push(
                        `${time}: SoC ${soc.toFixed(1)}% above max ${caps.maxSocPercent}%`,
                    )
                }
            }

            const chargeKw = Math.max(
                slot.battery_charge_kw ?? slot.charge_kw ?? 0,
                0,
            )
            const dischargeKw = Math.max(
                slot.battery_discharge_kw ?? slot.discharge_kw ?? 0,
                0,
            )

            if (caps.maxChargeKw > 0 && chargeKw > caps.maxChargeKw + 1e-6) {
                violations.push(
                    `${time}: charge ${chargeKw.toFixed(
                        2,
                    )} kW exceeds max ${caps.maxChargeKw} kW`,
                )
            }
            if (caps.maxDischargeKw > 0 && dischargeKw > caps.maxDischargeKw + 1e-6) {
                violations.push(
                    `${time}: discharge ${dischargeKw.toFixed(
                        2,
                    )} kW exceeds max ${caps.maxDischargeKw} kW`,
                )
            }
        }

        if (!violations.length) return { ok: true }

        const first = violations[0]
        const extraCount = violations.length - 1
        const suffix =
            extraCount > 0 ? ` (and ${extraCount} more slots)` : ''
        return {
            ok: false,
            message: `Manual plan violates device/SoC limits: ${first}${suffix}`,
        }
    }

    const handleApply = () => {
        if (!blocks.length || applying) return
        setApplying(true)
        setError(null)
        const laneDefaultAction: Record<LaneId, string> = {
            battery: 'Charge',
            water: 'Water Heating',
            export: 'Export',
            hold: 'Hold',
        }
        const payload = blocks.map(b => ({
            id: b.id,
            group: b.lane,
            title: null,
            action: laneDefaultAction[b.lane],
            start: b.start.toISOString(),
            end: b.end.toISOString(),
        }))
        Api.simulate(payload)
            .then(res => {
                const sched = res.schedule ?? []
                const validation = validateSimulatedSchedule(sched, constraints)
                if (!validation.ok) {
                    console.error('Manual plan validation failed:', validation.message)
                    setError(validation.message)
                    return
                }
                setError(null)
                setSchedule(sched)
                setBlocks(classifyBlocks(sched, constraints))
                setSelectedBlockId(null)
                setChartRefreshToken(token => token + 1)
            })
            .catch(err => {
                console.error('Failed to apply manual changes:', err)
                setError('Failed to apply manual changes')
            })
            .finally(() => {
                setApplying(false)
            })
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
        <Card className="p-4 md:p-6 mb-6">
        <div className="flex items-baseline justify-between pb-4">
        <div className="text-sm text-muted">Planning Timeline</div>
        <div className="text-[11px] text-muted">
            {loading && 'Loading schedule…'}
            {!loading && error && error}
        </div>
        </div>

        <div className="rounded-xl2 border border-line/60 bg-surface2 overflow-hidden">
        <PlanningTimeline
            lanes={planningLanes}
            blocks={planningBlocks}
            selectedBlockId={selectedBlockId}
            onBlockMove={handleBlockMove}
            onBlockResize={handleBlockResize}
            onBlockSelect={handleBlockSelect}
            onAddBlock={handleAddBlock}
        />
        </div>

        <div className="mt-4 flex flex-wrap items-center gap-3">
        <button
            className="rounded-pill bg-accent text-canvas px-5 py-2.5 font-semibold disabled:opacity-40"
            disabled={loading || applying || blocks.length === 0}
            onClick={handleApply}
        >
            Apply manual changes
        </button>
        <div className="flex gap-2">
            <button
                className="rounded-pill border border-line/70 px-4 py-2.5 text-text hover:border-accent disabled:opacity-40"
                disabled={!selectedBlockId}
                onClick={handleDeleteSelected}
            >
                Delete block
            </button>
            <button
                className="rounded-pill border border-line/70 px-4 py-2.5 text-text hover:border-accent disabled:opacity-40"
                disabled={loading || !schedule}
                onClick={() => {
                    if (!schedule) return
                    setBlocks(classifyBlocks(schedule))
                    setSelectedBlockId(null)
                }}
            >
                Reset plan
            </button>
        </div>
        </div>
        </Card>

        {chartSlots && chartSlots.length > 0 && (
            <ChartCard
                day="today"
                range="48h"
                showDayToggle={false}
                refreshToken={chartRefreshToken}
                slotsOverride={chartSlots}
            />
        )}
        </main>
    )
}
