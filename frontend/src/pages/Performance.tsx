import { useEffect, useState } from 'react'
import { Line, Bar } from 'react-chartjs-2'
import {
    Chart as ChartJS,
    CategoryScale,
    LinearScale,
    PointElement,
    LineElement,
    BarElement,
    Title,
    Tooltip,
    Legend,
    TimeScale
} from 'chart.js'
import 'chartjs-adapter-moment'

ChartJS.register(
    CategoryScale,
    LinearScale,
    PointElement,
    LineElement,
    BarElement,
    Title,
    Tooltip,
    Legend,
    TimeScale
)

interface SoCPoint {
    time: string
    planned: number | null
    actual: number | null
}

interface CostPoint {
    date: string
    planned: number
    realized: number
}

interface PerformanceData {
    soc_series: SoCPoint[]
    cost_series: CostPoint[]
}

import { Api } from '../lib/api'

export default function PerformancePage() {
    const [data, setData] = useState<PerformanceData | null>(null)
    const [loading, setLoading] = useState(true)
    const [error, setError] = useState<string | null>(null)

    useEffect(() => {
        Api.performanceData(7)
            .then(setData)
            .catch(err => {
                console.error("Performance Data Fetch Error:", err)
                setError(err.message)
            })
            .finally(() => setLoading(false))
    }, [])

    if (loading) return <div className="p-8 text-muted">Loading performance data...</div>
    if (error) return <div className="p-8 text-red-400">Error: {error}</div>
    if (!data) return null

    // Metrics Calculation
    const totalPlanned = data.cost_series.reduce((sum, d) => sum + d.planned, 0)
    const totalRealized = data.cost_series.reduce((sum, d) => sum + d.realized, 0)
    const deviation = Math.abs(totalPlanned - totalRealized)
    const isGood = totalRealized <= totalPlanned

    const socChartData = {
        datasets: [
            {
                label: 'Planned SoC',
                data: data.soc_series.map(d => ({ x: d.time, y: d.planned })),
                borderColor: '#94a3b8',
                borderDash: [5, 5],
                borderWidth: 2,
                pointRadius: 0,
                tension: 0.4
            },
            {
                label: 'Actual SoC',
                data: data.soc_series.map(d => ({ x: d.time, y: d.actual })),
                borderColor: '#60a5fa',
                backgroundColor: 'rgba(96, 165, 250, 0.1)',
                borderWidth: 2,
                pointRadius: 0,
                fill: true,
                tension: 0.4
            }
        ]
    }

    const costChartData = {
        labels: data.cost_series.map(d => d.date),
        datasets: [
            {
                label: 'Planned',
                data: data.cost_series.map(d => d.planned),
                backgroundColor: '#94a3b8',
                borderRadius: 4
            },
            {
                label: 'Realized',
                data: data.cost_series.map(d => d.realized),
                backgroundColor: data.cost_series.map(d => d.realized <= d.planned ? '#34d399' : '#f87171'),
                borderRadius: 4
            }
        ]
    }

    return (
        <div className="p-6 max-w-7xl mx-auto space-y-6">
            <header>
                <h1 className="text-3xl font-bold bg-clip-text text-transparent bg-gradient-to-r from-blue-400 to-emerald-400">
                    The Mirror
                </h1>
                <p className="text-slate-400">Plan vs Actual Performance</p>
            </header>

            <div className="grid grid-cols-1 lg:grid-cols-2 gap-6">
                {/* SoC Tunnel */}
                <div className="bg-surface border border-line/60 rounded-2xl p-6 col-span-2 shadow-sm">
                    <h2 className="text-xl font-semibold mb-4 text-blue-400">SoC Tunnel: Plan vs Reality</h2>
                    <div className="h-96 w-full">
                        <Line
                            data={socChartData}
                            options={{
                                responsive: true,
                                maintainAspectRatio: false,
                                interaction: { mode: 'index', intersect: false },
                                scales: {
                                    x: {
                                        type: 'time',
                                        time: { unit: 'hour', displayFormats: { hour: 'HH:mm' } },
                                        grid: { color: '#334155' },
                                        ticks: { color: '#94a3b8' }
                                    },
                                    y: {
                                        min: 0, max: 100,
                                        grid: { color: '#334155' },
                                        ticks: { color: '#94a3b8' }
                                    }
                                },
                                plugins: { legend: { labels: { color: '#e2e8f0' } } }
                            }}
                        />
                    </div>
                </div>

                {/* Cost Reality */}
                <div className="bg-surface border border-line/60 rounded-2xl p-6 col-span-2 lg:col-span-1 shadow-sm">
                    <h2 className="text-xl font-semibold mb-4 text-emerald-400">Cost Reality (Daily)</h2>
                    <div className="h-80 w-full">
                        <Bar
                            data={costChartData}
                            options={{
                                responsive: true,
                                maintainAspectRatio: false,
                                scales: {
                                    x: { grid: { display: false }, ticks: { color: '#94a3b8' } },
                                    y: { grid: { color: '#334155' }, ticks: { color: '#94a3b8' } }
                                },
                                plugins: { legend: { labels: { color: '#e2e8f0' } } }
                            }}
                        />
                    </div>
                </div>

                {/* Metrics Summary */}
                <div className="bg-surface border border-line/60 rounded-2xl p-6 col-span-2 lg:col-span-1 shadow-sm">
                    <h2 className="text-xl font-semibold mb-4 text-purple-400">Performance Metrics (7 Days)</h2>
                    <div className="grid grid-cols-2 gap-4">
                        <div className="p-4 bg-surface2 rounded-xl border border-line/40">
                            <p className="text-sm text-slate-400">Total Planned Cost</p>
                            <p className="text-2xl font-bold text-foreground">{totalPlanned.toFixed(2)} SEK</p>
                        </div>
                        <div className="p-4 bg-surface2 rounded-xl border border-line/40">
                            <p className="text-sm text-slate-400">Total Realized Cost</p>
                            <p className="text-2xl font-bold text-foreground">{totalRealized.toFixed(2)} SEK</p>
                        </div>
                        <div className="p-4 bg-surface2 rounded-xl border border-line/40 col-span-2">
                            <p className="text-sm text-slate-400">Cost Deviation</p>
                            <p className={`text-2xl font-bold ${isGood ? 'text-emerald-400' : 'text-red-400'}`}>
                                {deviation.toFixed(2)} SEK
                            </p>
                        </div>
                    </div>
                </div>
            </div>
        </div>
    )
}
