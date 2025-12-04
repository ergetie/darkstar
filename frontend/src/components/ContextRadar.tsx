import {
    Chart as ChartJS,
    RadialLinearScale,
    PointElement,
    LineElement,
    Filler,
    Tooltip,
    Legend,
} from 'chart.js'
import { Radar } from 'react-chartjs-2'

ChartJS.register(
    RadialLinearScale,
    PointElement,
    LineElement,
    Filler,
    Tooltip,
    Legend
)

interface ContextRadarProps {
    weatherVolatility: {
        cloud: number
        temp: number
        overall: number
    }
    riskFactor: number // 0.9 to 1.5 usually
    forecastAccuracy: number // 0 to 100 (derived from MAE)
}

export default function ContextRadar({
    weatherVolatility,
    riskFactor,
    forecastAccuracy,
}: ContextRadarProps) {
    // Normalize values to 0-100 scale for the chart
    const cloudScore = Math.min(100, weatherVolatility.cloud * 100)
    const tempScore = Math.min(100, weatherVolatility.temp * 100)

    // Risk: 1.0 is baseline (50), 1.5 is high (100), 0.9 is low (0)
    const riskScore = Math.max(0, Math.min(100, ((riskFactor - 0.9) / 0.6) * 100))

    // Forecast Confidence: Inverse of error? Or just passed in accuracy.
    // Let's assume passed in is "Confidence %"
    const confidenceScore = forecastAccuracy

    const labels = ['Cloud Volatility', 'Temp Volatility', 'Strategy Aggression', 'Forecast Confidence']
    const pointColors = ['#38bdf8', '#f472b6', '#fbbf24', '#34d399'] // Sky, Pink, Amber, Emerald

    const data = {
        labels,
        datasets: [
            {
                label: 'Current Context',
                data: [cloudScore, tempScore, riskScore, confidenceScore],
                backgroundColor: 'rgba(56, 189, 248, 0.2)',
                borderColor: 'rgba(56, 189, 248, 0.5)',
                borderWidth: 2,
                pointBackgroundColor: pointColors,
                pointBorderColor: '#fff',
                pointHoverBackgroundColor: '#fff',
                pointHoverBorderColor: pointColors,
                pointRadius: 4,
            },
        ],
    }

    const options = {
        scales: {
            r: {
                angleLines: { color: 'rgba(255, 255, 255, 0.1)' },
                grid: { color: 'rgba(255, 255, 255, 0.1)' },
                pointLabels: { display: false }, // Hide labels on chart
                ticks: { display: false, backdropColor: 'transparent' },
                suggestedMin: 0,
                suggestedMax: 100,
            },
        },
        plugins: {
            legend: { display: false },
            tooltip: {
                backgroundColor: '#1e293b',
                titleColor: '#f8fafc',
                bodyColor: '#cbd5e1',
                borderColor: '#334155',
                borderWidth: 1,
            }
        },
        maintainAspectRatio: false,
    }

    return (
        <div className="relative w-full h-full min-h-[200px]">
            {/* Chart Container - Absolute to prevent layout locking */}
            <div className="absolute inset-0 overflow-hidden">
                <Radar data={data} options={options} />
            </div>

            {/* Legend - Bottom Left */}
            <div className="absolute bottom-0 left-0 flex flex-col gap-1.5 p-3 z-10">
                {labels.map((label, idx) => (
                    <div key={label} className="flex items-center gap-2">
                        <div
                            className="w-2 h-2 rounded-full shadow-sm ring-1 ring-white/10"
                            style={{ backgroundColor: pointColors[idx] }}
                        />
                        <span className="text-[10px] text-muted font-medium leading-tight">
                            {label}
                        </span>
                    </div>
                ))}
            </div>
        </div>
    )
}
