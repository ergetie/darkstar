import { useEffect, useState } from 'react'
import Card from '../components/Card'
import ChartCard from '../components/ChartCard'
import Kpi from '../components/Kpi'
import ProbabilisticChart, { SlotData } from '../components/ProbabilisticChart'
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
    aurora_pv_p10?: number | null
    aurora_pv_p90?: number | null
    aurora_load_p10?: number | null
    aurora_load_p90?: number | null
}

type ForecastDayResponse = {
    date: string
    slots: ForecastSlot[]
}

export default function Forecasting() {
    const [evalData, setEvalData] = useState<ForecastEvalResponse | null>(null)
    const [dayData, setDayData] = useState<ForecastDayResponse | null>(null)
    const [activeVersion, setActiveVersion] = useState<'baseline' | 'aurora'>('baseline')
    const [loading, setLoading] = useState(false)
    const [config, setConfig] = useState<Record<string, any> | null>(null)
    const [savingSource, setSavingSource] = useState(false)
    const [runningEval, setRunningEval] = useState(false)
    const [runningForward, setRunningForward] = useState(false)

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

    const baselineEval = evalData?.versions.find((v) => v.version === 'baseline_7_day_avg') || null
    const auroraEval = evalData?.versions.find((v) => v.version === 'aurora') || null

    const kpiValue = (v: ForecastEvalVersion | null, key: 'mae_pv' | 'mae_load') => {
        if (!v) return '—'
        const val = v[key]
        if (val == null) return '—'
        return val.toFixed(3)
    }

    const slots = dayData?.slots ?? []

    // Simple line data for load: actual vs selected version
    const chartLabels = slots.map((s) =>
        new Date(s.slot_start).toLocaleTimeString([], { hour: '2-digit', minute: '2-digit' }),
    )
    const chartActual = slots.map((s) => s.load_kwh ?? 0)
    const chartBaseline = slots.map((s) => s.baseline_load ?? 0)
    const chartAurora = slots.map((s) => s.aurora_load ?? 0)

    const chartDatasets = [
        {
            label: 'Actual load (kWh)',
            data: chartActual,
            borderColor: 'rgba(248, 250, 252, 0.9)',
            backgroundColor: 'rgba(248, 250, 252, 0.15)',
            tension: 0.2,
        },
        {
            label: 'Baseline load (kWh)',
            data: chartBaseline,
            borderColor: 'rgba(96, 165, 250, 0.8)',
            backgroundColor: 'rgba(96, 165, 250, 0.15)',
            borderDash: activeVersion === 'baseline' ? [] : [4, 4],
            tension: 0.2,
        },
        {
            label: 'AURORA load (kWh)',
            data: chartAurora,
            borderColor: 'rgba(52, 211, 153, 0.8)',
            backgroundColor: 'rgba(52, 211, 153, 0.15)',
            borderDash: activeVersion === 'aurora' ? [] : [4, 4],
            tension: 0.2,
        },
    ]

    const activeSource = (config?.forecasting?.active_forecast_version as string) || 'baseline_7_day_avg'

    const auroraAvailable = !!auroraEval && auroraEval.samples > 0

    const maeDelta = (
        baseline: ForecastEvalVersion | null,
        aurora: ForecastEvalVersion | null,
        key: 'mae_pv' | 'mae_load',
    ): number | null => {
        if (!baseline || !aurora) return null
        const b = baseline[key]
        const a = aurora[key]
        if (b == null || a == null) return null
        return b - a
    }

    const pvDelta = maeDelta(baselineEval, auroraEval, 'mae_pv')
    const loadDelta = maeDelta(baselineEval, auroraEval, 'mae_load')

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

    const reloadData = async () => {
        try {
            const [evalRes, dayRes] = await Promise.all([Api.forecastEval(), Api.forecastDay()])
            setEvalData(evalRes as any)
            setDayData(dayRes as any)
        } catch (err) {
            console.error('Failed to reload forecasting data:', err)
        }
    }

    const handleRunEval = async () => {
        setRunningEval(true)
        try {
            await Api.forecastRunEval(7)
            await reloadData()
        } catch (err) {
            console.error('Failed to run AURORA evaluation:', err)
        } finally {
            setRunningEval(false)
        }
    }

    const handleRunForward = async () => {
        setRunningForward(true)
        try {
            await Api.forecastRunForward(48)
            await reloadData()
        } catch (err) {
            console.error('Failed to run AURORA forward forecasts:', err)
        } finally {
            setRunningForward(false)
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
                    <div className="inline-flex items-center gap-2 text-[11px]">
                        <button
                            type="button"
                            onClick={handleRunEval}
                            disabled={runningEval}
                            className="rounded-full border border-line/80 bg-surface2 px-2 py-1 text-[11px] text-white hover:border-accent disabled:opacity-50"
                        >
                            {runningEval ? 'Running eval…' : 'Run eval (7d)'}
                        </button>
                        <button
                            type="button"
                            onClick={handleRunForward}
                            disabled={runningForward}
                            className="rounded-full border border-line/80 bg-surface2 px-2 py-1 text-[11px] text-white hover:border-accent disabled:opacity-50"
                        >
                            {runningForward ? 'Running forward…' : 'Run forward (48h)'}
                        </button>
                    </div>
                </div>
            </div>

            <div className="grid grid-cols-2 md:grid-cols-4 gap-3">
                <Kpi label="Baseline MAE PV" value={kpiValue(baselineEval, 'mae_pv')} hint="Last window" />
                <Kpi label="Baseline MAE Load" value={kpiValue(baselineEval, 'mae_load')} hint="Last window" />
                <Kpi label="AURORA MAE PV" value={kpiValue(auroraEval, 'mae_pv')} hint="Last window" />
                <Kpi label="AURORA MAE Load" value={kpiValue(auroraEval, 'mae_load')} hint="Last window" />
            </div>

            {baselineEval && auroraEval && (
                <Card className="p-3 md:p-4">
                    <div className="text-[11px] text-muted mb-1">MAE delta (AURORA vs baseline, last window)</div>
                    <div className="flex flex-wrap gap-4 text-[11px]">
                        <div>
                            <span className="text-muted mr-1">PV:</span>
                            {pvDelta != null ? (
                                <span className={pvDelta > 0 ? 'text-green-400' : pvDelta < 0 ? 'text-amber-300' : ''}>
                                    {pvDelta > 0 ? '↓ ' : pvDelta < 0 ? '↑ ' : ''}
                                    {Math.abs(pvDelta).toFixed(3)} kWh MAE
                                </span>
                            ) : (
                                <span className="text-muted">—</span>
                            )}
                        </div>
                        <div>
                            <span className="text-muted mr-1">Load:</span>
                            {loadDelta != null ? (
                                <span
                                    className={loadDelta > 0 ? 'text-green-400' : loadDelta < 0 ? 'text-amber-300' : ''}
                                >
                                    {loadDelta > 0 ? '↓ ' : loadDelta < 0 ? '↑ ' : ''}
                                    {Math.abs(loadDelta).toFixed(3)} kWh MAE
                                </span>
                            ) : (
                                <span className="text-muted">—</span>
                            )}
                        </div>
                    </div>
                </Card>
            )}

            {!auroraAvailable && (
                <div className="text-[11px] text-amber-300">
                    AURORA metrics are not available yet. Run an evaluation or keep the planner on baseline.
                </div>
            )}

            <ChartCard day="today" range="48h" showDayToggle={false} />

            {/* Probabilistic Forecast Charts */}
            {slots.some((s) => s.aurora_pv_p10 != null || s.aurora_load_p10 != null) && (
                <div className="grid grid-cols-1 lg:grid-cols-2 gap-4">
                    <Card className="p-4">
                        <ProbabilisticChart
                            title="PV Forecast (kWh) with Confidence Bands"
                            color="#22c55e"
                            slots={slots.map((s) => ({
                                time: s.slot_start,
                                p10: s.aurora_pv_p10 ?? null,
                                p50: s.aurora_pv ?? null,
                                p90: s.aurora_pv_p90 ?? null,
                                actual: s.pv_kwh,
                            }))}
                        />
                    </Card>
                    <Card className="p-4">
                        <ProbabilisticChart
                            title="Load Forecast (kWh) with Confidence Bands"
                            color="#f97316"
                            slots={slots.map((s) => ({
                                time: s.slot_start,
                                p10: s.aurora_load_p10 ?? null,
                                p50: s.aurora_load ?? null,
                                p90: s.aurora_load_p90 ?? null,
                                actual: s.load_kwh,
                            }))}
                        />
                    </Card>
                </div>
            )}

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
                            {slots.map((slot) => {
                                const t = new Date(slot.slot_start).toLocaleTimeString([], {
                                    hour: '2-digit',
                                    minute: '2-digit',
                                })
                                return (
                                    <tr key={slot.slot_start} className="border-b border-line/20">
                                        <td className="py-1 pr-3">{t}</td>
                                        <td className="py-1 pr-3 text-right">{slot.load_kwh?.toFixed(3) ?? '—'}</td>
                                        <td className="py-1 pr-3 text-right">
                                            {slot.baseline_load?.toFixed(3) ?? '—'}
                                        </td>
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
