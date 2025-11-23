import {
  Chart as ChartJS,
  CategoryScale,
  LinearScale,
  PointElement,
  LineElement,
  BarElement,
  Tooltip,
  Legend,
} from 'chart.js'
import { Line } from 'react-chartjs-2'
import type { AuroraHorizonSlot } from '../lib/types'

ChartJS.register(CategoryScale, LinearScale, PointElement, LineElement, BarElement, Tooltip, Legend)

type Props = {
  slots: AuroraHorizonSlot[]
  mode: 'load' | 'pv'
}

export default function DecompositionChart({ slots, mode }: Props) {
  if (!slots || slots.length === 0) {
    return (
      <div className="text-[11px] text-muted px-4 py-6">
        No forecast data available for the next 48 hours.
      </div>
    )
  }

  const labels = slots.map((s) =>
    new Date(s.slot_start).toLocaleTimeString([], { hour: '2-digit', minute: '2-digit' }),
  )

  const isLoad = mode === 'load'

  const baseSeries = slots.map((s) => (isLoad ? s.base.load_kwh : s.base.pv_kwh))
  const finalSeries = slots.map((s) => (isLoad ? s.final.load_kwh : s.final.pv_kwh))
  const correctionSeries = slots.map((s) =>
    isLoad ? s.correction.load_kwh : s.correction.pv_kwh,
  )

  const correctionColors = correctionSeries.map((v) =>
    v >= 0 ? 'rgba(34, 197, 94, 0.65)' : 'rgba(239, 68, 68, 0.65)',
  )

  const data = {
    labels,
    datasets: [
      {
        type: 'line' as const,
        label: isLoad ? 'Base load (kWh)' : 'Base solar (kWh)',
        data: baseSeries,
        borderColor: 'rgba(148, 163, 184, 0.9)',
        backgroundColor: 'rgba(148, 163, 184, 0.2)',
        borderWidth: 1.5,
        tension: 0.25,
        pointRadius: 0,
      },
      {
        type: 'line' as const,
        label: isLoad ? 'Final load (kWh)' : 'Final solar (kWh)',
        data: finalSeries,
        borderColor: 'rgba(96, 165, 250, 0.95)',
        backgroundColor: 'rgba(96, 165, 250, 0.2)',
        borderWidth: 1.5,
        borderDash: [4, 3],
        tension: 0.25,
        pointRadius: 0,
      },
      {
        type: 'bar' as const,
        label: isLoad ? 'Load correction (kWh)' : 'Solar correction (kWh)',
        data: correctionSeries,
        backgroundColor: correctionColors,
        borderColor: correctionColors,
        borderWidth: 0,
        yAxisID: 'y',
      },
    ],
  }

  const options = {
    responsive: true,
    interaction: {
      mode: 'index' as const,
      intersect: false,
    },
    plugins: {
      legend: {
        labels: {
          color: '#e5e7eb',
          font: { size: 10 },
        },
      },
      tooltip: {
        callbacks: {
          label(context: any) {
            const label = context.dataset.label || ''
            const value = context.parsed.y
            return `${label}: ${typeof value === 'number' ? value.toFixed(3) : value}`
          },
        },
      },
    },
    scales: {
      x: {
        ticks: {
          color: '#9ca3af',
          maxRotation: 0,
          autoSkip: true,
          maxTicksLimit: 12,
          font: { size: 9 },
        },
        grid: {
          color: 'rgba(31, 41, 55, 0.8)',
        },
      },
      y: {
        ticks: {
          color: '#9ca3af',
          font: { size: 9 },
        },
        grid: {
          color: 'rgba(31, 41, 55, 0.6)',
        },
      },
    },
  }

  return (
    <div className="w-full h-64">
      <Line data={data} options={options} />
    </div>
  )
}
