import React, { useState } from 'react'
import { Link } from 'react-router-dom'
import { Plus, Trash2, ChevronDown, ChevronUp } from 'lucide-react'
import { motion, AnimatePresence } from 'framer-motion'
import { Badge } from '../../../components/ui/Badge'
import Switch from '../../../components/ui/Switch'
import EntitySelect from '../../../components/EntitySelect'
import { NumberInput } from '../../../components/ui/NumberInput'
import { HaEntity } from '../types'
import Tooltip from '../../../components/Tooltip'

// Water Heater Entity Type
export interface WaterHeaterEntity {
    id: string
    name: string
    enabled: boolean
    power_kw: number
    min_kwh_per_day: number
    max_hours_between_heating: number
    water_min_spacing_hours: number
    sensor: string
    target_entity: string
    type: 'binary' | 'modulating'
}

// EV Charger Entity Type
export interface EVChargerEntity {
    id: string
    name: string
    enabled: boolean
    max_power_kw: number
    battery_capacity_kwh: number
    sensor: string
    soc_sensor: string
    plug_sensor: string
    type: 'binary' | 'current'
    nominal_power_kw: number
    penalty_levels?: Array<{ max_soc: number; penalty_sek: number }>
    departure_time?: string
    switch_entity?: string
    replan_on_plugin?: boolean
    replan_on_unplug?: boolean
    current_entity?: string
    min_current_a?: number
    max_current_a?: number
    phases?: number[]
    phase_sensor_l1?: string
    phase_sensor_l2?: string
    phase_sensor_l3?: string
    phase_mode_entity?: string
    phase_switching_enabled?: boolean
    phase_switch_hysteresis_kw?: number
    phase_switch_min_dwell_s?: number
    ha_ready_by_entity?: string
    ha_target_soc_entity?: string
    target_soc_percent?: number
    ready_by?: string
    repeat?: string
    ready_by_date?: string
    keep_on_after_target?: boolean
}

type EntityType = 'water_heater' | 'ev_charger'

interface EntityArrayEditorProps {
    entities: WaterHeaterEntity[] | EVChargerEntity[]
    entityType: EntityType
    onChange: (entities: WaterHeaterEntity[] | EVChargerEntity[]) => void
    disabled?: boolean
    haEntities?: HaEntity[]
    haLoading?: boolean
}

const createDefaultWaterHeater = (index: number): WaterHeaterEntity => ({
    id: `water_heater_${index + 1}`,
    name: `Water Heater ${index + 1}`,
    enabled: true,
    power_kw: 3.0,
    min_kwh_per_day: 6.0,
    max_hours_between_heating: 8,
    water_min_spacing_hours: 4,
    sensor: '',
    target_entity: '',
    type: 'binary',
})

const createDefaultEVCharger = (index: number): EVChargerEntity => ({
    id: `ev_charger_${index + 1}`,
    name: `EV Charger ${index + 1}`,
    enabled: true,
    max_power_kw: 11.0,
    battery_capacity_kwh: 82.0,
    sensor: '',
    soc_sensor: '',
    plug_sensor: '',
    type: 'binary',
    nominal_power_kw: 11.0,
    penalty_levels: [
        { max_soc: 50, penalty_sek: 0.5 },
        { max_soc: 80, penalty_sek: 0.2 },
        { max_soc: 100, penalty_sek: 0.0 },
    ],
    departure_time: '',
    switch_entity: '',
    replan_on_plugin: true,
    replan_on_unplug: false,
    current_entity: '',
    min_current_a: 6,
    phases: [1, 2, 3],
    phase_mode_entity: '',
    phase_switching_enabled: false,
    phase_switch_hysteresis_kw: 0.5,
    phase_switch_min_dwell_s: 600,
    target_soc_percent: 80,
    ready_by: '07:00',
    repeat: 'daily',
    keep_on_after_target: false,
    ha_ready_by_entity: '',
    ha_target_soc_entity: '',
})

