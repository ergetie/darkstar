import Card from './Card'
import { useEffect, useRef } from 'react'
import { Chart, ChartConfiguration } from 'chart.js/auto'
import { sampleChart } from '../lib/sample'

export default function ChartCard(){
    const ref = useRef<HTMLCanvasElement | null>(null)
    const chartRef = useRef<Chart | null>(null)

    useEffect(() => {
        if(!ref.current) return
            const cfg: ChartConfiguration = {
                type: 'bar',
              data: {
                  labels: sampleChart.labels,
              datasets: [
                  {
                      type: 'line',
              label: 'Import Price (SEK/kWh)',
              data: sampleChart.price,
              borderColor: '#7ea0ff',
              backgroundColor: 'rgba(126,160,255,.12)',
              yAxisID: 'y',
              tension: 0.2,
              pointRadius: 0,
                  },
              {
                  type: 'line',
              label: 'PV Forecast (kW)',
              data: sampleChart.pv,
              borderColor: '#87F0A3',
              backgroundColor: 'rgba(135,240,163,.18)',
              fill: true,
              yAxisID: 'y1',
              tension: .35,
              pointRadius: 0,
              },
              {
                  type: 'bar',
              label: 'Load (kW)',
              data: sampleChart.load,
              backgroundColor: '#F5D547',
              borderRadius: 6,
              yAxisID: 'y1',
              barPercentage: 1,
              categoryPercentage: .9,
              },
              ]
              },
              options: {
                  maintainAspectRatio: false,
              plugins: {
                  legend: {
                      labels: {
                          color: '#e6e9ef',
              boxWidth: 10,
              font: { size: 12 }
                      }
                  }
              },
              scales: {
                  x: {
                      grid: { color: 'rgba(255,255,255,0.06)' },
              ticks: { color: '#a6b0bf', maxRotation: 0, autoSkip: true }
                  },
              y: {
                  position: 'right',
              grid: { color: 'rgba(255,255,255,0.06)' },
              ticks: { color: '#a6b0bf' }
              },
              y1: {
                  position: 'left',
              grid: { display: false },
              ticks: { color: '#a6b0bf' }
              }
              }
              }
            }
            chartRef.current = new Chart(ref.current, cfg)
            return () => chartRef.current?.destroy()
    }, [])

    return (
        <Card className="p-4 md:p-6 h-[380px]">
        <div className="flex items-baseline justify-between pb-3">
        <div className="text-sm text-muted">Schedule Overview</div>
        <div className="text-[11px] text-muted">today → tomorrow</div>
        </div>
        <div className="h-[310px]">
        <canvas ref={ref}/>
        </div>
        </Card>
    )
}
