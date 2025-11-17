import { useEffect, useState } from 'react'
import Card from '../components/Card'
import ChartCard from '../components/ChartCard'
import Kpi from '../components/Kpi'
import { Api } from '../lib/api'

type ForecastEvalVersion = {
  version: string
  mae_pv: number | null
  mae_load: number | null
  samples: number
}

type ForecastEvalResponse = {
  window: { start: string; end: string }
  versions: ForecastEvalVersion[]
}

type ForecastSlot = {
  slot_start: string
  pv_kwh: number | null
  load_kwh: number | null
  baseline_pv: number | null
  baseline_load: number | null
  aurora_pv: number | null
  aurora_load: number | null
}

type ForecastDayResponse = {
  date: string
  slots: ForecastSlot[]
}

export default function Forecasting(){
  const [evalData, setEvalData] = useState<ForecastEvalResponse | null>(null)
  const [dayData, setDayData] = useState<ForecastDayResponse | null>(null)
  const [activeVersion, setActiveVersion] = useState<'baseline' | 'aurora'>('baseline')
  const [loading, setLoading] = useState(false)
  const [config, setConfig] = useState<Record<string, any> | null>(null)
  const [savingSource, setSavingSource] = useState(false)

  useEffect(() => {
    const fetchEval = async () => {
      try {
        const res = await Api.forecastEval()
        setEvalData(res as any)
      } catch (err) {
        console.error('Failed to load forecast eval:', err)
      }
    }
    fetchEval()
  }, [])

  useEffect(() => {
    const fetchToday = async () => {
      setLoading(true)
      try {
        const res = await Api.forecastDay()
        setDayData(res as any)
      } catch (err) {
        console.error('Failed to load forecast day:', err)
      } finally {
        setLoading(false)
      }
    }
    fetchToday()
  }, [])

  useEffect(() => {
    const fetchConfig = async () => {
      try {
        const cfg = await Api.config()
        setConfig(cfg as any)
      } catch (err) {
        console.error('Failed to load config for forecasting:', err)
      }
    }
    fetchConfig()
  }, [])

  const baselineEval = evalData?.versions.find(v => v.version === 'baseline_7_day_avg') || null
  const auroraEval = evalData?.versions.find(v => v.version === 'aurora') || null

  const kpiValue = (v: ForecastEvalVersion | null, key: 'mae_pv' | 'mae_load') => {
    if (!v) return '—'
    const val = v[key]
    if (val == null) return '—'
    return val.toFixed(3)
  }

  const slots = dayData?.slots ?? []

  // Simple line data for load: actual vs selected version
  const chartLabels = slots.map(s => new Date(s.slot_start).toLocaleTimeString([], { hour: '2-digit', minute: '2-digit' }))
  const chartActual = slots.map(s => s.load_kwh ?? 0)
  const chartBaseline = slots.map(s => s.baseline_load ?? 0)
  const chartAurora = slots.map(s => s.aurora_load ?? 0)

  const chartDatasets = [
    {
      label: 'Actual load',
      data: chartActual,
      borderColor: 'rgba(248, 250, 252, 0.9)',
      backgroundColor: 'rgba(248, 250, 252, 0.15)',
      tension: 0.2,
    },
    {
      label: 'Baseline load',
      data: chartBaseline,
      borderColor: 'rgba(96, 165, 250, 0.8)',
      backgroundColor: 'rgba(96, 165, 250, 0.15)',
      borderDash: activeVersion === 'baseline' ? [] : [4, 4],
      tension: 0.2,
    },
    {
      label: 'AURORA load',
      data: chartAurora,
      borderColor: 'rgba(52, 211, 153, 0.8)',
      backgroundColor: 'rgba(52, 211, 153, 0.15)',
      borderDash: activeVersion === 'aurora' ? [] : [4, 4],
      tension: 0.2,
    },
  ]

  const activeSource = (config?.forecasting?.active_forecast_version as string) || 'baseline_7_day_avg'

  const handleSourceChange = async (value: string) => {
    if (!config) return
    setSavingSource(true)
    try {
      await Api.configSave({ forecasting: { active_forecast_version: value } })
      const fresh = await Api.config()
      setConfig(fresh as any)
    } catch (err) {
      console.error('Failed to save active forecast version:', err)
    } finally {
      setSavingSource(false)
    }
  }

  return (
    <div className="px-4 pt-16 pb-10 lg:px-8 lg:pt-10 space-y-6">
      <div className="flex flex-col lg:flex-row lg:items-center lg:justify-between gap-3">
        <div>
          <h1 className="text-lg font-medium text-text">Forecasting</h1>
          <p className="text-[11px] text-muted">
            Baseline vs AURORA forecasts. Use the selector to choose which source the planner uses.
          </p>
        </div>
        <div className="flex flex-col items-end gap-2">
          <div className="inline-flex items-center gap-2 rounded-full border border-line/80 bg-surface2 px-2 py-1 text-[11px]">
            <span className="text-muted">Highlight</span>
            <button
              type="button"
              className={`px-2 py-0.5 rounded-full ${
                activeVersion === 'baseline' ? 'bg-accent text-[#0F1216]' : 'text-muted'
              }`}
              onClick={() => setActiveVersion('baseline')}
            >
              Baseline
            </button>
            <button
              type="button"
              className={`px-2 py-0.5 rounded-full ${
                activeVersion === 'aurora' ? 'bg-accent text-[#0F1216]' : 'text-muted'
              }`}
              onClick={() => setActiveVersion('aurora')}
            >
              AURORA
            </button>
          </div>
          <div className="inline-flex items-center gap-2 text-[11px]">
            <span className="text-muted">Planner forecast source</span>
            <select
              value={activeSource}
              onChange={(event) => handleSourceChange(event.target.value)}
              disabled={savingSource}
              className="rounded-full border border-line/80 bg-surface2 px-2 py-1 text-[11px] text-white focus:border-accent focus:outline-none"
            >
              <option value="baseline_7_day_avg">Baseline (7-day average)</option>
              <option value="aurora">AURORA (ML model, experimental)</option>
            </select>
          </div>
        </div>
      </div>

      <div className="grid grid-cols-2 md:grid-cols-4 gap-3">
        <Kpi label="Baseline MAE PV" value={kpiValue(baselineEval, 'mae_pv')} hint="Last window" />
        <Kpi label="Baseline MAE Load" value={kpiValue(baselineEval, 'mae_load')} hint="Last window" />
        <Kpi label="AURORA MAE PV" value={kpiValue(auroraEval, 'mae_pv')} hint="Last window" />
        <Kpi label="AURORA MAE Load" value={kpiValue(auroraEval, 'mae_load')} hint="Last window" />
      </div>

      <ChartCard
        title={`Load forecast vs actual (${dayData?.date ?? 'today'})`}
        description="Actual load vs baseline and AURORA forecasts, 15-minute slots."
        labels={chartLabels}
        datasets={chartDatasets}
        loading={loading}
      />

      <Card>
        <div className="text-[11px] text-muted mb-2">Today&apos;s slots</div>
        <div className="overflow-x-auto">
          <table className="min-w-full text-[11px] text-muted">
            <thead>
              <tr className="border-b border-line/60">
                <th className="py-1 pr-3 text-left font-normal">Time</th>
                <th className="py-1 pr-3 text-right font-normal">Load (kWh)</th>
                <th className="py-1 pr-3 text-right font-normal">Baseline (kWh)</th>
                <th className="py-1 pr-3 text-right font-normal">AURORA (kWh)</th>
              </tr>
            </thead>
            <tbody>
              {slots.map(slot => {
                const t = new Date(slot.slot_start).toLocaleTimeString([], { hour: '2-digit', minute: '2-digit' })
                return (
                  <tr key={slot.slot_start} className="border-b border-line/20">
                    <td className="py-1 pr-3">{t}</td>
                    <td className="py-1 pr-3 text-right">{slot.load_kwh?.toFixed(3) ?? '—'}</td>
                    <td className="py-1 pr-3 text-right">{slot.baseline_load?.toFixed(3) ?? '—'}</td>
                    <td className="py-1 pr-3 text-right">{slot.aurora_load?.toFixed(3) ?? '—'}</td>
                  </tr>
                )
              })}
              {slots.length === 0 && (
                <tr>
                  <td colSpan={4} className="py-2 text-center text-muted">
                    No slots available for today.
                  </td>
                </tr>
              )}
            </tbody>
          </table>
        </div>
      </Card>
    </div>
  )
}
