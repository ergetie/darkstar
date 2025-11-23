import { useEffect, useMemo, useState } from 'react'
import { Sparkles } from 'lucide-react'
import Card from '../components/Card'
import ChartCard from '../components/ChartCard'
import DecompositionChart from '../components/DecompositionChart'
import { Api } from '../lib/api'
import type { AuroraDashboardResponse } from '../lib/api'

export default function Aurora() {
  const [dashboard, setDashboard] = useState<AuroraDashboardResponse | null>(null)
  const [briefing, setBriefing] = useState<string>('')
  const [loading, setLoading] = useState(false)
  const [briefingLoading, setBriefingLoading] = useState(false)
  const [riskBaseFactor, setRiskBaseFactor] = useState<number | null>(null)
  const [savingRisk, setSavingRisk] = useState(false)
  const [chartMode, setChartMode] = useState<'load' | 'pv'>('load')

  useEffect(() => {
    const fetchDashboard = async () => {
      setLoading(true)
      try {
        const res = await Api.aurora.dashboard()
        setDashboard(res)
        const bf = res.state?.risk_profile?.base_factor
        if (typeof bf === 'number') setRiskBaseFactor(bf)
      } catch (err) {
        console.error('Failed to load Aurora dashboard:', err)
      } finally {
        setLoading(false)
      }
    }
    fetchDashboard()
  }, [])

  const handleBriefing = async () => {
    if (!dashboard) return
    setBriefingLoading(true)
    try {
      const res = await Api.aurora.briefing(dashboard)
      setBriefing(res.briefing)
    } catch (err) {
      console.error('Failed to fetch Aurora briefing:', err)
      setBriefing('Failed to fetch Aurora briefing.')
    } finally {
      setBriefingLoading(false)
    }
  }

  const handleRiskChange = async (value: number) => {
    setRiskBaseFactor(value)
    setSavingRisk(true)
    try {
      await Api.configSave({ s_index: { base_factor: value } })
      const fresh = await Api.config()
      const bf = (fresh as any)?.s_index?.base_factor
      if (typeof bf === 'number') {
        setRiskBaseFactor(bf)
      }
    } catch (err) {
      console.error('Failed to save risk level (s_index.base_factor):', err)
    } finally {
      setSavingRisk(false)
    }
  }

  const riskLabel = useMemo(() => {
    const persona = dashboard?.state?.risk_profile?.persona
    if (!persona) return 'Unknown'
    return persona
  }, [dashboard])

  const graduationLabel = dashboard?.identity?.graduation?.label ?? 'infant'
  const graduationRuns = dashboard?.identity?.graduation?.runs ?? 0

  const volatility = dashboard?.state?.weather_volatility
  const overallVol = volatility?.overall ?? 0

  const waveColor =
    overallVol < 0.3 ? 'bg-accent/70' : overallVol < 0.7 ? 'bg-sky-400/80' : 'bg-amber-400/90'

  const horizonSlots = dashboard?.horizon?.slots ?? []

  const correctionHistory = dashboard?.history?.correction_volume_days ?? []

  return (
    <div className="px-4 pt-16 pb-10 lg:px-8 lg:pt-10 space-y-6">
      <div className="flex flex-col lg:flex-row lg:items-center lg:justify-between gap-3">
        <div>
          <h1 className="text-lg font-medium text-text">Aurora</h1>
          <p className="text-[11px] text-muted">
            The brain of Darkstar. Identity, risk, and forecast corrections.
          </p>
        </div>
      </div>

      <div className="grid gap-4 md:grid-cols-3">
        <Card className="md:col-span-3 bg-surface border border-line/60 shadow-float px-4 py-3">
          <div className="flex items-center gap-4">
            <div className="flex items-center justify-center w-14 h-14 rounded-2xl bg-surface2 border border-line/80 shadow-inner">
              <span className="text-2xl">
                {graduationLabel === 'graduate'
                  ? '🎓'
                  : graduationLabel === 'statistician'
                  ? '📊'
                  : '🍼'}
              </span>
            </div>
            <div className="flex flex-col gap-1">
              <div className="text-xs font-semibold text-text uppercase tracking-wide">
                Aurora
              </div>
              <div className="text-[13px] font-medium text-text capitalize">
                {graduationLabel || 'infant'} mode
              </div>
              <div className="text-[11px] text-muted">
                Runs:{' '}
                <span className="font-mono text-text">{graduationRuns}</span>
              </div>
              <div className="text-[11px] text-muted">
                Risk:{' '}
                <span className="font-semibold text-text">
                  {riskLabel} ({riskBaseFactor != null ? riskBaseFactor.toFixed(2) : '—'})
                </span>
              </div>
            </div>
            <div className="ml-auto flex items-center gap-3">
              <div className="text-right text-[11px] text-muted">
                <div className="uppercase tracking-wide text-[10px] text-muted">
                  Volatility
                </div>
                <div>{(overallVol * 100).toFixed(0)}% (48h)</div>
              </div>
              <div className="flex items-end gap-[3px] h-8">
                {[0, 1, 2].map((idx) => (
                  // eslint-disable-next-line react/no-array-index-key
                  <div
                    key={idx}
                    className={`w-1.5 rounded-full ${waveColor} animate-pulse`}
                    style={{
                      height: `${30 + idx * 15}%`,
                      animationDelay: `${idx * 140}ms`,
                    }}
                  />
                ))}
              </div>
            </div>
          </div>
        </Card>
      </div>

      <div className="grid gap-4 lg:grid-cols-3">
        <Card className="lg:col-span-2">
          <div className="flex items-center justify-between mb-3">
            <div className="flex items-center gap-2">
              <span className="inline-flex h-6 w-6 items-center justify-center rounded-full bg-surface2 border border-line/70">
                <Sparkles className="h-3 w-3 text-accent" />
              </span>
              <div>
                <div className="text-xs font-medium text-text">Daily Briefing</div>
                <div className="text-[11px] text-muted">
                  Aurora explains how it feels about the next 48 hours.
                </div>
              </div>
            </div>
            <button
              type="button"
              onClick={handleBriefing}
              disabled={!dashboard || briefingLoading}
              className="rounded-full border border-line/80 bg-surface2 px-3 py-1 text-[11px] text-white hover:border-accent disabled:opacity-50"
            >
              {briefingLoading ? 'Thinking…' : 'Refresh briefing'}
            </button>
          </div>
          <div className="text-[12px] leading-relaxed text-text bg-surface2/60 border border-line/70 rounded-md px-3 py-3 font-mono tracking-tight">
            {briefing || 'No briefing yet. Click “Refresh briefing” to ask Aurora.'}
          </div>
        </Card>

        <Card>
          <div className="flex items-center justify-between mb-3">
            <div>
              <div className="text-xs font-medium text-text">Risk Dial</div>
              <div className="text-[11px] text-muted">
                Tune base S-index factor. Lower is bolder, higher is cautious.
              </div>
            </div>
          </div>
            <div className="space-y-2">
              <div className="flex justify-between text-[11px] text-muted">
                <span>Gambler (0.8)</span>
                <span>Balanced (1.1)</span>
                <span>Paranoid (1.5)</span>
              </div>
            <div className="relative mt-1">
              <div className="absolute inset-x-0 top-1/2 h-[3px] -translate-y-1/2 rounded-full bg-gradient-to-r from-emerald-500/40 via-sky-500/50 to-amber-500/40" />
              <input
                type="range"
                min={0.8}
                max={1.5}
                step={0.01}
                value={riskBaseFactor ?? 1.1}
                onChange={(event) => {
                  const val = parseFloat(event.target.value)
                  setRiskBaseFactor(val)
                }}
                onMouseUp={(event) => {
                  const val = parseFloat((event.target as HTMLInputElement).value)
                  handleRiskChange(val)
                }}
                onTouchEnd={(event) => {
                  const val = parseFloat((event.target as HTMLInputElement).value)
                  handleRiskChange(val)
                }}
                className="relative w-full bg-transparent accent-accent cursor-pointer"
              />
            </div>
            <div className="mt-1 flex justify-between text-[10px] text-muted">
              <span className="flex flex-col items-start">
                <span className="h-1 w-[1px] bg-line/80 mb-1" />
                <span>0.8</span>
              </span>
              <span className="flex flex-col items-center">
                <span className="h-2 w-[1px] bg-accent mb-1" />
                <span>1.0</span>
              </span>
              <span className="flex flex-col items-center">
                <span className="h-3 w-[1px] bg-accent mb-1" />
                <span>1.2</span>
              </span>
              <span className="flex flex-col items-end">
                <span className="h-1 w-[1px] bg-line/80 mb-1" />
                <span>1.5</span>
              </span>
            </div>
            <div className="text-[11px] text-muted">
              Current base factor:{' '}
              <span className="font-mono text-text">
                {riskBaseFactor != null ? riskBaseFactor.toFixed(2) : '—'}
              </span>
            </div>
            {savingRisk && (
              <div className="text-[11px] text-muted">Saving and reloading config…</div>
            )}
          </div>
        </Card>
      </div>

      <ChartCard
        title={chartMode === 'load' ? 'Forecast Decomposition (Load)' : 'Forecast Decomposition (Solar)'}
        subtitle={
          chartMode === 'load'
            ? 'Base vs correction vs final load over the next 48 hours.'
            : 'Base vs correction vs final solar production over the next 48 hours.'
        }
      >
        <div className="flex items-center justify-between px-4 pt-3">
          <div className="inline-flex items-center gap-1 rounded-full border border-line/70 bg-surface2 px-1 py-0.5 text-[11px]">
            <button
              type="button"
              className={`px-2 py-0.5 rounded-full ${
                chartMode === 'load' ? 'bg-accent text-[#0F1216]' : 'text-muted'
              }`}
              onClick={() => setChartMode('load')}
            >
              Load forecast
            </button>
            <button
              type="button"
              className={`px-2 py-0.5 rounded-full ${
                chartMode === 'pv' ? 'bg-accent text-[#0F1216]' : 'text-muted'
              }`}
              onClick={() => setChartMode('pv')}
            >
              Solar forecast
            </button>
          </div>
        </div>
        {loading ? (
          <div className="text-[11px] text-muted px-4 py-6">Loading Aurora horizon…</div>
        ) : (
          <DecompositionChart slots={horizonSlots} mode={chartMode} />
        )}
      </ChartCard>

      {correctionHistory.length > 0 && (
        <Card>
          <div className="mb-2">
            <div className="text-xs font-medium text-text">Correction Volume (14d)</div>
            <div className="text-[11px] text-muted">
              Daily sum of absolute PV + load corrections used by Aurora.
            </div>
          </div>
          <div className="flex gap-1 items-end h-24">
            {correctionHistory.map((day) => {
              const v = day.total_correction_kwh
              const height = Math.min(100, v * 40)
              return (
                <div key={day.date} className="flex flex-col items-center gap-1">
                  <div
                    className="w-2 rounded-full bg-accent/80"
                    style={{ height: `${height}%` }}
                    title={`${day.date}: ${v.toFixed(3)} kWh`}
                  />
                  <span className="text-[9px] text-muted">
                    {new Date(day.date).toLocaleDateString(undefined, {
                      month: 'numeric',
                      day: 'numeric',
                    })}
                  </span>
                </div>
              )
            })}
          </div>
        </Card>
      )}
    </div>
  )
}
