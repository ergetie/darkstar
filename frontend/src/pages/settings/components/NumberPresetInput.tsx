import React, { useState } from 'react'
import { NumberInput } from '../../../components/ui/NumberInput'

interface NumberPresetInputProps {
    /** Form value (string, as held by the settings form). */
    value: string
    onChange: (value: string) => void
    presets: { value: number; label: string }[]
    /** Value to seed the custom input with when switching from a preset. */
    customDefault: number
    ariaLabel: string
    disabled?: boolean
    min?: number
    max?: number
    step?: number
}

/** Quick-choice select for a numeric setting, with a "Custom…" option revealing a number input. */
export const NumberPresetInput: React.FC<NumberPresetInputProps> = ({
    value,
    onChange,
    presets,
    customDefault,
    ariaLabel,
    disabled,
    min,
    max,
    step,
}) => {
    const current = Number(value)
    const isPreset = presets.some((p) => p.value === current)
    const [custom, setCustom] = useState(value !== '' && !isPreset)
    const showCustom = custom || (value !== '' && !isPreset)

    return (
        <div>
            <select
                aria-label={ariaLabel}
                value={showCustom ? 'custom' : String(current)}
                onChange={(event) => {
                    if (event.target.value === 'custom') {
                        setCustom(true)
                        if (isPreset) onChange(String(customDefault))
                    } else {
                        setCustom(false)
                        onChange(event.target.value)
                    }
                }}
                disabled={disabled}
                className="w-full rounded-lg border border-line/50 bg-surface2 px-3 py-2 text-sm text-text focus:border-accent focus:outline-none disabled:opacity-50"
            >
                {presets.map((p) => (
                    <option key={p.value} value={String(p.value)}>
                        {p.label}
                    </option>
                ))}
                <option value="custom">Custom…</option>
            </select>
            {showCustom && (
                <div className="mt-2">
                    <NumberInput
                        aria-label={`${ariaLabel} (custom)`}
                        value={value}
                        onChange={(val) => onChange(val)}
                        disabled={disabled}
                        step={step}
                        min={min}
                        max={max}
                    />
                </div>
            )}
        </div>
    )
}
