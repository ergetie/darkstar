import { useState } from 'react'
import { ChevronLeft, ChevronRight } from 'lucide-react'
import { SOC_STEP, clampSoc, parseSocInput } from './socStepper'

interface SocStepperProps {
    value: number
    min: number
    max: number
    onChange: (value: number) => void
    disabled?: boolean
    /** Accessible name for the control, e.g. "Top Up target" */
    label: string
    /** Amount − / + moves the value (default: SOC_STEP) */
    step?: number
    /** Suffix shown after the value (default: "%") */
    unit?: string
}

/**
 * Numeric target selector (SoC by default): − / + move by `step` (15 percentage points) (clamped to
 * [min, max]); tapping the value opens an input for an exact integer.
 * Enter or blur commits, Escape cancels, invalid input keeps the old value.
 */
export default function SocStepper({
    value,
    min,
    max,
    onChange,
    disabled = false,
    label,
    step = SOC_STEP,
    unit = '%',
}: SocStepperProps) {
    const [draft, setDraft] = useState<string | null>(null)

    const commit = () => {
        if (draft === null) return
        const parsed = parseSocInput(draft, min, max)
        if (parsed !== null && parsed !== value) onChange(parsed)
        setDraft(null)
    }

    return (
        <div className="soc-stepper" role="group" aria-label={label}>
            <button
                type="button"
                className="soc-stepper-btn"
                aria-label={`Decrease ${label}`}
                onClick={() => onChange(clampSoc(value - step, min, max))}
                disabled={disabled || value <= min}
            >
                <ChevronLeft className="h-2.5 w-2.5" />
            </button>
            {draft !== null ? (
                <input
                    type="number"
                    inputMode="numeric"
                    className="soc-stepper-input"
                    aria-label={label}
                    min={min}
                    max={max}
                    value={draft}
                    autoFocus
                    onChange={(e) => setDraft(e.target.value)}
                    onBlur={commit}
                    onKeyDown={(e) => {
                        if (e.key === 'Enter') commit()
                        else if (e.key === 'Escape') setDraft(null)
                    }}
                />
            ) : (
                <button
                    type="button"
                    className="soc-stepper-value"
                    aria-label={`${label}: ${value}${unit}, tap to type`}
                    onClick={() => setDraft(String(value))}
                    disabled={disabled}
                >
                    {value}
                    {unit}
                </button>
            )}
            <button
                type="button"
                className="soc-stepper-btn"
                aria-label={`Increase ${label}`}
                onClick={() => onChange(clampSoc(value + step, min, max))}
                disabled={disabled || value >= max}
            >
                <ChevronRight className="h-2.5 w-2.5" />
            </button>
        </div>
    )
}
