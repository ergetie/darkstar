import { useEffect, useMemo, useState } from 'react'
import { Bot, Sparkles, Zap, SunMedium, Activity, Brain } from 'lucide-react'
import Card from '../components/Card'
import DecompositionChart from '../components/DecompositionChart'
import ContextRadar from '../components/ContextRadar'
import ActivityLog from '../components/ActivityLog'
import KPIStrip from '../components/KPIStrip'
import ProbabilisticChart from '../components/ProbabilisticChart'
import { Line, Bar } from 'react-chartjs-2'
import { Api } from '../lib/api'
import type { AuroraDashboardResponse, SchedulerStatusResponse, AuroraPerformanceData } from '../lib/api'

// Import ChartJS components for the inline charts
import {
    Chart as ChartJS,
    CategoryScale,
    LinearScale,
    PointElement,
    LineElement,
    BarElement,
    Title,
    Tooltip,
    Legend,
    TimeScale,
} from 'chart.js'
import 'chartjs-adapter-moment'

ChartJS.register(CategoryScale, LinearScale, PointElement, LineElement, BarElement, Title, Tooltip, Legend, TimeScale)

export default function Aurora() {
    const [dashboard, setDashboard] = useState<AuroraDashboardResponse | null>(null)
    const [schedulerStatus, setSchedulerStatus] = useState<SchedulerStatusResponse | null>(null)
    const [briefing, setBriefing] = useState<string>('')
    const [loading, setLoading] = useState(false)
    const [briefingLoading, setBriefingLoading] = useState(false)
    const [riskAppetite, setRiskAppetite] = useState<number>(3)
    const [replanning, setReplanning] = useState(false)
    const [chartMode, setChartMode] = useState<'load' | 'pv'>('load')
    const [viewMode, setViewMode] = useState<'forecast' | 'soc'>('forecast')
    const [autoTuneEnabled, setAutoTuneEnabled] = useState<boolean>(false)
    const [togglingAutoTune, setTogglingAutoTune] = useState(false)
    const [reflexEnabled, setReflexEnabled] = useState<boolean>(false)
    const [togglingReflex, setTogglingReflex] = useState(false)
    const [probabilisticMode, setProbabilisticMode] = useState<boolean>(false)
    const [togglingProbabilistic, setTogglingProbabilistic] = useState(false)

    // Performance Data State
    const [perfData, setPerfData] = useState<AuroraPerformanceData | null>(null)

    const fetchDashboard = async () => {
        setLoading(true)
        try {
            const res = await Api.aurora.dashboard()
            setDashboard(res)
            const ra = res.state?.risk_profile?.risk_appetite
            if (typeof ra === 'number') {
                setRiskAppetite(ra)
            }
            setAutoTuneEnabled(!!res.state?.auto_tune_enabled)
            setReflexEnabled(!!res.state?.reflex_enabled)
            setProbabilisticMode(res.state?.risk_profile?.mode === 'probabilistic')
        } catch (err) {
            console.error('Failed to load Aurora dashboard:', err)
        } finally {
            setLoading(false)
        }
    }

    useEffect(() => {
        fetchDashboard()

        const fetchSchedulerStatus = async () => {
            try {
                const res = await Api.schedulerStatus()
                setSchedulerStatus(res)
            } catch (err) {
                console.error('Failed to load scheduler status:', err)
            }
        }
        fetchSchedulerStatus()
    }, [])

    useEffect(() => {
        // Fetch Performance Data (merged from Performance.tsx)
        const fetchPerf = async () => {
            try {
                const data = await Api.performanceData(7)
                setPerfData(data)
            } catch (err) {
                console.error('Failed to load performance data:', err)
            }
        }
        fetchPerf()
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
        setRiskAppetite(value)
        try {
            await Api.configSave({ s_index: { risk_appetite: value } })
        } catch (err) {
            console.error('Failed to save risk level (risk_appetite):', err)
        }
    }

    const handleAutoTuneToggle = async () => {
        const newValue = !autoTuneEnabled
        setAutoTuneEnabled(newValue)
        setTogglingAutoTune(true)
        try {
            await Api.configSave({ learning: { auto_tune_enabled: newValue } })
        } catch (err) {
            console.error('Failed to toggle auto-tune:', err)
            setAutoTuneEnabled(!newValue) // Revert on error
        } finally {
            setTogglingAutoTune(false)
        }
    }

    const handleReflexToggle = async () => {
        const newValue = !reflexEnabled
        setReflexEnabled(newValue)
        setTogglingReflex(true)
        try {
            await Api.aurora.toggleReflex(newValue)
        } catch (err) {
            console.error('Failed to toggle reflex:', err)
            setReflexEnabled(!newValue) // Revert on error
        } finally {
            setTogglingReflex(false)
        }
    }

    const handleProbabilisticToggle = async () => {
        const newValue = !probabilisticMode
        setProbabilisticMode(newValue)
        setTogglingProbabilistic(true)
        try {
            await Api.configSave({ s_index: { mode: newValue ? 'probabilistic' : 'dynamic' } })
        } catch (err) {
            console.error('Failed to toggle probabilistic mode:', err)
            setProbabilisticMode(!newValue)
        } finally {
            setTogglingProbabilistic(false)
        }
    }

    const graduationLabel = dashboard?.identity?.graduation?.label ?? 'infant'

    const volatility = dashboard?.state?.weather_volatility
    const overallVol = volatility?.overall ?? 0

    const waveColor = overallVol < 0.3 ? 'bg-emerald-400/90' : overallVol < 0.7 ? 'bg-sky-400/90' : 'bg-amber-400/90'

    const heroGradient =
        overallVol < 0.3
            ? 'from-emerald-900/60 via-surface to-surface'
            : overallVol < 0.7
                ? 'from-sky-900/60 via-surface to-surface'
                : 'from-amber-900/60 via-surface to-surface'

    const horizonSlots = dashboard?.horizon?.slots ?? []
    const originalHorizonEnd = dashboard?.horizon?.end ?? new Date().toISOString()

    // Extract Strategy History
    const strategyEvents = dashboard?.history?.strategy_events ?? []

    // Performance Charts Data
    const socChartData = useMemo(() => {
        if (!perfData || !perfData.soc_series || perfData.soc_series.length === 0) return null
        return {
            datasets: [
                {
                    label: 'Planned',
                    data: perfData.soc_series.map((d) => ({ x: d.time, y: d.planned })),
                    borderColor: '#94a3b8',
                    borderDash: [5, 5],
                    borderWidth: 1.5,
                    pointRadius: 0,
                    tension: 0.4,
                },
                {
                    label: 'Actual',
                    data: perfData.soc_series.map((d) => ({ x: d.time, y: d.actual })),
                    borderColor: '#60a5fa',
                    backgroundColor: 'rgba(96, 165, 250, 0.1)',
                    borderWidth: 1.5,
                    pointRadius: 0,
                    fill: true,
                    tension: 0.4,
                },
            ],
        }
    }, [perfData])

    const costChartData = useMemo(() => {
        if (!perfData || !perfData.cost_series || perfData.cost_series.length === 0) return null
        return {
            labels: perfData.cost_series.map((d: { date: string; planned: number; realized: number }) =>
                d.date.slice(5),
            ), // MM-DD
            datasets: [
                {
                    label: 'Plan',
                    data: perfData.cost_series.map(
                        (d: { date: string; planned: number; realized: number }) => d.planned,
                    ),
                    backgroundColor: '#94a3b8',
                    borderRadius: 2,
                },
                {
                    label: 'Real',
                    data: perfData.cost_series.map(
                        (d: { date: string; planned: number; realized: number }) => d.realized,
                    ),
                    backgroundColor: perfData.cost_series.map(
                        (d: { date: string; planned: number; realized: number }) =>
                            d.realized <= d.planned ? '#34d399' : '#f87171',
                    ),
                    borderRadius: 2,
                },
            ],
        }
    }, [perfData])

    // For UI display, but currently handled via useMemo persona

    return (
        <div className="px-4 pt-16 pb-10 lg:px-8 lg:pt-10 space-y-6">
            {/* Header */}
            <div className="flex flex-col lg:flex-row lg:items-center lg:justify-between gap-3">
                <div>
                    <h1 className="text-lg font-medium text-text flex items-center gap-2">
                        Aurora Command Center
                        <span className="px-2 py-0.5 rounded-full bg-surface2 border border-line/50 text-[10px] text-muted uppercase tracking-wider">
                            {graduationLabel}
                        </span>
                    </h1>
                    <p className="text-[11px] text-muted">
                        The Mastermind. Observing context, managing risk, and learning from reality.
                    </p>
                </div>
            </div>

            {/* 1. THE BRIDGE (Top Section) */}
            <div className="grid gap-4 lg:grid-cols-12">
                {/* Identity & Status Card */}
                <Card className={`lg:col-span-6 p-4 md:p-5 bg-gradient-to-br ${heroGradient} relative overflow-hidden`}>
                    <div className="relative z-10 flex flex-col md:flex-row gap-6">
                        {/* Avatar & Pulse */}
                        <div className="flex items-center gap-4">
                            <div className="relative flex items-center justify-center">
                                <div
                                    className={`absolute h-16 w-16 rounded-full ${waveColor} opacity-30 animate-pulse`}
                                />
                                <div className="relative flex items-center justify-center w-14 h-14 rounded-full bg-surface/90 border border-line/80 shadow-float ring-2 ring-accent/20">
                                    <Bot className="h-8 w-8 text-accent drop-shadow-[0_0_12px_rgba(56,189,248,0.75)]" />
                                </div>
                            </div>
                            <div>
                                <div className="text-xs font-semibold text-text uppercase tracking-wide">Status</div>
                                <div className="text-lg font-medium text-text">
                                    {overallVol > 0.6
                                        ? 'Defensive Mode'
                                        : overallVol > 0.3
                                            ? 'Cautious Mode'
                                            : 'Optimal Mode'}
                                </div>
                                <div className="text-[11px] text-muted flex items-center gap-2">
                                    <span
                                        className={`h-1.5 w-1.5 rounded-full ${overallVol > 0.6 ? 'bg-amber-400' : 'bg-emerald-400'}`}
                                    />
                                    {overallVol > 0.6 ? 'High Volatility Detected' : 'Conditions Stable'}
                                </div>
                            </div>
                        </div>

                        {/* Briefing */}
                        <div className="flex-1 bg-surface/40 rounded-xl p-3 border border-white/5 backdrop-blur-sm">
                            <div className="flex items-center justify-between mb-2">
                                <div className="flex items-center gap-2 text-[11px] text-text font-medium">
                                    <Sparkles className="h-3 w-3 text-accent" />
                                    Daily Briefing
                                </div>
                                <button
                                    onClick={handleBriefing}
                                    disabled={!dashboard || briefingLoading}
                                    className="text-[10px] text-muted hover:text-accent disabled:opacity-50 transition-colors"
                                >
                                    {briefingLoading ? 'Thinking...' : 'Refresh'}
                                </button>
                            </div>
                            <div className="text-[11px] leading-relaxed text-muted/90 font-mono">
                                {briefing || 'Aurora is analyzing current market and weather conditions...'}
                            </div>
                        </div>
                    </div>
                </Card>

                {/* Risk Dial (Control) */}
                <Card className="lg:col-span-3 p-4 md:p-5 flex flex-col justify-center">
                    <div className="flex justify-between items-center mb-4">
                        <span className="text-[10px] uppercase font-bold text-muted tracking-wider">Risk Appetite</span>
                        <div className="flex items-center gap-2">
                            {/* Calc/Applied Indicators */}
                            {dashboard?.state?.risk_profile?.raw_factor != null &&
                                (dashboard.state.risk_profile.raw_factor ?? 0) > 0 && (
                                    <span className="text-[9px] text-muted/60" title="Calculated based on risk">
                                        Calc: {(dashboard.state.risk_profile.raw_factor ?? 0).toFixed(2)}
                                    </span>
                                )}
                            <span className="text-[9px] text-muted" title="Proected factor for next run">
                                Applied: {(dashboard?.state?.risk_profile?.current_factor ?? 1.0).toFixed(2)}
                            </span>
                        </div>
                    </div>

                    <div className="flex flex-col gap-3">
                        {/* 5-Step Segmented Control */}
                        <div className="grid grid-cols-5 gap-1 p-1 bg-surface2/50 rounded-lg border border-line/30">
                            {[1, 2, 3, 4, 5].map((step) => {
                                const isActive = riskAppetite === step
                                // Determine color based on risk level
                                let activeClass = 'bg-surface border-line text-text shadow-sm'
                                if (isActive) {
                                    if (step === 1)
                                        activeClass =
                                            'bg-emerald-500/20 border-emerald-500/50 text-emerald-100 shadow-[0_0_10px_rgba(16,185,129,0.2)]'
                                    else if (step === 2) activeClass = 'bg-teal-500/20 border-teal-500/50 text-teal-100'
                                    else if (step === 3) activeClass = 'bg-blue-500/20 border-blue-500/50 text-blue-100'
                                    else if (step === 4)
                                        activeClass = 'bg-amber-500/20 border-amber-500/50 text-amber-100'
                                    else if (step === 5)
                                        activeClass =
                                            'bg-red-500/20 border-red-500/50 text-red-100 shadow-[0_0_10px_rgba(239,68,68,0.2)]'
                                }

                                return (
                                    <button
                                        key={step}
                                        onClick={() => handleRiskChange(step)}
                                        className={`
                       relative flex items-center justify-center h-9 rounded-md text-[10px] font-medium transition-all duration-200
                       border border-transparent
                       ${isActive ? activeClass : 'text-muted hover:bg-surface/50 hover:text-text'}
                     `}
                                    >
                                        {step}
                                    </button>
                                )
                            })}
                        </div>

                        {/* Descriptions */}
                        <div className="text-center h-8 flex flex-col justify-center">
                            <span
                                className={`text-[11px] font-medium transition-colors duration-300 ${riskAppetite === 1
                                    ? 'text-emerald-400'
                                    : riskAppetite === 2
                                        ? 'text-teal-400'
                                        : riskAppetite === 3
                                            ? 'text-blue-400'
                                            : riskAppetite === 4
                                                ? 'text-amber-400'
                                                : 'text-red-400'
                                    }`}
                            >
                                {
                                    {
                                        1: 'Safety First',
                                        2: 'Conservative',
                                        3: 'Neutral (Balanced)',
                                        4: 'Aggressive',
                                        5: 'Gambler',
                                    }[riskAppetite]
                                }
                            </span>
                            <span className="text-[9px] text-muted/70">
                                {
                                    {
                                        1: 'Covers Worst Case (p90)',
                                        2: 'Covers High Load (p75)',
                                        3: 'Trusts the Mean (p50)',
                                        4: 'Expects Lower Load',
                                        5: 'Bets on Sun/Empty',
                                    }[riskAppetite]
                                }
                            </span>
                        </div>
                    </div>

                    {/* Re-Plan Trigger */}
                    <div className="mt-4 pt-3 border-t border-line/30 flex flex-col items-center gap-2">
                        <button
                            onClick={async () => {
                                setReplanning(true)
                                try {
                                    // Save first (already done by setRisk logic, but ensuring)
                                    await handleRiskChange(riskAppetite)
                                    // Trigger Planner
                                    await Api.runPlanner()
                                    // Refresh Dashboard
                                    await fetchDashboard()
                                } finally {
                                    setReplanning(false)
                                }
                            }}
                            disabled={replanning}
                            className={`flex items-center gap-2 px-3 py-1.5 rounded-full bg-surface hover:bg-surface2 border border-line/50 text-[10px] transition-colors ${replanning ? 'opacity-70 cursor-not-allowed text-muted' : 'text-muted hover:text-text'
                                }`}
                            title="Run Strategy Engine to update forecast based on new risk"
                        >
                            {replanning ? (
                                <>
                                    <div className="h-3 w-3 border-2 border-accent/30 border-t-accent rounded-full animate-spin" />
                                    <span>Re-planning...</span>
                                </>
                            ) : (
                                <>
                                    <Zap className="h-3 w-3 text-accent" />
                                    <span>Apply & Re-Plan</span>
                                </>
                            )}
                        </button>
                        {replanning && (
                            <span className="text-[9px] text-muted/70 animate-pulse">
                                Regenerating schedule with new risk level...
                            </span>
                        )}
                    </div>
                </Card>

                {/* Controls Card (Auto-Tuner) */}
                <Card className="lg:col-span-3 p-4 md:p-5 flex flex-col">
                    <div className="flex items-center gap-2 mb-4">
                        <Zap className="h-4 w-4 text-accent" />
                        <span className="text-xs font-medium text-text">Controls</span>
                    </div>

                    <div className="flex items-center justify-between p-2 rounded-lg bg-surface2/50 border border-line/50">
                        <div className="flex flex-col">
                            <span className="text-[11px] font-medium text-text">Auto-Tuner</span>
                            <span className="text-[9px] text-muted">Allow Aurora to act</span>
                        </div>
                        <button
                            onClick={handleAutoTuneToggle}
                            disabled={togglingAutoTune}
                            className={`relative inline-flex h-5 w-9 items-center rounded-full transition-colors focus:outline-none focus:ring-2 focus:ring-accent focus:ring-offset-2 focus:ring-offset-surface ${autoTuneEnabled ? 'bg-accent' : 'bg-surface2'
                                }`}
                        >
                            <span
                                className={`${autoTuneEnabled ? 'translate-x-5' : 'translate-x-1'
                                    } inline-block h-3 w-3 transform rounded-full bg-white transition-transform`}
                            />
                        </button>
                    </div>

                    <div className="flex items-center justify-between p-2 rounded-lg bg-surface2/50 border border-line/50 mt-2">
                        <div className="flex flex-col">
                            <span className="text-[11px] font-medium text-text">Aurora Reflex</span>
                            <span className="text-[9px] text-muted">Long-term auto-tuning</span>
                        </div>
                        <button
                            onClick={handleReflexToggle}
                            disabled={togglingReflex}
                            className={`relative inline-flex h-5 w-9 items-center rounded-full transition-colors focus:outline-none focus:ring-2 focus:ring-accent focus:ring-offset-2 focus:ring-offset-surface ${reflexEnabled ? 'bg-accent' : 'bg-surface2'
                                }`}
                        >
                            <span
                                className={`${reflexEnabled ? 'translate-x-5' : 'translate-x-1'
                                    } inline-block h-3 w-3 transform rounded-full bg-white transition-transform`}
                            />
                        </button>
                    </div>

                    <div className="flex items-center justify-between p-2 rounded-lg bg-surface2/50 border border-line/50 mt-2">
                        <div className="flex flex-col">
                            <span className="text-[11px] font-medium text-text">Probabilistic</span>
                            <span className="text-[9px] text-muted">Use p10/p90 confidence bands</span>
                        </div>
                        <button
                            onClick={handleProbabilisticToggle}
                            disabled={togglingProbabilistic}
                            className={`relative inline-flex h-5 w-9 items-center rounded-full transition-colors focus:outline-none focus:ring-2 focus:ring-accent focus:ring-offset-2 focus:ring-offset-surface ${probabilisticMode ? 'bg-accent' : 'bg-surface2'
                                }`}
                        >
                            <span
                                className={`${probabilisticMode ? 'translate-x-5' : 'translate-x-1'
                                    } inline-block h-3 w-3 transform rounded-full bg-white transition-transform`}
                            />
                        </button>
                    </div>

                    <div className="mt-auto pt-2 text-center text-[10px] text-muted">More controls coming soon.</div>
                </Card>
            </div>

            {/* 1.5 KPI STRIP */}
            <KPIStrip metrics={dashboard?.metrics} perfData={perfData} />

            {/* 2. THE DASHBOARD (Middle Section) */}
            <div className="grid gap-4 lg:grid-cols-12 lg:h-[450px]">
                {/* Context Radar */}
                <Card className="lg:col-span-4 p-4 flex flex-col h-full min-h-0 overflow-hidden">
                    <div className="mb-4 flex items-center justify-between shrink-0">
                        <div className="flex items-center gap-2">
                            <Activity className="h-4 w-4 text-accent" />
                            <span className="text-xs font-medium text-text">Context Radar</span>
                        </div>
                    </div>
                    <div className="flex-1 min-h-0 relative">
                        <ContextRadar
                            weatherVolatility={{
                                cloud: volatility?.cloud_volatility ?? 0,
                                temp: volatility?.temp_volatility ?? 0,
                                overall: overallVol,
                            }}
                            riskFactor={riskAppetite ?? 3}
                            forecastAccuracy={
                                dashboard?.metrics?.mae_pv_aurora != null
                                    ? Math.max(0, 100 - dashboard.metrics.mae_pv_aurora * 20)
                                    : 85
                            }
                            priceSpread={dashboard?.metrics?.max_price_spread}
                            forecastBias={dashboard?.metrics?.forecast_bias}
                        />
                    </div>
                </Card>

                {/* Activity Log */}
                <Card className="lg:col-span-4 p-4 flex flex-col h-full min-h-0 overflow-hidden">
                    <div className="mb-4 flex items-center justify-between shrink-0">
                        <div className="flex items-center gap-2">
                            <Brain className="h-4 w-4 text-accent" />
                            <span className="text-xs font-medium text-text">Activity Log</span>
                        </div>
                        <div className="flex flex-col items-end">
                            <span className="text-[10px] text-muted">{strategyEvents.length} events</span>
                            {schedulerStatus?.ml_training_last_run_at && (
                                <span className="text-[9px] text-muted/70" title="Last ML Training Run">
                                    ML Train:{' '}
                                    {new Date(schedulerStatus.ml_training_last_run_at).toLocaleString('sv-SE', {
                                        month: '2-digit',
                                        day: '2-digit',
                                        hour: '2-digit',
                                        minute: '2-digit',
                                    })}
                                </span>
                            )}
                        </div>
                    </div>
                    <div className="flex-1 min-h-0 overflow-y-auto pr-2 custom-scrollbar">
                        <ActivityLog events={strategyEvents} />
                    </div>
                </Card>

                {/* SoC Tunnel (Moved from bottom) */}
                {/* This card is being removed and its logic merged into Forecast View */}
                {/*
        <Card className="lg:col-span-4 p-4 md:p-5 flex flex-col h-full min-h-0 overflow-hidden">
          <div className="mb-4 shrink-0">
            <div className="text-xs font-medium text-text">SoC Tunnel</div>
            <div className="text-[11px] text-muted">Plan vs Reality</div>
          </div>
          <div className="flex-1 min-h-0">
            {socChartData && (
              <Line
                data={socChartData}
                options={{
                  responsive: true,
                  maintainAspectRatio: false,
                  interaction: { mode: 'index', intersect: false },
                  scales: {
                    x: {
                      type: 'time',
                      time: { unit: 'hour', displayFormats: { hour: 'HH:mm' } },
                      grid: { color: '#334155', display: false },
                      ticks: { color: '#94a3b8', maxTicksLimit: 6 }
                    },
                    y: {
                      min: 0, max: 100,
                      grid: { color: '#334155' },
                      ticks: { color: '#94a3b8', display: false }
                    }
                  },
                  plugins: { legend: { display: false } }
                }}
              />
            )}
          </div>
        </Card>
        */}

                {/* Cost Reality (Moved here) */}
                <Card className="lg:col-span-4 p-4 md:p-5 flex flex-col h-full min-h-0 overflow-hidden">
                    <div className="mb-4 shrink-0">
                        <div className="text-xs font-medium text-text">Cost Reality</div>
                        <div className="text-[11px] text-muted">Daily financial outcome</div>
                    </div>
                    <div className="flex-1 min-h-0">
                        {costChartData && (
                            <Bar
                                data={costChartData}
                                options={{
                                    responsive: true,
                                    maintainAspectRatio: false,
                                    scales: {
                                        x: {
                                            grid: { display: false },
                                            ticks: { color: '#94a3b8', font: { size: 10 } },
                                        },
                                        y: { grid: { color: '#334155' }, ticks: { color: '#94a3b8' } },
                                    },
                                    plugins: { legend: { labels: { color: '#e2e8f0', font: { size: 10 } } } },
                                }}
                            />
                        )}
                    </div>
                </Card>
            </div>

            {/* 3. THE MIRROR (Bottom Section) */}
            <div className="grid gap-4 lg:grid-cols-12">
                {/* Forecast View / SoC Tunnel (Merged with toggle) */}
                <Card className="lg:col-span-12 p-4 flex flex-col h-[350px] overflow-hidden">
                    <div className="flex items-center justify-between mb-3 shrink-0">
                        <div>
                            <div className="text-xs font-medium text-text">
                                {viewMode === 'forecast' ? 'Forecast Horizon (48h)' : 'SoC Tunnel'}
                            </div>
                            <div className="text-[11px] text-muted">
                                {viewMode === 'forecast'
                                    ? probabilisticMode
                                        ? `Probabilistic View (${chartMode.toUpperCase()})`
                                        : `Decomposition View (${chartMode.toUpperCase()})`
                                    : 'Plan vs Reality'}
                                {viewMode === 'forecast' && (
                                    <>
                                        {' • '}
                                        {new Date().toISOString().slice(0, 10)} -{' '}
                                        {new Date(originalHorizonEnd).toISOString().slice(0, 10)}
                                    </>
                                )}
                            </div>
                        </div>

                        <div className="flex items-center gap-2">
                            {/* View Toggle */}
                            <div className="inline-flex items-center gap-1 rounded-full border border-line/70 bg-surface2 px-1 py-0.5 text-[11px] mr-2">
                                <button
                                    className={`px-3 py-0.5 rounded-full ${viewMode === 'forecast' ? 'bg-accent text-[#0F1216]' : 'text-muted'}`}
                                    onClick={() => setViewMode('forecast')}
                                >
                                    Forecast
                                </button>
                                <button
                                    className={`px-3 py-0.5 rounded-full ${viewMode === 'soc' ? 'bg-accent text-[#0F1216]' : 'text-muted'}`}
                                    onClick={() => setViewMode('soc')}
                                >
                                    SoC
                                </button>
                            </div>

                            {/* Forecast Mode Toggles (Only visible in forecast view) */}
                            {viewMode === 'forecast' && (
                                <div className="inline-flex items-center gap-1 rounded-full border border-line/70 bg-surface2 px-1 py-0.5 text-[11px]">
                                    <button
                                        type="button"
                                        className={`px-2 py-0.5 rounded-full ${chartMode === 'load' ? 'bg-accent text-[#0F1216]' : 'text-muted'}`}
                                        onClick={() => setChartMode('load')}
                                    >
                                        <Zap className="h-3 w-3" />
                                    </button>
                                    <button
                                        type="button"
                                        className={`px-2 py-0.5 rounded-full ${chartMode === 'pv' ? 'bg-accent text-[#0F1216]' : 'text-muted'}`}
                                        onClick={() => setChartMode('pv')}
                                    >
                                        <SunMedium className="h-3 w-3" />
                                    </button>
                                </div>
                            )}
                        </div>
                    </div>

                    <div className="flex-1 min-h-0">
                        {loading ? (
                            <div className="text-[11px] text-muted">Loading...</div>
                        ) : viewMode === 'soc' ? (
                            // SoC Chart
                            <div className="h-full w-full">
                                {socChartData && (
                                    <Line
                                        data={socChartData}
                                        options={{
                                            responsive: true,
                                            maintainAspectRatio: false,
                                            interaction: { mode: 'index', intersect: false },
                                            scales: {
                                                x: {
                                                    type: 'time',
                                                    time: { unit: 'hour', displayFormats: { hour: 'HH:mm' } },
                                                    grid: { color: '#334155', display: false },
                                                    ticks: { color: '#94a3b8', maxTicksLimit: 6 },
                                                },
                                                y: {
                                                    min: 0,
                                                    max: 100,
                                                    grid: { color: '#334155' },
                                                    ticks: { color: '#94a3b8', display: false },
                                                },
                                            },
                                            plugins: { legend: { display: false } },
                                        }}
                                    />
                                )}
                            </div>
                        ) : probabilisticMode ? (
                            // Probabilistic Forecast Chart
                            <div className="h-full w-full">
                                <ProbabilisticChart
                                    title=""
                                    color={chartMode === 'load' ? '#f97316' : '#22c55e'}
                                    slots={(() => {
                                        const histData =
                                            dashboard?.horizon?.history_series?.[
                                            chartMode === 'load' ? 'load' : 'pv'
                                            ] || []
                                        const futureData = horizonSlots.map((s) => {
                                            if (chartMode === 'load') {
                                                return {
                                                    time: s.slot_start,
                                                    p10: s.probabilistic?.load_p10 ?? null,
                                                    p50: s.final.load_kwh,
                                                    p90: s.probabilistic?.load_p90 ?? null,
                                                    actual: null as number | null,
                                                }
                                            } else {
                                                return {
                                                    time: s.slot_start,
                                                    p10: s.probabilistic?.pv_p10 ?? null,
                                                    p50: s.final.pv_kwh,
                                                    p90: s.probabilistic?.pv_p90 ?? null,
                                                    actual: null as number | null,
                                                }
                                            }
                                        })

                                        type ProbabilisticSlot = {
                                            time: string
                                            p10: number | null
                                            p50: number | null
                                            p90: number | null
                                            actual?: number | null
                                        }

                                        // 1. Create a map by timestamp to merge overlaps
                                        const merged = new Map<string, ProbabilisticSlot>()

                                        // 2. Add History (Actuals + Forecasts)
                                        histData.forEach((h) => {
                                            merged.set(h.slot_start, {
                                                time: h.slot_start,
                                                p10: h.p10 ?? null,
                                                p50: h.forecast ?? null,
                                                p90: h.p90 ?? null,
                                                actual: h.actual,
                                            })
                                        })

                                        // 3. Add/Merge Future (Forecast)
                                        futureData.forEach((f) => {
                                            const existing = merged.get(f.time)
                                            if (existing) {
                                                // Merge: Keep actual, add forecast
                                                merged.set(f.time, { ...existing, p10: f.p10, p50: f.p50, p90: f.p90 })
                                            } else {
                                                merged.set(f.time, f)
                                            }
                                        })

                                        // 4. Sort and Slice (-24h to +24h)
                                        const now = new Date().getTime()
                                        const H24 = 24 * 60 * 60 * 1000

                                        return Array.from(merged.values())
                                            .sort((a, b) => new Date(a.time).getTime() - new Date(b.time).getTime())
                                            .filter((s) => {
                                                const t = new Date(s.time).getTime()
                                                return t >= now - H24 && t <= now + H24
                                            })
                                    })()}
                                />
                            </div>
                        ) : (
                            // Decomposition Chart
                            <DecompositionChart slots={horizonSlots} mode={chartMode} />
                        )}
                    </div>
                </Card>
            </div>
        </div>
    )
}
