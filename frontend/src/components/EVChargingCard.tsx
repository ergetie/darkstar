import React, { useState, useEffect } from 'react'
import { Link } from 'react-router-dom'
import { Clock, RotateCw, Sun, Trash2, Loader2, Save } from 'lucide-react'
import {
    Api,
    EVChargerState,
    type ConfigResponse,
    type LoadBalancerStatusResponse,
    type LoadBalancerEvStatus,
} from '../lib/api'
import { useToast } from '../lib/useToast'
import Switch from './ui/Switch'

type ExcessPvPriorityEntry = NonNullable<
    NonNullable<NonNullable<ConfigResponse['executor']>['excess_pv']>['priority']
>[number]

/** Format a Date as a local (not UTC) YYYY-MM-DD string — never use
 * toISOString().slice(0, 10) for calendar logic, it shifts across midnight
 * in timezones behind/ahead of UTC. */
// eslint-disable-next-line react-refresh/only-export-components -- pure helper, tested directly
export function toLocalISODate(d: Date): string {
    const year = d.getFullYear()
    const month = String(d.getMonth() + 1).padStart(2, '0')
    const day = String(d.getDate()).padStart(2, '0')
    return `${year}-${month}-${day}`
}

/** Parse a YYYY-MM-DD string as a local date — never use `new Date("YYYY-MM-DD")`
 * for calendar logic, it parses as UTC midnight and can shift a day in local time. */
// eslint-disable-next-line react-refresh/only-export-components -- pure helper, tested directly
export function parseLocalISODate(dateStr: string): Date {
    const [year, month, day] = dateStr.split('-').map(Number)
    return new Date(year, (month || 1) - 1, day || 1)
}

// eslint-disable-next-line react-refresh/only-export-components -- pure helper, tested directly
export function tomorrowLocalISODate(): string {
    const tomorrow = new Date()
    tomorrow.setDate(tomorrow.getDate() + 1)
    return toLocalISODate(tomorrow)
}

const EV_BALANCER_STATE_LABELS: Record<string, string> = {
    throttling: 'Throttling by Load Balancer',
    paused: 'Paused by Load Balancer',
    stale_fallback: 'Load Balancer Fail-Safe',
}

const EV_BALANCER_STATE_COLORS: Record<string, string> = {
    throttling: 'bg-amber-500/10 text-amber-400 border border-amber-500/20',
    paused: 'bg-blue-500/10 text-blue-400 border border-blue-500/20',
    stale_fallback: 'bg-rose-500/10 text-rose-400 border border-rose-500/20',
}

/** Percentage of the charge goal delivered so far, capped at 100. Returns 0
 * (rather than dividing by zero) when the goal has no required_kwh set. */
// eslint-disable-next-line react-refresh/only-export-components -- pure helper, tested directly
export function computeProgressPercent(charger: EVChargerState): number {
    const delivered = charger.delivered_kwh ?? 0
    const required = charger.required_kwh ?? 0
    return required > 0 ? Math.min(100, Math.round((delivered / required) * 100)) : 0
}

/** Derives the displayed status text/color for a charger, giving load-balancer
 * fail-safe states (throttling/paused/stale_fallback) priority over the
 * charger's own on_track/behind/complete/idle status. */
// eslint-disable-next-line react-refresh/only-export-components -- pure helper, tested directly
export function deriveChargerStatus(
    charger: EVChargerState,
    balancerEv: LoadBalancerEvStatus | undefined,
): { statusText: string; statusColor: string } {
    const balancerState = balancerEv?.state
    const balancerOverrideLabel = balancerState ? EV_BALANCER_STATE_LABELS[balancerState] : undefined
    const balancerOverrideColor = balancerState ? EV_BALANCER_STATE_COLORS[balancerState] : undefined

    let statusText: string = charger.status || 'idle'
    let statusColor = 'bg-surface2 text-muted'
    if (balancerOverrideLabel && balancerOverrideColor) {
        // A fail-safe pause/throttle must never read as "on track".
        statusText = balancerOverrideLabel
        statusColor = balancerOverrideColor
    } else if (charger.status === 'on_track') {
        statusText = 'On track'
        statusColor = 'bg-emerald-500/10 text-emerald-400 border border-emerald-500/20'
    } else if (charger.status === 'behind') {
        statusText = 'Behind'
        statusColor = 'bg-rose-500/10 text-rose-400 border border-rose-500/20'
    } else if (charger.status === 'complete') {
        statusText = 'Complete'
        statusColor = 'bg-emerald-500/20 text-emerald-300 border border-emerald-500/40'
    } else if (charger.status === 'idle') {
        statusText = 'Idle'
        statusColor = 'bg-surface2 text-muted'
    }

    return { statusText, statusColor }
}

