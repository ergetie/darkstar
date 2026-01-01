import { useState, useEffect } from 'react'
import { Sparkles, RefreshCw, Zap, SunMedium } from 'lucide-react'
import { Api, type AnalystReport } from '../lib/api'
import Card from './Card'

export default function SmartAdvisor() {
    const [advice, setAdvice] = useState<string | null>(null)
    const [loading, setLoading] = useState(false)
    const [error, setError] = useState(false)
    const [llmEnabled, setLlmEnabled] = useState<boolean | null>(null)
    const [autoFetch, setAutoFetch] = useState<boolean>(true)
    const [analystReport, setAnalystReport] = useState<AnalystReport | null>(null)

    const fetchAdvice = async () => {
        if (!llmEnabled) return
        setLoading(true)
        setError(false)
        try {
            const res = await Api.getAdvice()
            if ((res as any).status === 'disabled') {
                setLlmEnabled(false)
                setAdvice(null)
            } else {
                setAdvice(res.advice ?? null)
            }
        } catch (e) {
            console.error(e)
            setError(true)
        } finally {
            setLoading(false)
        }
    }

    const fetchAnalystSummary = async () => {
        setLoading(true)
        setError(false)
        try {
            const res = await Api.analystRun()
            setAnalystReport(res)
        } catch (e) {
            console.error('Failed to fetch analyst summary:', e)
            setError(true)
        } finally {
            setLoading(false)
        }
    }

    useEffect(() => {
        // Load advisor settings (enable_llm + auto_fetch) from config
        Api.config()
            .then((cfg) => {
                const advisor = cfg.advisor || {}
                const enabled = advisor.enable_llm !== false
                const auto = advisor.auto_fetch !== false
                setLlmEnabled(enabled)
                setAutoFetch(auto)
                if (enabled && auto) {
                    fetchAdvice()
                }
                if (!enabled) {
                    fetchAnalystSummary()
                }
            })
            .catch((err) => {
                console.error('Failed to load advisor config:', err)
                setLlmEnabled(false)
            })
    }, [])

    const canRequest = !!llmEnabled && !loading

    const toggleAutoFetch = async () => {
        const next = !autoFetch
        setAutoFetch(next)
        try {
            await Api.configSave({ advisor: { auto_fetch: next } })
            if (next && llmEnabled && !advice) {
                fetchAdvice()
            }
        } catch (err) {
            console.error('Failed to update advisor auto_fetch setting:', err)
        }
    }

    return (
        <Card className="h-full p-4 md:p-5 flex flex-col">
            <div className="flex items-baseline justify-between mb-3">
                <div className="flex items-center gap-2 text-sm text-muted">
                    <Sparkles className="h-4 w-4 text-accent" />
                    <span>Aurora Advisor</span>
                </div>
                <div className="flex items-center gap-2">
                    {llmEnabled && (
                        <button
                            onClick={toggleAutoFetch}
                            className={`rounded-pill px-2 py-1 text-[10px] font-medium transition ${
                                autoFetch
                                    ? 'bg-accent text-canvas border border-accent'
                                    : 'bg-surface border border-line/60 text-muted hover:border-accent hover:text-accent'
                            }`}
                            title={
                                autoFetch
                                    ? 'Disable auto-fetch (advisor runs only on manual request)'
                                    : 'Enable auto-fetch when the plan changes'
                            }
                        >
                            ⏱
                        </button>
                    )}
                    {llmEnabled !== null && (
                        <button
                            onClick={fetchAdvice}
                            disabled={!canRequest}
                            className="text-[10px] text-muted hover:text-text transition-colors p-1 disabled:opacity-40"
                            title={llmEnabled ? 'Fetch latest advice' : 'Enable LLM advice in Settings'}
                        >
                            <RefreshCw className={`h-4 w-4 ${loading ? 'animate-spin' : ''}`} />
                        </button>
                    )}
                </div>
            </div>
            <div className="text-[11px] text-text leading-relaxed">
                {llmEnabled === false && (
                    <>
                        {loading && <span className="animate-pulse">Analyzing schedule (offline)…</span>}
                        {!loading && error && (
                            <span className="text-red-400">
                                Unable to analyze schedule. Check backend logs for details.
                            </span>
                        )}
                        {!loading && !error && analystReport && analystReport.recommendations && (
                            <div className="space-y-2">
                                {Object.entries(analystReport.recommendations)
                                    .slice(0, 3)
                                    .map(([key, value]) => {
                                        const rec: any = value ?? {}
                                        const label = rec.label || key
                                        const grid = rec.best_grid_window || {}
                                        const solar = rec.best_solar_window || {}
                                        const fmtTime = (iso?: string) =>
                                            iso && iso.length >= 16 ? iso.slice(11, 16) : '—'
                                        const gridText =
                                            grid.start && grid.end
                                                ? `${fmtTime(grid.start)}–${fmtTime(grid.end)} (${grid.avg_price?.toFixed?.(2) ?? '–'} SEK/kWh)`
                                                : null
                                        const solarText =
                                            solar.start && solar.end
                                                ? `${fmtTime(solar.start)}–${fmtTime(solar.end)} (${solar.avg_pv_surplus?.toFixed?.(2) ?? '–'} kW surplus)`
                                                : null
                                        return (
                                            <div key={key} className="flex flex-col gap-1">
                                                <div className="font-medium">{label}</div>
                                                <div className="flex flex-wrap gap-3 text-[10px] text-muted">
                                                    {gridText && (
                                                        <span className="inline-flex items-center gap-1">
                                                            <Zap className="h-3 w-3 text-accent" />
                                                            <span>Grid: {gridText}</span>
                                                        </span>
                                                    )}
                                                    {solarText && (
                                                        <span className="inline-flex items-center gap-1">
                                                            <SunMedium className="h-3 w-3 text-accent" />
                                                            <span>Solar: {solarText}</span>
                                                        </span>
                                                    )}
                                                </div>
                                            </div>
                                        )
                                    })}
                            </div>
                        )}
                        {!loading && !error && (!analystReport || !analystReport.recommendations) && (
                            <span className="text-muted">
                                No appliance recommendations available. Configure appliances in Settings to see
                                suggested run windows.
                            </span>
                        )}
                    </>
                )}
                {llmEnabled === true && (
                    <>
                        {loading && <span className="animate-pulse">Analyzing schedule...</span>}
                        {!loading && error && (
                            <span className="text-red-400">
                                Unable to fetch advice. Check AI settings or try again.
                            </span>
                        )}
                        {!loading && !error && !advice && !autoFetch && (
                            <span className="text-muted">Click the refresh icon to analyze your current schedule.</span>
                        )}
                        {!loading && !error && advice && <span>{advice}</span>}
                    </>
                )}
                {llmEnabled === null && !loading && !error && (
                    <span className="text-muted">Loading advisor settings…</span>
                )}
            </div>
        </Card>
    )
}
