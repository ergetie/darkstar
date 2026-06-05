import { useEffect, useMemo, useState } from 'react'
import {
    Bot,
    Zap,
    SunMedium,
    Activity,
    Brain,
    Cloud,
    Thermometer,
    TrendingUp,
    Target,
    BarChart3,
    AlertCircle,
    DollarSign,
} from 'lucide-react'
import Card from '../components/Card'
import DecompositionChart from '../components/DecompositionChart'
import ActivityLog from '../components/ActivityLog'
import KPIStrip from '../components/KPIStrip'
import ProbabilisticChart from '../components/ProbabilisticChart'
import SystemHealthCard from '../components/SystemHealthCard'
import ModelTrainingCard from '../components/aurora/ModelTrainingCard'
import { Bar } from 'react-chartjs-2'
import { Api } from '../lib/api'
import { getAuroraForecastTogglePatch, getPvForecastSourceDisplay } from './auroraDisplay'
import type {
    AuroraDashboardResponse,
    SchedulerStatusResponse,
    AuroraPerformanceData,
    PriceForecastSlot,
    PriceAccuracyResponse,
    LearningStatusResponse,
} from '../lib/api'

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
    const [loading, setLoading] = useState(false)
    const [riskAppetite, setRiskAppetite] = useState<number>(3)
    const [chartMode, setChartMode] = useState<'load' | 'pv' | 'price'>('pv')
    const [reflexEnabled, setReflexEnabled] = useState<boolean>(false)
    const [togglingReflex, setTogglingReflex] = useState(false)
    const [probabilisticMode, setProbabilisticMode] = useState<boolean>(false)
    const [togglingProbabilistic, setTogglingProbabilistic] = useState(false)
    const [priceForecastEnabled, setPriceForecastEnabled] = useState<boolean>(false)
    const [priceForecastSlots, setPriceForecastSlots] = useState<PriceForecastSlot[]>([])
    const [priceForecastLoading, setPriceForecastLoading] = useState(false)
    const [priceAccuracy, setPriceAccuracy] = useState<PriceAccuracyResponse | undefined>(undefined)
    const [learningStatus, setLearningStatus] = useState<LearningStatusResponse | null>(null)
    const [auroraLoadEnabled, setAuroraLoadEnabled] = useState(true)
    const [auroraPvEnabled, setAuroraPvEnabled] = useState(true)
    const [togglingForecastDomain, setTogglingForecastDomain] = useState<'load' | 'pv' | null>(null)

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

        const fetchPriceForecastStatus = async () => {
            try {
                const res = await Api.priceForecast.priceForecastStatus()
                setPriceForecastEnabled(res.enabled)
            } catch {
                setPriceForecastEnabled(false)
            }
        }
        fetchPriceForecastStatus()

        const fetchPriceAccuracy = async () => {
            try {
                const res = await Api.priceForecast.accuracy()
                setPriceAccuracy(res)
            } catch (err) {
                console.error('Failed to load price accuracy:', err)
            }
        }
        fetchPriceAccuracy()

        const fetchLearningStatus = async () => {
            try {
                const res = await Api.learningStatus()
                setLearningStatus(res)
            } catch (err) {
                console.error('Failed to load learning status:', err)
            }
        }
        fetchLearningStatus()

        const fetchConfig = async () => {
            try {
                const res = await Api.config()
                setAuroraLoadEnabled(res.forecasting?.aurora_load_enabled ?? true)
                setAuroraPvEnabled(res.forecasting?.aurora_pv_enabled ?? true)
            } catch (err) {
                console.error('Failed to load forecast controls:', err)
            }
        }
        fetchConfig()
    }, [])

    useEffect(() => {
        if (chartMode === 'price' && priceForecastSlots.length === 0) {
            setPriceForecastLoading(true)
            Api.priceForecast
                .forecasts(true)
                .then((res) => setPriceForecastSlots(res.forecasts ?? []))
                .catch((err) => console.error('Failed to load price forecasts:', err))
                .finally(() => setPriceForecastLoading(false))
        }
    }, [chartMode, priceForecastSlots.length])

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

    const handleForecastDomainToggle = async (domain: 'load' | 'pv') => {
        const currentValue = domain === 'load' ? auroraLoadEnabled : auroraPvEnabled
        const newValue = !currentValue
        if (domain === 'load') {
            setAuroraLoadEnabled(newValue)
        } else {
            setAuroraPvEnabled(newValue)
        }
        setTogglingForecastDomain(domain)
        try {
            await Api.configSave(getAuroraForecastTogglePatch(domain, newValue))
            window.dispatchEvent(new Event('config-changed'))
        } catch (err) {
            console.error(`Failed to toggle Aurora ${domain} forecasting:`, err)
            if (domain === 'load') {
                setAuroraLoadEnabled(currentValue)
            } else {
                setAuroraPvEnabled(currentValue)
            }
        } finally {
            setTogglingForecastDomain(null)
        }
    }

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
    const pvPersonalization = learningStatus?.pv_personalization
    const pvSourceDisplay = getPvForecastSourceDisplay(pvPersonalization, auroraPvEnabled)

    // Extract Strategy History
    const strategyEvents = dashboard?.history?.strategy_events ?? []

    // Performance Charts Data
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
                    <h1 className="text-lg font-medium text-text">Aurora Command Center</h1>
                    <p className="text-[11px] text-muted">
                        The Mastermind. Observing context, managing risk, and learning from reality.
                    </p>
                </div>
            </div>

            {/* 1. THE BRIDGE (Top Section) */}
            <div className="grid gap-4 lg:grid-cols-12">
                {/* Identity & Status Card */}
                <Card className={`lg:col-span-3 p-4 md:p-5 bg-gradient-to-br ${heroGradient} relative overflow-hidden`}>
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
                    </div>
                </Card>

                {/* System Health Card */}
                <div className="lg:col-span-3 h-full">
                    <SystemHealthCard />
                </div>

                {/* Training Status Card */}
                <div className="lg:col-span-3 h-full">
                    <ModelTrainingCard />
                </div>

                {/* Controls Card */}
                <Card className="lg:col-span-3 p-4 md:p-5 flex flex-col">
                    <div className="flex items-center gap-2 mb-4">
                        <Zap className="h-4 w-4 text-accent" />
                        <span className="text-xs font-medium text-text">Controls</span>
                    </div>

                    <div className="flex flex-col gap-2 flex-grow">
                        <div className="flex items-center justify-between p-2 rounded-lg bg-surface2/50 border border-line/50">
                            <div className="flex flex-col">
                                <span className="text-[11px] font-medium text-text">Aurora Reflex</span>
                                <span className="text-[9px] text-muted">Long-term auto-tuning</span>
                            </div>
                            <button
                                onClick={handleReflexToggle}
                                disabled={togglingReflex}
                                className={`relative inline-flex h-5 w-9 items-center rounded-full transition-colors focus:outline-none focus:ring-2 focus:ring-accent focus:ring-offset-2 focus:ring-offset-surface ${
                                    reflexEnabled ? 'bg-accent' : 'bg-surface2'
                                }`}
                            >
                                <span
                                    className={`${
                                        reflexEnabled ? 'translate-x-5' : 'translate-x-1'
                                    } inline-block h-3 w-3 transform rounded-full bg-white transition-transform`}
                                />
                            </button>
                        </div>

                        <div className="flex items-center justify-between p-2 rounded-lg bg-surface2/50 border border-line/50">
                            <div className="flex flex-col">
                                <span className="text-[11px] font-medium text-text">Probabilistic</span>
                                <span className="text-[9px] text-muted">Use p10/p90 confidence bands</span>
                            </div>
                            <button
                                onClick={handleProbabilisticToggle}
                                disabled={togglingProbabilistic}
                                className={`relative inline-flex h-5 w-9 items-center rounded-full transition-colors focus:outline-none focus:ring-2 focus:ring-accent focus:ring-offset-2 focus:ring-offset-surface ${
                                    probabilisticMode ? 'bg-accent' : 'bg-surface2'
                                }`}
                            >
                                <span
                                    className={`${
                                        probabilisticMode ? 'translate-x-5' : 'translate-x-1'
                                    } inline-block h-3 w-3 transform rounded-full bg-white transition-transform`}
                                />
                            </button>
                        </div>
                        <div className="flex items-center justify-between p-2 rounded-lg bg-surface2/50 border border-line/50">
                            <div className="flex flex-col pr-3">
                                <span className="text-[11px] font-medium text-text">Aurora load forecasting</span>
                                <span className="text-[9px] text-muted">Off uses the HA load profile fallback</span>
                            </div>
                            <button
                                onClick={() => handleForecastDomainToggle('load')}
                                disabled={togglingForecastDomain === 'load'}
                                className={`relative inline-flex h-5 w-9 items-center rounded-full transition-colors focus:outline-none focus:ring-2 focus:ring-accent focus:ring-offset-2 focus:ring-offset-surface ${
                                    auroraLoadEnabled ? 'bg-accent' : 'bg-surface2'
                                }`}
                                title="Toggle Aurora load forecasting"
                            >
                                <span
                                    className={`${
                                        auroraLoadEnabled ? 'translate-x-5' : 'translate-x-1'
                                    } inline-block h-3 w-3 transform rounded-full bg-white transition-transform`}
                                />
                            </button>
                        </div>
                        <div className="flex items-center justify-between p-2 rounded-lg bg-surface2/50 border border-line/50">
                            <div className="flex flex-col pr-3">
                                <span className="text-[11px] font-medium text-text">Aurora PV forecasting</span>
                                <span className="text-[9px] text-muted">
                                    Off keeps Open-Meteo baseline without the ML residual
                                </span>
                            </div>
                            <button
                                onClick={() => handleForecastDomainToggle('pv')}
                                disabled={togglingForecastDomain === 'pv'}
                                className={`relative inline-flex h-5 w-9 items-center rounded-full transition-colors focus:outline-none focus:ring-2 focus:ring-accent focus:ring-offset-2 focus:ring-offset-surface ${
                                    auroraPvEnabled ? 'bg-accent' : 'bg-surface2'
                                }`}
                                title="Toggle Aurora PV forecasting"
                            >
                                <span
                                    className={`${
                                        auroraPvEnabled ? 'translate-x-5' : 'translate-x-1'
                                    } inline-block h-3 w-3 transform rounded-full bg-white transition-transform`}
                                />
                            </button>
                        </div>
                    </div>
                </Card>
            </div>

            {/* 1.5 KPI STRIP */}
            <KPIStrip metrics={dashboard?.metrics} perfData={perfData} priceAccuracy={priceAccuracy} />

            {/* 2. THE DASHBOARD (Middle Section) */}
            <div className="grid gap-4 lg:grid-cols-12 lg:h-[450px]">
                {/* Context Metrics - Simple Cards (Option B) */}
                <Card className="lg:col-span-4 p-4 flex flex-col h-full min-h-0 overflow-hidden">
                    <div className="mb-4 flex items-center justify-between shrink-0">
                        <div className="flex items-center gap-2">
                            <Activity className="h-4 w-4 text-accent" />
                            <span className="text-xs font-medium text-text">Context</span>
                        </div>
                    </div>
                    <div className="flex-1 min-h-0 overflow-y-auto custom-scrollbar">
                        <div className="grid grid-cols-2 gap-2">
                            {/* Cloud Volatility */}
                            <div className="p-3 rounded-lg bg-surface2/50 border border-line/50">
                                <div className="flex items-center gap-2 mb-1">
                                    <Cloud className="h-3 w-3 text-sky-400" />
                                    <span className="text-[10px] text-muted">Cloud Vol</span>
                                </div>
                                <div className="text-lg font-semibold text-text">
                                    {Math.round((volatility?.cloud_volatility ?? 0) * 100)}%
                                </div>
                                <div className="text-[9px] text-muted/70">
                                    {(volatility?.cloud_volatility ?? 0) < 0.3
                                        ? 'Stable'
                                        : (volatility?.cloud_volatility ?? 0) < 0.7
                                          ? 'Variable'
                                          : 'Volatile'}
                                </div>
                            </div>

                            {/* Temp Volatility */}
                            <div className="p-3 rounded-lg bg-surface2/50 border border-line/50">
                                <div className="flex items-center gap-2 mb-1">
                                    <Thermometer className="h-3 w-3 text-pink-400" />
                                    <span className="text-[10px] text-muted">Temp Vol</span>
                                </div>
                                <div className="text-lg font-semibold text-text">
                                    {Math.round((volatility?.temp_volatility ?? 0) * 100)}%
                                </div>
                                <div className="text-[9px] text-muted/70">
                                    {(volatility?.temp_volatility ?? 0) < 0.3
                                        ? 'Stable'
                                        : (volatility?.temp_volatility ?? 0) < 0.7
                                          ? 'Variable'
                                          : 'Volatile'}
                                </div>
                            </div>

                            {/* Risk Appetite */}
                            <div className="p-3 rounded-lg bg-surface2/50 border border-line/50">
                                <div className="flex items-center gap-2 mb-1">
                                    <TrendingUp className="h-3 w-3 text-amber-400" />
                                    <span className="text-[10px] text-muted">Aggression</span>
                                </div>
                                <div className="text-lg font-semibold text-text">{riskAppetite ?? 3}/5</div>
                                <div className="text-[9px] text-muted/70">
                                    {(riskAppetite ?? 3) <= 2
                                        ? 'Conservative'
                                        : (riskAppetite ?? 3) >= 4
                                          ? 'Aggressive'
                                          : 'Balanced'}
                                </div>
                            </div>

                            {/* Forecast Accuracy */}
                            <div className="p-3 rounded-lg bg-surface2/50 border border-line/50">
                                <div className="flex items-center gap-2 mb-1">
                                    <Target className="h-3 w-3 text-emerald-400" />
                                    <span className="text-[10px] text-muted">Accuracy</span>
                                </div>
                                <div className="text-lg font-semibold text-text">
                                    {Math.max(0, 100 - (dashboard?.metrics?.mae_pv_aurora ?? 0) * 20)}%
                                </div>
                                <div className="text-[9px] text-muted/70">PV forecast quality</div>
                            </div>

                            {/* PV Forecast Source */}
                            <div className="col-span-2 p-3 rounded-lg bg-surface2/50 border border-line/50">
                                <div className="flex items-center justify-between gap-2 mb-2">
                                    <div className="flex items-center gap-2">
                                        <SunMedium className="h-3 w-3 text-amber-300" />
                                        <span className="text-[10px] text-muted">PV source</span>
                                    </div>
                                    <span
                                        className={`text-[9px] px-2 py-0.5 rounded-full border ${
                                            pvSourceDisplay.statusTone === 'personalized'
                                                ? 'text-emerald-300 border-emerald-400/30 bg-emerald-400/10'
                                                : pvSourceDisplay.statusTone === 'disabled'
                                                  ? 'text-amber-300 border-amber-400/30 bg-amber-400/10'
                                                  : 'text-sky-300 border-sky-400/30 bg-sky-400/10'
                                        }`}
                                    >
                                        {pvSourceDisplay.status}
                                    </span>
                                </div>
                                <div className="text-xs font-semibold text-text">{pvSourceDisplay.label}</div>
                                <div className="mt-2 h-1.5 rounded-full bg-surface overflow-hidden">
                                    <div
                                        className="h-full rounded-full bg-gradient-to-r from-sky-400 to-emerald-400"
                                        style={{ width: `${pvSourceDisplay.progressWeight}%` }}
                                    />
                                </div>
                                <div className="mt-1 text-[9px] text-muted/70">{pvSourceDisplay.progressText}</div>
                            </div>

                            {/* Price Spread */}
                            <div className="p-3 rounded-lg bg-surface2/50 border border-line/50">
                                <div className="flex items-center gap-2 mb-1">
                                    <BarChart3 className="h-3 w-3 text-violet-400" />
                                    <span className="text-[10px] text-muted">Spread</span>
                                </div>
                                <div className="text-lg font-semibold text-text">
                                    {(dashboard?.metrics?.max_price_spread ?? 0).toFixed(2)}
                                </div>
                                <div className="text-[9px] text-muted/70">SEK/kWh range</div>
                            </div>

                            {/* Forecast Bias */}
                            <div className="p-3 rounded-lg bg-surface2/50 border border-line/50">
                                <div className="flex items-center gap-2 mb-1">
                                    <AlertCircle className="h-3 w-3 text-orange-400" />
                                    <span className="text-[10px] text-muted">Bias</span>
                                </div>
                                <div className="text-lg font-semibold text-text">
                                    {(dashboard?.metrics?.forecast_bias ?? 0) > 0 ? '+' : ''}
                                    {(dashboard?.metrics?.forecast_bias ?? 0).toFixed(1)}
                                </div>
                                <div className="text-[9px] text-muted/70">
                                    {(dashboard?.metrics?.forecast_bias ?? 0) > 0.5
                                        ? 'Over-predicting'
                                        : (dashboard?.metrics?.forecast_bias ?? 0) < -0.5
                                          ? 'Under-predicting'
                                          : 'Centered'}
                                </div>
                            </div>
                        </div>
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
                                {`Forecast Horizon (${chartMode === 'price' ? '7' : '3'} Days)`}
                            </div>
                            <div className="text-[11px] text-muted">
                                {chartMode === 'price'
                                    ? 'Price Forecast'
                                    : probabilisticMode
                                      ? `Probabilistic View (${chartMode.toUpperCase()})`
                                      : `Decomposition View (${chartMode.toUpperCase()})`}
                                {' • '}
                                {new Date().toISOString().slice(0, 10)} -{' '}
                                {new Date(originalHorizonEnd).toISOString().slice(0, 10)}
                            </div>
                        </div>

                        <div className="flex items-center gap-2">
                            {/* Forecast Mode Toggles */}
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
                                {priceForecastEnabled && (
                                    <button
                                        type="button"
                                        className={`px-2 py-0.5 rounded-full ${chartMode === 'price' ? 'bg-accent text-[#0F1216]' : 'text-muted'}`}
                                        onClick={() => setChartMode('price')}
                                    >
                                        <DollarSign className="h-3 w-3" />
                                    </button>
                                )}
                            </div>
                        </div>
                    </div>

                    <div className="flex-1 min-h-0">
                        {loading ? (
                            <div className="text-[11px] text-muted">Loading...</div>
                        ) : chartMode === 'price' ? (
                            priceForecastLoading ? (
                                <div className="text-[11px] text-muted">Loading price forecast...</div>
                            ) : priceForecastSlots.length === 0 ? (
                                <div className="text-[11px] text-muted">No price forecast data available</div>
                            ) : (
                                <div className="h-full w-full">
                                    <ProbabilisticChart
                                        title=""
                                        color="#FFCE59"
                                        showOpenMeteo={false}
                                        dateAxisMode
                                        allowNegativeY
                                        slots={priceForecastSlots.map((s) => ({
                                            time: s.slot_start,
                                            p10: s.spot_p10,
                                            p50: s.spot_p50,
                                            p90: s.spot_p90,
                                            actual: s.actual_spot ?? null,
                                            open_meteo_kwh: null,
                                        }))}
                                    />
                                </div>
                            )
                        ) : probabilisticMode ? (
                            <div className="h-full w-full">
                                <ProbabilisticChart
                                    title=""
                                    color={chartMode === 'load' ? '#f97316' : '#22c55e'}
                                    showOpenMeteo={chartMode === 'pv'}
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
                                                    open_meteo_kwh: null as number | null,
                                                    open_meteo_arrays: undefined,
                                                }
                                            } else {
                                                return {
                                                    time: s.slot_start,
                                                    p10: s.probabilistic?.pv_p10 ?? null,
                                                    p50: s.final.pv_kwh,
                                                    p90: s.probabilistic?.pv_p90 ?? null,
                                                    actual: null as number | null,
                                                    open_meteo_kwh: s.open_meteo_kwh ?? null,
                                                    open_meteo_arrays: s.open_meteo_arrays,
                                                }
                                            }
                                        })

                                        type ProbabilisticSlot = {
                                            time: string
                                            p10: number | null
                                            p50: number | null
                                            p90: number | null
                                            actual?: number | null
                                            open_meteo_kwh?: number | null
                                            open_meteo_arrays?: {
                                                name: string
                                                kwh: number
                                            }[]
                                        }

                                        const merged = new Map<string, ProbabilisticSlot>()

                                        histData.forEach((h) => {
                                            merged.set(h.slot_start, {
                                                time: h.slot_start,
                                                p10: h.p10 ?? null,
                                                p50: h.forecast ?? null,
                                                p90: h.p90 ?? null,
                                                actual: h.actual,
                                                open_meteo_kwh: null,
                                                open_meteo_arrays: undefined,
                                            })
                                        })

                                        futureData.forEach((f) => {
                                            const existing = merged.get(f.time)
                                            if (existing) {
                                                merged.set(f.time, {
                                                    ...existing,
                                                    p10: f.p10,
                                                    p50: f.p50,
                                                    p90: f.p90,
                                                    open_meteo_kwh: f.open_meteo_kwh,
                                                    open_meteo_arrays: f.open_meteo_arrays,
                                                })
                                            } else {
                                                merged.set(f.time, f)
                                            }
                                        })

                                        const horizonStart = dashboard?.horizon?.start
                                            ? new Date(dashboard.horizon.start).getTime()
                                            : null
                                        const horizonEnd = dashboard?.horizon?.end
                                            ? new Date(dashboard.horizon.end).getTime()
                                            : null

                                        return Array.from(merged.values())
                                            .sort((a, b) => new Date(a.time).getTime() - new Date(b.time).getTime())
                                            .filter((s) => {
                                                const t = new Date(s.time).getTime()
                                                if (horizonStart && horizonEnd) {
                                                    return t >= horizonStart && t < horizonEnd
                                                }
                                                return true
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
