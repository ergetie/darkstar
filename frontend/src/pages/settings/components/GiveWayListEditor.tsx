import React, { useState } from 'react'
import { Link } from 'react-router-dom'
import { BatteryCharging, ExternalLink, Plus, Trash2 } from 'lucide-react'
import EntitySelect from '../../../components/EntitySelect'
import OrderedListEditor from '../../../components/ui/OrderedListEditor'
import { HaEntity } from '../types'
import { batteryGiveWayAvailable, healOrderForDisplay, type GiveWayEntry } from './giveWayOrder'

export type { GiveWayEntry } from './giveWayOrder'

export type ShedLoadDeviceType = 'ev_charger' | 'water_heater' | 'custom_entity'

export interface ShedLoad {
    device_type: ShedLoadDeviceType
    device_id: string
    phases: number[]
    entity?: string
    on_value?: string
    off_value?: string
    /** custom_entity only: the load's power (kW), used to decide when it fits back in. */
    power_kw?: number
    /** custom_entity only: live power sensor, preferred over power_kw. */
    power_sensor?: string
    /** Minimum seconds on / off before the load may switch again (default 300). */
    min_on_s?: number
    min_off_s?: number
}

interface ChargerInfo {
    id: string
    name: string
    phases: number[]
    min_current_a: number
    max_current_a: number | null
}

interface GiveWayListEditorProps {
    /** JSON string of load_balancing.give_way_order */
    orderValue: string
    /** JSON string of load_balancing.loads */
    loadsValue: string
    onChangeOrder: (entries: GiveWayEntry[]) => void
    onChangeLoads: (loads: ShedLoad[]) => void
    disabled?: boolean
    config?: Record<string, unknown>
    haEntities?: HaEntity[]
    haLoading?: boolean
}

const DEVICE_TYPE_OPTIONS: { value: ShedLoadDeviceType; label: string }[] = [
    { value: 'water_heater', label: 'Water Heater' },
    { value: 'ev_charger', label: 'EV Charger (on/off)' },
    { value: 'custom_entity', label: 'Custom Entity' },
]

function parseJsonArray<T>(raw: string): T[] {
    try {
        const parsed: unknown = JSON.parse(raw || '[]')
        return Array.isArray(parsed) ? (parsed as T[]) : []
    } catch {
        return []
    }
}

const PhaseBadges: React.FC<{ phases: number[] }> = ({ phases }) => (
    <span className="flex gap-1">
        {(phases.length > 0 ? phases : []).map((p) => (
            <span key={p} className="rounded bg-surface2 px-1.5 py-0.5 text-[9px] font-bold text-muted">
                L{p}
            </span>
        ))}
    </span>
)

