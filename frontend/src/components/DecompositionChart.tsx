import {
    Chart as ChartJS,
    CategoryScale,
    LinearScale,
    PointElement,
    LineElement,
    BarElement,
    Tooltip,
    Legend,
    ScriptableContext,
    TooltipItem,
    ChartData,
    ChartConfiguration,
} from 'chart.js'
import { Line } from 'react-chartjs-2'
import type { AuroraHorizonSlot } from '../lib/types'

ChartJS.register(CategoryScale, LinearScale, PointElement, LineElement, BarElement, Tooltip, Legend)

interface Props {
    slots: AuroraHorizonSlot[]
    mode: 'pv' | 'load'
    highlightIndex?: number | null
}

export default function DecompositionChart({ slots, mode }: Props) {
    if (!slots || slots.length === 0) {
        return <div className="text-[11px] text-muted px-4 py-6">No forecast data available for the next 48 hours.</div>
    }

    const labels = slots.map((s) =>
        new Date(s.slot_start).toLocaleTimeString([], { hour: '2-digit', minute: '2-digit' }),
    )

    const data: ChartData<'line' | 'bar'> = {
        labels,
        datasets: [
            {
                type: 'line',
                label: mode === 'pv' ? 'Final PV' : 'Final Load',
                data: slots.map((s) => (mode === 'pv' ? s.final.pv_kwh : s.final.load_kwh)),
                borderColor: mode === 'pv' ? '#22c55e' : '#f97316',
                backgroundColor: (context: ScriptableContext<'line'>) => {
                    const ctx = context.chart.ctx
                    const gradient = ctx.createLinearGradient(0, 0, 0, 200)
                    gradient.addColorStop(0, 'rgba(15, 23, 42, 0.0)')
                    gradient.addColorStop(1, mode === 'pv' ? 'rgba(34, 197, 94, 0.1)' : 'rgba(249, 115, 22, 0.1)')
                    return gradient
                },
                borderWidth: 2,
                tension: 0.4,
                pointRadius: 0,
                fill: true,
            },
            {
                type: 'bar',
                label: 'Base',
                data: slots.map((s) => (mode === 'pv' ? s.base.pv_kwh : s.base.load_kwh)),
                backgroundColor: 'rgba(255, 255, 255, 0.05)',
                borderColor: 'rgba(255, 255, 255, 0.1)',
                borderWidth: 1,
                borderRadius: 2,
                yAxisID: 'y',
            },
            {
                type: 'bar',
                label: 'Correction',
                data: slots.map((s) => (mode === 'pv' ? s.correction.pv_kwh : s.correction.load_kwh)),
                backgroundColor: mode === 'pv' ? 'rgba(34, 197, 94, 0.2)' : 'rgba(249, 115, 22, 0.2)',
                borderRadius: 2,
                yAxisID: 'y',
            },
        ],
    }

    const options: ChartConfiguration<'line' | 'bar'>['options'] = {
        responsive: true,
        maintainAspectRatio: false,
        plugins: {
            legend: { display: false },
            tooltip: {
                backgroundColor: 'rgba(15, 23, 42, 0.95)',
                titleColor: 'rgba(255, 255, 255, 0.9)',
                bodyColor: 'rgba(255, 255, 255, 0.7)',
                borderColor: 'rgba(255, 255, 255, 0.1)',
                borderWidth: 1,
                padding: 10,
                callbacks: {
                    label: (context: TooltipItem<'line' | 'bar'>) => {
                        let label = context.dataset.label || ''
                        if (label) label += ': '
                        if (context.parsed.y !== null) {
                            label += context.parsed.y.toFixed(3) + ' kWh'
                        }
                        return label
                    },
                },
            },
        },
        scales: {
            x: {
                grid: { display: false },
                ticks: { color: '#64748b', font: { size: 10 }, maxTicksLimit: 8 },
            },
            y: {
                grid: { color: 'rgba(255, 255, 255, 0.05)' },
                ticks: { color: '#64748b', font: { size: 10 } },
            },
        },
        interaction: {
            intersect: false,
            mode: 'index',
        },
    }

    return (
        <div className="w-full h-full min-h-[240px]">
            <Line
                key={mode}
                data={data as unknown as ChartData<'line'>}
                options={options as unknown as ChartConfiguration<'line'>['options']}
            />
        </div>
    )
}
