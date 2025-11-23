import {
  Chart as ChartJS,
  CategoryScale,
  LinearScale,
  BarElement,
  Tooltip,
  Legend,
} from 'chart.js'
import { Bar } from 'react-chartjs-2'
import type { AuroraHistoryDay } from '../lib/types'

ChartJS.register(CategoryScale, LinearScale, BarElement, Tooltip, Legend)

type Props = {
  history: AuroraHistoryDay[]
  impactTrend: { lastAvg: number; prevAvg: number; delta: number; pct: number } | null
}

export default function CorrectionHistoryChart({ history, impactTrend }: Props) {
  if (!history || history.length === 0) return null

  const labels = history.map((d) =>
    new Date(d.date).toLocaleDateString(undefined, { month: 'numeric', day: 'numeric' }),
  )
  const values = history.map((d) => d.total_correction_kwh)

  const data = {
    labels,
    datasets: [
      {
        label: 'Correction (kWh)',
        data: values,
        backgroundColor: 'rgba(45, 212, 191, 0.8)',
        borderRadius: 4,
        maxBarThickness: 14,
      },
    ],
  }

  const options = {
    responsive: true,
    plugins: {
      legend: {
        display: false,
      },
      tooltip: {
        backgroundColor: '#020617',
        borderColor: '#4b5563',
        borderWidth: 1,
        titleColor: '#e5e7eb',
        bodyColor: '#e5e7eb',
        padding: 8,
        callbacks: {
          title(context: any) {
            const idx = context[0].dataIndex
            const raw = history[idx]
            return raw?.date ?? ''
          },
          label(context: any) {
            const v = context.parsed.y
            return `Total correction: ${typeof v === 'number' ? v.toFixed(2) : v} kWh`
          },
        },
      },
    },
    scales: {
      x: {
        ticks: {
          color: '#9ca3af',
          maxRotation: 0,
          font: { size: 9 },
        },
        grid: {
          display: false,
        },
      },
      y: {
        ticks: {
          display: false,
        },
        grid: {
          display: false,
        },
      },
    },
  }

  return (
    <div className="p-3 md:p-4 rounded-xl2 bg-surface shadow-float border border-line/60">
      <div className="mb-1">
        <div className="text-xs font-medium text-text">Intervention History (14d)</div>
        <div className="text-[11px] text-muted">
          Daily total correction volume. Taller bars mean more Aurora intervention.
        </div>
      </div>
      <div className="h-32">
        <Bar data={data} options={options} />
      </div>
      {impactTrend && (
        <div className="mt-1 text-[10px] text-muted">
          Aurora has been{' '}
          <span className="font-semibold text-text">
            {impactTrend.delta > 0 ? 'more active' : 'less active'}
          </span>{' '}
          over the last week (avg {impactTrend.lastAvg.toFixed(2)} kWh/day vs{' '}
          {impactTrend.prevAvg.toFixed(2)} kWh/day).
        </div>
      )}
    </div>
  )
}

