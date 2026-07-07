import React, { useState } from 'react'
import { ChevronDown, ChevronUp, Plus, Trash2 } from 'lucide-react'
import EntitySelect from '../../../components/EntitySelect'
import Select from '../../../components/ui/Select'
import { NumberInput } from '../../../components/ui/NumberInput'
import OrderedListEditor from '../../../components/ui/OrderedListEditor'
import { HaEntity } from '../types'

export type ExcessPvSinkType = 'ev' | 'water_heater_boost' | 'custom_entity'

export interface ExcessPvPriorityEntry {
    type: ExcessPvSinkType
    charger_id?: string
    surplus_deadband_kw?: number
    reward_sek_per_kwh?: number
    entity?: string
    on_value?: string
    off_value?: string
    power_kw?: number
}

interface ChargerOption {
    id: string
    name: string
}

interface ExcessPvPriorityEditorProps {
    /** JSON string of executor.excess_pv.priority */
    value: string
    onChange: (entries: ExcessPvPriorityEntry[]) => void
    disabled?: boolean
    config?: Record<string, unknown>
    haEntities?: HaEntity[]
    haLoading?: boolean
}

const TYPE_LABELS: Record<ExcessPvSinkType, string> = {
    ev: 'EV Surplus Charging',
    water_heater_boost: 'Water Heater Boost',
    custom_entity: 'Custom Entity',
}

function parseJsonArray<T>(raw: string): T[] {
    try {
        const parsed: unknown = JSON.parse(raw || '[]')
        return Array.isArray(parsed) ? (parsed as T[]) : []
    } catch {
        return []
    }
}

