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

export type ChartVariant = 'field' | 'oled' | 'swiss'

interface Props {
    slots: AuroraHorizonSlot[]
    mode: 'pv' | 'load'
    highlightIndex?: number | null
    variant?: ChartVariant
}

export default function DecompositionChart({ slots, mode, variant = 'field' }: Props) {
    if (!slots || slots.length === 0) {
        return <div className="text-[11px] text-muted px-4 py-6">No forecast data available for the next 48 hours.</div>
    }

    const labels = slots.map((s) =>
        new Date(s.slot_start).toLocaleTimeString([], { hour: '2-digit', minute: '2-digit' }),
    )

    // --- Variant Config ---
    const isField = variant === 'field'
    const isOled = variant === 'oled'
    const isSwiss = variant === 'swiss'

    // Colors
    const colorPV = isOled ? '#22d3ee' : isSwiss ? '#171717' : '#22c55e' // OLED Cyan, Swiss Black
    const colorLoad = isOled ? '#f472b6' : isSwiss ? '#ef4444' : '#f97316' // OLED Pink, Swiss Red
    const mainColor = mode === 'pv' ? colorPV : colorLoad

    const data: ChartData<'line' | 'bar'> = {
        labels,
        datasets: [
            {
                type: 'line',
                label: mode === 'pv' ? 'Final PV' : 'Final Load',
                data: slots.map((s) => (mode === 'pv' ? s.final.pv_kwh : s.final.load_kwh)),
                borderColor: mainColor,
                backgroundColor: (context: ScriptableContext<'line'>) => {
                    const ctx = context.chart.ctx
                    // Option A: Field - Beautiful vertical gradient
                    if (isField) {
                        const gradient = ctx.createLinearGradient(0, 0, 0, 200)
                        gradient.addColorStop(0, mode === 'pv' ? 'rgba(34, 197, 94, 0.2)' : 'rgba(249, 115, 22, 0.2)')
                        gradient.addColorStop(1, 'rgba(15, 23, 42, 0.0)')
                        return gradient
                    }
                    return 'transparent'
                },
                borderWidth: isSwiss ? 4 : isOled ? 2 : 3, // Swiss thick, OLED thin
                tension: isSwiss ? 0.2 : 0.4,
                pointRadius: isOled ? 2 : 0,
                pointBackgroundColor: '#000',
                pointBorderColor: mainColor,
                fill: isField,
                // @ts-expect-error shadowColor is custom plugin prop
                shadowColor: isField ? mainColor : isOled ? mainColor : 'transparent',
                shadowBlur: isField ? 15 : isOled ? 8 : 0,
            },
            {
                type: 'bar',
                label: 'Base',
                data: slots.map((s) => (mode === 'pv' ? s.base.pv_kwh : s.base.load_kwh)),
                backgroundColor: isSwiss ? 'rgba(0,0,0,0.1)' : 'rgba(255, 255, 255, 0.05)',
                borderWidth: 0,
                borderRadius: isSwiss ? 0 : 2,
                yAxisID: 'y',
                barPercentage: 0.8,
            },
        ],
    }

    const options: ChartConfiguration<'line' | 'bar'>['options'] = {
        responsive: true,
        maintainAspectRatio: false,
        layout: {
            padding: { top: 20, bottom: 10, left: 10, right: 10 },
        },
        plugins: {
            legend: { display: false },
            tooltip: {
                enabled: true,
                backgroundColor: isOled ? '#000' : 'rgba(15, 23, 42, 0.95)',
                titleColor: isOled ? '#fff' : 'rgba(255, 255, 255, 0.9)',
                bodyColor: isOled ? '#fff' : 'rgba(255, 255, 255, 0.7)',
                borderColor: isOled ? '#333' : 'rgba(255, 255, 255, 0.1)',
                borderWidth: 1,
                padding: 10,
                displayColors: !isOled,
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
                grid: {
                    display: isOled, // Field uses CSS grid, Swiss uses no grid
                    color: isOled ? '#333' : 'transparent',
                },
                ticks: {
                    color: isOled ? '#666' : isSwiss ? '#000' : '#64748b',
                    font: {
                        size: 10,
                        family: isOled ? 'monospace' : 'inherit',
                        weight: isSwiss ? 'bold' : 'normal',
                    },
                    maxTicksLimit: 8,
                },
                border: { display: isSwiss || isOled },
            },
            y: {
                grid: {
                    display: isOled,
                    color: isOled ? '#333' : 'transparent',
                },
                ticks: {
                    display: !isField, // Hide Y axis for Field aesthetics
                    color: isOled ? '#666' : isSwiss ? '#000' : '#64748b',
                    font: {
                        size: 10,
                        family: isOled ? 'monospace' : 'inherit',
                        weight: isSwiss ? 'bold' : 'normal',
                    },
                },
                border: { display: isSwiss || isOled },
            },
        },
        interaction: {
            intersect: false,
            mode: 'index',
        },
    }

    return (
        <div
            className={`w-full h-full min-h-[240px] ${isOled ? 'font-mono' : ''}`}
            style={
                isField
                    ? {
                          backgroundImage: `radial-gradient(rgb(var(--color-grid) / 0.2) 1px, transparent 1px)`,
                          backgroundSize: '20px 20px',
                      }
                    : undefined
            }
        >
            <Line
                key={`${mode}-${variant}`}
                data={data as unknown as ChartData<'line'>}
                options={options as unknown as ChartConfiguration<'line'>['options']}
            />
        </div>
    )
}
