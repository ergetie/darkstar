import React, { useEffect, useId, useState } from 'react'
import { createPortal } from 'react-dom'
import { ChevronDown, ChevronUp, Plus, Trash2 } from 'lucide-react'
import Switch from '../../../components/ui/Switch'
import Select from '../../../components/ui/Select'
import { NumberInput } from '../../../components/ui/NumberInput'
import {
    MONTH_LABELS,
    WEEKDAY_LABELS,
    parseLocalDateTime,
    resolveTransferFee,
    type TransferFeeMode,
    type TransferFeeRule,
} from '../transferFees'

interface TransferFeeRulesEditorProps {
    mode: TransferFeeMode
    rules: TransferFeeRule[]
    flatFee: string
    holidaysAsWeekend: boolean
    onModeChange: (mode: TransferFeeMode) => void
    onRulesChange: (rules: TransferFeeRule[]) => void
    onFlatFeeChange: (value: string) => void
    onHolidaysChange: (value: boolean) => void
    disabled?: boolean
}

const MODES: { value: TransferFeeMode; label: string }[] = [
    { value: 'flat', label: 'Flat' },
    { value: 'time_of_use', label: 'Time-of-use' },
]

const ALL_DAY = 'all'
const START_OPTIONS = [
    { label: 'All day', value: ALL_DAY },
    ...Array.from({ length: 24 }, (_, h) => ({ label: `${String(h).padStart(2, '0')}:00`, value: String(h) })),
]
const END_OPTIONS = Array.from({ length: 24 }, (_, i) => ({
    label: `${String(i + 1).padStart(2, '0')}:00`,
    value: String(i + 1),
}))

const chipClass = (active: boolean) =>
    `px-2 py-1 rounded-ds-md text-[11px] font-semibold border transition-colors disabled:opacity-40 disabled:cursor-not-allowed ${
        active
            ? 'bg-accent/20 border-accent/50 text-accent'
            : 'bg-surface2 border-line/50 text-muted hover:border-accent/40 hover:text-text'
    }`

const iconBtn =
    'flex items-center justify-center w-7 h-7 rounded-ds-md text-muted hover:text-text hover:bg-surface-elevated disabled:opacity-30 disabled:cursor-not-allowed transition-colors'

function toggleValue(list: number[] | undefined, value: number): number[] {
    const current = list ?? []
    const next = current.includes(value) ? current.filter((v) => v !== value) : [...current, value]
    return next.sort((a, b) => a - b)
}

function todayIso(): string {
    const now = new Date()
    return `${now.getFullYear()}-${String(now.getMonth() + 1).padStart(2, '0')}-${String(now.getDate()).padStart(2, '0')}`
}

interface ChipGroupProps {
    label: string
    labels: string[]
    offset: number
    selected: number[] | undefined
    onToggle: (value: number) => void
    disabled?: boolean
}

const ChipGroup: React.FC<ChipGroupProps> = ({ label, labels, offset, selected, onToggle, disabled }) => {
    const all = !selected || selected.length === 0
    return (
        <div>
            <div className="text-[10px] uppercase font-bold text-muted mb-1.5">
                {label} <span className="normal-case font-normal">{all ? '(all)' : ''}</span>
            </div>
            <div className="flex flex-wrap gap-1" role="group" aria-label={label}>
                {labels.map((text, i) => {
                    const value = i + offset
                    const active = !all && selected.includes(value)
                    return (
                        <button
                            key={value}
                            type="button"
                            aria-pressed={active}
                            disabled={disabled}
                            onClick={() => onToggle(value)}
                            className={chipClass(active)}
                        >
                            {text}
                        </button>
                    )
                })}
            </div>
        </div>
    )
}

const pad2 = (n: number) => String(n).padStart(2, '0')

/** "06:00–07:00" for a preview hour. */
function hourRange(hour: number): string {
    return `${pad2(hour)}:00–${pad2(hour + 1)}:00`
}

/** Which rule set the fee, or the catch-all row. */
function ruleName(ruleIndex: number | null): string {
    return ruleIndex === null ? 'All other times' : `Rule ${ruleIndex + 1}`
}

function hourLabel(h: { hour: number; fee: number; ruleIndex: number | null }): string {
    return `${hourRange(h.hour)}: ${h.fee.toFixed(2)} SEK/kWh (${ruleName(h.ruleIndex)})`
}

interface PreviewProps {
    mode: TransferFeeMode
    rules: TransferFeeRule[]
    flatFee: number
    holidaysAsWeekend: boolean
}