export const ExcessPvPriorityEditor: React.FC<ExcessPvPriorityEditorProps> = ({
    value,
    onChange,
    disabled = false,
    config,
    haEntities = [],
    haLoading = false,
}) => {
    const entries = parseJsonArray<ExcessPvPriorityEntry>(value)
    const [expandedIndex, setExpandedIndex] = useState<number | null>(null)

    const systemCfg = (config?.system as { has_water_heater?: boolean } | undefined) || {}
    const hasWaterHeater = systemCfg.has_water_heater !== false

    const currentTypeChargers: ChargerOption[] = (
        (config?.ev_chargers as { id: string; name?: string; type?: string; enabled?: boolean }[] | undefined) || []
    )
        .filter((c) => c.type === 'current' && c.enabled !== false)
        .map((c) => ({ id: c.id, name: c.name || c.id }))

    const hasBoostEntry = entries.some((e) => e.type === 'water_heater_boost')
    const hasEvChargerAvailable = currentTypeChargers.length > 0

    const addableOptions: { label: string; value: ExcessPvSinkType }[] = [
        ...(hasEvChargerAvailable ? [{ label: TYPE_LABELS.ev, value: 'ev' as ExcessPvSinkType }] : []),
        ...(hasWaterHeater && !hasBoostEntry
            ? [{ label: TYPE_LABELS.water_heater_boost, value: 'water_heater_boost' as ExcessPvSinkType }]
            : []),
        { label: TYPE_LABELS.custom_entity, value: 'custom_entity' as ExcessPvSinkType },
    ]

    const stableKeyFor = (entry: ExcessPvPriorityEntry): string => {
        if (entry.type === 'ev') return `ev:${entry.charger_id || ''}`
        if (entry.type === 'custom_entity') return `custom_entity:${entry.entity || ''}`
        return 'water_heater_boost'
    }

    const addEntry = (type: ExcessPvSinkType) => {
        const entry: ExcessPvPriorityEntry =
            type === 'ev'
                ? { type, charger_id: currentTypeChargers[0]?.id || '', surplus_deadband_kw: 0.2 }
                : type === 'custom_entity'
                  ? { type, entity: '', on_value: '1', off_value: '0', power_kw: 1.0 }
                  : { type }
        onChange([...entries, entry])
        setExpandedIndex(entries.length)
    }

    const removeEntry = (index: number) => {
        onChange(entries.filter((_, i) => i !== index))
        setExpandedIndex(null)
    }

    const updateEntry = (index: number, updates: Partial<ExcessPvPriorityEntry>) => {
        onChange(entries.map((e, i) => (i === index ? { ...e, ...updates } : e)))
    }

    const summaryFor = (entry: ExcessPvPriorityEntry): string => {
        if (entry.type === 'ev') {
            const charger = currentTypeChargers.find((c) => c.id === entry.charger_id)
            return charger?.name || entry.charger_id || '(no charger selected)'
        }
        if (entry.type === 'custom_entity') {
            return entry.entity || '(no entity set)'
        }
        return 'Heats water to max temperature'
    }

    const renderEntry = (entry: ExcessPvPriorityEntry, index: number) => {
        const isExpanded = expandedIndex === index
        const isEvMissingCharger = entry.type === 'ev' && !entry.charger_id
        const isCustomMissingEntity = entry.type === 'custom_entity' && !entry.entity

        return (
            <div className="py-1 pr-1">
                <button
                    type="button"
                    onClick={() => setExpandedIndex(isExpanded ? null : index)}
                    className="flex w-full items-center gap-x-3 gap-y-1 text-left"
                >
                    {isExpanded ? (
                        <ChevronUp size={14} className="shrink-0 text-muted" />
                    ) : (
                        <ChevronDown size={14} className="shrink-0 text-muted" />
                    )}
                    <div className="min-w-0 flex-1">
                        <div className="flex items-center gap-2">
                            <span className="truncate text-sm font-semibold text-text">{TYPE_LABELS[entry.type]}</span>
                            {(isEvMissingCharger || isCustomMissingEntity) && (
                                <span className="rounded bg-bad/10 px-1.5 py-0.5 text-[9px] font-bold text-bad">
                                    incomplete
                                </span>
                            )}
                        </div>
                        <div className="truncate text-[11px] text-muted">{summaryFor(entry)}</div>
                    </div>
                    {!disabled && (
                        <span
                            role="button"
                            aria-label={`Remove ${TYPE_LABELS[entry.type]} entry`}
                            onClick={(e) => {
                                e.stopPropagation()
                                removeEntry(index)
                            }}
                            className="shrink-0 rounded-lg p-1.5 text-muted transition-colors hover:bg-bad/10 hover:text-bad"
                        >
                            <Trash2 size={14} />
                        </span>
                    )}
                </button>

                {isExpanded && (
                    <div className="mt-3 space-y-3 border-t border-line/10 pt-3">
                        {entry.type === 'ev' && (
                            <>
                                <div>
                                    <label className="mb-1 block text-[10px] font-bold uppercase text-muted">
                                        Charger
                                    </label>
                                    <Select
                                        value={entry.charger_id || ''}
                                        onChange={(val) => updateEntry(index, { charger_id: val })}
                                        options={currentTypeChargers.map((c) => ({ label: c.name, value: c.id }))}
                                        placeholder={
                                            currentTypeChargers.length === 0
                                                ? 'No current-type chargers configured'
                                                : 'Select charger...'
                                        }
                                        disabled={disabled || currentTypeChargers.length === 0}
                                    />
                                </div>
                                <div>
                                    <label className="mb-1 block text-[10px] font-bold uppercase text-muted">
                                        Surplus Deadband (kW)
                                    </label>
                                    <NumberInput
                                        value={entry.surplus_deadband_kw ?? 0.2}
                                        onChange={(val) => updateEntry(index, { surplus_deadband_kw: Number(val) })}
                                        disabled={disabled}
                                        step={0.05}
                                        min={0}
                                    />
                                    <p className="mt-1 text-[10px] text-muted">
                                        How much export/import must exist before the executor adjusts the charge
                                        current.
                                    </p>
                                </div>
                            </>
                        )}

                        {entry.type === 'custom_entity' && (
                            <>
                                <div>
                                    <label className="mb-1 block text-[10px] font-bold uppercase text-muted">
                                        Entity
                                    </label>
                                    <EntitySelect
                                        entities={haEntities}
                                        value={entry.entity || ''}
                                        onChange={(val) => updateEntry(index, { entity: val })}
                                        loading={haLoading}
                                        placeholder="Select Home Assistant entity..."
                                        disabled={disabled}
                                    />
                                    {isCustomMissingEntity && (
                                        <p className="mt-1 text-[10px] text-bad">Entity is required.</p>
                                    )}
                                </div>
                                <div className="grid grid-cols-1 gap-3 sm:grid-cols-3">
                                    <div>
                                        <label className="mb-1 block text-[10px] font-bold uppercase text-muted">
                                            On Value
                                        </label>
                                        <input
                                            type="text"
                                            value={entry.on_value ?? '1'}
                                            onChange={(e) => updateEntry(index, { on_value: e.target.value })}
                                            disabled={disabled}
                                            className="w-full rounded-lg border border-line/50 bg-surface2 px-2 py-1.5 text-xs text-text focus:border-accent focus:outline-none disabled:opacity-50"
                                        />
                                    </div>
                                    <div>
                                        <label className="mb-1 block text-[10px] font-bold uppercase text-muted">
                                            Off Value
                                        </label>
                                        <input
                                            type="text"
                                            value={entry.off_value ?? '0'}
                                            onChange={(e) => updateEntry(index, { off_value: e.target.value })}
                                            disabled={disabled}
                                            className="w-full rounded-lg border border-line/50 bg-surface2 px-2 py-1.5 text-xs text-text focus:border-accent focus:outline-none disabled:opacity-50"
                                        />
                                    </div>
                                    <div>
                                        <label className="mb-1 block text-[10px] font-bold uppercase text-muted">
                                            Power (kW)
                                        </label>
                                        <NumberInput
                                            value={entry.power_kw ?? 1.0}
                                            onChange={(val) => updateEntry(index, { power_kw: Number(val) })}
                                            disabled={disabled}
                                            step={0.1}
                                            min={0}
                                        />
                                    </div>
                                </div>
                            </>
                        )}

                        <div>
                            <label className="mb-1 block text-[10px] font-bold uppercase text-muted">
                                Reward Override (SEK/kWh)
                            </label>
                            <NumberInput
                                value={entry.reward_sek_per_kwh ?? ''}
                                onChange={(val) =>
                                    updateEntry(index, {
                                        reward_sek_per_kwh: val === '' ? undefined : Number(val),
                                    })
                                }
                                disabled={disabled}
                                step={0.05}
                                min={0}
                                placeholder="Auto (rank-scaled)"
                            />
                            <p className="mt-1 text-[10px] text-muted">
                                Optional. Leave blank to use the default priority-scaled reward (15% lower per rank).
                            </p>
                        </div>
                    </div>
                )}
            </div>
        )
    }

    return (
        <div className="space-y-3">
            <div className="rounded-xl border border-line/20 bg-surface2/30 p-3">
                <p className="text-[11px] leading-relaxed text-muted">
                    List order is priority order — the <b>top</b> entry is fed surplus PV first. The house battery is
                    always implicitly first (gated by the SoC threshold below). Multiple sinks can be active at once
                    when surplus is large enough.
                </p>
            </div>

            {entries.length === 0 && (
                <div className="rounded-xl border border-dashed border-line/20 bg-surface-elevated px-4 py-6 text-center">
                    <div className="text-sm text-muted">
                        Excess-PV dispatch is disabled. Add a sink below to enable it.
                    </div>
                </div>
            )}

            <OrderedListEditor
                items={entries}
                keyFor={stableKeyFor}
                onReorder={onChange}
                disabled={disabled}
                itemLabel="excess-PV sink"
                renderItem={renderEntry}
            />

            {!disabled && (
                <div className="flex items-center gap-2">
                    <Select
                        value=""
                        onChange={(val) => {
                            if (val) addEntry(val as ExcessPvSinkType)
                        }}
                        options={addableOptions}
                        placeholder="Add a sink..."
                    />
                    <Plus size={16} className="shrink-0 text-muted" />
                </div>
            )}
            {!hasEvChargerAvailable && (
                <p className="text-[11px] text-muted">
                    Enable variable current control (<code>type: current</code>) on an EV charger in the EV tab to add
                    an EV Surplus Charging sink.
                </p>
            )}
        </div>
    )
}
