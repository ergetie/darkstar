import React, { useCallback, useEffect, useState } from 'react'
import Card from '../../../components/Card'
import { Api } from '../../../lib/api'
import type { LearnedParameter, LearnedParameterHistoryEntry, LearnedParametersResponse } from '../../../lib/types'
import {
    SOURCE_BADGE,
    boundsText,
    evidenceSummary,
    formatDate,
    formatValue,
    missingText,
    statusText,
    unitSuffix,
    validateLock,
    valueCaption,
    valueText,
} from './learnedParameters'

const EVENT_TEXT: Record<LearnedParameterHistoryEntry['event'], string> = {
    learned: 'updated',
    expired: 'expired',
    recovered: 'recovered',
    locked: 'locked',
    lock_changed: 'lock changed',
    unlocked: 'unlocked',
}

function errorMessage(error: unknown): string {
    return error instanceof Error ? error.message : 'Request failed.'
}

const ParameterRow: React.FC<{ parameter: LearnedParameter; onChanged: () => void }> = ({ parameter, onChanged }) => {
    const [input, setInput] = useState('')
    const [error, setError] = useState<string | null>(null)
    const [busy, setBusy] = useState(false)
    const badge = SOURCE_BADGE[parameter.source]
    const evidence = evidenceSummary(parameter.evidence)
    const caption = valueCaption(parameter)

    const lock = async () => {
        const result = validateLock(parameter, input)
        if ('error' in result) {
            setError(result.error)
            return
        }
        setBusy(true)
        setError(null)
        try {
            await Api.learnedParameters.lock(parameter.key, result.value)
            setInput('')
            onChanged()
        } catch (e) {
            setError(errorMessage(e))
        } finally {
            setBusy(false)
        }
    }

    const unlock = async () => {
        setBusy(true)
        setError(null)
        try {
            await Api.learnedParameters.unlock(parameter.key)
            onChanged()
        } catch (e) {
            setError(errorMessage(e))
        } finally {
            setBusy(false)
        }
    }

    return (
        <div
            className="rounded-lg border border-line/50 bg-surface2/50 p-3 space-y-2"
            data-testid={`learned-${parameter.key}`}
        >
            <div className="flex flex-wrap items-center justify-between gap-2">
                <div className="flex items-center gap-2">
                    <span className="text-sm font-medium text-text">{parameter.label}</span>
                    <span className={badge.className} data-testid="source-badge">
                        {badge.label}
                    </span>
                </div>
                <div className="text-right">
                    <span className="text-lg font-semibold text-text" data-testid="effective-value">
                        {valueText(parameter)}
                    </span>
                    {caption && (
                        <p className="text-xs text-muted" data-testid="value-caption">
                            {caption}
                        </p>
                    )}
                </div>
            </div>

            <div className="text-xs text-muted space-y-0.5">
                {parameter.learned_value !== null && (
                    <p data-testid="learned-value">
                        Learned {formatValue(parameter, parameter.learned_value)}
                        {parameter.confidence !== null && ` (confidence ${Math.round(parameter.confidence * 100)} %)`}
                        {parameter.estimated_at && `, estimated ${formatDate(parameter.estimated_at)}`}
                    </p>
                )}
                {evidence && <p data-testid="evidence">{evidence}</p>}
                <p data-testid="status-text">{statusText(parameter)}</p>
            </div>

            <div className="flex flex-wrap items-center gap-2">
                <input
                    type="text"
                    inputMode="decimal"
                    className="input w-32"
                    aria-label={`${parameter.label} lock value (${unitSuffix(parameter)})`}
                    placeholder={`${boundsText(parameter)}`}
                    value={input}
                    onChange={(e) => {
                        setInput(e.target.value)
                        setError(null)
                    }}
                    disabled={busy}
                />
                <button type="button" className="btn btn-secondary btn-pill" onClick={lock} disabled={busy}>
                    {parameter.locked ? 'Change lock' : 'Lock'}
                </button>
                {parameter.locked && (
                    <button type="button" className="btn btn-ghost btn-pill" onClick={unlock} disabled={busy}>
                        Unlock
                    </button>
                )}
            </div>
            {error && (
                <p className="text-xs text-bad" role="alert">
                    {error}
                </p>
            )}
        </div>
    )
}

