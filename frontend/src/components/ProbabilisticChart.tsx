import {
    Chart as ChartJS,
    CategoryScale,
    LinearScale,
    PointElement,
    LineElement,
    Title,
    Tooltip,
    Legend,
    Filler,
} from 'chart.js'
import { Line } from 'react-chartjs-2'

ChartJS.register(
    CategoryScale,
    LinearScale,
    PointElement,
    LineElement,
    Title,
    Tooltip,
    Legend,
    Filler
)

export type SlotData = {
    time: string
    p10: number | null
    p90: number | null
    p50: number | null
    actual?: number | null
}

type Props = {
    title: string
    slots: SlotData[]
    color: string
}

export default function ProbabilisticChart({ title, slots, color }: Props) {
    const labels = slots.map(s => {
        const d = new Date(s.time)
        return d.toLocaleTimeString([], { hour: '2-digit', minute: '2-digit', hour12: false })
    })

    const data = {
        labels,
        datasets: [
            {
                label: 'Actual',
                data: slots.map(s => s.actual ?? null),
                borderColor: '#94a3b8', // Slate-400
                backgroundColor: '#94a3b8',
                borderWidth: 2,
                pointRadius: 2,
                tension: 0.2,
                fill: false,
            },
            {
                label: 'p90',
                data: slots.map(s => s.p90),
                borderColor: `${color}40`, // 25% opacity line
                borderWidth: 1,
                backgroundColor: `${color}33`, // 20% opacity fill
                pointRadius: 0,
                tension: 0.2,
                fill: '+1', // Fill to next dataset (p10)
            },
            {
                label: 'p10 (Risk)',
                data: slots.map(s => s.p10),
                borderColor: `${color}80`, // Higher opacity
                borderWidth: 1.5,
                borderDash: [4, 4], // Dashed line
                backgroundColor: 'transparent',
                pointRadius: 0,
                tension: 0.2,
                fill: false,
            },
            {
                label: 'p50 (Forecast)',
                data: slots.map(s => s.p50),
                borderColor: color,
                backgroundColor: color,
                borderWidth: 2,
                pointRadius: 0,
                tension: 0.2,
                fill: false,
            },
        ],
    }

    const options = {
        responsive: true,
        maintainAspectRatio: false,
        plugins: {
            legend: {
                display: true,
                labels: {
                    color: '#cbd5e1', // Slate-300
                    font: { size: 11 },
                    boxWidth: 8,
                    usePointStyle: true,
                }
            },
            title: {
                display: !!title,
                text: title,
                color: '#e2e8f0', // Slate-200
                font: { size: 13, weight: 'normal' as const },
                align: 'start' as const,
                padding: { bottom: 10 }
            },
            tooltip: {
                mode: 'index' as const,
                intersect: false,
                backgroundColor: '#1e293b',
                titleColor: '#e2e8f0',
                bodyColor: '#cbd5e1',
                borderColor: '#334155',
                borderWidth: 1,
            },
        },
        scales: {
            x: {
                grid: {
                    color: '#334155', // Slate-700
                    drawBorder: false,
                },
                ticks: {
                    color: '#94a3b8',
                    maxRotation: 0,
                    autoSkip: true,
                    maxTicksLimit: 8,
                },
            },
            y: {
                grid: {
                    color: '#334155',
                    drawBorder: false,
                },
                ticks: {
                    color: '#94a3b8',
                },
                min: 0,
            },
        },
        interaction: {
            mode: 'nearest' as const,
            axis: 'x' as const,
            intersect: false,
        },
        layout: {
            padding: {
                bottom: 0,
                left: 10,
                right: 10
            }
        }
    }

    return (
        <div className="w-full h-[250px]">
            <Line data={data} options={options} />
        </div>
    )
}
