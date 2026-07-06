import React from 'react'
import { Plus, Trash2 } from 'lucide-react'
import EntitySelect from '../../../components/EntitySelect'
import { NumberInput } from '../../../components/ui/NumberInput'
import { HaEntity } from '../types'

export type BalancedLoadDeviceType = 'ev_charger' | 'water_heater' | 'custom_entity'

export interface BalancedLoad {
    device_type: BalancedLoadDeviceType
    device_id: string
    phases: number[]
    priority: number
    entity?: string
    on_value?: string
    off_value?: string
}

interface DeviceOption {
    id: string
    name: string
}

interface BalancedLoadsEditorProps {
    value: BalancedLoad[] | string
    onChange: (value: BalancedLoad[]) => void
    disabled?: boolean
    config?: Record<string, unknown>
    haEntities?: HaEntity[]
    haLoading?: boolean
}

const DEVICE_TYPE_OPTIONS: { value: BalancedLoadDeviceType; label: string }[] = [
    { value: 'water_heater', label: 'Water Heater' },
    { value: 'ev_charger', label: 'EV Charger (binary shed)' },
    { value: 'custom_entity', label: 'Custom Entity' },
]

const createDefaultLoad = (deviceOptions: (type: BalancedLoadDeviceType) => DeviceOption[]): BalancedLoad => {
    const waterHeaters = deviceOptions('water_heater')
    return {
        device_type: 'water_heater',
        device_id: waterHeaters[0]?.id || '',
        phases: [],
        priority: 1,
    }
}

