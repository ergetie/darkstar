import type { SensorUnit } from '../lib/api'

const UNITS: readonly SensorUnit[] = ['W', 'kW']

interface SensorUnitSelectProps {
    /** The unit chosen so far; undefined means none (the sensor is read as kW). */
    value?: SensorUnit
    onChange: (unit: SensorUnit) => void
    disabled?: boolean
}

/** W/kW segmented control for a power sensor whose Home Assistant state reports no unit. */
export default function SensorUnitSelect({ value, onChange, disabled = false }: SensorUnitSelectProps) {
    return (
        <div className="mt-1.5 space-y-1" data-testid="sensor-unit-select">
            <p className="text-[11px] text-muted">
                {value
                    ? 'Home Assistant reports no unit for this sensor. Unit set manually.'
                    : 'Home Assistant reports no unit for this sensor. Choose W or kW (read as kW until you do).'}
            </p>
            <div
                className="inline-flex rounded-ds-md border border-line/30 bg-surface2/50 p-0.5"
                role="group"
                aria-label="Sensor unit"
            >
                {UNITS.map((unit) => (
                    <button
                        key={unit}
                        type="button"
                        disabled={disabled}
                        aria-pressed={value === unit}
                        onClick={() => onChange(unit)}
                        className={`min-h-[44px] rounded-ds-md px-3 py-1 text-[11px] font-semibold transition-colors disabled:opacity-50 sm:min-h-0 ${
                            value === unit ? 'bg-accent/20 text-accent' : 'text-muted hover:text-text'
                        }`}
                    >
                        {unit}
                    </button>
                ))}
            </div>
        </div>
    )
}