export const EntityArrayEditor: React.FC<EntityArrayEditorProps> = ({
    entities,
    entityType,
    onChange,
    disabled = false,
    haEntities = [],
    haLoading = false,
}) => {
    const [expandedIndex, setExpandedIndex] = useState<number | null>(entities.length > 0 ? 0 : null)

    const isWaterHeater = entityType === 'water_heater'
    const maxEntities = isWaterHeater ? 4 : 3
    const title = isWaterHeater ? 'Water Heaters' : 'EV Chargers'
    const addEntity = () => {
        if (entities.length >= maxEntities) return
        const newEntity = isWaterHeater
            ? createDefaultWaterHeater(entities.length)
            : createDefaultEVCharger(entities.length)
        const newEntities = [...entities, newEntity] as WaterHeaterEntity[] | EVChargerEntity[]
        onChange(newEntities)
        setExpandedIndex(newEntities.length - 1)
    }

    const removeEntity = (index: number) => {
        const newEntities = entities.filter((_, i) => i !== index) as WaterHeaterEntity[] | EVChargerEntity[]
        onChange(newEntities)
        if (expandedIndex === index) {
            setExpandedIndex(null)
        } else if (expandedIndex !== null && expandedIndex > index) {
            setExpandedIndex(expandedIndex - 1)
        }
    }

    const updateEntity = (index: number, updates: Partial<WaterHeaterEntity | EVChargerEntity>) => {
        const newEntities = entities.map((e, i) => (i === index ? { ...e, ...updates } : e)) as
            | WaterHeaterEntity[]
            | EVChargerEntity[]
        onChange(newEntities)
    }

    const toggleEnabled = (index: number) => {
        const entity = entities[index]
        updateEntity(index, { enabled: !entity.enabled } as Partial<WaterHeaterEntity | EVChargerEntity>)
    }

    const totalPower = entities.reduce(
        (sum, e) =>
            sum +
            (Number(
                e.enabled
                    ? isWaterHeater
                        ? (e as WaterHeaterEntity).power_kw
                        : (e as EVChargerEntity).max_power_kw
                    : 0,
            ) || 0),
        0,
    )
    const enabledCount = entities.filter((e) => e.enabled).length

    return (
        <div className="space-y-4 col-span-2">
            <div className="flex items-center justify-between bg-surface-elevated p-3 rounded-xl border border-line/40">
                <div className="flex items-center gap-3">
                    <span className="text-xs font-bold uppercase tracking-wider text-muted">{title}</span>
                    <Badge variant={enabledCount === 0 ? 'warning' : 'info'}>
                        {enabledCount} / {entities.length} enabled · {totalPower.toFixed(1)} kW total
                    </Badge>
                </div>
                {!disabled && (
                    <button
                        type="button"
                        onClick={addEntity}
                        disabled={entities.length >= maxEntities}
                        className="flex items-center gap-1.5 px-3 py-1.5 rounded-lg bg-surface2 hover:bg-good/20 hover:text-good border border-line/50 transition-colors disabled:opacity-30 text-xs font-semibold"
                    >
                        <Plus size={14} />
                        Add {isWaterHeater ? 'Heater' : 'Charger'}
                    </button>
                )}
            </div>

            <div className="space-y-3 overflow-visible pb-4">
                {entities.length === 0 && (
                    <div className="text-center py-8 px-4 bg-surface-elevated rounded-xl border border-line/20 border-dashed">
                        <div className="text-muted text-sm mb-2">No {title.toLowerCase()} configured</div>
                        <button
                            type="button"
                            onClick={addEntity}
                            disabled={disabled}
                            className="text-accent text-xs font-semibold hover:underline disabled:opacity-50"
                        >
                            + Add your first {isWaterHeater ? 'water heater' : 'EV charger'}
                        </button>
                    </div>
                )}

                {entities.map((entity, index) => (
                    <div
                        key={entity.id || index}
                        className={`overflow-visible border rounded-xl bg-surface-elevated mb-2 transition-all duration-200 ${
                            entity.enabled ? 'border-line/40' : 'border-line/20 opacity-75'
                        }`}
                    >
                        <button
                            type="button"
                            onClick={() => setExpandedIndex(expandedIndex === index ? null : index)}
                            className="w-full flex items-center justify-between p-3 hover:bg-surface2 transition-colors text-left rounded-xl"
                        >
                            <div className="flex items-center gap-3">
                                <div
                                    className={`w-6 h-6 rounded-full flex items-center justify-center text-[10px] font-bold ${
                                        entity.enabled
                                            ? 'bg-accent/10 border border-accent/20 text-accent'
                                            : 'bg-surface2 border border-line/30 text-muted'
                                    }`}
                                >
                                    {index + 1}
                                </div>
                                <div>
                                    <div className="text-sm font-semibold flex items-center gap-2">
                                        {entity.name || `${isWaterHeater ? 'Water Heater' : 'EV Charger'} ${index + 1}`}
                                        {!entity.enabled && (
                                            <span className="text-[10px] px-1.5 py-0.5 bg-surface2 text-muted rounded-full">
                                                Disabled
                                            </span>
                                        )}
                                    </div>
                                    <div className="text-[10px] text-muted uppercase tracking-tight">
                                        {isWaterHeater
                                            ? `${(entity as WaterHeaterEntity).power_kw} kW · ${(entity as WaterHeaterEntity).min_kwh_per_day} kWh/day · ${(entity as WaterHeaterEntity).sensor || 'No sensor'}`
                                            : `${(entity as EVChargerEntity).max_power_kw} kW max · ${(entity as EVChargerEntity).battery_capacity_kwh} kWh battery · ${entity.sensor || 'No sensor'}${(entity as EVChargerEntity).soc_sensor || (entity as EVChargerEntity).plug_sensor ? ` · SoC: ${(entity as EVChargerEntity).soc_sensor || '-'}${(entity as EVChargerEntity).plug_sensor ? ` · Plug: ${(entity as EVChargerEntity).plug_sensor}` : ''}` : ''}`}
                                    </div>
                                </div>
                            </div>
                            <div className="flex items-center gap-2">
                                {!disabled && (
                                    <>
                                        <span onClick={(e) => e.stopPropagation()}>
                                            <Switch
                                                checked={entity.enabled}
                                                onCheckedChange={() => toggleEnabled(index)}
                                            />
                                        </span>
                                        <span
                                            onClick={(e) => {
                                                e.stopPropagation()
                                                removeEntity(index)
                                            }}
                                            className="p-1.5 rounded-lg text-muted hover:text-bad hover:bg-bad/10 transition-colors ml-2 cursor-pointer"
                                            role="button"
                                            aria-label="Delete"
                                            tabIndex={0}
                                            onKeyDown={(e) => {
                                                if (e.key === 'Enter' || e.key === ' ') {
                                                    e.stopPropagation()
                                                    removeEntity(index)
                                                }
                                            }}
                                        >
                                            <Trash2 size={14} />
                                        </span>
                                    </>
                                )}
                                {expandedIndex === index ? <ChevronUp size={16} /> : <ChevronDown size={16} />}
                            </div>
                        </button>

                        <AnimatePresence initial={false}>
                            {expandedIndex === index && (
                                <motion.div
                                    initial={{ height: 0, opacity: 0 }}
                                    animate={{ height: 'auto', opacity: 1 }}
                                    exit={{ height: 0, opacity: 0 }}
                                    transition={{ duration: 0.2 }}
                                    className="overflow-visible"
                                >
                                    <div className="p-4 border-t border-line/10 grid grid-cols-1 sm:grid-cols-2 gap-4">
                                        {/* ID Field - Read Only */}
                                        <div>
                                            <label className="text-[10px] uppercase font-bold text-muted mb-1.5 block">
                                                ID (Read-only)
                                            </label>
                                            <input
                                                type="text"
                                                value={entity.id}
                                                disabled
                                                className="w-full rounded-lg border border-line/30 bg-surface2/50 px-3 py-2 text-sm text-muted cursor-not-allowed"
                                            />
                                            <p className="text-[10px] text-muted mt-1">
                                                Unique identifier used internally
                                            </p>
                                        </div>

                                        {/* Name Field */}
                                        <div>
                                            <label className="text-[10px] uppercase font-bold text-muted mb-1.5 block">
                                                Display Name *
                                            </label>
                                            <input
                                                type="text"
                                                value={entity.name}
                                                onChange={(e) => updateEntity(index, { name: e.target.value })}
                                                disabled={disabled}
                                                placeholder={`e.g. Main ${isWaterHeater ? 'Tank' : 'Charger'}`}
                                                className="w-full rounded-lg border border-line/50 bg-surface2 px-3 py-2 text-sm text-text focus:border-accent focus:outline-none disabled:opacity-50"
                                            />
                                        </div>

                                        {/* Power Rating */}
                                        <div>
                                            <label className="text-[10px] uppercase font-bold text-muted mb-1.5 block">
                                                {isWaterHeater ? 'Power Rating' : 'Max Charging Power'} (kW) *
                                                {!isWaterHeater && (
                                                    <span className="normal-case font-normal text-muted/70 ml-1">
                                                        Required (e.g. 7.4, 11, 22 kW). Missing or zero disables the
                                                        charger.
                                                    </span>
                                                )}
                                            </label>
                                            <NumberInput
                                                value={
                                                    isWaterHeater
                                                        ? (entity as WaterHeaterEntity).power_kw
                                                        : (entity as EVChargerEntity).max_power_kw
                                                }
                                                onChange={(val) =>
                                                    updateEntity(index, {
                                                        [isWaterHeater ? 'power_kw' : 'max_power_kw']: Number(val),
                                                    } as Partial<WaterHeaterEntity | EVChargerEntity>)
                                                }
                                                disabled={disabled}
                                                step={0.1}
                                                min={0}
                                            />
                                        </div>

                                        {/* Daily Energy / Battery Capacity */}
                                        <div>
                                            <label className="text-[10px] uppercase font-bold text-muted mb-1.5 block">
                                                {isWaterHeater ? 'Daily Energy Requirement' : 'Battery Capacity'} (kWh)
                                            </label>
                                            <NumberInput
                                                value={
                                                    isWaterHeater
                                                        ? (entity as WaterHeaterEntity).min_kwh_per_day
                                                        : (entity as EVChargerEntity).battery_capacity_kwh
                                                }
                                                onChange={(val) =>
                                                    updateEntity(index, {
                                                        [isWaterHeater ? 'min_kwh_per_day' : 'battery_capacity_kwh']:
                                                            Number(val),
                                                    } as Partial<WaterHeaterEntity | EVChargerEntity>)
                                                }
                                                disabled={disabled}
                                                step={0.1}
                                                min={0}
                                            />
                                        </div>

                                        {/* Power Sensor */}
                                        <div className="sm:col-span-2">
                                            <label className="text-[10px] uppercase font-bold text-muted mb-1.5 block">
                                                Power sensor *
                                            </label>
                                            <EntitySelect
                                                entities={haEntities}
                                                value={entity.sensor}
                                                onChange={(val) => updateEntity(index, { sensor: val })}
                                                loading={haLoading}
                                                placeholder="Select Home Assistant power sensor..."
                                                disabled={disabled}
                                            />
                                        </div>

                                        {/* Target Entity (Water Heater only - ARC15) */}
                                        {isWaterHeater && (
                                            <div className="sm:col-span-2">
                                                <label className="text-[10px] uppercase font-bold text-muted mb-1.5 block">
                                                    Thermostat entity
                                                </label>
                                                <EntitySelect
                                                    entities={haEntities}
                                                    value={(entity as WaterHeaterEntity).target_entity}
                                                    onChange={(val) =>
                                                        updateEntity(index, {
                                                            target_entity: val,
                                                        } as Partial<WaterHeaterEntity>)
                                                    }
                                                    loading={haLoading}
                                                    placeholder="Select Home Assistant thermostat..."
                                                    disabled={disabled}
                                                />
                                                <p className="text-[10px] text-muted mt-1">
                                                    Thermostat entity for controlling water heater temperature. The
                                                    executor sets this to temp_off/temp_normal/temp_boost based on
                                                    schedule.
                                                </p>
                                            </div>
                                        )}

                                        {/* SoC Sensor (EV only) */}
                                        {!isWaterHeater && (
                                            <div className="sm:col-span-2">
                                                <label className="text-[10px] uppercase font-bold text-muted mb-1.5 block">
                                                    SoC Sensor
                                                </label>
                                                <EntitySelect
                                                    entities={haEntities}
                                                    value={(entity as EVChargerEntity).soc_sensor}
                                                    onChange={(val) =>
                                                        updateEntity(index, {
                                                            soc_sensor: val,
                                                        } as Partial<EVChargerEntity>)
                                                    }
                                                    loading={haLoading}
                                                    placeholder="Select Home Assistant SoC sensor..."
                                                    disabled={disabled}
                                                />
                                                <p className="text-[10px] text-muted mt-1">
                                                    EV battery state of charge (%) - Required for smart charging
                                                </p>
                                            </div>
                                        )}

                                        {/* Plug Sensor (EV only) */}
                                        {!isWaterHeater && (
                                            <div className="sm:col-span-2">
                                                <label className="text-[10px] uppercase font-bold text-muted mb-1.5 block">
                                                    Plug Sensor
                                                </label>
                                                <EntitySelect
                                                    entities={haEntities}
                                                    value={(entity as EVChargerEntity).plug_sensor}
                                                    onChange={(val) =>
                                                        updateEntity(index, {
                                                            plug_sensor: val,
                                                        } as Partial<EVChargerEntity>)
                                                    }
                                                    loading={haLoading}
                                                    placeholder="Select Home Assistant plug sensor..."
                                                    disabled={disabled}
                                                />
                                                <p className="text-[10px] text-muted mt-1">
                                                    EV plug status (on/off or connected/disconnected) - Required for
                                                    smart charging
                                                </p>
                                            </div>
                                        )}

                                        {/* Switch Entity (EV only) */}
                                        {!isWaterHeater && (
                                            <div className="sm:col-span-2">
                                                <label className="text-[10px] uppercase font-bold text-muted mb-1.5 block">
                                                    Switch Entity
                                                </label>
                                                <EntitySelect
                                                    entities={haEntities}
                                                    value={(entity as EVChargerEntity).switch_entity || ''}
                                                    onChange={(val) =>
                                                        updateEntity(index, {
                                                            switch_entity: val,
                                                        } as Partial<EVChargerEntity>)
                                                    }
                                                    loading={haLoading}
                                                    placeholder="Select Home Assistant switch entity..."
                                                    disabled={disabled}
                                                />
                                                <p className="text-[10px] text-muted mt-1">
                                                    Switch to enable/disable charging (e.g. switch.ev_charger)
                                                </p>
                                            </div>
                                        )}

                                        {/* HA Ready-By Entity (EV only) */}
                                        {!isWaterHeater && (
                                            <div className="sm:col-span-2">
                                                <label className="text-[10px] uppercase font-bold text-muted mb-1.5 block">
                                                    HA Ready-By Entity
                                                </label>
                                                <EntitySelect
                                                    entities={haEntities}
                                                    value={(entity as EVChargerEntity).ha_ready_by_entity || ''}
                                                    onChange={(val) =>
                                                        updateEntity(index, {
                                                            ha_ready_by_entity: val,
                                                        } as Partial<EVChargerEntity>)
                                                    }
                                                    loading={haLoading}
                                                    placeholder="Select Home Assistant input_datetime..."
                                                    disabled={disabled}
                                                />
                                                <p className="text-[10px] text-muted mt-1">
                                                    HA entity to sync ready-by time (e.g. input_datetime.ev_ready_by)
                                                </p>
                                            </div>
                                        )}

                                        {/* HA Target-SoC Entity (optional) (EV only) */}
                                        {!isWaterHeater && (
                                            <div className="sm:col-span-2">
                                                <label className="text-[10px] uppercase font-bold text-muted mb-1.5 block">
                                                    HA Target-SoC Entity (optional)
                                                </label>
                                                <EntitySelect
                                                    entities={haEntities}
                                                    value={(entity as EVChargerEntity).ha_target_soc_entity || ''}
                                                    onChange={(val) =>
                                                        updateEntity(index, {
                                                            ha_target_soc_entity: val,
                                                        } as Partial<EVChargerEntity>)
                                                    }
                                                    loading={haLoading}
                                                    placeholder="Select Home Assistant input_number..."
                                                    disabled={disabled}
                                                />
                                                <p className="text-[10px] text-muted mt-1">
                                                    HA entity to sync target SoC % (e.g. input_number.ev_target_soc)
                                                </p>
                                            </div>
                                        )}

                                        {/* Replan on Plugin (EV only) */}
                                        {!isWaterHeater && (
                                            <div>
                                                <label className="text-[10px] uppercase font-bold text-muted mb-1.5 block">
                                                    Re-plan on Plugin
                                                </label>
                                                <div className="flex items-center gap-2 mt-2">
                                                    <Switch
                                                        checked={(entity as EVChargerEntity).replan_on_plugin ?? true}
                                                        onCheckedChange={(checked) =>
                                                            updateEntity(index, {
                                                                replan_on_plugin: checked,
                                                            } as Partial<EVChargerEntity>)
                                                        }
                                                        disabled={disabled}
                                                    />
                                                    <span className="text-xs text-text">
                                                        Re-run planner immediately when plugged in
                                                    </span>
                                                </div>
                                            </div>
                                        )}

                                        {/* Type Selection */}
                                        <div>
                                            <label className="text-[10px] uppercase font-bold text-muted mb-1.5 block">
                                                Load Type
                                            </label>
                                            <select
                                                value={entity.type}
                                                onChange={(e) =>
                                                    updateEntity(index, {
                                                        type: e.target.value as 'binary' | 'modulating' | 'current',
                                                    })
                                                }
                                                disabled={disabled}
                                                className="w-full rounded-lg border border-line/50 bg-surface2 px-3 py-2 text-sm text-text focus:border-accent focus:outline-none disabled:opacity-50"
                                            >
                                                {isWaterHeater ? (
                                                    <>
                                                        <option value="binary">Binary (On/Off)</option>
                                                        <option value="modulating">Modulating</option>
                                                    </>
                                                ) : (
                                                    <>
                                                        <option value="binary">Binary (On/Off)</option>
                                                        <option value="current">Dynamic</option>
                                                    </>
                                                )}
                                            </select>
                                            {!isWaterHeater && (entity as EVChargerEntity).type === 'current' && (
                                                <details className="mt-2 text-[11px] text-muted">
                                                    <summary className="font-semibold text-accent hover:underline cursor-pointer select-none outline-none">
                                                        Choosing dynamic current means:
                                                    </summary>
                                                    <div className="mt-1.5 rounded-lg border border-ai/20 bg-ai/5 p-2.5 leading-relaxed">
                                                        <ul className="list-disc space-y-0.5 pl-4">
                                                            <li>The planner sets the charge current for every slot.</li>
                                                            <li>
                                                                The charger is automatically load-balanced — it appears
                                                                in the give-way list in the{' '}
                                                                <Link
                                                                    to="/settings?tab=load-balancing"
                                                                    className="font-semibold text-accent hover:underline"
                                                                >
                                                                    Load Balancing tab
                                                                </Link>
                                                                .
                                                            </li>
                                                            <li>It becomes eligible for PV-surplus charging.</li>
                                                        </ul>
                                                    </div>
                                                </details>
                                            )}
                                            {!isWaterHeater &&
                                                (entity as EVChargerEntity).type === 'current' &&
                                                !(entity as EVChargerEntity).soc_sensor && (
                                                    <div
                                                        role="alert"
                                                        className="mt-2 rounded-lg border border-accent/40 bg-accent/10 p-2.5 text-[11px] leading-relaxed text-text"
                                                    >
                                                        <span className="font-semibold">No SoC sensor configured:</span>{' '}
                                                        Darkstar cannot track this car&apos;s charging progress or
                                                        recover load-balancer throttling shortfall — plans assume the
                                                        battery starts at 0%. Set the SoC sensor above.
                                                    </div>
                                                )}
                                        </div>

                                        {/* Replan on Unplug (EV only) */}
                                        {!isWaterHeater && (
                                            <div>
                                                <label className="text-[10px] uppercase font-bold text-muted mb-1.5 block">
                                                    Re-plan on Unplug
                                                </label>
                                                <div className="flex items-center gap-2 mt-2">
                                                    <Switch
                                                        checked={(entity as EVChargerEntity).replan_on_unplug ?? false}
                                                        onCheckedChange={(checked) =>
                                                            updateEntity(index, {
                                                                replan_on_unplug: checked,
                                                            } as Partial<EVChargerEntity>)
                                                        }
                                                        disabled={disabled}
                                                    />
                                                    <span className="text-xs text-text">
                                                        Re-run planner immediately when unplugged
                                                    </span>
                                                </div>
                                            </div>
                                        )}

                                        {/* Water Heater Specific Fields */}
                                        {isWaterHeater && (
                                            <>
                                                <div>
                                                    <label className="text-[10px] uppercase font-bold text-muted mb-1.5 block">
                                                        Max Hours Between Heating
                                                    </label>
                                                    <NumberInput
                                                        value={(entity as WaterHeaterEntity).max_hours_between_heating}
                                                        onChange={(val) =>
                                                            updateEntity(index, {
                                                                max_hours_between_heating: Number(val),
                                                            } as Partial<WaterHeaterEntity>)
                                                        }
                                                        disabled={disabled}
                                                        step={1}
                                                        min={1}
                                                        max={24}
                                                    />
                                                </div>
                                                <div>
                                                    <label className="text-[10px] uppercase font-bold text-muted mb-1.5 block">
                                                        Min Spacing (hours)
                                                    </label>
                                                    <NumberInput
                                                        value={(entity as WaterHeaterEntity).water_min_spacing_hours}
                                                        onChange={(val) =>
                                                            updateEntity(index, {
                                                                water_min_spacing_hours: Number(val),
                                                            } as Partial<WaterHeaterEntity>)
                                                        }
                                                        disabled={disabled}
                                                        step={0.5}
                                                        min={0}
                                                        max={12}
                                                    />
                                                </div>
                                            </>
                                        )}

                                        {/* EV Charger Specific Fields */}
                                        {!isWaterHeater && (
                                            <>
                                                {/* Current Control Fields (type: current) */}
                                                {(entity as EVChargerEntity).type === 'current' && (
                                                    <>
                                                        <div className="sm:col-span-2">
                                                            <label className="text-[10px] uppercase font-bold text-muted mb-1.5 block">
                                                                Current Entity
                                                            </label>
                                                            <EntitySelect
                                                                entities={haEntities}
                                                                value={(entity as EVChargerEntity).current_entity || ''}
                                                                onChange={(val) =>
                                                                    updateEntity(index, {
                                                                        current_entity: val,
                                                                    } as Partial<EVChargerEntity>)
                                                                }
                                                                loading={haLoading}
                                                                placeholder="Select Home Assistant current control entity..."
                                                                disabled={disabled}
                                                            />
                                                            <p className="text-[10px] text-muted mt-1">
                                                                HA number entity that sets charge current (A)
                                                            </p>
                                                        </div>

                                                        <div>
                                                            <label className="text-[10px] uppercase font-bold text-muted mb-1.5 block">
                                                                Min Current (A)
                                                            </label>
                                                            <NumberInput
                                                                value={(entity as EVChargerEntity).min_current_a ?? 6}
                                                                onChange={(val) =>
                                                                    updateEntity(index, {
                                                                        min_current_a: Number(val),
                                                                    } as Partial<EVChargerEntity>)
                                                                }
                                                                disabled={disabled}
                                                                step={1}
                                                                min={0}
                                                            />
                                                        </div>

                                                        <div>
                                                            <label className="text-[10px] uppercase font-bold text-muted mb-1.5 block">
                                                                Max Current (A)
                                                            </label>
                                                            <NumberInput
                                                                value={(entity as EVChargerEntity).max_current_a ?? ''}
                                                                onChange={(val) =>
                                                                    updateEntity(index, {
                                                                        max_current_a: Number(val),
                                                                    } as Partial<EVChargerEntity>)
                                                                }
                                                                disabled={disabled}
                                                                step={1}
                                                                min={(entity as EVChargerEntity).min_current_a ?? 6}
                                                            />
                                                        </div>

                                                        <div className="sm:col-span-2">
                                                            <label className="text-[10px] uppercase font-bold text-muted mb-1.5 block">
                                                                Phases
                                                            </label>
                                                            <div className="flex gap-2">
                                                                {[1, 2, 3].map((phase) => {
                                                                    const phases = (entity as EVChargerEntity)
                                                                        .phases ?? [1, 2, 3]
                                                                    const checked = phases.includes(phase)
                                                                    return (
                                                                        <button
                                                                            key={phase}
                                                                            type="button"
                                                                            disabled={disabled}
                                                                            onClick={() => {
                                                                                const nextPhases = checked
                                                                                    ? phases.filter((p) => p !== phase)
                                                                                    : [...phases, phase].sort(
                                                                                          (a, b) => a - b,
                                                                                      )
                                                                                updateEntity(index, {
                                                                                    phases: nextPhases,
                                                                                } as Partial<EVChargerEntity>)
                                                                            }}
                                                                            className={`
                                                                                px-3.5 py-1.5 rounded-lg text-xs font-semibold border transition-all duration-200
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
                                                            <p className="text-[10px] text-muted mt-1.5">
                                                                Phases this charger draws current on.
                                                            </p>
                                                        </div>

                                                        {/* Commanded 1<->3 Phase Switching (excess-pv-priority-dispatch) */}
                                                        <div className="sm:col-span-2">
                                                            <div className="bg-surface2/30 rounded-lg p-4 border border-line/20 space-y-3">
                                                                <div className="flex items-center justify-between">
                                                                    <label className="text-[10px] uppercase font-bold text-muted">
                                                                        Commanded Phase Switching
                                                                    </label>
                                                                    <Switch
                                                                        checked={
                                                                            (entity as EVChargerEntity)
                                                                                .phase_switching_enabled ?? false
                                                                        }
                                                                        onCheckedChange={(checked) =>
                                                                            updateEntity(index, {
                                                                                phase_switching_enabled: checked,
                                                                            } as Partial<EVChargerEntity>)
                                                                        }
                                                                        disabled={disabled}
                                                                    />
                                                                </div>
                                                                <p className="text-[10px] text-muted">
                                                                    Lets Darkstar switch this charger to 1-phase mode so
                                                                    small PV surpluses (~1.4-4.1kW) still charge the
                                                                    car. Requires the charger&apos;s phase-mode entity
                                                                    (e.g. go-e Gemini Flex via the MQTT integration).
                                                                </p>
                                                                <div>
                                                                    <label className="text-[10px] uppercase font-bold text-muted mb-1.5 block">
                                                                        Phase Mode Entity
                                                                    </label>
                                                                    <EntitySelect
                                                                        entities={haEntities}
                                                                        value={
                                                                            (entity as EVChargerEntity)
                                                                                .phase_mode_entity || ''
                                                                        }
                                                                        onChange={(val) =>
                                                                            updateEntity(index, {
                                                                                phase_mode_entity: val,
                                                                            } as Partial<EVChargerEntity>)
                                                                        }
                                                                        loading={haLoading}
                                                                        placeholder="Select Home Assistant phase-mode entity..."
                                                                        disabled={disabled}
                                                                    />
                                                                    {(entity as EVChargerEntity)
                                                                        .phase_switching_enabled &&
                                                                        !(entity as EVChargerEntity)
                                                                            .phase_mode_entity && (
                                                                            <p className="text-[10px] text-bad mt-1">
                                                                                Required when phase switching is
                                                                                enabled.
                                                                            </p>
                                                                        )}
                                                                </div>
                                                                <div className="grid grid-cols-2 gap-3">
                                                                    <div>
                                                                        <label className="text-[10px] uppercase font-bold text-muted mb-1.5 flex items-center gap-1.5">
                                                                            <span>Hysteresis (kW)</span>
                                                                            <Tooltip text="Buffer added to the 3-phase minimum (4.14 kW). Target power must exceed 3ph_min + Hysteresis to switch to 3-phase, and drop below to switch back. Prevents boundary oscillation. Default: 0.5 kW." />
                                                                        </label>
                                                                        <NumberInput
                                                                            value={
                                                                                (entity as EVChargerEntity)
                                                                                    .phase_switch_hysteresis_kw ?? 0.5
                                                                            }
                                                                            onChange={(val) =>
                                                                                updateEntity(index, {
                                                                                    phase_switch_hysteresis_kw:
                                                                                        Number(val),
                                                                                } as Partial<EVChargerEntity>)
                                                                            }
                                                                            disabled={disabled}
                                                                            step={0.1}
                                                                            min={0}
                                                                        />
                                                                    </div>
                                                                    <div>
                                                                        <label className="text-[10px] uppercase font-bold text-muted mb-1.5 flex items-center gap-1.5">
                                                                            <span>Dwell (seconds)</span>
                                                                            <Tooltip text="Minimum time power must remain above/below the threshold before switching, and the minimum lockout between switches. Protects physical charger contactor relays and EV onboard chargers. Default: 600s (10 min)." />
                                                                        </label>
                                                                        <NumberInput
                                                                            value={
                                                                                (entity as EVChargerEntity)
                                                                                    .phase_switch_min_dwell_s ?? 600
                                                                            }
                                                                            onChange={(val) =>
                                                                                updateEntity(index, {
                                                                                    phase_switch_min_dwell_s:
                                                                                        Number(val),
                                                                                } as Partial<EVChargerEntity>)
                                                                            }
                                                                            disabled={disabled}
                                                                            step={30}
                                                                            min={0}
                                                                        />
                                                                    </div>
                                                                </div>
                                                            </div>
                                                        </div>
                                                    </>
                                                )}

                                                {/* Penalty Levels Section */}
                                                <div className="sm:col-span-2">
                                                    <div className="bg-surface2/30 rounded-lg p-4 border border-line/20">
                                                        <div className="flex items-center justify-between mb-3">
                                                            <label className="text-[10px] uppercase font-bold text-muted flex items-center gap-1.5">
                                                                <span>Penalty Levels</span>
                                                                <Tooltip text="Defines target battery SoC ranges and the maximum price/incentive (SEK/kWh) you are willing to pay to charge within each range." />
                                                            </label>
                                                            {!disabled && (
                                                                <button
                                                                    type="button"
                                                                    onClick={() => {
                                                                        const currentLevels =
                                                                            (entity as EVChargerEntity)
                                                                                .penalty_levels || []
                                                                        const newLevel = {
                                                                            max_soc:
                                                                                currentLevels.length > 0
                                                                                    ? Math.min(
                                                                                          100,
                                                                                          currentLevels[
                                                                                              currentLevels.length - 1
                                                                                          ].max_soc + 10,
                                                                                      )
                                                                                    : 50,
                                                                            penalty_sek: 0.5,
                                                                        }
                                                                        updateEntity(index, {
                                                                            penalty_levels: [
                                                                                ...currentLevels,
                                                                                newLevel,
                                                                            ],
                                                                        } as Partial<EVChargerEntity>)
                                                                    }}
                                                                    disabled={
                                                                        (
                                                                            (entity as EVChargerEntity)
                                                                                .penalty_levels || []
                                                                        ).length >= 5
                                                                    }
                                                                    className="text-[10px] px-2 py-1 rounded bg-accent/10 text-accent hover:bg-accent/20 disabled:opacity-50 transition-colors"
                                                                >
                                                                    + Add Level
                                                                </button>
                                                            )}
                                                        </div>

                                                        <p className="text-[10px] text-muted mb-1.5">
                                                            Define your willingness to pay (charging incentive) for
                                                            reaching different battery SoC targets.
                                                        </p>
                                                        <details className="mb-3 text-[11px] text-muted">
                                                            <summary className="font-semibold text-accent hover:underline cursor-pointer select-none outline-none">
                                                                How to configure & scenarios:
                                                            </summary>
                                                            <div className="mt-1.5 rounded-lg border border-ai/20 bg-ai/5 p-2.5 leading-relaxed text-[11px] text-muted space-y-2">
                                                                <p>
                                                                    Each level defines an incentive (SEK/kWh) to charge
                                                                    up to that target SoC. The scheduler will schedule
                                                                    charging if the net electricity price (spot price
                                                                    minus solar export value) is below this incentive.
                                                                </p>
                                                                <ul className="list-disc space-y-1.5 pl-4">
                                                                    <li>
                                                                        <strong>Standard smart split (Default):</strong>{' '}
                                                                        Set 3 levels (e.g., 50% SoC at 0.5 SEK/kWh, 80%
                                                                        SoC at 0.2 SEK, and 100% SoC at 0.0 SEK). This
                                                                        guarantees a baseline charge while leaving room
                                                                        for cheaper hours or solar surplus.
                                                                    </li>
                                                                    <li>
                                                                        <strong>Cheapest only:</strong> Delete extra
                                                                        levels and keep just one level at 100% SoC set
                                                                        to 0.0 SEK/kWh. The car will only charge during
                                                                        the single cheapest window of the day or when
                                                                        solar surplus is available.
                                                                    </li>
                                                                    <li>
                                                                        <strong>Force charging:</strong> Set a level's
                                                                        penalty high (e.g., 5.0 SEK/kWh). This forces
                                                                        charging up to that SoC target regardless of
                                                                        spot prices.
                                                                    </li>
                                                                </ul>
                                                            </div>
                                                        </details>

                                                        {((entity as EVChargerEntity).penalty_levels || []).length ===
                                                        0 ? (
                                                            <div className="text-center py-4 text-[10px] text-muted">
                                                                No penalty levels configured. Using defaults.
                                                            </div>
                                                        ) : (
                                                            <div className="space-y-2">
                                                                {((entity as EVChargerEntity).penalty_levels || []).map(
                                                                    (level, levelIndex) => (
                                                                        <div
                                                                            key={levelIndex}
                                                                            className="flex items-center gap-3 bg-surface-elevated p-2 rounded-lg"
                                                                        >
                                                                            <div className="flex-1">
                                                                                <label className="text-[10px] text-muted flex items-center gap-1.5 mb-1">
                                                                                    <span>Max SoC (%)</span>
                                                                                    <Tooltip text="The State of Charge (SoC) target limit for this priority range." />
                                                                                </label>
                                                                                <NumberInput
                                                                                    value={level.max_soc}
                                                                                    onChange={(val) => {
                                                                                        const newLevels = [
                                                                                            ...((
                                                                                                entity as EVChargerEntity
                                                                                            ).penalty_levels || []),
                                                                                        ]
                                                                                        newLevels[levelIndex] = {
                                                                                            ...level,
                                                                                            max_soc: Math.max(
                                                                                                0,
                                                                                                Math.min(
                                                                                                    100,
                                                                                                    Number(val),
                                                                                                ),
                                                                                            ),
                                                                                        }
                                                                                        updateEntity(index, {
                                                                                            penalty_levels: newLevels,
                                                                                        } as Partial<EVChargerEntity>)
                                                                                    }}
                                                                                    disabled={disabled}
                                                                                    step={1}
                                                                                    min={0}
                                                                                    max={100}
                                                                                    className="text-sm"
                                                                                />
                                                                            </div>
                                                                            <div className="flex-1">
                                                                                <label className="text-[10px] text-muted flex items-center gap-1.5 mb-1">
                                                                                    <span>Penalty (SEK/kWh)</span>
                                                                                    <Tooltip text="The maximum rate (SEK/kWh) you are willing to pay to charge within this SoC range. Set high to force charging, set low to charge only when cheap/surplus." />
                                                                                </label>
                                                                                <NumberInput
                                                                                    value={level.penalty_sek}
                                                                                    onChange={(val) => {
                                                                                        const newLevels = [
                                                                                            ...((
                                                                                                entity as EVChargerEntity
                                                                                            ).penalty_levels || []),
                                                                                        ]
                                                                                        newLevels[levelIndex] = {
                                                                                            ...level,
                                                                                            penalty_sek: Math.max(
                                                                                                0,
                                                                                                Number(val),
                                                                                            ),
                                                                                        }
                                                                                        updateEntity(index, {
                                                                                            penalty_levels: newLevels,
                                                                                        } as Partial<EVChargerEntity>)
                                                                                    }}
                                                                                    disabled={disabled}
                                                                                    step={0.1}
                                                                                    min={0}
                                                                                    className="text-sm"
                                                                                />
                                                                            </div>
                                                                            {!disabled && (
                                                                                <button
                                                                                    type="button"
                                                                                    onClick={() => {
                                                                                        const newLevels = (
                                                                                            (entity as EVChargerEntity)
                                                                                                .penalty_levels || []
                                                                                        ).filter(
                                                                                            (_, i) => i !== levelIndex,
                                                                                        )
                                                                                        updateEntity(index, {
                                                                                            penalty_levels: newLevels,
                                                                                        } as Partial<EVChargerEntity>)
                                                                                    }}
                                                                                    className="p-1.5 rounded-lg text-muted hover:text-bad hover:bg-bad/10 transition-colors mt-4"
                                                                                    aria-label="Remove level"
                                                                                >
                                                                                    <Trash2 size={14} />
                                                                                </button>
                                                                            )}
                                                                        </div>
                                                                    ),
                                                                )}
                                                            </div>
                                                        )}
                                                    </div>
                                                </div>
                                            </>
                                        )}
                                    </div>
                                </motion.div>
                            )}
                        </AnimatePresence>
                    </div>
                ))}
            </div>

            {enabledCount === 0 && entities.length > 0 && (
                <div className="p-3 bg-bad/10 border border-bad/30 rounded-xl text-xs text-bad flex items-start gap-2">
                    <span className="text-base leading-none mt-0.5">⚠️</span>
                    <div>
                        <strong>No {title.toLowerCase()} enabled.</strong>
                        <p className="mt-1 opacity-80">Enable at least one device for optimization to work.</p>
                    </div>
                </div>
            )}
        </div>
    )
}