export const GiveWayListEditor: React.FC<GiveWayListEditorProps> = ({
    orderValue,
    loadsValue,
    onChangeOrder,
    onChangeLoads,
    disabled = false,
    config,
    haEntities = [],
    haLoading = false,
}) => {
    const [adding, setAdding] = useState(false)
    const [selectedLoad, setSelectedLoad] = useState('')
    const loads = parseJsonArray<ShedLoad>(loadsValue)
    const rawOrder = parseJsonArray<GiveWayEntry>(orderValue)

    const chargers: ChargerInfo[] = (
        (config?.ev_chargers as
            | {
                  id: string
                  name?: string
                  type?: string
                  enabled?: boolean
                  phases?: number[]
                  min_current_a?: number
                  max_current_a?: number
              }[]
            | undefined) || []
    )
        .filter((c) => c.type === 'current' && c.enabled !== false)
        .map((c) => ({
            id: c.id,
            name: c.name || c.id,
            phases: c.phases || [1, 2, 3],
            min_current_a: c.min_current_a ?? 6,
            max_current_a: c.max_current_a ?? null,
        }))

    const entries = healOrderForDisplay(
        rawOrder,
        chargers.map((c) => c.id),
        loads.map((l) => l.device_id),
        batteryGiveWayAvailable(config),
    )

    const shedDeviceOptions = (type: ShedLoadDeviceType): { id: string; name: string }[] => {
        if (type === 'water_heater') {
            const heaters = (config?.water_heaters as { id: string; name?: string }[] | undefined) || []
            return heaters.map((h) => ({ id: h.id, name: h.name || h.id }))
        }
        if (type === 'ev_charger') {
            const all = (config?.ev_chargers as { id: string; name?: string; type?: string }[] | undefined) || []
            // Dynamic-current chargers use throttling entries; binary chargers are shed.
            return all.filter((c) => c.type !== 'current').map((c) => ({ id: c.id, name: c.name || c.id }))
        }
        return []
    }

    const shedDisplayName = (load: ShedLoad): string => {
        const options = shedDeviceOptions(load.device_type).filter(
            (device) => device.id === load.device_id || !loads.some((other) => other.device_id === device.id),
        )
        return options.find((o) => o.id === load.device_id)?.name || load.device_id || '(no device)'
    }

    const availableChargers = chargers.filter(
        (charger) => !entries.some((entry) => entry.kind === 'charger' && entry.id === charger.id),
    )
    const batteryAvailable = batteryGiveWayAvailable(config) && !entries.some((entry) => entry.kind === 'battery')
    const addLoad = () => {
        if (!selectedLoad) return
        if (selectedLoad === 'battery') {
            if (batteryAvailable) onChangeOrder([...entries, { kind: 'battery', id: 'battery' }])
        } else if (selectedLoad.startsWith('charger:')) {
            const id = selectedLoad.slice('charger:'.length)
            if (availableChargers.some((charger) => charger.id === id))
                onChangeOrder([...entries, { kind: 'charger', id }])
        } else {
            const available = (type: ShedLoadDeviceType) =>
                shedDeviceOptions(type).filter((device) => !loads.some((load) => load.device_id === device.id))
            const heater = available('water_heater')[0]
            const binaryCharger = available('ev_charger')[0]
            let customId = 'custom_load'
            for (let suffix = 2; loads.some((load) => load.device_id === customId); suffix++)
                customId = `custom_load_${suffix}`
            const newLoad: ShedLoad = {
                device_type: heater ? 'water_heater' : binaryCharger ? 'ev_charger' : 'custom_entity',
                device_id: heater?.id || binaryCharger?.id || customId,
                phases: [],
            }
            onChangeLoads([...loads, newLoad])
            onChangeOrder([...entries, { kind: 'shed', id: newLoad.device_id }])
        }
        setAdding(false)
        setSelectedLoad('')
    }
    const removeEntry = (kind: 'charger' | 'battery', id: string) =>
        onChangeOrder(entries.filter((entry) => !(entry.kind === kind && entry.id === id)))

    const removeShedLoad = (deviceId: string) => {
        onChangeLoads(loads.filter((l) => l.device_id !== deviceId))
        onChangeOrder(entries.filter((e) => !(e.kind === 'shed' && e.id === deviceId)))
    }

    const updateShedLoad = (deviceId: string, updates: Partial<ShedLoad>) => {
        if (
            updates.device_id !== undefined &&
            updates.device_id !== deviceId &&
            loads.some((load) => load.device_id === updates.device_id)
        )
            return
        onChangeLoads(loads.map((l) => (l.device_id === deviceId ? { ...l, ...updates } : l)))
        if (updates.device_id !== undefined && updates.device_id !== deviceId) {
            // Keep the order entry pointing at the renamed device, same position.
            onChangeOrder(
                entries.map((e) => (e.kind === 'shed' && e.id === deviceId ? { ...e, id: updates.device_id! } : e)),
            )
        }
    }

    const togglePhase = (load: ShedLoad, phase: number) => {
        const has = load.phases.includes(phase)
        const nextPhases = has ? load.phases.filter((p) => p !== phase) : [...load.phases, phase].sort((a, b) => a - b)
        updateShedLoad(load.device_id, { phases: nextPhases })
    }

    const renderChargerRow = (charger: ChargerInfo) => (
        <div className="flex flex-wrap items-center gap-x-3 gap-y-1 py-2 pr-1">
            <div className="min-w-0">
                <div className="flex items-center gap-2">
                    <span className="truncate text-sm font-semibold text-text">{charger.name}</span>
                    <PhaseBadges phases={charger.phases} />
                </div>
                <div className="text-[11px] text-muted">
                    {charger.max_current_a !== null
                        ? `Throttle ${charger.max_current_a} → ${charger.min_current_a} A, then pause`
                        : `Throttle to ${charger.min_current_a} A, then pause`}
                </div>
            </div>
            <Link
                to="/settings?tab=ev"
                className="ml-auto flex shrink-0 items-center gap-1 text-[11px] font-semibold text-accent hover:underline"
            >
                Configured in EV tab
                <ExternalLink size={11} />
            </Link>
            {!disabled && (
                <button
                    type="button"
                    onClick={() => removeEntry('charger', charger.id)}
                    className="btn btn-ghost"
                    aria-label={`Remove ${charger.name}`}
                >
                    <Trash2 size={14} />
                </button>
            )}
        </div>
    )

    const renderBatteryRow = () => (
        <div className="flex flex-wrap items-center gap-x-3 gap-y-1 py-2 pr-1">
            <div className="min-w-0">
                <div className="flex items-center gap-2">
                    <BatteryCharging size={14} className="shrink-0 text-accent" aria-hidden="true" />
                    <span className="truncate text-sm font-semibold text-text">House battery (grid charging)</span>
                    <PhaseBadges phases={[1, 2, 3]} />
                </div>
                <div className="text-[11px] text-muted">
                    Lower grid charge power, then pause grid charging. Solar charging and discharge are not touched.
                </div>
            </div>
            {!disabled && (
                <button
                    type="button"
                    onClick={() => removeEntry('battery', 'battery')}
                    className="btn btn-ghost ml-auto"
                    aria-label="Remove House battery (grid charging)"
                >
                    <Trash2 size={14} />
                </button>
            )}
        </div>
    )

    const renderShedRow = (load: ShedLoad) => {
        const options = shedDeviceOptions(load.device_type).filter(
            (device) => device.id === load.device_id || !loads.some((other) => other.device_id === device.id),
        )
        return (
            <div className="space-y-2 py-2 pr-1">
                <div className="flex flex-wrap items-center gap-x-3 gap-y-1">
                    <span className="truncate text-sm font-semibold text-text">{shedDisplayName(load)}</span>
                    <PhaseBadges phases={load.phases} />
                    <span className="text-[11px] text-muted">Switch off</span>
                    {!disabled && (
                        <button
                            type="button"
                            onClick={() => removeShedLoad(load.device_id)}
                            className="ml-auto rounded-lg p-1.5 text-muted transition-colors hover:bg-bad/10 hover:text-bad"
                            aria-label={`Remove ${shedDisplayName(load)}`}
                        >
                            <Trash2 size={14} />
                        </button>
                    )}
                </div>
                <div className="grid grid-cols-1 gap-3 sm:grid-cols-[1fr_1fr_auto]">
                    <div>
                        <label className="mb-1 block text-[10px] font-bold uppercase text-muted">Device Type</label>
                        <select
                            value={load.device_type}
                            onChange={(e) =>
                                updateShedLoad(load.device_id, {
                                    device_type: e.target.value as ShedLoadDeviceType,
                                })
                            }
                            disabled={disabled}
                            className="w-full rounded-lg border border-line/50 bg-surface2 px-2 py-1.5 text-xs text-text focus:border-accent focus:outline-none disabled:opacity-50"
                        >
                            {DEVICE_TYPE_OPTIONS.map((opt) => (
                                <option key={opt.value} value={opt.value}>
                                    {opt.label}
                                </option>
                            ))}
                        </select>
                    </div>
                    <div>
                        <label className="mb-1 block text-[10px] font-bold uppercase text-muted">Device</label>
                        {load.device_type === 'custom_entity' ? (
                            <input
                                type="text"
                                value={load.device_id}
                                onChange={(e) => updateShedLoad(load.device_id, { device_id: e.target.value })}
                                disabled={disabled}
                                placeholder="e.g. pool_pump"
                                className="w-full rounded-lg border border-line/50 bg-surface2 px-2 py-1.5 text-xs text-text focus:border-accent focus:outline-none disabled:opacity-50"
                            />
                        ) : (
                            <select
                                value={load.device_id}
                                onChange={(e) => updateShedLoad(load.device_id, { device_id: e.target.value })}
                                disabled={disabled || options.length === 0}
                                className="w-full rounded-lg border border-line/50 bg-surface2 px-2 py-1.5 text-xs text-text focus:border-accent focus:outline-none disabled:opacity-50"
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
                    <div>
                        <label className="mb-1 block text-[10px] font-bold uppercase text-muted">Phases</label>
                        <div className="flex gap-2 pt-1">
                            {[1, 2, 3].map((phase) => {
                                const checked = load.phases.includes(phase)
                                return (
                                    <button
                                        key={phase}
                                        type="button"
                                        disabled={disabled}
                                        onClick={() => togglePhase(load, phase)}
                                        className={`
                                            px-3 py-1 rounded-lg text-xs font-semibold border transition-all duration-200
                                            ${
                                                checked
                                                    ? 'bg-accent/20 border-accent/50 text-accent shadow-[0_0_10px_rgba(var(--accent-rgb),0.05)] font-bold'
                                                    : 'bg-surface2 border-line/50 text-muted hover:border-accent/40 hover:text-text'
                                            }
                                            disabled:opacity-40 disabled:cursor-not-allowed
                                        `}
                                    >
                                        L{phase}
                                    </button>
                                )
                            })}
                        </div>
                        {load.phases.length === 0 && (
                            <p className="mt-1 text-[10px] text-bad">Select at least one phase</p>
                        )}
                    </div>
                </div>
                {load.device_type === 'custom_entity' && (
                    <div className="grid grid-cols-1 gap-3 border-t border-line/10 pt-2 sm:grid-cols-3">
                        <div className="sm:col-span-3">
                            <label className="mb-1 block text-[10px] font-bold uppercase text-muted">Entity</label>
                            <EntitySelect
                                entities={haEntities}
                                value={load.entity || ''}
                                onChange={(val) => updateShedLoad(load.device_id, { entity: val })}
                                loading={haLoading}
                                placeholder="Select Home Assistant entity..."
                                disabled={disabled}
                            />
                        </div>
                        <div>
                            <label className="mb-1 block text-[10px] font-bold uppercase text-muted">On Value</label>
                            <input
                                type="text"
                                value={load.on_value ?? '1'}
                                onChange={(e) => updateShedLoad(load.device_id, { on_value: e.target.value })}
                                disabled={disabled}
                                className="w-full rounded-lg border border-line/50 bg-surface2 px-2 py-1.5 text-xs text-text focus:border-accent focus:outline-none disabled:opacity-50"
                            />
                        </div>
                        <div>
                            <label className="mb-1 block text-[10px] font-bold uppercase text-muted">Off Value</label>
                            <input
                                type="text"
                                value={load.off_value ?? '0'}
                                onChange={(e) => updateShedLoad(load.device_id, { off_value: e.target.value })}
                                disabled={disabled}
                                className="w-full rounded-lg border border-line/50 bg-surface2 px-2 py-1.5 text-xs text-text focus:border-accent focus:outline-none disabled:opacity-50"
                            />
                        </div>
                        <div>
                            <label className="mb-1 block text-[10px] font-bold uppercase text-muted">Power (kW)</label>
                            <input
                                type="number"
                                min={0}
                                step={0.1}
                                value={load.power_kw ?? ''}
                                onChange={(e) =>
                                    updateShedLoad(load.device_id, {
                                        power_kw: e.target.value === '' ? undefined : Number(e.target.value),
                                    })
                                }
                                disabled={disabled}
                                placeholder="Unknown"
                                className="w-full rounded-lg border border-line/50 bg-surface2 px-2 py-1.5 text-xs text-text focus:border-accent focus:outline-none disabled:opacity-50"
                            />
                        </div>
                        <div className="sm:col-span-2">
                            <label className="mb-1 block text-[10px] font-bold uppercase text-muted">
                                Power sensor (optional)
                            </label>
                            <EntitySelect
                                entities={haEntities}
                                value={load.power_sensor || ''}
                                onChange={(val) => updateShedLoad(load.device_id, { power_sensor: val || undefined })}
                                loading={haLoading}
                                placeholder="Select live power sensor..."
                                disabled={disabled}
                            />
                        </div>
                        <p className="text-[10px] leading-relaxed text-muted sm:col-span-3">
                            After this load is switched off to protect the fuse, it is only switched back on when there
                            is room for its power: the live power sensor (while it reads a real draw), else the power
                            above. With neither, it is only restored when its whole phase is free.
                        </p>
                    </div>
                )}
                <div className="grid grid-cols-1 gap-3 border-t border-line/10 pt-2 sm:grid-cols-2">
                    <div>
                        <label className="mb-1 block text-[10px] font-bold uppercase text-muted">
                            Minimum on time (s)
                        </label>
                        <input
                            type="number"
                            min={0}
                            max={3600}
                            value={load.min_on_s ?? 300}
                            onChange={(e) => updateShedLoad(load.device_id, { min_on_s: Number(e.target.value) })}
                            disabled={disabled}
                            className="w-full rounded-lg border border-line/50 bg-surface2 px-2 py-1.5 text-xs text-text focus:border-accent focus:outline-none disabled:opacity-50"
                        />
                    </div>
                    <div>
                        <label className="mb-1 block text-[10px] font-bold uppercase text-muted">
                            Minimum off time (s)
                        </label>
                        <input
                            type="number"
                            min={0}
                            max={3600}
                            value={load.min_off_s ?? 300}
                            onChange={(e) => updateShedLoad(load.device_id, { min_off_s: Number(e.target.value) })}
                            disabled={disabled}
                            className="w-full rounded-lg border border-line/50 bg-surface2 px-2 py-1.5 text-xs text-text focus:border-accent focus:outline-none disabled:opacity-50"
                        />
                    </div>
                    <p className="text-[10px] leading-relaxed text-muted sm:col-span-2">
                        Keeps the load from switching too often: the plan cannot switch it (water heaters) or the
                        balancer restore it before these times have passed. Switching off to protect the fuse is always
                        immediate.
                    </p>
                </div>
            </div>
        )
    }

    return (
        <div className="col-span-2 space-y-3">
            <div className="flex items-start justify-between gap-4 rounded-xl border border-line/20 bg-surface2/30 p-3">
                <div className="space-y-ds-2 text-sm text-muted">
                    <p>Only include loads whose reduction lowers current through the protected fuse.</p>
                    <details>
                        <summary className="cursor-pointer">How the give-way order works</summary>
                        <p className="mt-ds-2">
                            The top entry gives way first; recovery follows the reverse order. EV chargers throttle then
                            pause; the battery lowers grid charging then pauses; on/off loads switch off. Removing an
                            entry only excludes it from load balancing. Its normal device configuration stays in place.
                            Phase assignments must match physical wiring.
                        </p>
                    </details>
                </div>
                {!disabled && (
                    <button
                        type="button"
                        onClick={() => setAdding((open) => !open)}
                        className="flex shrink-0 items-center gap-1.5 rounded-lg border border-line/50 bg-surface2 px-3 py-1.5 text-xs font-semibold transition-colors hover:bg-good/20 hover:text-good"
                    >
                        <Plus size={14} />
                        Add Load
                    </button>
                )}
            </div>

            {adding && !disabled && (
                <div className="flex flex-wrap items-center gap-ds-2">
                    <select
                        className="input"
                        aria-label="Load to add"
                        value={selectedLoad}
                        onChange={(event) => setSelectedLoad(event.target.value)}
                    >
                        <option value="">Select a load…</option>
                        {batteryAvailable && <option value="battery">House battery (grid charging)</option>}
                        {availableChargers.map((charger) => (
                            <option key={charger.id} value={`charger:${charger.id}`}>
                                {charger.name} (dynamic current)
                            </option>
                        ))}
                        <option value="on_off">Water heater, on/off charger or custom entity</option>
                    </select>
                    <button type="button" className="btn btn-secondary" disabled={!selectedLoad} onClick={addLoad}>
                        Add selected load
                    </button>
                </div>
            )}

            {entries.length === 0 && (
                <div className="rounded-xl border border-dashed border-line/20 bg-surface-elevated px-4 py-6 text-center">
                    <div className="text-sm text-muted">
                        Nothing to balance yet. Use Add Load to select a battery, EV charger, water heater or custom
                        entity.
                    </div>
                </div>
            )}

            <OrderedListEditor
                items={entries}
                keyFor={(e) => `${e.kind}:${e.id}`}
                onReorder={onChangeOrder}
                disabled={disabled}
                itemLabel="give-way entry"
                renderItem={(entry) => {
                    if (entry.kind === 'battery') return renderBatteryRow()
                    if (entry.kind === 'charger') {
                        const charger = chargers.find((c) => c.id === entry.id)
                        return charger ? renderChargerRow(charger) : null
                    }
                    const load = loads.find((l) => l.device_id === entry.id)
                    return load ? renderShedRow(load) : null
                }}
            />
        </div>
    )
}
