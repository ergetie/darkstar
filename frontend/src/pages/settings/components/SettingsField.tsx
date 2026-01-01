import React from 'react'
import { BaseField, HaEntity } from '../types'
import Tooltip from '../../../components/Tooltip'
import AzimuthDial from '../../../components/AzimuthDial'
import TiltDial from '../../../components/TiltDial'
import EntitySelect from '../../../components/EntitySelect'
import ServiceSelect from '../../../components/ServiceSelect'
import Select from '../../../components/ui/Select'
import Switch from '../../../components/ui/Switch'
import configHelp from '../../../config-help.json'

interface SettingsFieldProps {
    field: BaseField
    value: string
    onChange: (key: string, value: string) => void
    error?: string
    haEntities?: HaEntity[]
    haLoading?: boolean
}

export const SettingsField: React.FC<SettingsFieldProps> = ({
    field,
    value,
    onChange,
    error,
    haEntities = [],
    haLoading = false,
}) => {
    const renderInput = () => {
        switch (field.type) {
            case 'boolean':
                return (
                    <div className="flex items-center gap-3 pt-2">
                        <Switch
                            checked={value === 'true'}
                            onCheckedChange={(checked) => onChange(field.key, checked ? 'true' : 'false')}
                        />
                        <span className="text-sm font-semibold">{field.label}</span>
                    </div>
                )

            case 'select':
                return (
                    <Select
                        value={value}
                        onChange={(val) => onChange(field.key, val)}
                        options={field.options || []}
                        placeholder="Select..."
                    />
                )

            case 'entity':
                return (
                    <EntitySelect
                        entities={haEntities}
                        value={value}
                        onChange={(val) => onChange(field.key, val)}
                        loading={haLoading}
                        placeholder="Select entity..."
                    />
                )

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

            case 'number':
            case 'text':
            case 'array':
            default:
                return (
                    <input
                        type={field.type === 'number' ? 'number' : 'text'}
                        inputMode={field.type === 'number' ? 'decimal' : undefined}
                        value={value}
                        onChange={(e) => onChange(field.key, e.target.value)}
                        className="w-full rounded-lg border border-line/50 bg-surface2 px-3 py-2 text-sm text-text focus:border-accent focus:outline-none"
                    />
                )
        }
    }

    return (
        <div className="space-y-1">
            <label className="block text-sm font-medium mb-1.5 flex items-center gap-1">
                <span
                    className={field.type === 'boolean' ? 'sr-only' : 'text-[10px] uppercase tracking-wide text-muted'}
                >
                    {field.label}
                </span>
                <Tooltip text={(configHelp as Record<string, string>)[field.key] || field.helper} />
            </label>
            {renderInput()}
            {field.helper && field.type !== 'boolean' && <p className="text-[11px] text-muted">{field.helper}</p>}
            {error && <p className="text-[11px] text-bad">{error}</p>}
        </div>
    )
}