const History: React.FC = () => {
    const [entries, setEntries] = useState<LearnedParameterHistoryEntry[] | null>(null)
    const [error, setError] = useState<string | null>(null)

    const load = (open: boolean) => {
        if (!open || entries !== null) return
        Api.learnedParameters
            .history(50)
            .then((r) => setEntries(r.history))
            .catch((e) => setError(errorMessage(e)))
    }

    return (
        <details onToggle={(e) => load((e.currentTarget as HTMLDetailsElement).open)} data-testid="learned-history">
            <summary className="cursor-pointer text-xs font-medium text-muted">History</summary>
            <div className="mt-2 space-y-1 text-xs text-muted">
                {error && <p className="text-bad">{error}</p>}
                {entries?.length === 0 && <p>No changes yet.</p>}
                {entries?.map((entry) => {
                    const unit = entry.key === 'inverter_standby_w' ? ('W' as const) : ('fraction' as const)
                    return (
                        <p key={entry.id}>
                            {formatDate(entry.at)} · {entry.key.replace(/_/g, ' ')} · {EVENT_TEXT[entry.event]}
                            {entry.old_value !== null || entry.new_value !== null
                                ? `: ${formatValue({ unit }, entry.old_value)} → ${formatValue({ unit }, entry.new_value)}`
                                : ''}
                        </p>
                    )
                })}
            </div>
        </details>
    )
}

export const LearnedParametersSection: React.FC = () => {
    const [data, setData] = useState<LearnedParametersResponse | null>(null)
    const [loadError, setLoadError] = useState<string | null>(null)

    const load = useCallback(() => {
        Api.learnedParameters
            .list()
            .then((response) => {
                setData(response)
                setLoadError(null)
            })
            .catch((e) => setLoadError(errorMessage(e)))
    }, [])

    useEffect(() => {
        load()
    }, [load])

    return (
        <div data-testid="learned-parameters">
            <Card className="overflow-hidden">
                <div className="px-6 py-4">
                    <h2 className="text-lg font-semibold text-foreground">Learned parameters</h2>
                    <p className="mt-1 text-sm text-muted">
                        Darkstar measures these from your recorded data. The planner uses a learned value while it is
                        valid (re-estimated at least every 30 days) and your configured efficiencies otherwise. You can
                        lock any value to your own number.
                    </p>
                </div>
                <div className="space-y-3 px-6 pb-6">
                    {loadError && (
                        <div className="banner banner-error">Could not load learned parameters: {loadError}</div>
                    )}
                    {!data && !loadError && <p className="text-sm text-muted">Loading learned parameters…</p>}
                    {data && (
                        <>
                            <div className="banner banner-info text-xs" data-testid="effective-basis">
                                {data.effective.basis === 'learned'
                                    ? `Planner efficiencies: charge ${(data.effective.charge_efficiency * 100).toFixed(1)} %, discharge ${(data.effective.discharge_efficiency * 100).toFixed(1)} % (from learned and locked values).`
                                    : `Planner efficiencies: configured values (charge ${(data.effective.config_charge_efficiency * 100).toFixed(1)} %, discharge ${(data.effective.config_discharge_efficiency * 100).toFixed(1)} %). Still missing: ${missingText(data.effective.missing, data.parameters)}.`}
                            </div>
                            {data.parameters.map((parameter) => (
                                <ParameterRow key={parameter.key} parameter={parameter} onChanged={load} />
                            ))}
                            <History />
                        </>
                    )}
                </div>
            </Card>
        </div>
    )
}