export default function EVChargingCard({
    charger,
    config,
    loadBalancing,
    onRefresh,
}: {
    charger: EVChargerState
    config: ConfigResponse | null
    loadBalancing: LoadBalancerStatusResponse | null
    onRefresh: () => Promise<void>
}) {
    const { toast } = useToast()

    // View-vs-edit mode is derived from the current charger prop every
    // render — never a one-shot init — so a goal cleared server-side (by
    // another client, HA, or this component) always shows the no-goal
    // (create) form, never a phantom stale goal. `manualEdit` only tracks
    // the user explicitly opening the form to edit an EXISTING goal.
    const hasGoal = charger.target_soc_percent !== null
    const [manualEdit, setManualEdit] = useState(false)
    const isEditing = !hasGoal || manualEdit

    const [submitting, setSubmitting] = useState(false)
    const [formError, setFormError] = useState<string | null>(null)
    // True while a save's refetch is in flight — the reset-from-props effect
    // is skipped during this window so the just-submitted values stay
    // displayed instead of flashing back to the (momentarily stale) props.
    const [pendingRefresh, setPendingRefresh] = useState(false)

    // Form states
    const [targetSoc, setTargetSoc] = useState<number>(charger.target_soc_percent ?? 80)
    const [readyBy, setReadyBy] = useState<string>(charger.ready_by ?? '07:00')
    const [repeat, setRepeat] = useState<string>(charger.repeat ?? 'daily')
    const [readyByDate, setReadyByDate] = useState<string>(charger.ready_by_date ?? tomorrowLocalISODate())
    const [nDays, setNDays] = useState<number>(charger.n_days ?? 2)
    const [keepOn, setKeepOn] = useState<boolean>(charger.keep_on_after_target ?? false)

    // Reset form states if charger changes externally (e.g. from HA socket sync).
    // Every field resets unconditionally from props (including to its default
    // when the server value is null) — a stale local value must never survive
    // a server-side change just because it happened to be falsy.
    useEffect(() => {
        if (!isEditing && !pendingRefresh) {
            setTargetSoc(charger.target_soc_percent ?? 80)
            setReadyBy(charger.ready_by ?? '07:00')
            setRepeat(charger.repeat ?? 'daily')
            setReadyByDate(charger.ready_by_date ?? tomorrowLocalISODate())
            setNDays(charger.n_days ?? 2)
            setKeepOn(charger.keep_on_after_target ?? false)
        }
    }, [charger, isEditing, pendingRefresh])

    // Load balancer check — states mirror LoadBalancerStatusCard's per-EV
    // states exactly: idle (no override), throttling, paused, stale_fallback.
    const balancerEv = loadBalancing?.ev?.find((e: LoadBalancerEvStatus) => e.charger_id === charger.id)

    // Surplus absorption check
    const excessPv = config?.executor?.excess_pv?.priority ?? []
    const isSurplusPriority = excessPv.some(
        (entry: ExcessPvPriorityEntry) => entry.type === 'ev' && entry.charger_id === charger.id,
    )

    const handleSave = async (e: React.FormEvent) => {
        e.preventDefault()
        setSubmitting(true)
        setFormError(null)
        setPendingRefresh(true)

        try {
            await Api.ev.setSchedule(charger.id, {
                target_soc_percent: targetSoc,
                ready_by: readyBy,
                repeat: repeat,
                ready_by_date: repeat === 'none' ? readyByDate : null,
                n_days: repeat === 'every_n_days' ? nDays : null,
                keep_on_after_target: targetSoc === 100 ? keepOn : false,
            })
            toast({ message: `Goal saved for ${charger.name}`, variant: 'success' })
            setManualEdit(false)
            await onRefresh()
        } catch (err: unknown) {
            console.error(err)
            setFormError(err instanceof Error ? err.message : 'Failed to save goal')
            toast({ message: 'Failed to save goal', variant: 'error' })
        } finally {
            setSubmitting(false)
            setPendingRefresh(false)
        }
    }

    const handleClear = async () => {
        if (!window.confirm(`Are you sure you want to clear the goal for ${charger.name}?`)) return
        setSubmitting(true)
        try {
            await Api.ev.setSchedule(charger.id, {
                target_soc_percent: null,
            })
            toast({ message: `Goal cleared for ${charger.name}`, variant: 'success' })
            await onRefresh()
        } catch (err: unknown) {
            console.error(err)
            toast({ message: 'Failed to clear goal', variant: 'error' })
        } finally {
            setSubmitting(false)
        }
    }

    // Progress math
    const delivered = charger.delivered_kwh ?? 0
    const required = charger.required_kwh ?? 0
    const progressPercent = computeProgressPercent(charger)
    const { statusText, statusColor } = deriveChargerStatus(charger, balancerEv)

    return (
        <div className="bg-surface2/30 rounded-xl p-3 border border-line/10 relative overflow-hidden transition-all duration-300">
            {/* Charger Info Header */}
            <div className="flex items-center justify-between mb-3">
                <div>
                    <h4 className="text-xs font-semibold text-text">{charger.name}</h4>
                    <p className="text-[10px] text-muted flex items-center gap-1">
                        <span className={`h-1.5 w-1.5 rounded-full ${charger.plugged_in ? 'bg-good' : 'bg-muted'}`} />
                        {charger.plugged_in ? 'Plugged' : 'Away'}
                        {charger.soc_percent !== null && ` · ${charger.soc_percent}% SoC`}
                        {charger.power_kw !== null && charger.power_kw > 0.05 && ` · ${charger.power_kw.toFixed(1)} kW`}
                    </p>
                </div>
                {!isEditing && (
                    <div className="flex items-center gap-1.5">
                        {charger.source === 'ha' && (
                            <span className="text-[9px] px-2 py-0.5 rounded-full font-semibold bg-blue-500/10 text-blue-400 border border-blue-500/20 uppercase">
                                HA-Driven
                            </span>
                        )}
                        <span className={`text-[9px] px-2 py-0.5 rounded-full font-semibold ${statusColor}`}>
                            {statusText.toUpperCase()}
                        </span>
                    </div>
                )}
            </div>

            {isEditing ? (
                /* Configure Schedule Form */
                <form onSubmit={handleSave} className="space-y-3 pt-1">
                    {formError && (
                        <div className="text-[10px] text-bad bg-bad/10 p-2 rounded-lg border border-bad/20">
                            {formError}
                        </div>
                    )}

                    {/* Target SoC Slider */}
                    <div>
                        <div className="flex justify-between text-[10px] font-medium mb-1">
                            <span className="text-text">Target SoC</span>
                            <span className="text-accent">{targetSoc}%</span>
                        </div>
                        <input
                            type="range"
                            min="10"
                            max="100"
                            step="5"
                            value={targetSoc}
                            onChange={(e) => setTargetSoc(parseInt(e.target.value))}
                            className="w-full accent-accent h-1 bg-surface-elevated rounded-lg cursor-pointer"
                        />
                    </div>

                    {/* Time & Repeat inputs in grid */}
                    <div className="grid grid-cols-2 gap-2">
                        <div>
                            <label className="block text-[9px] text-muted mb-1 font-medium">Ready By</label>
                            <input
                                type="time"
                                value={readyBy}
                                onChange={(e) => setReadyBy(e.target.value)}
                                className="w-full bg-surface-elevated border border-line/20 rounded px-2 py-1 text-xs text-text focus:outline-none focus:border-accent"
                            />
                        </div>
                        <div>
                            <label className="block text-[9px] text-muted mb-1 font-medium">Repeat</label>
                            <select
                                value={repeat}
                                onChange={(e) => setRepeat(e.target.value)}
                                className="w-full bg-surface-elevated border border-line/20 rounded px-2 py-1 text-xs text-text focus:outline-none focus:border-accent"
                            >
                                <option value="none">Once</option>
                                <option value="daily">Daily</option>
                                <option value="weekdays">Weekdays</option>
                                <option value="weekends">Weekends</option>
                                <option value="every_n_days">Every N Days</option>
                            </select>
                        </div>
                    </div>

                    {/* Conditional Repeat Settings */}
                    {repeat === 'none' && (
                        <div>
                            <label className="block text-[9px] text-muted mb-1 font-medium">Date</label>
                            <input
                                type="date"
                                value={readyByDate}
                                onChange={(e) => setReadyByDate(e.target.value)}
                                className="w-full bg-surface-elevated border border-line/20 rounded px-2 py-1 text-xs text-text focus:outline-none focus:border-accent"
                            />
                        </div>
                    )}

                    {repeat === 'every_n_days' && (
                        <div>
                            <label className="block text-[9px] text-muted mb-1 font-medium">Interval (Days)</label>
                            <input
                                type="number"
                                min="2"
                                max="7"
                                value={nDays}
                                onChange={(e) => setNDays(parseInt(e.target.value) || 2)}
                                className="w-full bg-surface-elevated border border-line/20 rounded px-2 py-1 text-xs text-text focus:outline-none focus:border-accent"
                            />
                        </div>
                    )}

                    {/* Keep charger on after target — only meaningful at 100% target */}
                    <div className="flex items-center gap-2 pt-1">
                        <Switch
                            checked={keepOn}
                            onCheckedChange={(checked) => setKeepOn(checked)}
                            disabled={targetSoc !== 100}
                        />
                        <span className="text-[10px] text-text font-normal">
                            Keep charger enabled after target SoC is met
                            {targetSoc !== 100 && <span className="text-muted ml-1">(requires 100% target)</span>}
                        </span>
                    </div>

                    {/* Form Actions */}
                    <div className="flex gap-2 pt-1">
                        {hasGoal && (
                            <button
                                type="button"
                                onClick={() => setManualEdit(false)}
                                className="flex-1 bg-surface-elevated hover:bg-surface border border-line/20 text-muted hover:text-text py-1 px-3 rounded-lg text-xs transition font-semibold"
                            >
                                Cancel
                            </button>
                        )}
                        <button
                            type="submit"
                            disabled={submitting}
                            className="flex-1 bg-accent hover:bg-accent2 text-surface-elevated py-1 px-3 rounded-lg text-xs font-bold transition flex items-center justify-center gap-1"
                        >
                            {submitting ? (
                                <Loader2 className="h-3 w-3 animate-spin" />
                            ) : (
                                <>
                                    <Save className="h-3 w-3" />
                                    Save Goal
                                </>
                            )}
                        </button>
                    </div>
                </form>
            ) : (
                /* Viewing Active Goal */
                <div className="space-y-3">
                    {/* Visual Progress Bar (delivered_kwh / required_kwh) */}
                    <div className="space-y-1">
                        <div className="flex justify-between text-[9px] text-muted font-medium">
                            <span>Delivered: {delivered.toFixed(1)} kWh</span>
                            <span>
                                Target: {required.toFixed(1)} kWh ({progressPercent}% of goal)
                            </span>
                        </div>
                        <div className="h-1.5 w-full bg-line/20 rounded-full relative overflow-hidden">
                            <div
                                className="h-full bg-ev rounded-full animate-pulse"
                                style={{ width: `${progressPercent}%` }}
                            />
                        </div>
                    </div>

                    {/* Quota schedule summary */}
                    {charger.delivered_kwh !== null && charger.required_kwh !== null && (
                        <div className="flex justify-between text-[10px] bg-surface-elevated p-2 rounded-lg border border-line/10">
                            <div>
                                <span className="text-muted text-[9px] block">Delivered Today</span>
                                <span className="font-semibold text-text">
                                    {(charger.delivered_kwh ?? 0).toFixed(1)} kWh
                                </span>
                            </div>
                            <div className="text-right">
                                <span className="text-muted text-[9px] block">Remaining Need</span>
                                <span className="font-semibold text-accent">
                                    {charger.remaining_kwh !== null
                                        ? `${(charger.remaining_kwh ?? 0).toFixed(1)} kWh`
                                        : '—'}
                                </span>
                            </div>
                        </div>
                    )}

                    {/* Schedule and Repeat Info */}
                    <div className="flex flex-wrap gap-x-3 gap-y-1.5 text-[10px] text-muted font-medium pt-1">
                        <div className="flex items-center gap-1">
                            <Clock className="h-3 w-3 text-accent" />
                            <span>{readyBy}</span>
                        </div>
                        <div className="flex items-center gap-1">
                            <RotateCw className="h-3 w-3 text-accent" />
                            <span className="capitalize">
                                {repeat === 'every_n_days'
                                    ? `Every ${nDays} Days`
                                    : repeat === 'none'
                                      ? `Once (${readyByDate})`
                                      : repeat}
                            </span>
                        </div>
                        {keepOn && (
                            <div className="flex items-center gap-1 text-emerald-400/80">
                                <span className="h-1 w-1 rounded-full bg-emerald-400" />
                                <span>Keep enabled</span>
                            </div>
                        )}
                    </div>

                    {/* Day-by-day quota (from multi-day spreading) */}
                    {charger.quota_schedule && Object.keys(charger.quota_schedule).length > 0 && (
                        <div className="pt-1 border-t border-line/10">
                            <div className="text-[9px] text-muted font-medium mb-1">Upcoming Daily Quotas</div>
                            <div className="flex gap-2 overflow-x-auto pb-0.5 custom-scrollbar">
                                {Object.entries(charger.quota_schedule).map(([dateStr, kwh]) => {
                                    const d = parseLocalISODate(dateStr)
                                    const dayName = d.toLocaleDateString([], { weekday: 'short' })
                                    const isToday = dateStr === toLocalISODate(new Date())
                                    return (
                                        <div
                                            key={dateStr}
                                            className={`p-1.5 rounded-lg border text-center min-w-[45px] ${
                                                isToday
                                                    ? 'bg-accent/10 border-accent/30 text-accent'
                                                    : 'bg-surface-elevated border-line/20 text-muted'
                                            }`}
                                        >
                                            <span className="text-[8px] uppercase block font-semibold">{dayName}</span>
                                            <span className="text-[10px] font-mono font-bold block">
                                                {kwh.toFixed(1)}
                                            </span>
                                        </div>
                                    )
                                })}
                            </div>
                        </div>
                    )}

                    {/* Surplus PV Hint (Decision 7) */}
                    {charger.type === 'current' ? (
                        isSurplusPriority ? (
                            <div className="text-[9px] text-emerald-400 bg-emerald-500/10 p-2 rounded-lg border border-emerald-500/20 flex items-center gap-1">
                                <Sun className="h-3 w-3 animate-spin-slow" />
                                <span>Charges from surplus PV when available</span>
                            </div>
                        ) : (
                            <div className="text-[9px] text-amber-300 bg-amber-500/10 p-2 rounded-lg border border-amber-500/25 flex items-start gap-1">
                                <span>⚠️</span>
                                <div>
                                    Surplus absorption off —{' '}
                                    <Link
                                        to="/settings?tab=load-balancing"
                                        className="text-accent hover:underline font-semibold"
                                    >
                                        add this charger to Excess PV priority
                                    </Link>
                                </div>
                            </div>
                        )
                    ) : (
                        <div className="text-[9px] text-muted bg-surface-elevated p-2 rounded-lg border border-line/10">
                            ℹ️ Binary chargers can't absorb surplus — set up a current-type charger to use free PV.
                        </div>
                    )}

                    {/* Action buttons */}
                    <div className="flex gap-2 pt-1">
                        <button
                            onClick={handleClear}
                            disabled={submitting}
                            className="flex-1 bg-surface-elevated hover:bg-surface border border-line/20 text-bad py-1 px-3 rounded-lg text-xs transition font-semibold flex items-center justify-center gap-1"
                        >
                            <Trash2 className="h-3 w-3" />
                            Clear Goal
                        </button>
                        <button
                            onClick={() => setManualEdit(true)}
                            className="flex-1 bg-accent hover:bg-accent2 text-surface-elevated py-1 px-3 rounded-lg text-xs font-bold transition flex items-center justify-center gap-1"
                        >
                            Configure Goal
                        </button>
                    </div>
                </div>
            )}
        </div>
    )
}
