import { useEffect, useState } from 'react'
import Card from '../components/Card'
import ChartCard from '../components/ChartCard'
import QuickActions from '../components/QuickActions'
import Kpi from '../components/Kpi'
import { motion } from 'framer-motion'
import { Api, Sel } from '../lib/api'
import type { DaySel } from '../lib/time'

export default function Dashboard(){
    const [soc, setSoc] = useState<number | null>(null)
    const [horizon, setHorizon] = useState<{pvDays?: number; weatherDays?: number} | null>(null)
    const [plannerMeta, setPlannerMeta] = useState<{plan: 'local' | 'db'; plannedAt?: string; version?: string} | null>(null)
    const [batteryCapacity, setBatteryCapacity] = useState<number | null>(null)
    const [pvToday, setPvToday] = useState<number | null>(null)
    const [avgLoad, setAvgLoad] = useState<{kw?: number; dailyKwh?: number} | null>(null)
    const [currentSlotTarget, setCurrentSlotTarget] = useState<number | null>(null)

    useEffect(() => {
        Api.status()
            .then((data) => {
                setSoc(Sel.socValue(data) ?? null)
                // Prefer local meta; fall back to db if present
                const local = data.local ?? {}
                const db = (data.db && 'planned_at' in data.db) ? (data.db as any) : null
                if (local?.planned_at || local?.planner_version) {
                    setPlannerMeta({ plan: 'local', plannedAt: local.planned_at, version: local.planner_version })
                } else if (db?.planned_at || db?.planner_version) {
                    setPlannerMeta({ plan: 'db', plannedAt: db.planned_at, version: db.planner_version })
                } else {
                    setPlannerMeta(null)
                }
            })
            .catch(() => {})
        Api.horizon()
            .then((data) =>
                setHorizon({
                    pvDays: Sel.pvDays(data) ?? undefined,
                    weatherDays: Sel.wxDays(data) ?? undefined,
                }),
            )
            .catch(() => {})
        Api.config()
            .then((data) => {
                if (data.system?.battery?.capacity_kwh) {
                    setBatteryCapacity(data.system.battery.capacity_kwh)
                }
            })
            .catch(() => {})
        Api.haAverage()
            .then((data) => {
                setAvgLoad({
                    kw: data.average_load_kw,
                    dailyKwh: data.daily_kwh
                })
            })
            .catch(() => {})
        Api.schedule()
            .then((data) => {
                // Calculate PV today from schedule data
                const today = new Date().toISOString().split('T')[0]
                const todaySlots = data.schedule?.filter(slot => 
                    slot.start_time?.startsWith(today)
                ) || []
                const pvTotal = todaySlots.reduce((sum, slot) => 
                    sum + (slot.pv_forecast_kwh || 0), 0
                )
                setPvToday(pvTotal)
                
                // Get current slot target
                const now = new Date()
                const currentSlot = data.schedule?.find(slot => {
                    const slotTime = new Date(slot.start_time || '')
                    const slotEnd = new Date(slotTime.getTime() + 30 * 60 * 1000) // 30 min slots
                    return now >= slotTime && now < slotEnd
                })
                if (currentSlot?.soc_target_percent !== undefined) {
                    setCurrentSlotTarget(currentSlot.soc_target_percent)
                }
            })
            .catch(() => {})
    }, [])

    const socDisplay = soc !== null ? `${soc.toFixed(1)}%` : '—'
    const pvDays = horizon?.pvDays ?? '—'
    const weatherDays = horizon?.weatherDays ?? '—'
    const planBadge = plannerMeta ? `${plannerMeta.plan === 'local' ? 'local' : 'server'} plan` : 'plan'
    const planMeta = plannerMeta?.plannedAt || plannerMeta?.version ? ` · ${plannerMeta?.plannedAt ?? ''} ${plannerMeta?.version ?? ''}`.trim() : ''



    return (
        <main className="mx-auto max-w-7xl px-6 pb-24 pt-10 lg:pt-12">
        <div className="grid gap-6 lg:grid-cols-3">
        <motion.div className="lg:col-span-2" initial={{opacity:0, y:8}} animate={{opacity:1,y:0}}>
        <ChartCard />
        </motion.div>
        <motion.div className="space-y-4" initial={{opacity:0, y:8}} animate={{opacity:1,y:0}}>
        <Card className="p-4 md:p-5">
        <div className="flex items-baseline justify-between mb-3">
        <div className="text-sm text-muted">System Status</div>
        <div className="text-[10px] text-muted">live</div>
        </div>
        <div className="flex flex-wrap gap-4 pb-4 text-[11px] uppercase tracking-wider text-muted">
        <div className="text-text">Now showing: {planBadge}{planMeta}</div>
        </div>
        <div className="grid grid-cols-2 gap-3">
        <Kpi label="Current SoC" value={socDisplay} hint={currentSlotTarget !== null ? `target ${currentSlotTarget.toFixed(0)}%` : 'target —%'} />
        <Kpi label="Battery Cap" value={batteryCapacity !== null ? `${batteryCapacity.toFixed(1)} kWh` : '— kWh'} />
        <Kpi label="PV Today" value={pvToday !== null ? `${pvToday.toFixed(1)} kWh` : '— kWh'} hint={`PV ${pvDays}d · Weather ${weatherDays}d`} />
        <Kpi label="Avg Load" value={avgLoad?.kw !== undefined ? `${avgLoad.kw.toFixed(1)} kW` : '— kW'} hint={avgLoad?.dailyKwh !== undefined ? `HA ${avgLoad.dailyKwh.toFixed(1)} kWh/day` : ''} />
        </div>
        </Card>
        <Card className="p-4 md:p-5">
        <div className="text-sm text-muted mb-3">Quick Actions</div>
        <QuickActions />
        </Card>
        </motion.div>
        </div>

        <div className="grid grid-cols-1 lg:grid-cols-3 gap-6 mt-6">
        <Card className="p-5">
        <div className="text-sm text-muted mb-3">Water heater</div>
        <div className="flex items-center justify-between">
        <div className="text-2xl">Eco mode</div>
        <div className="rounded-pill bg-surface2 border border-line/60 px-3 py-1 text-muted text-xs">today 1.7 kWh</div>
        </div>
        </Card>
        <Card className="p-5">
        <div className="text-sm text-muted mb-3">Export guard</div>
        <div className="text-2xl">Passive</div>
        </Card>
        <Card className="p-5">
        <div className="text-sm text-muted mb-3">Learning</div>
        <div className="text-2xl">Ready</div>
        </Card>
        </div>
        </main>
    )
}