export const BalancedLoadsEditor: React.FC<BalancedLoadsEditorProps> = ({
    value,
    onChange,
    disabled = false,
    config,
    haEntities = [],
    haLoading = false,
}) => {
    const loads: BalancedLoad[] = Array.isArray(value)
        ? value
        : typeof value === 'string' && value.trim()
          ? (JSON.parse(value) as BalancedLoad[])
          : []

    const deviceOptionsFor = (type: BalancedLoadDeviceType): DeviceOption[] => {
        if (type === 'water_heater') {
            const heaters = (config?.water_heaters as { id: string; name?: string }[] | undefined) || []
            return heaters.map((h) => ({ id: h.id, name: h.name || h.id }))
        }
        if (type === 'ev_charger') {
            const chargers = (config?.ev_chargers as { id: string; name?: string; type?: string }[] | undefined) || []
            // type: current chargers are always dynamically throttled (see the
            // group above) and must not be shed on/off here.
            return chargers.filter((c) => c.type !== 'current').map((c) => ({ id: c.id, name: c.name || c.id }))
        }
        return []
    }

    const addLoad = () => {
        onChange([...loads, createDefaultLoad(deviceOptionsFor)])
    }

    const removeLoad = (index: number) => {
        onChange(loads.filter((_, i) => i !== index))
    }

    const updateLoad = (index: number, updates: Partial<BalancedLoad>) => {
        onChange(loads.map((load, i) => (i === index ? { ...load, ...updates } : load)))
    }

    const togglePhase = (index: number, phase: number) => {
        const load = loads[index]
        const has = load.phases.includes(phase)
        const nextPhases = has ? load.phases.filter((p) => p !== phase) : [...load.phases, phase].sort((a, b) => a - b)
        updateLoad(index, { phases: nextPhases })
    }

    return (
        <div className="space-y-3 col-span-2">
            <div className="flex items-start justify-between gap-4 bg-surface2/30 rounded-xl border border-line/20 p-3">
                <p className="text-[11px] text-muted leading-relaxed">
                    Phase assignment must match your home&apos;s physical wiring — the balancer can only protect a phase
                    it knows a load sits on. This group only activates once every charger in Dynamically Throttled
                    Chargers above is at its floor or paused. Chargers with a variable-current setpoint are throttled
                    automatically up there and can&apos;t be added here — only binary on/off EV chargers are offered.
                </p>
                {!disabled && (
                    <button
                        type="button"
                        onClick={addLoad}
                        className="flex shrink-0 items-center gap-1.5 px-3 py-1.5 rounded-lg bg-surface2 hover:bg-good/20 hover:text-good border border-line/50 transition-colors text-xs font-semibold"
                    >
                        <Plus size={14} />
                        Add Load
                    </button>
                )}
            </div>

            {loads.length === 0 && (
                <div className="text-center py-6 px-4 bg-surface-elevated rounded-xl border border-line/20 border-dashed">
                    <div className="text-muted text-sm">No balanced loads configured</div>
                </div>
            )}

            <div className="space-y-2">
                {loads.map((load, index) => {
                    const options = deviceOptionsFor(load.device_type)
                    return (
                        <div key={index} className="p-3 rounded-xl border border-line/40 bg-surface-elevated space-y-3">
                            <div className="grid grid-cols-1 sm:grid-cols-[1fr_1fr_auto] gap-3 items-end">
                                <div>
                                    <label className="text-[10px] uppercase font-bold text-muted mb-1.5 block">
                                        Device Type
                                    </label>
                                    <select
                                        value={load.device_type}
                                        onChange={(e) =>
                                            updateLoad(index, {
                                                device_type: e.target.value as BalancedLoadDeviceType,
                                                device_id: '',
                                            })
                                        }
                                        disabled={disabled}
                                        className="w-full rounded-lg border border-line/50 bg-surface2 px-3 py-2 text-sm text-text focus:border-accent focus:outline-none disabled:opacity-50"
                                    >
                                        {DEVICE_TYPE_OPTIONS.map((opt) => (
                                            <option key={opt.value} value={opt.value}>
                                                {opt.label}
                                            </option>
                                        ))}
                                    </select>
                                </div>

                                <div>
                                    <label className="text-[10px] uppercase font-bold text-muted mb-1.5 block">
                                        Device
                                    </label>
                                    {load.device_type === 'custom_entity' ? (
                                        <input
                                            type="text"
                                            value={load.device_id}
                                            onChange={(e) => updateLoad(index, { device_id: e.target.value })}
                                            disabled={disabled}
                                            placeholder="e.g. pool_pump"
                                            className="w-full rounded-lg border border-line/50 bg-surface2 px-3 py-2 text-sm text-text focus:border-accent focus:outline-none disabled:opacity-50"
                                        />
                                    ) : (
                                        <select
                                            value={load.device_id}
                                            onChange={(e) => updateLoad(index, { device_id: e.target.value })}
                                            disabled={disabled || options.length === 0}
                                            className="w-full rounded-lg border border-line/50 bg-surface2 px-3 py-2 text-sm text-text focus:border-accent focus:outline-none disabled:opacity-50"
                                        >
                                            <option value="">
                                                {options.length === 0 ? 'No devices configured' : '-- Select --'}
                                            </option>
                                            {options.map((opt) => (
                                                <option key={opt.id} value={opt.id}>
                                                    {opt.name}
                                                </option>
                                            ))}
                                        </select>
                                    )}
                                </div>

                                {!disabled && (
                                    <button
                                        type="button"
                                        onClick={() => removeLoad(index)}
                                        className="p-2 rounded-lg text-muted hover:text-bad hover:bg-bad/10 transition-colors"
                                        aria-label="Remove load"
                                    >
                                        <Trash2 size={16} />
                                    </button>
                                )}
                            </div>

                            <div className="grid grid-cols-1 sm:grid-cols-[auto_auto] gap-4 items-end">
                                <div>
                                    <label className="text-[10px] uppercase font-bold text-muted mb-1.5 block">
                                        Phases
                                    </label>
                                    <div className="flex gap-3">
                                        {[1, 2, 3].map((phase) => (
                                            <label
                                                key={phase}
                                                className="flex items-center gap-1.5 text-xs font-semibold text-text"
                                            >
                                                <input
                                                    type="checkbox"
                                                    checked={load.phases.includes(phase)}
                                                    onChange={() => togglePhase(index, phase)}
                                                    disabled={disabled}
                                                />
                                                L{phase}
                                            </label>
                                        ))}
                                    </div>
                                    {load.phases.length === 0 && (
                                        <p className="text-[10px] text-bad mt-1">Select at least one phase</p>
                                    )}
                                </div>

                                <div className="w-28">
                                    <label className="text-[10px] uppercase font-bold text-muted mb-1.5 block">
                                        Priority
                                    </label>
                                    <NumberInput
                                        value={load.priority}
                                        onChange={(val) => updateLoad(index, { priority: Number(val) || 0 })}
                                        disabled={disabled}
                                        step={1}
                                        min={0}
                                    />
                                    <p className="text-[10px] text-muted mt-1">Lowest sheds first</p>
                                </div>
                            </div>

                            {load.device_type === 'custom_entity' && (
                                <div className="grid grid-cols-1 sm:grid-cols-3 gap-3 pt-2 border-t border-line/10">
                                    <div className="sm:col-span-3">
                                        <label className="text-[10px] uppercase font-bold text-muted mb-1.5 block">
                                            Entity
                                        </label>
                                        <EntitySelect
                                            entities={haEntities}
                                            value={load.entity || ''}
                                            onChange={(val) => updateLoad(index, { entity: val })}
                                            loading={haLoading}
                                            placeholder="Select Home Assistant entity..."
                                            disabled={disabled}
                                        />
                                    </div>
                                    <div>
                                        <label className="text-[10px] uppercase font-bold text-muted mb-1.5 block">
                                            On Value
                                        </label>
                                        <input
                                            type="text"
                                            value={load.on_value ?? '1'}
                                            onChange={(e) => updateLoad(index, { on_value: e.target.value })}
                                            disabled={disabled}
                                            className="w-full rounded-lg border border-line/50 bg-surface2 px-3 py-2 text-sm text-text focus:border-accent focus:outline-none disabled:opacity-50"
                                        />
                                    </div>
                                    <div>
                                        <label className="text-[10px] uppercase font-bold text-muted mb-1.5 block">
                                            Off Value
                                        </label>
                                        <input
                                            type="text"
                                            value={load.off_value ?? '0'}
                                            onChange={(e) => updateLoad(index, { off_value: e.target.value })}
                                            disabled={disabled}
                                            className="w-full rounded-lg border border-line/50 bg-surface2 px-3 py-2 text-sm text-text focus:border-accent focus:outline-none disabled:opacity-50"
                                        />
                                    </div>
                                </div>
                            )}
                        </div>
                    )
                })}
            </div>
        </div>
    )
}