export const TransferFeePreview: React.FC<PreviewProps> = ({ mode, rules, flatFee, holidaysAsWeekend }) => {
    const [date, setDate] = useState(todayIso)
    // Computed on every render (24 cheap lookups) so unsaved edits show immediately.
    const hours = /^\d{4}-\d{2}-\d{2}$/.test(date)
        ? Array.from({ length: 24 }, (_, hour) => ({
              hour,
              ...resolveTransferFee(mode, rules, flatFee, parseLocalDateTime(date, hour), holidaysAsWeekend),
          }))
        : []

    const [active, setActive] = useState<{ index: number; x: number; y: number } | null>(null)
    const tooltipId = useId()
    const show = (e: React.SyntheticEvent<HTMLElement>, index: number) => {
        const rect = e.currentTarget.getBoundingClientRect()
        setActive({ index, x: rect.left + rect.width / 2, y: rect.top })
    }
    const activeHour = active ? hours[active.index] : undefined

    // Hide on scroll/resize (fixed positioning would drift) and on outside tap.
    useEffect(() => {
        if (!active) return
        const hide = () => setActive(null)
        const onPointerDown = (e: PointerEvent) => {
            if (!(e.target instanceof Element) || !e.target.closest('[data-testid="transfer-fee-preview-hour"]')) hide()
        }
        window.addEventListener('scroll', hide, true)
        window.addEventListener('resize', hide)
        document.addEventListener('pointerdown', onPointerDown)
        return () => {
            window.removeEventListener('scroll', hide, true)
            window.removeEventListener('resize', hide)
            document.removeEventListener('pointerdown', onPointerDown)
        }
    }, [active])

    const fees = hours.map((h) => h.fee)
    const min = fees.length ? Math.min(...fees) : 0
    const max = fees.length ? Math.max(...fees) : 0

    return (
        <div className="space-y-2" data-testid="transfer-fee-preview">
            <div className="flex flex-wrap items-center justify-between gap-2">
                <span className="text-[10px] uppercase font-bold text-muted">Preview (excl. VAT)</span>
                <input
                    type="date"
                    aria-label="Preview date"
                    value={date}
                    onChange={(e) => setDate(e.target.value)}
                    className="input text-xs py-1"
                />
            </div>
            <div
                className="flex gap-px rounded-ds-md overflow-hidden border border-line/40"
                role="group"
                aria-label="Transfer fee per hour"
                onPointerLeave={(e) => e.pointerType !== 'touch' && setActive(null)}
            >
                {hours.map((h, i) => {
                    const strength = max > min ? 0.25 + (0.75 * (h.fee - min)) / (max - min) : 0.5
                    const label = hourLabel(h)
                    return (
                        <button
                            key={h.hour}
                            type="button"
                            data-testid="transfer-fee-preview-hour"
                            data-fee={h.fee}
                            title={label}
                            aria-label={label}
                            aria-describedby={active?.index === i ? tooltipId : undefined}
                            className="flex-1 h-6 bg-peak cursor-help focus-visible:outline focus-visible:outline-2 focus-visible:outline-accent focus-visible:-outline-offset-2"
                            style={{ opacity: strength }}
                            // Touch taps are handled by onClick; hover only for mouse/pen.
                            onPointerEnter={(e) => e.pointerType !== 'touch' && show(e, i)}
                            onFocus={(e) => show(e, i)}
                            onBlur={() => setActive(null)}
                            onClick={(e) => (active?.index === i ? setActive(null) : show(e, i))}
                        />
                    )
                })}
            </div>
            {activeHour &&
                active &&
                createPortal(
                    <div
                        id={tooltipId}
                        role="tooltip"
                        data-testid="transfer-fee-preview-tooltip"
                        className="fixed z-[9999] -translate-x-1/2 -translate-y-full px-2.5 py-1.5 text-xs bg-surface2 border border-line rounded-lg shadow-xl pointer-events-none whitespace-nowrap"
                        style={{ left: active.x, top: active.y - 6 }}
                    >
                        <div className="font-mono text-text">{hourRange(activeHour.hour)}</div>
                        <div className="text-text font-semibold">{activeHour.fee.toFixed(2)} SEK/kWh</div>
                        <div className="text-muted">{ruleName(activeHour.ruleIndex)}</div>
                    </div>,
                    document.body,
                )}
            <div className="flex justify-between text-[10px] text-muted font-mono">
                <span>00</span>
                <span>06</span>
                <span>12</span>
                <span>18</span>
                <span>24</span>
            </div>
            {fees.length > 0 && (
                <p className="text-[11px] text-muted">
                    {min === max
                        ? `${min.toFixed(2)} SEK/kWh all day`
                        : `${min.toFixed(2)}–${max.toFixed(2)} SEK/kWh (darker = higher)`}
                </p>
            )}
        </div>
    )
}

