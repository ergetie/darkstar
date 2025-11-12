import Card from './Card'
import { useEffect, useRef, useState } from 'react'
import { Chart as ChartJS, ChartConfiguration } from 'chart.js/auto'
import type { Chart } from 'chart.js/auto'
import { sampleChart } from '../lib/sample'
import { Api } from '../lib/api'
import type { ScheduleSlot } from '../lib/types'
import { filterSlotsByDay, formatHour, DaySel } from '../lib/time'

const chartOptions: ChartConfiguration['options'] = {
    maintainAspectRatio: false,
    spanGaps: false,
    plugins: {
        legend: {
            labels: {
                color: '#e6e9ef',
                boxWidth: 10,
                font: { size: 12 },
                filter: (item) =>
                    typeof item.datasetIndex === 'number' && item.datasetIndex < 3,
            },
        },
    },
    scales: {
        x: {
            grid: { color: 'rgba(255,255,255,0.06)' },
            ticks: { color: '#a6b0bf', maxRotation: 0, autoSkip: true },
        },
        y: {
            position: 'right',
            grid: { color: 'rgba(255,255,255,0.06)' },
            ticks: { color: '#a6b0bf' },
        },
        y1: {
            position: 'left',
            grid: { display: false },
            ticks: { color: '#a6b0bf' },
        },
    },
}

type ChartValues = {
    labels: string[]
    price: (number | null)[]
    pv: (number | null)[]
    load: (number | null)[]
    charge?: (number | null)[]
    discharge?: (number | null)[]
    export?: (number | null)[]
    water?: (number | null)[]
    socTarget?: (number | null)[]
    socProjected?: (number | null)[]
}

const createChartData = (values: ChartValues) => ({
    labels: values.labels,
    datasets: [
        {
            type: 'line',
            label: 'Import Price (SEK/kWh)',
            data: values.price,
            borderColor: '#2196F3', // Material Blue
            backgroundColor: 'rgba(33,150,243,0.1)',
            yAxisID: 'y',
            tension: 0.2,
            pointRadius: 0,
        },
        {
            type: 'line',
            label: 'PV Forecast (kW)',
            data: values.pv,
            borderColor: '#4CAF50', // Material Green
            backgroundColor: 'rgba(76,175,80,0.15)',
            fill: true,
            yAxisID: 'y1',
            tension: .35,
            pointRadius: 0,
        },
        {
            type: 'bar',
            label: 'Load (kW)',
            data: values.load,
            backgroundColor: '#FF9800', // Material Orange
            borderRadius: 6,
            yAxisID: 'y1',
            barPercentage: 1,
            categoryPercentage: .9,
        },
        {
            type: 'bar',
            label: 'Charge (kW)',
            data: values.charge ?? values.labels.map(() => null),
            backgroundColor: '#2196F3', // Material Blue
            hidden: true,
            yAxisID: 'y1',
        },
        {
            type: 'bar',
            label: 'Discharge (kW)',
            data: values.discharge ?? values.labels.map(() => null),
            backgroundColor: '#F44336', // Material Red
            hidden: true,
            yAxisID: 'y1',
        },
        {
            type: 'bar',
            label: 'Export (kWh)',
            data: values.export ?? values.labels.map(() => null),
            backgroundColor: '#4CAF50', // Material Green
            hidden: true,
            yAxisID: 'y1',
        },
        {
            type: 'bar',
            label: 'Water Heating (kW)',
            data: values.water ?? values.labels.map(() => null),
            backgroundColor: '#FF5722', // Material Deep Orange
            hidden: true,
            yAxisID: 'y1',
        },
        {
            type: 'line',
            label: 'SoC Target (%)',
            data: values.socTarget ?? values.labels.map(() => null),
            borderColor: '#9C27B0', // Material Purple
            yAxisID: 'y1',
            pointRadius: 0,
            hidden: true,
        },
        {
            type: 'line',
            label: 'SoC Projected (%)',
            data: values.socProjected ?? values.labels.map(() => null),
            borderColor: '#607D8B', // Material Blue Grey
            yAxisID: 'y1',
            pointRadius: 0,
            hidden: true,
        },
    ],
})

const fallbackData = createChartData({
    labels: sampleChart.labels,
    price: sampleChart.price,
    pv: sampleChart.pv,
    load: sampleChart.load,
})

