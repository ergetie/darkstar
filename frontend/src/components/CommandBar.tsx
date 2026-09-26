/* eslint-disable @typescript-eslint/no-explicit-any */
import { useState, useEffect } from 'react'
import {
    AlertTriangle,
    Play,
    Pause,
    Loader2,
    Rocket,
    Flame,
    BatteryCharging,
    Palmtree,
    Car,
    Gauge,
    Droplets,
    CalendarCheck,
    CalendarX,
    type LucideIcon,
} from 'lucide-react'
import Card from './Card'
import SocStepper from './ui/SocStepper'
import QuickAction, { QuickActionChips, QuickActionSection, type QuickActionTone } from './ui/QuickAction'
import { clampSoc } from './ui/socStepper'
import { Api, type EVChargerState, type ExecutorStatusResponse, type PlannerSIndex } from '../lib/api'
import { useSocket } from '../lib/hooks'
import { useToast } from '../lib/useToast'

type PlannerMeta = {
    planned_at?: string
    planner_version?: string
    s_index?: PlannerSIndex
} | null

const TOP_UP_DEFAULT_SOC = 60
const EV_CHARGE_DEFAULT_SOC = 60
const SOC_PRESETS = [40, 60, 80, 100]
const BOOST_MINUTES_OPTIONS = [30, 60, 120]
const BOOST_DEFAULT_MINUTES = 60
/** Custom boost range; must match WATER_BOOST_* in executor/engine.py */
const BOOST_MIN_MINUTES = 15
const BOOST_MAX_MINUTES = 360
const BOOST_STEP_MINUTES = 15
const VACATION_DAYS_OPTIONS = [1, 3, 7, 14, 30]
const VACATION_DEFAULT_DAYS = 3
const VACATION_MAX_DAYS = 365
/** Plan counts as outdated after this many missed scheduler intervals */
const PLAN_STALE_RUN_MULTIPLE = 3
/** Outdated threshold when the scheduler interval is unknown */
const PLAN_STALE_FALLBACK_MINUTES = 180

function formatMinutes(minutes: number): string {
    const h = Math.floor(minutes / 60)
    const m = minutes % 60
    if (h === 0) return `${m}m`
    return m === 0 ? `${h}h` : `${h}h ${m}m`
}

interface CommandBarProps {
    riskAppetite: number
    comfortLevel: number
    executorStatus: {
        shadow_mode?: boolean
        paused?: { paused_at?: string; paused_minutes?: number } | null
        quick_action?: ExecutorStatusResponse['quick_action']
    } | null
    automationConfig: {
        enable_scheduler?: boolean
        every_minutes?: number | null
    } | null
    schedulerStatus: {
        last_run_at?: string | null
        last_run_status?: string | null
        next_run_at?: string | null
    } | null
    vacationMode: boolean
    vacationModeHA: boolean
    waterBoostActive: {
        boost: boolean
        expires_at?: string
        remaining_seconds?: number
        heaters?: Record<string, { expires_at: string; remaining_seconds: number }>
    } | null
    waterHeaters: { id: string; name: string }[]
    soc: number | null
    /** Configured battery min SoC — lower bound of the Top Up target */
    batteryMinSoc: number
    /** EV chargers (status + live plug/SoC) for the EV Charge control */
    evChargers: EVChargerState[]
    onEvRefresh: () => void
    plannerMeta: PlannerMeta
    onSetRiskAppetite: (level: number) => void
    onSetComfortLevel: (level: number) => void
    onRefresh: () => void
}

type PlannerProgress = { phase: string; elapsed_ms: number }

function formatLocalIso(d: Date | null): string {
    if (!d) return '—'
    const year = d.getFullYear()
    const month = String(d.getMonth() + 1).padStart(2, '0')
    const day = String(d.getDate()).padStart(2, '0')
    const hours = String(d.getHours()).padStart(2, '0')
    const minutes = String(d.getMinutes()).padStart(2, '0')
    return `${year}-${month}-${day} ${hours}:${minutes}`
}