export const TransferFeeRulesEditor: React.FC<TransferFeeRulesEditorProps> = ({
    mode,
    rules,
    flatFee,
    holidaysAsWeekend,
    onModeChange,
    onRulesChange,
    onFlatFeeChange,
    onHolidaysChange,
    disabled,
}) => {
    const updateRule = (index: number, updates: Partial<TransferFeeRule>) => {
        onRulesChange(rules.map((r, i) => (i === index ? { ...r, ...updates } : r)))
    }

    const setHours = (index: number, rule: TransferFeeRule, startValue: string) => {
        if (startValue === ALL_DAY) {
            const rest = { ...rule }
            delete rest.hours
            onRulesChange(rules.map((r, i) => (i === index ? rest : r)))
            return
        }
        const start = Number(startValue)
        const end = rule.hours && rule.hours.end !== start ? rule.hours.end : 24
        updateRule(index, { hours: { start, end } })
    }

    const move = (index: number, delta: number) => {
        const target = index + delta
        if (target < 0 || target >= rules.length) return
        const next = [...rules]
        ;[next[index], next[target]] = [next[target], next[index]]
        onRulesChange(next)
    }

    const addRule = () => {
        onRulesChange([...rules, { hours: { start: 6, end: 22 }, fee_sek: Number(flatFee) || 0 }])
    }

    const removeRule = (index: number) => onRulesChange(rules.filter((_, i) => i !== index))

    const flatFeeNumber = Number(flatFee) || 0

    return (
        <div className="space-y-4 col-span-2" data-testid="transfer-fee-editor">
            <div className="flex flex-wrap items-center justify-between gap-3">
                <span className="text-[10px] uppercase font-bold text-muted">Grid transfer fee</span>
                <div
                    className="flex bg-surface2/50 rounded-ds-md p-0.5 border border-line/30"
                    role="group"
                    aria-label="Transfer fee mode"
                >
                    {MODES.map((m) => (
                        <button
                            key={m.value}
                            type="button"
                            disabled={disabled}
                            aria-pressed={mode === m.value}
                            onClick={() => onModeChange(m.value)}
                            className={`px-3 py-1 text-[11px] font-semibold rounded-ds-md transition-colors ${
                                mode === m.value ? 'bg-accent/20 text-accent' : 'text-muted hover:text-text'
                            }`}
                        >
                            {m.label}
                        </button>
                    ))}
                </div>
            </div>

            {mode === 'flat' ? (
                <div className="space-y-1">
                    <label className="text-[10px] uppercase font-bold text-muted">Fee (SEK/kWh)</label>
                    <NumberInput
                        aria-label="Flat transfer fee"
                        value={flatFee}
                        onChange={onFlatFeeChange}
                        step={0.01}
                        min={0}
                        disabled={disabled}
                    />
                    <p className="text-[11px] text-muted">
                        Same fee for every hour. Switch to Time-of-use if your grid operator charges more at certain
                        times (tidstariff).
                    </p>
                </div>
            ) : (
                <>
                    <p className="text-[11px] text-muted">
                        Rules are checked top to bottom; the first rule that matches a time slot sets its fee. Hours are
                        local time, from inclusive to exclusive; a range like 22:00–06:00 wraps past midnight.
                    </p>
                    <div className="space-y-3">
                        {rules.map((rule, index) => {
                            const startValue = rule.hours ? String(rule.hours.start) : ALL_DAY
                            return (
                                <div
                                    key={index}
                                    data-testid="transfer-fee-rule"
                                    className="p-3 bg-surface-elevated border border-line/40 rounded-ds-lg space-y-3"
                                >
                                    <div className="flex items-center justify-between">
                                        <span className="text-xs font-bold text-text">Rule {index + 1}</span>
                                        <div className="flex items-center gap-1">
                                            <button
                                                type="button"
                                                aria-label={`Move rule ${index + 1} up`}
                                                className={iconBtn}
                                                disabled={disabled || index === 0}
                                                onClick={() => move(index, -1)}
                                            >
                                                <ChevronUp size={14} />
                                            </button>
                                            <button
                                                type="button"
                                                aria-label={`Move rule ${index + 1} down`}
                                                className={iconBtn}
                                                disabled={disabled || index === rules.length - 1}
                                                onClick={() => move(index, 1)}
                                            >
                                                <ChevronDown size={14} />
                                            </button>
                                            <button
                                                type="button"
                                                aria-label={`Delete rule ${index + 1}`}
                                                className={`${iconBtn} hover:text-bad`}
                                                disabled={disabled}
                                                onClick={() => removeRule(index)}
                                            >
                                                <Trash2 size={14} />
                                            </button>
                                        </div>
                                    </div>
                                    <ChipGroup
                                        label="Months"
                                        labels={MONTH_LABELS}
                                        offset={1}
                                        selected={rule.months}
                                        disabled={disabled}
                                        onToggle={(v) => updateRule(index, { months: toggleValue(rule.months, v) })}
                                    />
                                    <ChipGroup
                                        label="Weekdays"
                                        labels={WEEKDAY_LABELS}
                                        offset={0}
                                        selected={rule.weekdays}
                                        disabled={disabled}
                                        onToggle={(v) => updateRule(index, { weekdays: toggleValue(rule.weekdays, v) })}
                                    />
                                    <div className="grid gap-3 sm:grid-cols-3">
                                        <div>
                                            <div className="text-[10px] uppercase font-bold text-muted mb-1.5">
                                                From
                                            </div>
                                            <Select
                                                value={startValue}
                                                options={START_OPTIONS}
                                                disabled={disabled}
                                                onChange={(v) => setHours(index, rule, v)}
                                            />
                                        </div>
                                        <div>
                                            <div className="text-[10px] uppercase font-bold text-muted mb-1.5">To</div>
                                            <Select
                                                value={rule.hours ? String(rule.hours.end) : ''}
                                                options={END_OPTIONS}
                                                placeholder="—"
                                                disabled={disabled || !rule.hours}
                                                onChange={(v) =>
                                                    rule.hours &&
                                                    updateRule(index, {
                                                        hours: { start: rule.hours.start, end: Number(v) },
                                                    })
                                                }
                                            />
                                        </div>
                                        <div>
                                            <div className="text-[10px] uppercase font-bold text-muted mb-1.5">
                                                Fee (SEK/kWh)
                                            </div>
                                            <NumberInput
                                                aria-label={`Rule ${index + 1} fee`}
                                                value={
                                                    rule.fee_sek === null || rule.fee_sek === undefined
                                                        ? ''
                                                        : String(rule.fee_sek)
                                                }
                                                step={0.01}
                                                min={0}
                                                disabled={disabled}
                                                onChange={(v) =>
                                                    updateRule(index, {
                                                        fee_sek: (v.trim() === '' ? null : Number(v)) as number,
                                                    })
                                                }
                                            />
                                        </div>
                                    </div>
                                </div>
                            )
                        })}

                        <div
                            data-testid="transfer-fee-catch-all"
                            className="p-3 bg-surface2 border border-dashed border-line/50 rounded-ds-lg grid gap-3 sm:grid-cols-3 items-end"
                        >
                            <div className="sm:col-span-2">
                                <div className="text-xs font-bold text-text">All other times</div>
                                <p className="text-[11px] text-muted">Used when no rule above matches.</p>
                            </div>
                            <div>
                                <div className="text-[10px] uppercase font-bold text-muted mb-1.5">Fee (SEK/kWh)</div>
                                <NumberInput
                                    aria-label="All other times fee"
                                    value={flatFee}
                                    onChange={onFlatFeeChange}
                                    step={0.01}
                                    min={0}
                                    disabled={disabled}
                                />
                            </div>
                        </div>
                    </div>

                    <button
                        type="button"
                        className="btn btn-secondary flex items-center gap-1.5"
                        disabled={disabled}
                        onClick={addRule}
                    >
                        <Plus size={14} /> Add rule
                    </button>

                    <div className="flex items-start gap-3" data-testid="transfer-fee-holidays">
                        <Switch
                            checked={holidaysAsWeekend}
                            onCheckedChange={onHolidaysChange}
                            disabled={disabled}
                            className="shrink-0 mt-0.5"
                        />
                        <div className="min-w-0">
                            <div className="text-sm font-semibold text-text">Treat holidays as weekend</div>
                            <p className="text-[11px] text-muted">
                                Swedish public holidays plus Midsommarafton, Julafton and Nyårsafton count as
                                Saturday/Sunday when matching weekdays.
                            </p>
                        </div>
                    </div>
                </>
            )}

            <TransferFeePreview
                mode={mode}
                rules={rules}
                flatFee={flatFeeNumber}
                holidaysAsWeekend={holidaysAsWeekend}
            />
        </div>
    )
}