type ChartCardProps = { day?: DaySel }

export default function ChartCard({ day = 'today' }: ChartCardProps){
    const ref = useRef<HTMLCanvasElement | null>(null)
    const chartRef = useRef<Chart | null>(null)
    const [overlays, setOverlays] = useState({
        charge: false,
        discharge: false,
        export: false,
        water: false,
        socTarget: false,
        socProjected: false,
    })

    useEffect(() => {
        if(!ref.current) return
        const cfg: ChartConfiguration = {
            type: 'bar',
            data: fallbackData,
            options: chartOptions,
        }
        chartRef.current = new ChartJS(ref.current, cfg)
        return () => chartRef.current?.destroy()
    }, [])

    useEffect(() => {
        const chartInstance = chartRef.current
        if(!chartInstance) return
        Api.schedule()
            .then(data => {
                const liveData = buildLiveData(data.schedule ?? [], day)
                if(!liveData) return
                // Apply overlay visibility based on toggles
                const ds = liveData.datasets
                // Index mapping: 0 price, 1 pv, 2 load, 3 charge, 4 discharge, 5 export, 6 water, 7 socTarget, 8 socProjected
                if (ds[3]) ds[3].hidden = !overlays.charge
                if (ds[4]) ds[4].hidden = !overlays.discharge
                if (ds[5]) ds[5].hidden = !overlays.export
                if (ds[6]) ds[6].hidden = !overlays.water
                if (ds[7]) ds[7].hidden = !overlays.socTarget
                if (ds[8]) ds[8].hidden = !overlays.socProjected
                ;(chartInstance as any).data = liveData
                chartInstance.update()
            })
            .catch(() => {})
    }, [day, overlays])

    return (
        <Card className="p-4 md:p-6 h-[380px]">
        <div className="flex items-baseline justify-between pb-3">
        <div className="text-sm text-muted">Schedule Overview</div>
        <div className="text-[11px] text-muted">today → tomorrow</div>
        </div>
        <div className="h-[310px]">
        <canvas ref={ref}/>
        </div>
        <div className="mt-3 flex flex-wrap gap-2 text-[11px]">
        {([
            ['Charge', 'charge'],
            ['Discharge', 'discharge'],
            ['Export', 'export'],
            ['Water', 'water'],
            ['SoC Target', 'socTarget'],
            ['SoC Projected', 'socProjected'],
        ] as const).map(([label, key]) => (
            <button
                key={key}
                onClick={(e) => { e.preventDefault(); setOverlays(o => ({...o, [key]: !o[key as keyof typeof o]})) }}
                className={`rounded-pill px-3 py-1 border ${overlays[key as keyof typeof overlays] ? 'bg-accent text-canvas border-accent' : 'border-line/60 text-muted hover:border-accent'}`}
            >
                {label}
            </button>
        ))}
        </div>
        </Card>
    )
}

function buildLiveData(slots: ScheduleSlot[], day: DaySel) {
    const filtered = filterSlotsByDay(slots, day)
    if(!filtered.length) return null
    const ordered = [...filtered].sort((a, b) => {
        const aTime = new Date(a.start_time).getTime()
        const bTime = new Date(b.start_time).getTime()
        return aTime - bTime
    })

    const price = ordered.map(slot => slot.import_price_sek_kwh ?? null)
    const pv = ordered.map(slot => slot.pv_forecast_kwh ?? null)
    const load = ordered.map(slot => slot.load_forecast_kwh ?? null)
    const charge = ordered.map(slot => slot.battery_charge_kw ?? slot.charge_kw ?? null)
    const discharge = ordered.map(slot => slot.battery_discharge_kw ?? slot.discharge_kw ?? null)
    const exp = ordered.map(slot => slot.export_kwh ?? null)
    const water = ordered.map(slot => slot.water_heating_kw ?? null)
    const socTarget = ordered.map(slot => slot.soc_target_percent ?? null)
    const socProjected = ordered.map(slot => slot.projected_soc_percent ?? null)

    const labels = ordered.map(slot => formatHour(slot.start_time))
    return createChartData({
        labels,
        price,
        pv,
        load,
        charge,
        discharge,
        export: exp,
        water,
        socTarget,
        socProjected,
    })
}