export default function CommandBar({
    riskAppetite,
    comfortLevel,
    executorStatus,
    automationConfig,
    schedulerStatus,
    vacationMode,
    vacationModeHA,
    waterBoostActive,
    waterHeaters,
    batteryMinSoc,
    evChargers,
    onEvRefresh,
    plannerMeta,
    onSetRiskAppetite,
    onSetComfortLevel,
    onRefresh,
}: CommandBarProps) {
    const { toast } = useToast()

    const [plannerProgress, setPlannerProgress] = useState<PlannerProgress | null>(null)
    const [quickActionLoading, setQuickActionLoading] = useState<string | null>(null)
    const [vacationDays, setVacationDays] = useState(VACATION_DEFAULT_DAYS)
    const [boostMinutes, setBoostMinutes] = useState(BOOST_DEFAULT_MINUTES)
    const [loadingTopUp, setLoadingTopUp] = useState(false)
    const [topUpSoc, setTopUpSoc] = useState(TOP_UP_DEFAULT_SOC)
    const [evTargetSoc, setEvTargetSoc] = useState(EV_CHARGE_DEFAULT_SOC)
    /** null = charger maximum (no current_a sent) */
    const [evAmps, setEvAmps] = useState<number | null>(null)
    const [selectedEvId, setSelectedEvId] = useState<string>('')
    const [loadingEv, setLoadingEv] = useState(false)
    const [loadingVacation, setLoadingVacation] = useState(false)
    const [loadingBoost, setLoadingBoost] = useState(false)
    const [selectedHeaterId, setSelectedHeaterId] = useState<string>('')
    const [now, setNow] = useState(() => Date.now())

    useEffect(() => {
        if (!waterBoostActive?.boost || !waterBoostActive.expires_at) return
        const id = setInterval(() => setNow(Date.now()), 1000)
        return () => clearInterval(id)
    }, [waterBoostActive?.boost, waterBoostActive?.expires_at])

    // Minute tick so the plan status can turn stale without a refresh
    useEffect(() => {
        const id = setInterval(() => setNow(Date.now()), 60_000)
        return () => clearInterval(id)
    }, [])

    useSocket('planner_progress', (data: any) => {
        if (data.phase === 'failed') {
            setPlannerProgress(data)
            setTimeout(() => setPlannerProgress(null), 3000)
        } else {
            setPlannerProgress(data)
        }
    })

    // Any failed run (manual or server-started: goal change, plug event,
    // scheduler) — including failures that never emit a `failed` phase.
    useSocket('planner_error', (raw: unknown) => {
        const data = (raw ?? {}) as { error?: string | null; duration_ms?: number }
        setPlannerProgress({ phase: 'failed', elapsed_ms: data.duration_ms ?? 0 })
        setTimeout(() => setPlannerProgress(null), 3000)
        toast({ message: `Planner failed: ${data.error || 'Unknown error'}`, variant: 'error' })
    })

    useSocket('schedule_updated', () => {
        setPlannerProgress({ phase: 'complete', elapsed_ms: 0 })
        setTimeout(() => setPlannerProgress(null), 2000)
    })

    useSocket('water_boost_updated', () => {
        onRefresh()
    })

    const handleRunPlanner = async () => {
        setPlannerProgress({ phase: 'starting', elapsed_ms: 0 })
        try {
            await Api.runPlanner()
            await Api.executor.run()
        } catch (err) {
            toast({ message: err instanceof Error ? err.message : 'Failed', variant: 'error' })
            setPlannerProgress(null)
        }
    }

    const handleTogglePause = async () => {
        setQuickActionLoading('pause')
        try {
            if (executorStatus?.paused) {
                await Api.executor.resume()
                toast({ message: 'Executor resumed', variant: 'success' })
                onRefresh()
            } else {
                await Api.executor.pause()
                toast({ message: 'Executor paused', variant: 'success' })
                onRefresh()
            }
        } catch (err) {
            toast({ message: err instanceof Error ? err.message : 'Failed', variant: 'error' })
        } finally {
            setQuickActionLoading(null)
        }
    }

    const handleToggleTopUp = async () => {
        if (loadingTopUp) return
        setLoadingTopUp(true)
        try {
            const activeQA = executorStatus?.quick_action
            if (activeQA?.type === 'force_charge') {
                await Api.executor.quickAction.clear()
                onRefresh()
                toast({ message: 'Top-Up Stopped', variant: 'success' })
            } else {
                const target = effectiveTopUpSoc
                // Runs until the battery reaches the target; the duration is ignored.
                await Api.executor.quickAction.set('force_charge', 60, { target_soc: target })
                onRefresh()
                toast({ message: `Top-Up to ${target}% started`, variant: 'success' })
            }
        } catch (e) {
            console.error('Top Up/Stop failed', e)
            toast({ message: e instanceof Error ? e.message : 'Action failed', variant: 'error' })
        } finally {
            setLoadingTopUp(false)
        }
    }

    const handleToggleEvCharge = async () => {
        if (loadingEv || !selectedEv) return
        setLoadingEv(true)
        try {
            if (selectedEv.manual_charge) {
                await Api.ev.manualCharge.stop(selectedEv.id)
                toast({ message: `EV charge stopped (${selectedEv.name})`, variant: 'success' })
            } else {
                const currentA = selectedEv.type === 'current' ? effectiveEvAmps : null
                await Api.ev.manualCharge.start(selectedEv.id, {
                    target_soc: evTargetSoc,
                    ...(currentA != null ? { current_a: currentA } : {}),
                })
                toast({ message: `EV charging to ${evTargetSoc}% (${selectedEv.name})`, variant: 'success' })
            }
            onEvRefresh()
        } catch (e) {
            console.error('EV charge start/stop failed', e)
            toast({ message: e instanceof Error ? e.message : 'Action failed', variant: 'error' })
        } finally {
            setLoadingEv(false)
        }
    }

    const handleToggleBoost = async () => {
        if (loadingBoost) return
        setLoadingBoost(true)
        try {
            if (waterBoostActive?.boost) {
                await Api.waterBoost.cancel(
                    waterHeaters.length > 1 && effectiveSelectedHeaterId ? [effectiveSelectedHeaterId] : undefined,
                )
                toast({ message: 'Water Boost Cancelled', variant: 'success' })
            } else {
                const duration = boostMinutes
                if (waterHeaters.length > 1 && effectiveSelectedHeaterId) {
                    await Api.waterBoost.startFor(duration, [effectiveSelectedHeaterId])
                } else {
                    await Api.waterBoost.start(duration)
                }
                toast({ message: `Water Boost Started (${duration}m)`, variant: 'success' })
            }
            onRefresh()
        } catch (e) {
            console.error('Failed to toggle boost', e)
            toast({ message: 'Action Failed', variant: 'error' })
        } finally {
            setLoadingBoost(false)
        }
    }

    const handleToggleVacation = async () => {
        setLoadingVacation(true)
        try {
            const vacationActive = vacationMode || vacationModeHA
            if (vacationActive) {
                await Api.configSave({ water_heating: { vacation_mode: { enabled: false, end_date: null } } })
                toast({ message: 'Vacation Mode Off', variant: 'success' })
            } else {
                const days = vacationDays
                const endDate = new Date()
                endDate.setDate(endDate.getDate() + days)
                const endDateStr = endDate.toISOString().split('T')[0]
                await Api.configSave({ water_heating: { vacation_mode: { enabled: true, end_date: endDateStr } } })
                toast({ message: `Vacation Active until ${endDateStr}`, variant: 'success' })
            }
            window.dispatchEvent(new Event('config-updated'))
            onRefresh()
        } catch {
            toast({ message: 'Vacation toggle failed', variant: 'error' })
        } finally {
            setLoadingVacation(false)
        }
    }

    const isPaused = executorStatus?.paused != null
    const isPlanning = plannerProgress !== null
    const plannerFailed = plannerProgress?.phase === 'failed'
    const isTopUpActive = executorStatus?.quick_action?.type === 'force_charge'
    const topUpMin = clampSoc(batteryMinSoc, 0, 100)
    const effectiveTopUpSoc = clampSoc(topUpSoc, topUpMin, 100)

    // EV Charge: controllable chargers with a car plugged in, plus any charger
    // still in a manual charge (so it can always be stopped).
    const evCandidates = evChargers.filter((c) => !c.externally_controlled && (c.plugged_in || c.manual_charge))
    const selectedEv = evCandidates.find((c) => c.id === selectedEvId) ?? evCandidates[0]
    const isEvChargeActive = Boolean(selectedEv?.manual_charge)
    const evMinA = selectedEv?.min_current_a ?? null
    const evMaxA = selectedEv?.max_current_a ?? null
    const evAmpsOptions =
        selectedEv?.type === 'current' && evMinA != null && evMaxA != null && evMaxA >= evMinA
            ? Array.from({ length: evMaxA - evMinA + 1 }, (_, i) => evMinA + i)
            : []
    const effectiveEvAmps = evAmps != null && evAmpsOptions.includes(evAmps) ? evAmps : null
    const isBoostActive = waterBoostActive?.boost ?? false
    const isVacationActive = vacationMode || vacationModeHA
    const effectiveSelectedHeaterId =
        selectedHeaterId && waterHeaters.some((heater) => heater.id === selectedHeaterId)
            ? selectedHeaterId
            : waterHeaters[0]?.id || ''
    const activeBoosts = waterBoostActive?.heaters ?? {}
    const activeBoostIds = Object.keys(activeBoosts)
    const activeBoostNames = activeBoostIds
        .map((id) => waterHeaters.find((heater) => heater.id === id)?.name || id)
        .join(', ')
    const selectedBoost = effectiveSelectedHeaterId ? activeBoosts[effectiveSelectedHeaterId] : undefined

    const boostCountdown = (() => {
        const expiresAt = selectedBoost?.expires_at || waterBoostActive?.expires_at
        if (!isBoostActive || !expiresAt) return null
        const rem = Math.max(0, Math.floor((new Date(expiresAt).getTime() - now) / 1000))
        return `${Math.floor(rem / 60)}:${String(rem % 60).padStart(2, '0')}`
    })()

    const lastRunIso = schedulerStatus?.last_run_at || plannerMeta?.planned_at
    const lastRunDate = lastRunIso ? new Date(lastRunIso) : null
    const everyMinutes =
        automationConfig?.every_minutes && automationConfig.every_minutes > 0 ? automationConfig.every_minutes : null
    let nextRunDate: Date | null = null
    if (schedulerStatus?.next_run_at) {
        nextRunDate = new Date(schedulerStatus.next_run_at)
    } else if (automationConfig?.enable_scheduler && lastRunDate && everyMinutes) {
        nextRunDate = new Date(lastRunDate.getTime() + everyMinutes * 60 * 1000)
    }

    const formatTime = (d: Date) => d.toLocaleTimeString([], { hour: '2-digit', minute: '2-digit' })
    const plannedDate = plannerMeta?.planned_at ? new Date(plannerMeta.planned_at) : null
    const staleAfterMinutes = everyMinutes ? everyMinutes * PLAN_STALE_RUN_MULTIPLE : PLAN_STALE_FALLBACK_MINUTES
    const isPlanStale = plannedDate != null && now - plannedDate.getTime() > staleAfterMinutes * 60_000
    const schedulerOn = Boolean(automationConfig?.enable_scheduler)
    const planNeedsAttention = !plannedDate || isPlanStale
    const PlanStatusIcon = planNeedsAttention ? CalendarX : CalendarCheck
    const lastValue = plannedDate ? formatTime(plannedDate) : 'No plan yet'
    const nextValue = !schedulerOn ? 'Auto off' : nextRunDate ? formatTime(nextRunDate) : '—'

    const riskLevels = [
        { level: 1, name: 'Safety', hint: 'Keeps ≥25% extra above min SoC' },
        { level: 2, name: 'Conservative', hint: 'Keeps ≥15% extra above min SoC' },
        { level: 3, name: 'Neutral', hint: 'Keeps ≥10% extra above min SoC' },
        { level: 4, name: 'Aggressive', hint: 'Keeps ≥3% extra above min SoC' },
        { level: 5, name: 'Gambler', hint: 'No extra reserve — down to min SoC' },
    ]
    const waterLevels = [
        { level: 1, name: 'Economy', hint: 'Bulk heating in the cheapest hours' },
        { level: 2, name: 'Balanced', hint: 'Mix of savings and comfort' },
        { level: 3, name: 'Neutral', hint: 'Baseline heating windows' },
        { level: 4, name: 'Priority', hint: 'More frequent heating' },
        { level: 5, name: 'Maximum', hint: 'Very frequent heating, most stable temperature' },
    ]

    const riskPillColorMap: Record<number, string> = {
        1: 'bg-good text-[#100f0e]',
        2: 'bg-night text-[#100f0e]',
        3: 'bg-water text-[#100f0e]',
        4: 'bg-warn text-[#100f0e]',
        5: 'bg-ai text-[#100f0e]',
    }
    const waterPillColorMap: Record<number, string> = {
        1: 'bg-good text-[#100f0e]',
        2: 'bg-night text-[#100f0e]',
        3: 'bg-water text-[#100f0e]',
        4: 'bg-warn text-[#100f0e]',
        5: 'bg-bad text-[#100f0e]',
    }

    const levelSelect = (
        name: string,
        title: string,
        icon: LucideIcon,
        tone: QuickActionTone,
        levels: { level: number; name: string; hint: string }[],
        current: number,
        colorMap: Record<number, string>,
        onSelect: (level: number) => void,
    ) => (
        <QuickAction
            label={name}
            icon={icon}
            tone={tone}
            title={title}
            active={false}
            value={`${current} · ${levels.find((l) => l.level === current)?.name ?? '—'}`}
        >
            {(close) => (
                <div className="qa-levels" role="radiogroup" aria-label={title}>
                    {levels.map((l) => (
                        <button
                            key={l.level}
                            type="button"
                            role="radio"
                            aria-checked={l.level === current}
                            className="qa-level"
                            data-selected={l.level === current || undefined}
                            onClick={() => {
                                if (l.level !== current) onSelect(l.level)
                                close()
                            }}
                        >
                            <span className={`qa-level-num ${colorMap[l.level]}`}>{l.level}</span>
                            <span className="qa-level-text">
                                <span className="qa-level-name">{l.name}</span>
                                <span className="qa-level-hint">{l.hint}</span>
                            </span>
                        </button>
                    ))}
                </div>
            )}
        </QuickAction>
    )

    const riskPills = levelSelect(
        'Risk',
        'Risk Appetite',
        Gauge,
        'accent',
        riskLevels,
        riskAppetite,
        riskPillColorMap,
        onSetRiskAppetite,
    )
    const waterPills = levelSelect(
        'Water',
        'Water Comfort',
        Droplets,
        'water',
        waterLevels,
        comfortLevel,
        waterPillColorMap,
        onSetComfortLevel,
    )

    const topUpActiveTarget = executorStatus?.quick_action?.params?.target_soc
    const topUpPresets = SOC_PRESETS.filter((p) => p >= topUpMin).map((p) => ({ value: p, label: `${p}%` }))
    const evPresets = SOC_PRESETS.map((p) => ({ value: p, label: `${p}%` }))

    const quickActions = (
        <div className="grid grid-cols-2 gap-2 w-full sm:flex sm:w-auto sm:flex-wrap sm:items-center">
            {/* Top Up */}
            <QuickAction
                label="Top Up"
                icon={BatteryCharging}
                tone="good"
                title="Battery Top Up"
                active={isTopUpActive}
                value={
                    isTopUpActive
                        ? typeof topUpActiveTarget === 'number'
                            ? `→ ${topUpActiveTarget}%`
                            : 'On'
                        : `${effectiveTopUpSoc}%`
                }
            >
                {(close) =>
                    isTopUpActive ? (
                        <>
                            <p className="qa-status">
                                Charging the battery from the grid
                                {typeof topUpActiveTarget === 'number' ? ` to ${topUpActiveTarget}%` : ''}.
                            </p>
                            <button
                                type="button"
                                className="qa-submit"
                                data-variant="stop"
                                disabled={loadingTopUp}
                                onClick={() => handleToggleTopUp().then(close)}
                            >
                                Stop Top Up
                            </button>
                        </>
                    ) : (
                        <>
                            <QuickActionSection label="Charge battery to">
                                <QuickActionChips
                                    label="Top Up target"
                                    options={topUpPresets}
                                    value={effectiveTopUpSoc}
                                    onChange={setTopUpSoc}
                                />
                                <div className="flex items-center justify-between">
                                    <span className="text-xs text-muted">Custom</span>
                                    <SocStepper
                                        value={effectiveTopUpSoc}
                                        min={topUpMin}
                                        max={100}
                                        onChange={setTopUpSoc}
                                        label="Top Up target"
                                    />
                                </div>
                            </QuickActionSection>
                            <button
                                type="button"
                                className="qa-submit"
                                disabled={loadingTopUp}
                                onClick={() => handleToggleTopUp().then(close)}
                            >
                                Start Top Up to {effectiveTopUpSoc}%
                            </button>
                        </>
                    )
                }
            </QuickAction>

            {/* EV Charge */}
            {selectedEv && (
                <QuickAction
                    label="EV"
                    icon={Car}
                    tone="ai"
                    title="EV Charge"
                    active={isEvChargeActive}
                    value={
                        isEvChargeActive && selectedEv.manual_charge
                            ? `→ ${selectedEv.manual_charge.target_soc}%`
                            : `${evTargetSoc}%`
                    }
                >
                    {(close) => (
                        <>
                            {evCandidates.length > 1 && (
                                <QuickActionSection label="Charger">
                                    <select
                                        aria-label="EV charger"
                                        value={selectedEv.id}
                                        onChange={(e) => setSelectedEvId(e.target.value)}
                                        className="qa-select"
                                        disabled={loadingEv}
                                    >
                                        {evCandidates.map((c) => (
                                            <option key={c.id} value={c.id}>
                                                {c.name}
                                            </option>
                                        ))}
                                    </select>
                                </QuickActionSection>
                            )}
                            {isEvChargeActive ? (
                                <p className="qa-status">
                                    {selectedEv.name} is charging
                                    {selectedEv.manual_charge ? ` to ${selectedEv.manual_charge.target_soc}%` : ''}
                                    {selectedEv.manual_charge?.current_a
                                        ? ` at ${selectedEv.manual_charge.current_a} A`
                                        : ''}
                                    .
                                </p>
                            ) : (
                                <>
                                    <QuickActionSection label="Charge car to">
                                        <QuickActionChips
                                            label="EV charge target"
                                            options={evPresets}
                                            value={evTargetSoc}
                                            onChange={setEvTargetSoc}
                                            disabled={loadingEv}
                                        />
                                        <div className="flex items-center justify-between">
                                            <span className="text-xs text-muted">Custom</span>
                                            <SocStepper
                                                value={evTargetSoc}
                                                min={1}
                                                max={100}
                                                onChange={setEvTargetSoc}
                                                label="EV charge target"
                                                disabled={loadingEv}
                                            />
                                        </div>
                                    </QuickActionSection>
                                    {evAmpsOptions.length > 0 && (
                                        <QuickActionSection label="Charging current">
                                            <select
                                                aria-label="Charging current in amps"
                                                value={effectiveEvAmps ?? ''}
                                                onChange={(e) =>
                                                    setEvAmps(e.target.value === '' ? null : Number(e.target.value))
                                                }
                                                className="qa-select"
                                                disabled={loadingEv}
                                            >
                                                <option value="">Charger maximum ({evMaxA} A)</option>
                                                {evAmpsOptions.map((a) => (
                                                    <option key={a} value={a}>
                                                        {a} A
                                                    </option>
                                                ))}
                                            </select>
                                        </QuickActionSection>
                                    )}
                                </>
                            )}
                            <button
                                type="button"
                                className="qa-submit"
                                data-variant={isEvChargeActive ? 'stop' : undefined}
                                disabled={loadingEv}
                                onClick={() => handleToggleEvCharge().then(close)}
                            >
                                {isEvChargeActive ? 'Stop EV Charge' : `Start charging to ${evTargetSoc}%`}
                            </button>
                        </>
                    )}
                </QuickAction>
            )}

            {/* Water Boost */}
            <QuickAction
                label="Boost"
                icon={Flame}
                tone="water"
                title="Water Heater Boost"
                active={isBoostActive}
                value={isBoostActive ? (boostCountdown ?? 'On') : formatMinutes(boostMinutes)}
            >
                {(close) => (
                    <>
                        {waterHeaters.length > 1 && (
                            <QuickActionSection label="Water heater">
                                <select
                                    aria-label="Water heater to boost"
                                    value={effectiveSelectedHeaterId}
                                    onChange={(e) => setSelectedHeaterId(e.target.value)}
                                    className="qa-select"
                                    disabled={loadingBoost}
                                >
                                    {waterHeaters.map((heater) => (
                                        <option key={heater.id} value={heater.id}>
                                            {heater.name}
                                        </option>
                                    ))}
                                </select>
                            </QuickActionSection>
                        )}
                        {isBoostActive ? (
                            <p className="qa-status">
                                Boosting{activeBoostNames ? ` ${activeBoostNames}` : ''}
                                {boostCountdown ? ` — ${boostCountdown} left` : ''}.
                            </p>
                        ) : (
                            <QuickActionSection label="Boost for">
                                <QuickActionChips
                                    label="Boost duration"
                                    options={BOOST_MINUTES_OPTIONS.map((m) => ({ value: m, label: formatMinutes(m) }))}
                                    value={boostMinutes}
                                    onChange={setBoostMinutes}
                                    disabled={loadingBoost}
                                />
                                <div className="flex items-center justify-between">
                                    <span className="text-xs text-muted">Custom (minutes)</span>
                                    <SocStepper
                                        value={boostMinutes}
                                        min={BOOST_MIN_MINUTES}
                                        max={BOOST_MAX_MINUTES}
                                        step={BOOST_STEP_MINUTES}
                                        unit="m"
                                        onChange={(m) =>
                                            setBoostMinutes(
                                                clampSoc(
                                                    Math.round(m / BOOST_STEP_MINUTES) * BOOST_STEP_MINUTES,
                                                    BOOST_MIN_MINUTES,
                                                    BOOST_MAX_MINUTES,
                                                ),
                                            )
                                        }
                                        label="Boost duration"
                                        disabled={loadingBoost}
                                    />
                                </div>
                            </QuickActionSection>
                        )}
                        <button
                            type="button"
                            className="qa-submit"
                            data-variant={isBoostActive ? 'stop' : undefined}
                            disabled={loadingBoost}
                            onClick={() => handleToggleBoost().then(close)}
                        >
                            {isBoostActive ? 'Stop Boost' : `Start Boost for ${formatMinutes(boostMinutes)}`}
                        </button>
                    </>
                )}
            </QuickAction>

            {/* Vacation */}
            <QuickAction
                label="Vacay"
                icon={Palmtree}
                tone="warn"
                title="Vacation Mode"
                active={isVacationActive}
                value={isVacationActive ? 'On' : `${vacationDays}d`}
            >
                {(close) => (
                    <>
                        {isVacationActive ? (
                            <p className="qa-status">
                                Vacation mode is on — normal water heating is paused; only the periodic anti-legionella
                                cycle runs.
                                {vacationModeHA && !vacationMode ? ' (Set from Home Assistant.)' : ''}
                            </p>
                        ) : (
                            <QuickActionSection label="Away for">
                                <QuickActionChips
                                    label="Vacation length"
                                    options={VACATION_DAYS_OPTIONS.map((d) => ({ value: d, label: `${d}d` }))}
                                    value={vacationDays}
                                    onChange={setVacationDays}
                                    disabled={loadingVacation}
                                />
                                <div className="flex items-center justify-between">
                                    <span className="text-xs text-muted">Custom</span>
                                    <SocStepper
                                        value={vacationDays}
                                        min={1}
                                        max={VACATION_MAX_DAYS}
                                        step={1}
                                        unit="d"
                                        onChange={setVacationDays}
                                        label="Vacation length"
                                        disabled={loadingVacation}
                                    />
                                </div>
                            </QuickActionSection>
                        )}
                        <button
                            type="button"
                            className="qa-submit"
                            data-variant={isVacationActive ? 'stop' : undefined}
                            disabled={loadingVacation}
                            onClick={() => handleToggleVacation().then(close)}
                        >
                            {isVacationActive
                                ? 'Turn off Vacation Mode'
                                : `Start Vacation (${vacationDays} ${vacationDays === 1 ? 'day' : 'days'})`}
                        </button>
                    </>
                )}
            </QuickAction>
        </div>
    )

    return (
        <Card className="px-4 py-3 border-accent/20 bg-surface/80 backdrop-blur-md">
            <div className="flex flex-wrap items-center justify-between gap-x-6 gap-y-3">
                {/* Mode: execution controls + planner parameters */}
                <div className="flex flex-wrap items-center gap-x-4 gap-y-3">
                    <div className="flex items-center gap-2">
                        <button
                            onClick={handleRunPlanner}
                            disabled={isPlanning}
                            className={`relative overflow-hidden flex items-center justify-center h-10 w-11 sm:h-9 sm:w-10 rounded-lg transition ${
                                plannerFailed
                                    ? 'bg-bad/10 border border-bad/50 text-bad'
                                    : isPlanning
                                      ? 'bg-surface border border-accent/50 text-accent cursor-wait'
                                      : 'bg-accent hover:bg-accent2 text-[#100f0e]'
                            }`}
                            title={plannerFailed ? 'Planner failed' : 'Run Planner'}
                            data-planner-phase={plannerProgress?.phase ?? 'idle'}
                        >
                            {plannerFailed ? (
                                <AlertTriangle className="h-4 w-4" />
                            ) : isPlanning && plannerProgress?.phase !== 'complete' ? (
                                <Loader2 className="h-4 w-4 animate-spin" />
                            ) : (
                                <Rocket className="h-4 w-4" />
                            )}
                            {isPlanning && (
                                <div
                                    className="absolute bottom-0 left-0 h-0.5 bg-accent/40 pointer-events-none transition-all duration-500 ease-linear"
                                    style={{ width: plannerProgress?.phase === 'complete' ? '100%' : '30%' }}
                                />
                            )}
                        </button>
                        <button
                            onClick={handleTogglePause}
                            disabled={quickActionLoading === 'pause'}
                            className={`flex items-center justify-center h-10 w-11 sm:h-9 sm:w-10 rounded-lg transition ${
                                isPaused
                                    ? 'bg-bad hover:bg-bad/80 text-white ring-2 ring-bad shadow-md'
                                    : 'bg-good hover:bg-good/80 text-white'
                            } ${quickActionLoading === 'pause' ? 'opacity-60 cursor-wait' : ''}`}
                            title={isPaused ? 'Resume execution' : 'Pause execution'}
                        >
                            {isPaused ? <Play className="h-4 w-4" /> : <Pause className="h-4 w-4" />}
                        </button>
                    </div>

                    {riskPills}
                    {waterPills}
                </div>

                {/* Quick actions */}
                {quickActions}

                {/* Status */}
                <div
                    className="flex items-center gap-2"
                    data-testid="plan-status"
                    data-stale={isPlanStale || undefined}
                    title={`Last run: ${formatLocalIso(lastRunDate)}\nNext run: ${schedulerOn ? formatLocalIso(nextRunDate) : '—'}`}
                >
                    <PlanStatusIcon
                        className={`h-4 w-4 shrink-0 ${planNeedsAttention ? 'text-warn' : 'text-good'}`}
                        aria-hidden="true"
                    />
                    <dl className="grid grid-cols-[auto_auto] gap-x-2 text-xs leading-tight tabular-nums">
                        <dt className="text-muted">Last</dt>
                        <dd className={isPlanStale || !plannedDate ? 'text-warn' : 'text-muted'}>
                            {lastValue}
                            {isPlanStale ? ' · outdated' : ''}
                        </dd>
                        <dt className="text-muted">Next</dt>
                        <dd className={schedulerOn ? 'text-text font-medium' : 'text-warn'}>{nextValue}</dd>
                    </dl>
                </div>
            </div>
        </Card>
    )
}
