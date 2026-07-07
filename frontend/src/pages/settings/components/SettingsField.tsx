import React from 'react'
import { BaseField, HaEntity } from '../types'
import { shouldRenderField } from '../logic'
import type { WaterHeaterEntity, EVChargerEntity } from './EntityArrayEditor'
import Tooltip from '../../../components/Tooltip'
import AzimuthDial from '../../../components/AzimuthDial'
import TiltDial from '../../../components/TiltDial'
import EntitySelect from '../../../components/EntitySelect'
import ServiceSelect from '../../../components/ServiceSelect'
import Select from '../../../components/ui/Select'
import Switch from '../../../components/ui/Switch'
import { Badge } from '../../../components/ui/Badge'
import configHelp from '../../../config-help.json'
import { SolarArraysEditor } from './SolarArraysEditor'
import { PenaltyLevelsEditor } from './PenaltyLevelsEditor'
import { EntityArrayEditor } from './EntityArrayEditor'
import { GiveWayListEditor, type GiveWayEntry, type ShedLoad } from './GiveWayListEditor'
import { ExcessPvPriorityEditor, type ExcessPvPriorityEntry } from './ExcessPvPriorityEditor'
import { NumberInput } from '../../../components/ui/NumberInput'

interface SettingsFieldProps {
    field: BaseField
    value: string
    onChange: (key: string, value: string) => void
    error?: string
    haEntities?: HaEntity[]
    haLoading?: boolean
    fullForm?: Record<string, string | boolean | number | undefined>
    config?: Record<string, unknown>
    advancedMode?: boolean
}

