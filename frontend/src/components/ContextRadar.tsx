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
    priceSpread?: number | null // SEK/kWh, typically 0.5 to 2.5
    forecastBias?: number | null // kWh, -2 to +2 typical range
}

export default function ContextRadar({
    weatherVolatility,
    riskFactor,
    forecastAccuracy,
    priceSpread,
    forecastBias,
}: ContextRadarProps) {
    // Normalize values to 0-100 scale for the chart
    const cloudScore = Math.min(100, weatherVolatility.cloud * 100)
    const tempScore = Math.min(100, weatherVolatility.temp * 100)

    // Risk: 1.0 is baseline (50), 1.5 is high (100), 0.9 is low (0)
    // Risk: 1-5 scale (1=0, 3=50, 5=100)
    // Formula: (Value - 1) * 25
    const riskScore = Math.max(0, Math.min(100, (riskFactor - 1) * 25))

    // Forecast Confidence: Inverse of error? Or just passed in accuracy.
    const confidenceScore = forecastAccuracy

    // Price Spread: 0 SEK = 0, 2.5 SEK = 100 (high opportunity)
    const spreadScore = priceSpread != null
        ? Math.max(0, Math.min(100, (priceSpread / 2.5) * 100))
        : 50 // Default to middle

    // Forecast Bias: 0 = centered (50), ±2 kWh = extremes
    // Positive bias = over-predicting (cautious), negative = under-predicting (risky)
    const biasScore = forecastBias != null
        ? Math.max(0, Math.min(100, ((forecastBias + 2) / 4) * 100))
        : 50 // Default to centered

    const labels = [
        'Cloud Vol.',
        'Temp Vol.',
        'Aggression',
        'Accuracy',
        'Spread',
        'Bias'
    ]
    const pointColors = [
        '#38bdf8', // Sky - Cloud
        '#f472b6', // Pink - Temp
        '#fbbf24', // Amber - Aggression
        '#34d399', // Emerald - Accuracy
        '#a78bfa', // Violet - Spread
        '#fb923c', // Orange - Bias
    ]

    const data = {
        labels,
        datasets: [
            {
                label: 'Current Context',
                data: [cloudScore, tempScore, riskScore, confidenceScore, spreadScore, biasScore],
                backgroundColor: 'rgba(56, 189, 248, 0.15)',
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

    // Compact legend with 2 columns
    const leftLabels = labels.slice(0, 3)
    const rightLabels = labels.slice(3)

    return (
        <div className="relative w-full h-full min-h-[200px]">
            {/* Chart Container - Absolute to prevent layout locking */}
            <div className="absolute inset-0 overflow-hidden">
                <Radar data={data} options={options} />
            </div>

            {/* Legend - Bottom with 2 columns */}
            <div className="absolute bottom-0 left-0 right-0 flex justify-between px-3 pb-2 z-10">
                <div className="flex flex-col gap-1">
                    {leftLabels.map((label, idx) => (
                        <div key={label} className="flex items-center gap-1.5">
                            <div
                                className="w-2 h-2 rounded-full shadow-sm ring-1 ring-white/10"
                                style={{ backgroundColor: pointColors[idx] }}
                            />
                            <span className="text-[9px] text-muted font-medium leading-tight">
                                {label}
                            </span>
                        </div>
                    ))}
                </div>
                <div className="flex flex-col gap-1">
                    {rightLabels.map((label, idx) => (
                        <div key={label} className="flex items-center gap-1.5">
                            <div
                                className="w-2 h-2 rounded-full shadow-sm ring-1 ring-white/10"
                                style={{ backgroundColor: pointColors[idx + 3] }}
                            />
                            <span className="text-[9px] text-muted font-medium leading-tight">
                                {label}
                            </span>
                        </div>
                    ))}
                </div>
            </div>
        </div>
    )
}

