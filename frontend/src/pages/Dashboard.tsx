import Card from '../components/Card'
import ChartCard from '../components/ChartCard'
import QuickActions from '../components/QuickActions'
import Kpi from '../components/Kpi'
import { motion } from 'framer-motion'

export default function Dashboard(){
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
        <div className="grid grid-cols-2 gap-3">
        <Kpi label="Current SoC" value="27%" hint="target 40%" />
        <Kpi label="Battery Cap" value="10.2 kWh" />
        <Kpi label="PV Today" value="6.4 kWh" />
        <Kpi label="Avg Load" value="1.2 kW" hint="HA 23.9 kWh/day" />
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
