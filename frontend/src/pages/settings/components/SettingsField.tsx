import React from 'react'
import { BaseField, HaEntity } from '../types'
import Tooltip from '../../../components/Tooltip'
import AzimuthDial from '../../../components/AzimuthDial'
import TiltDial from '../../../components/TiltDial'
import EntitySelect from '../../../components/EntitySelect'
import ServiceSelect from '../../../components/ServiceSelect'
import Select from '../../../components/ui/Select'
import Switch from '../../../components/ui/Switch'
import { Badge } from '../../../components/ui/Badge'
import configHelp from '../../../config-help.json'

interface SettingsFieldProps {
    field: BaseField
    value: string
    onChange: (key: string, value: string) => void
    error?: string
    haEntities?: HaEntity[]
    haLoading?: boolean
    fullForm?: Record<string, string>
}

export const SettingsField: React.FC<SettingsFieldProps> = ({
    field,
    value,
    onChange,
    error,
    haEntities = [],
    haLoading = false,
    fullForm = {},
}) => {
    const isEnabled = React.useMemo(() => {
        if (field.disabled) return false

        if (field.showIf) {
            const currentVal = fullForm[field.showIf.configKey]
            const expectedVal = field.showIf.value ?? true
            // Convert 'true'/'false' string to boolean for comparison if needed
            const boolCurrentVal = currentVal === 'true'
            return boolCurrentVal === expectedVal
        }

        if (field.showIfAll) {
            return field.showIfAll.every((k) => fullForm[k] === 'true')
        }

        if (field.showIfAny) {
            return field.showIfAny.some((k) => fullForm[k] === 'true')
        }

        return true
    }, [field, fullForm])

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
                        disabled={isDisabled}
                    />
                )

            case 'entity':
                return (
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
                        className={`w-full rounded-lg border border-line/50 bg-surface2 px-3 py-2 text-sm text-text focus:border-accent focus:outline-none ${
                            isDisabled ? 'opacity-50 cursor-not-allowed' : ''
                        }`}
                        disabled={isDisabled}
                    />
                )
        }
    }

    return (
        <div className={`space-y-1 ${!isEnabled ? 'opacity-40 pointer-events-none' : ''}`}>
            {!isEnabled && field.showIf?.disabledText && (
                <div className="text-xs text-muted italic mb-1">{field.showIf.disabledText}</div>
            )}
            <label className="block text-sm font-medium mb-1.5 flex items-center gap-1.5">
                <span
                    className={field.type === 'boolean' ? 'sr-only' : 'text-[10px] uppercase tracking-wide text-muted'}
                >
                    {field.label}
                </span>
                {field.notImplemented && <Badge variant="warning">NOT IMPLEMENTED</Badge>}
                <Tooltip text={(configHelp as Record<string, string>)[field.key] || field.helper} />
            </label>
            {renderInput()}
            {error && <p className="text-[11px] text-bad">{error}</p>}
        </div>
    )
}