export const SettingsField: React.FC<SettingsFieldProps> = ({
    field,
    value,
    onChange,
    error,
    haEntities = [],
    haLoading = false,
    fullForm = {},
    config,
}) => {
    const isEnabled = React.useMemo(() => {
        return shouldRenderField(field, fullForm as Record<string, string | boolean | number | undefined>, config)
    }, [field, fullForm, config])

    const isDisabled = field.disabled || !isEnabled

    const renderInput = () => {
        switch (field.type) {
            case 'boolean':
                return (
                    <div className="flex items-center gap-3 pt-2">
                        <Switch
                            checked={value === 'true'}
                            onCheckedChange={(checked) => onChange(field.key, checked ? 'true' : 'false')}
                            disabled={isDisabled}
                        />
                        <div className="flex items-center gap-1.5">
                            <span className="text-sm font-semibold">{field.label}</span>
                            <Tooltip text={(configHelp as Record<string, string>)[field.key] || field.helper} />
                        </div>
                    </div>
                )

            case 'select':
                return (
                    <Select
                        value={value}
                        onChange={(val) => onChange(field.key, val)}
                        options={field.options || []}
                        placeholder="Select..."
                        disabled={isDisabled}
                    />
                )

            case 'entity': {
                const selectedEntity = haEntities?.find((e) => e.entity_id === value)
                const unit = selectedEntity?.unit_of_measurement

                const getUnitFeedback = () => {
                    if (!unit) return null
                    const lower = unit.toLowerCase()
                    if (lower === 'a') {
                        return { text: `Detected Unit: ${unit}`, className: 'text-good/80' }
                    }
                    if (lower === 'w' || lower === 'kw') {
                        return { text: `Detected Unit: ${unit}`, className: 'text-accent/90' }
                    }
                    return { text: `Unit: ${unit}`, className: 'text-muted/80' }
                }

                const feedback = getUnitFeedback()

                return (
                    <div>
                        <div className="flex items-center gap-2">
                            <div className="flex-1">
                                <EntitySelect
                                    entities={haEntities}
                                    value={value}
                                    onChange={(val) => onChange(field.key, val)}
                                    loading={haLoading}
                                    placeholder="Select entity..."
                                />
                            </div>
                            {field.companionKey && (
                                <button
                                    type="button"
                                    onClick={() => {
                                        const current = fullForm[field.companionKey!] === 'true'
                                        onChange(field.companionKey!, current ? 'false' : 'true')
                                    }}
                                    className={`flex h-9 w-9 shrink-0 items-center justify-center rounded-xl border transition-all duration-200 ${
                                        fullForm[field.companionKey] === 'true'
                                            ? 'bg-accent/20 border-accent/50 text-accent shadow-[0_0_10px_rgba(var(--accent-rgb),0.1)]'
                                            : 'bg-surface2 border-line/50 text-muted hover:border-accent/40 hover:text-text'
                                    }`}
                                    title="Invert sensor logic (Positive <-> Negative)"
                                >
                                    <span className="text-sm font-bold">±</span>
                                </button>
                            )}
                        </div>
                        {feedback && (
                            <p className={`text-[10px] mt-1 transition-all ${feedback.className}`}>{feedback.text}</p>
                        )}
                    </div>
                )
            }

            case 'service':
                return (
                    <ServiceSelect
                        value={value}
                        onChange={(val) => onChange(field.key, val)}
                        placeholder="Select notification service..."
                    />
                )

            case 'azimuth': {
                const numericValue = value && value.trim() !== '' ? Number(value) : null
                return (
                    <div className="space-y-2">
                        <AzimuthDial
                            value={
                                typeof numericValue === 'number' && !Number.isNaN(numericValue) ? numericValue : null
                            }
                            onChange={(deg) => onChange(field.key, String(Math.round(deg)))}
                        />
                        <input
                            type="number"
                            inputMode="decimal"
                            value={value}
                            onChange={(e) => onChange(field.key, e.target.value)}
                            className="w-full rounded-lg border border-line/50 bg-surface2 px-3 py-2 text-sm text-text focus:border-accent focus:outline-none"
                        />
                    </div>
                )
            }

            case 'tilt': {
                const numericValue = value && value.trim() !== '' ? Number(value) : null
                return (
                    <div className="space-y-2">
                        <TiltDial
                            value={
                                typeof numericValue === 'number' && !Number.isNaN(numericValue) ? numericValue : null
                            }
                            onChange={(deg) => onChange(field.key, String(Math.round(deg)))}
                        />
                        <input
                            type="number"
                            inputMode="decimal"
                            value={value}
                            onChange={(e) => onChange(field.key, e.target.value)}
                            className="w-full rounded-lg border border-line/50 bg-surface2 px-3 py-2 text-sm text-text focus:border-accent focus:outline-none"
                        />
                    </div>
                )
            }

            case 'solar_arrays':
                return (
                    <SolarArraysEditor
                        arrays={JSON.parse(value || '[]')}
                        onChange={(arrays) => onChange(field.key, JSON.stringify(arrays))}
                        disabled={isDisabled}
                    />
                )
            case 'penalty_levels':
                return (
                    <PenaltyLevelsEditor
                        value={value}
                        onChange={(levels) => onChange(field.key, JSON.stringify(levels))}
                        disabled={isDisabled}
                    />
                )
            case 'entity_array': {
                // eslint-disable-next-line @typescript-eslint/no-explicit-any
                const entityField = field as any
                const entityType = entityField.entityType as 'water_heater' | 'ev_charger'
                const entities = JSON.parse(value || '[]') as WaterHeaterEntity[] | EVChargerEntity[]
                return (
                    <EntityArrayEditor
                        entities={entities}
                        entityType={entityType}
                        onChange={(newEntities) => onChange(field.key, JSON.stringify(newEntities))}
                        disabled={isDisabled}
                        haEntities={haEntities}
                        haLoading={haLoading}
                    />
                )
            }
            case 'give_way_list':
                // Edits both give_way_order (this field) and load_balancing.loads
                // (a hidden companion field in the same form).
                return (
                    <GiveWayListEditor
                        orderValue={value}
                        loadsValue={String(fullForm['load_balancing.loads'] ?? '[]')}
                        onChangeOrder={(entries: GiveWayEntry[]) => onChange(field.key, JSON.stringify(entries))}
                        onChangeLoads={(loads: ShedLoad[]) => onChange('load_balancing.loads', JSON.stringify(loads))}
                        disabled={isDisabled}
                        config={config}
                        haEntities={haEntities}
                        haLoading={haLoading}
                    />
                )
            case 'excess_pv_priority':
                return (
                    <ExcessPvPriorityEditor
                        value={value}
                        onChange={(entries: ExcessPvPriorityEntry[]) => onChange(field.key, JSON.stringify(entries))}
                        disabled={isDisabled}
                        config={config}
                        haEntities={haEntities}
                        haLoading={haLoading}
                    />
                )
            case 'info':
                return (
                    <div className="flex items-start gap-3 p-4 bg-ai/5 border border-ai/20 rounded-2xl">
                        <div className="p-2 bg-ai/10 rounded-lg shrink-0">
                            <span className="text-ai text-sm font-bold">ⓘ</span>
                        </div>
                        <div className="space-y-1">
                            <p className="text-xs font-bold text-ai/80 uppercase tracking-wider">Willingness to Pay</p>
                            <p className="text-[11px] text-muted leading-relaxed">
                                Defines the maximum electricity price (SEK/kWh) you are willing to pay for each charge
                                level.
                                <span className="text-text/80 mx-1 border-b border-dotted border-muted/50 pb-0.5 whitespace-nowrap">
                                    High values
                                </span>{' '}
                                force charging regardless of grid price.
                                <span className="text-text/80 mx-1 border-b border-dotted border-muted/50 pb-0.5 whitespace-nowrap">
                                    Low values
                                </span>{' '}
                                wait for cheap electricity.
                            </p>
                        </div>
                    </div>
                )
            case 'number':
            case 'text':
            case 'array':
            default: {
                if (field.type === 'number') {
                    // eslint-disable-next-line @typescript-eslint/no-explicit-any
                    const numField = field as any
                    return (
                        <NumberInput
                            value={value}
                            onChange={(val) => onChange(field.key, val)}
                            disabled={isDisabled}
                            className={isDisabled ? 'opacity-50 cursor-not-allowed' : ''}
                            step={numField.step ? Number(numField.step) : undefined}
                            min={numField.min ? Number(numField.min) : undefined}
                            max={numField.max ? Number(numField.max) : undefined}
                        />
                    )
                }
                return (
                    <input
                        type="text"
                        value={value}
                        onChange={(e) => onChange(field.key, e.target.value)}
                        className={`w-full rounded-lg border border-line/50 bg-surface2 px-3 py-2 text-sm text-text focus:border-accent focus:outline-none ${
                            isDisabled ? 'opacity-50 cursor-not-allowed' : ''
                        }`}
                        disabled={isDisabled}
                    />
                )
            }
        }
    }

    if (!isEnabled && !field.showIf?.disabledText) {
        return null
    }

    return (
        <div className={`space-y-1 ${!isEnabled ? 'opacity-40 pointer-events-none' : ''} ${field.className || ''}`}>
            {!isEnabled && field.showIf?.disabledText && (
                <div className="text-xs text-muted italic mb-1">{field.showIf.disabledText}</div>
            )}
            {field.type !== 'boolean' && field.type !== 'info' && (
                <label className="block text-sm font-medium mb-1.5 flex items-center gap-1.5">
                    <span className="text-[10px] uppercase tracking-wide text-muted">{field.label}</span>
                    {field.notImplemented && <Badge variant="warning">NOT IMPLEMENTED</Badge>}
                    <Tooltip text={(configHelp as Record<string, string>)[field.key] || field.helper} />
                </label>
            )}
            {renderInput()}
            {error && <p className="text-[11px] text-bad">{error}</p>}
        </div>
    )
}
