import { useEffect, useMemo, useState } from 'react'
import { Shield, Sparkles, Zap, SunMedium } from 'lucide-react'
import Card from '../components/Card'
import ChartCard from '../components/ChartCard'
import DecompositionChart from '../components/DecompositionChart'
import { Api } from '../lib/api'
import type { AuroraDashboardResponse } from '../lib/api'

export default function Aurora() {
  const [dashboard, setDashboard] = useState<AuroraDashboardResponse | null>(null)
  const [briefing, setBriefing] = useState<string>('')
  const [briefingUpdatedAt, setBriefingUpdatedAt] = useState<string | null>(null)
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
        if (typeof bf === 'number') {
          setRiskBaseFactor(bf)
        }
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
      setBriefingUpdatedAt(new Date().toISOString())
    } catch (err) {
      console.error('Failed to fetch Aurora briefing:', err)
      setBriefing('Failed to fetch Aurora briefing.')
    } finally {
      setBriefingLoading(false)
    }
  }

  const handleRiskChange = async (value: number) => {
    if (value == null) return
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
    overallVol < 0.3 ? 'bg-emerald-400/90' : overallVol < 0.7 ? 'bg-sky-400/90' : 'bg-amber-400/90'

  const heroGradient =
    overallVol < 0.3
      ? 'from-emerald-900/60 via-surface to-surface'
      : overallVol < 0.7
      ? 'from-sky-900/60 via-surface to-surface'
      : 'from-amber-900/60 via-surface to-surface'

  const horizonSlots = dashboard?.horizon?.slots ?? []

  const correctionHistory = dashboard?.history?.correction_volume_days ?? []

  const todayImpact = useMemo(() => {
    if (!correctionHistory || correctionHistory.length === 0) return null
    const todayIso = new Date().toISOString().slice(0, 10)
    const match = correctionHistory.find((d) => d.date === todayIso)
    return match ? match.total_correction_kwh : null
  }, [correctionHistory])

  const horizonSummary = useMemo(() => {
    if (!horizonSlots || horizonSlots.length === 0) return null
    let total = 0
    let peakAbs = 0
    let peakLabel: string | null = null
    horizonSlots.forEach((slot) => {
      const corr = chartMode === 'load' ? slot.correction.load_kwh : slot.correction.pv_kwh
      const v = typeof corr === 'number' ? corr : 0
      total += v
      const abs = Math.abs(v)
      if (abs > peakAbs) {
        peakAbs = abs
        peakLabel = new Date(slot.slot_start).toLocaleTimeString([], {
          hour: '2-digit',
          minute: '2-digit',
        })
      }
    })
    return {
      total,
      peakAbs,
      peakLabel,
    }
  }, [horizonSlots, chartMode])

  const impactTrend = useMemo(() => {
    if (!correctionHistory || correctionHistory.length < 4) return null
    const sorted = [...correctionHistory].sort((a, b) => a.date.localeCompare(b.date))
    const last7 = sorted.slice(-7)
    const prev7 = sorted.slice(-14, -7)
    if (last7.length === 0 || prev7.length === 0) return null
    const avg = (rows: typeof sorted) =>
      rows.reduce((sum, r) => sum + (r.total_correction_kwh || 0), 0) / rows.length
    const lastAvg = avg(last7)
    const prevAvg = avg(prev7)
    if (!isFinite(lastAvg) || !isFinite(prevAvg) || prevAvg === 0) return null
    const delta = lastAvg - prevAvg
    const pct = (delta / prevAvg) * 100
    return { lastAvg, prevAvg, delta, pct }
  }, [correctionHistory])

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
        <Card className={`md:col-span-3 p-4 md:p-5 bg-gradient-to-br ${heroGradient}`}>
          <div className="flex items-center gap-4">
            <div className="relative flex items-center justify-center w-16 h-16 rounded-3xl bg-surface/90 border border-line/80 shadow-float">
              <Shield className="h-10 w-10 text-accent drop-shadow-[0_0_12px_rgba(56,189,248,0.75)]" />
            </div>
            <div className="flex flex-col gap-2 flex-1">
              <div>
                <div className="text-xs font-semibold text-text uppercase tracking-wide">
                  Aurora
                </div>
                <div className="text-[13px] font-medium text-text capitalize">
                  {graduationLabel || 'infant'} mode
                </div>
              </div>
              <div className="flex flex-wrap gap-4 text-[11px] text-muted">
                <div>
                  <div className="uppercase tracking-wide text-[10px]">Experience</div>
                  <div className="font-mono text-text">
                    {graduationRuns} runs
                  </div>
                </div>
                <div>
                  <div className="uppercase tracking-wide text-[10px]">Strategy</div>
                  <div className="text-text">
                    {riskLabel}{' '}
                    <span className="font-mono">
                      ({riskBaseFactor != null ? riskBaseFactor.toFixed(2) : '—'})
                    </span>
                  </div>
                </div>
                <div>
                  <div className="uppercase tracking-wide text-[10px]">Today&apos;s Action</div>
                  <div className="text-text">
                    {todayImpact != null ? `${todayImpact.toFixed(2)} kWh corrected` : '—'}
                  </div>
                </div>
              </div>
            </div>
            <div className="ml-auto flex items-center gap-3">
              <div className="text-right text-[11px] text-muted">
                <div className="uppercase tracking-wide text-[10px] text-muted">
                  Volatility
                </div>
                <div>{(overallVol * 100).toFixed(0)}% (48h)</div>
              </div>
              <div className="relative flex items-center justify-center h-10 w-10">
                <div
                  className={`absolute inset-0 rounded-full ${waveColor} opacity-30 animate-ping`}
                />
                <div className={`relative h-5 w-5 rounded-full ${waveColor}`} />
              </div>
            </div>
          </div>
        </Card>
      </div>

      <div className="grid gap-4 lg:grid-cols-3">
        <Card className="lg:col-span-2 p-4 md:p-5">
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
          <div className="space-y-1">
            <div className="text-[12px] leading-relaxed bg-surface2/60 border border-line/70 rounded-md px-3 py-3 font-mono tracking-tight text-accent">
              {briefing || 'No briefing yet. Click “Refresh briefing” to ask Aurora.'}
            </div>
            {briefingUpdatedAt && (
              <div className="text-[10px] text-muted">
                Last updated:{' '}
                {new Date(briefingUpdatedAt).toLocaleTimeString([], {
                  hour: '2-digit',
                  minute: '2-digit',
                })}
              </div>
            )}
          </div>
        </Card>

        <Card className="p-4 md:p-5">
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
              <div className="absolute inset-x-0 top-1/2 h-[3px] -translate-y-1/2 rounded-full bg-surface2" />
              <div className="absolute inset-x-0 top-1/2 h-[3px] -translate-y-1/2 flex">
                <div className="flex-1 bg-emerald-500/25 rounded-l-full" />
                <div className="flex-1 bg-sky-500/20" />
                <div className="flex-1 bg-amber-500/25 rounded-r-full" />
              </div>
              <input
                type="range"
                min={0.8}
                max={1.5}
                step={0.01}
                value={riskBaseFactor ?? 1.1}
                onChange={(event) => {
                  const val = parseFloat(event.target.value)
                  setRiskBaseFactor(val)
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
            <div className="text-[11px] text-muted space-y-1">
              <div className="flex items-center gap-2">
                <span
                  className={`inline-block h-2 w-2 rounded-full ${
                    riskBaseFactor != null && riskBaseFactor < 1.0
                      ? 'bg-emerald-400'
                      : riskBaseFactor != null && riskBaseFactor > 1.2
                      ? 'bg-amber-400'
                      : 'bg-sky-400'
                  }`}
                />
                <span>
                  Current base factor:{' '}
                  <span className="font-mono text-text">
                    {riskBaseFactor != null ? riskBaseFactor.toFixed(2) : '—'}
                  </span>
                </span>
              </div>
              <div className="text-[10px]">
                {riskBaseFactor != null && riskBaseFactor < 1.0 && 'Aurora will be more aggressive in cheap windows.'}
                {riskBaseFactor != null &&
                  riskBaseFactor >= 1.0 &&
                  riskBaseFactor <= 1.2 &&
                  'Aurora is balancing savings and safety.'}
                {riskBaseFactor != null &&
                  riskBaseFactor > 1.2 &&
                  'Aurora will hold more reserve for uncertainty.'}
              </div>
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
              <span className="inline-flex items-center gap-1">
                <Zap className="h-3 w-3" />
                <span>Load</span>
              </span>
            </button>
            <button
              type="button"
              className={`px-2 py-0.5 rounded-full ${
                chartMode === 'pv' ? 'bg-accent text-[#0F1216]' : 'text-muted'
              }`}
              onClick={() => setChartMode('pv')}
            >
              <span className="inline-flex items-center gap-1">
                <SunMedium className="h-3 w-3" />
                <span>Solar</span>
              </span>
            </button>
          </div>
        </div>
        {loading ? (
          <div className="text-[11px] text-muted px-4 py-6">Loading Aurora horizon…</div>
        ) : (
          <>
            <DecompositionChart slots={horizonSlots} mode={chartMode} />
            {horizonSummary && (
              <div className="px-4 pb-3 pt-2 text-[10px] text-muted flex justify-between">
                <span>
                  Total correction:{' '}
                  <span className="font-mono text-text">
                    {horizonSummary.total.toFixed(2)} kWh
                  </span>
                </span>
                {horizonSummary.peakLabel && (
                  <span>
                    Peak at{' '}
                    <span className="font-mono text-text">
                      {horizonSummary.peakLabel}
                    </span>
                  </span>
                )}
              </div>
            )}
          </>
        )}
      </ChartCard>

      {correctionHistory.length > 0 && (
        <Card className="p-3 md:p-4">
          <div className="mb-1">
            <div className="text-xs font-medium text-text">Correction Volume (14d)</div>
            <div className="text-[11px] text-muted">
              Daily sum of absolute PV + load corrections used by Aurora.
            </div>
          </div>
          <div className="flex gap-[3px] items-end h-16">
            {correctionHistory.map((day) => {
              const v = day.total_correction_kwh
              const height = Math.min(100, v * 40)
              return (
                <div key={day.date} className="flex flex-col items-center gap-1">
                  <div
                    className="w-1.5 rounded-full bg-accent/70"
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
        </Card>
      )}
    </div>
  )
}
