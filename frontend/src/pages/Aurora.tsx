import { useEffect, useMemo, useState } from 'react'
import { Bot, Sparkles, Zap, SunMedium } from 'lucide-react'
import Card from '../components/Card'
import DecompositionChart from '../components/DecompositionChart'
import CorrectionHistoryChart from '../components/CorrectionHistoryChart'
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
  const [effectiveSIndex, setEffectiveSIndex] = useState<number | null>(null)
  const [effectiveSIndexMode, setEffectiveSIndexMode] = useState<string | null>(null)

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

  useEffect(() => {
    const fetchDebug = async () => {
      try {
        const res = await Api.debug()
        const sIndex = res.s_index
        if (sIndex) {
          setEffectiveSIndex(
            typeof sIndex.factor === 'number' ? sIndex.factor : null,
          )
          setEffectiveSIndexMode(
            typeof sIndex.mode === 'string' ? sIndex.mode : null,
          )
        }
      } catch (err) {
        console.error('Failed to load debug S-index for Aurora:', err)
      }
    }
    fetchDebug()
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

  const auroraMetrics = dashboard?.metrics

  const pvImprovement = useMemo(() => {
    const b = auroraMetrics?.mae_pv_baseline
    const a = auroraMetrics?.mae_pv_aurora
    if (b == null || a == null || b <= 0) return null
    const delta = b - a
    const pct = (delta / b) * 100
    return { baseline: b, aurora: a, delta, pct }
  }, [auroraMetrics])

  const loadImprovement = useMemo(() => {
    const b = auroraMetrics?.mae_load_baseline
    const a = auroraMetrics?.mae_load_aurora
    if (b == null || a == null || b <= 0) return null
    const delta = b - a
    const pct = (delta / b) * 100
    return { baseline: b, aurora: a, delta, pct }
  }, [auroraMetrics])

  const sliderSteps = [0.9, 1.1, 1.5]

  const snapToStep = (value: number): number => {
    let closest = sliderSteps[0]
    let minDiff = Math.abs(value - closest)
    for (const step of sliderSteps) {
      const diff = Math.abs(value - step)
      if (diff < minDiff) {
        minDiff = diff
        closest = step
      }
    }
    return closest
  }

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
            <div className="relative flex items-center justify-center">
              <div
                className={`absolute h-16 w-16 rounded-full ${waveColor} opacity-30 animate-pulse`}
              />
              <div className="relative flex items-center justify-center w-14 h-14 rounded-3xl bg-surface/90 border border-line/80 shadow-float">
                <Bot className="h-9 w-9 text-accent drop-shadow-[0_0_12px_rgba(56,189,248,0.75)]" />
              </div>
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
            <div className="ml-auto text-right text-[11px] text-muted">
              <div className="uppercase tracking-wide text-[10px] text-muted">
                Volatility
              </div>
              <div>{(overallVol * 100).toFixed(0)}% (48h)</div>
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
                <span>Frugal (0.9)</span>
                <span>Balanced (1.1)</span>
                <span>Fortified (1.5)</span>
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
                min={0.9}
                max={1.5}
                step={0.01}
                value={riskBaseFactor ?? 1.1}
                onChange={(event) => {
                  const raw = parseFloat(event.target.value)
                  const snapped = snapToStep(raw)
                  setRiskBaseFactor(snapped)
                  handleRiskChange(snapped)
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
                {riskBaseFactor === 0.9 && 'Aurora will be frugal, leaning into cheap windows.'}
                {riskBaseFactor === 1.1 && 'Aurora balances savings with safety margins.'}
                {riskBaseFactor === 1.5 && 'Aurora is fortified against forecast uncertainty.'}
              </div>
            </div>
            {savingRisk && (
              <div className="text-[11px] text-muted">Saving and reloading config…</div>
            )}
          </div>
        </Card>
      </div>

      <Card className="p-4 md:p-5">
        <div className="flex items-center justify-between mb-3">
          <div>
            <div className="text-xs font-medium text-text">Forecast Decomposition</div>
            <div className="text-[11px] text-muted">
              Base vs corrected forecast over the next 48 hours.
            </div>
          </div>
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
          <DecompositionChart slots={horizonSlots} mode={chartMode} />
        )}
      </Card>

      <div className="grid gap-4 lg:grid-cols-2">
        <Card className="p-4 md:p-5">
          <div className="mb-2">
            <div className="text-xs font-medium text-text">Aurora Performance</div>
            <div className="text-[11px] text-muted">
              Baseline vs Aurora forecast accuracy and effective S-index.
            </div>
          </div>
          <div className="space-y-2 text-[11px] text-muted">
            <div>
              <div className="uppercase tracking-wide text-[10px]">PV MAE</div>
              {pvImprovement ? (
                <div>
                  Baseline{' '}
                  <span className="font-mono text-text">
                    {pvImprovement.baseline.toFixed(3)}
                  </span>{' '}
                  → Aurora{' '}
                  <span className="font-mono text-text">
                    {pvImprovement.aurora.toFixed(3)}
                  </span>{' '}
                  kWh (
                  <span className="font-mono text-text">
                    {pvImprovement.pct.toFixed(1)}%
                  </span>{' '}
                  better)
                </div>
              ) : (
                <div>Not enough PV data yet.</div>
              )}
            </div>
            <div>
              <div className="uppercase tracking-wide text-[10px]">Load MAE</div>
              {loadImprovement ? (
                <div>
                  Baseline{' '}
                  <span className="font-mono text-text">
                    {loadImprovement.baseline.toFixed(3)}
                  </span>{' '}
                  → Aurora{' '}
                  <span className="font-mono text-text">
                    {loadImprovement.aurora.toFixed(3)}
                  </span>{' '}
                  kWh (
                  <span className="font-mono text-text">
                    {loadImprovement.pct.toFixed(1)}%
                  </span>{' '}
                  better)
                </div>
              ) : (
                <div>Not enough load data yet.</div>
              )}
            </div>
            <div>
              <div className="uppercase tracking-wide text-[10px]">Effective S-index</div>
              <div>
                Base{' '}
                <span className="font-mono text-text">
                  {riskBaseFactor != null ? riskBaseFactor.toFixed(2) : '—'}
                </span>
                {effectiveSIndex != null && (
                  <>
                    {' '}
                    → Effective{' '}
                    <span className="font-mono text-text">
                      {effectiveSIndex.toFixed(2)}
                    </span>
                  </>
                )}
                {effectiveSIndexMode && (
                  <span className="ml-1">
                    ({effectiveSIndexMode})
                  </span>
                )}
              </div>
            </div>
          </div>
        </Card>

        {correctionHistory.length > 0 && (
          <CorrectionHistoryChart history={correctionHistory} impactTrend={impactTrend} />
        )}
      </div>
    </div>
  )
}
