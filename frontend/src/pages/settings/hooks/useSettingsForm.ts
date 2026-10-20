import { useState, useEffect, useCallback, useMemo } from 'react'
import { Api, ApiError, ConfigResponse, type ConfigSaveError } from '../../../lib/api'
import { useToast } from '../../../lib/useToast'
import { BaseField, HaEntity, InverterProfile, standardInverterKeys } from '../types'
import { buildFormState, buildPatch, evChargerArrayError, getDeepValue } from '../utils'
import { rulesError } from '../transferFees'
import {
    HEATER_ERROR_PREFIX,
    getPendingHeaterErrors,
    hasPendingHeaterErrors,
    setPendingHeaterErrors,
} from './heaterErrors'

export interface UseSettingsFormReturn {
    config: ConfigResponse | null
    form: Record<string, string>
    fields: BaseField[]
    fieldErrors: Record<string, string>
    loading: boolean
    saving: boolean
    statusMessage: string | null
    isDirty: boolean
    haEntities: HaEntity[]
    haLoading: boolean
    handleChange: (key: string, value: string) => void
    save: (extraPatch?: Record<string, unknown>) => Promise<boolean>
    reset: () => void
    reload: () => Promise<void>
    reloadEntities: () => Promise<void>
}

function isValidInstallationStatsEndpoint(value: string): boolean {
    if (!value || value !== value.trim() || !/^https:\/\//i.test(value) || value.includes('\\')) return false
    if (value.slice(8).split(/[/?#]/, 1)[0].includes('@')) return false
    for (const character of value) {
        const code = character.charCodeAt(0)
        if (code <= 0x20 || code === 0x7f) return false
    }
    try {
        const url = new URL(value)
        return (
            url.protocol === 'https:' &&
            Boolean(url.hostname) &&
            !url.username &&
            !url.password &&
            !url.search &&
            !url.hash
        )
    } catch {
        return false
    }
}

export function useSettingsForm(baseFields: BaseField[], profiles: InverterProfile[] = []): UseSettingsFormReturn {
    const { toast } = useToast()
    const [config, setConfig] = useState<ConfigResponse | null>(null)
    const [form, setForm] = useState<Record<string, string>>({})
    const [fieldErrors, setFieldErrors] = useState<Record<string, string>>(() =>
        baseFields.some((f) => f.key === 'water_heaters') ? getPendingHeaterErrors() : {},
    )
    const [loading, setLoading] = useState(true)
    const [formInitialized, setFormInitialized] = useState(false)
    const [saving, setSaving] = useState(false)
    const [statusMessage, setStatusMessage] = useState<string | null>(null)
    const [haEntities, setHaEntities] = useState<HaEntity[]>([])
    const [haLoading, setHaLoading] = useState(false)

    // Compute dynamic field list including profile-specific entity fields.
    // Iterates the v2 flat entity registry (dict of EntityDefinition objects)
    // and injects fields grouped under 'Inverter Profile Entities' subsection.
    const fields = useMemo(() => {
        if (!config || profiles.length === 0) {
            return baseFields
        }

        // Get profile name from config
        const profileName = config.system?.inverter_profile
        const selectedProfile = profiles.find((p) => p.name === profileName)

        if (!selectedProfile || !selectedProfile.entities) {
            return baseFields
        }

        const dynamicFields = [...baseFields]
        const existingKeys = new Set(dynamicFields.map((f) => f.key))

        // v2 API returns entities as a flat Record<key, EntityDefinition>.
        // Each EntityDefinition has: default_entity, domain, category, description, required.
        const profileFields: BaseField[] = Object.entries(selectedProfile.entities)
            .map(([key, entity]) => {
                const isStandard = standardInverterKeys.has(key)
                const configKey = isStandard ? `executor.inverter.${key}` : `executor.inverter.custom_entities.${key}`
                const configPath = isStandard
                    ? ['executor', 'inverter', key]
                    : ['executor', 'inverter', 'custom_entities', key]

                return {
                    key: configKey,
                    label: entity.description,
                    path: configPath,
                    type: 'entity' as const,
                    required: entity.required,
                    subsection: 'Inverter Profile Entities',
                    helper: entity.default_entity ? `Suggested: ${entity.default_entity}` : undefined,
                }
            })
            .filter((f) => !existingKeys.has(f.key))

        dynamicFields.push(...profileFields)

        return dynamicFields
    }, [config, profiles, baseFields])

    const reload = useCallback(async () => {
        setLoading(true)
        setStatusMessage(null)
        try {
            const cfg = await Api.config()
            setConfig(cfg)
            // Form will be rebuilt by the fields useMemo effect below
        } catch (err: unknown) {
            console.error('Failed to load configuration', err)
            setStatusMessage('Failed to load configuration: ' + (err instanceof Error ? err.message : 'Unknown error'))
        } finally {
            setLoading(false)
        }
    }, [])

    const reloadEntities = useCallback(async () => {
        setHaLoading(true)
        try {
            const data = await Api.haEntities()
            setHaEntities(data.entities || [])
        } catch (e) {
            console.error('Failed to load HA entities', e)
        } finally {
            setHaLoading(false)
        }
    }, [])

    useEffect(() => {
        // eslint-disable-next-line react-hooks/set-state-in-effect -- mount IO fetch, not derivable
        reload()
        reloadEntities()
    }, [reload, reloadEntities])

    // Rebuild form state when fields change (for dynamic profile fields)
    useEffect(() => {
        if (config && fields.length > 0) {
            // eslint-disable-next-line react-hooks/set-state-in-effect -- guards against wiping in-progress edits on rebuild; render-derivation would lose them
            setForm(buildFormState(config as unknown as Record<string, unknown>, fields))
            setFieldErrors({})
            setFormInitialized(true)
        }
    }, [fields, config])

    const validateField = useCallback(
        (key: string, value: string, currentForm: Record<string, string>) => {
            const errors: Record<string, string> = {}
            const trimmed = value.trim()
            const field = fields.find((f) => f.key === key)

            if (!field) return errors

            if (key === 'battery.charge_efficiency' || key === 'battery.discharge_efficiency') {
                if (trimmed === '' && getDeepValue(config, field.path) === undefined) return errors
                const efficiency = Number(trimmed)
                if (!Number.isFinite(efficiency) || efficiency <= 0 || efficiency > 100) {
                    errors[key] = 'Must be greater than 0 and at most 100%'
                }
                return errors
            }

            if (key === 'installation_stats.endpoint' && !isValidInstallationStatsEndpoint(trimmed)) {
                errors[key] = 'Enter an absolute HTTPS URL without credentials, query, or fragment.'
                return errors
            }

            // DEBUG: Log all validation attempts for battery_soc
            if (key.includes('battery_soc')) {
                console.warn('[SETTINGS_DEBUG] Validating battery_soc:', {
                    key,
                    value,
                    trimmed,
                    fieldType: field.type,
                    fieldLabel: field.label,
                    fullField: field,
                })
            }

            // Required check
            if (trimmed === '' && (field.required || key.includes('power_kw') || key.includes('capacity_kwh'))) {
                errors[key] = 'Required'
                return errors
            }

            if (field.type === 'entity_array' && field.entityType === 'ev_charger') {
                const evError = evChargerArrayError(value)
                if (evError) errors[key] = evError
                return errors
            }

            if (field.type === 'transfer_fee_rules') {
                let parsed: unknown
                try {
                    parsed = JSON.parse(value || '[]')
                } catch {
                    parsed = null
                }
                const rulesErr = rulesError(parsed)
                if (rulesErr) errors[key] = rulesErr
                return errors
            }

            // Only apply numeric validation if the field type is numeric
            if (field.type === 'number' || field.type === 'azimuth' || field.type === 'tilt') {
                // DEBUG: Log when entering numeric validation block
                if (key.includes('battery_soc')) {
                    console.error(
                        '[SETTINGS_DEBUG] ERROR: battery_soc entered numeric validation block! Type:',
                        field.type,
                    )
                }
                const num = Number(trimmed)
                if (trimmed !== '' && Number.isNaN(num)) {
                    errors[key] = 'Must be a number'
                } else if (
                    trimmed !== '' &&
                    ((field.min !== undefined && num < field.min) || (field.max !== undefined && num > field.max))
                ) {
                    errors[key] = `Must be between ${field.min ?? '-∞'} and ${field.max ?? '∞'}`
                } else if (!Number.isNaN(num) && field.min === undefined && field.max === undefined) {
                    // Key-name heuristics only for fields that declare no explicit bounds
                    if (key.includes('percent') || key.includes('soc')) {
                        if (num < 0 || num > 100) {
                            errors[key] = 'Must be between 0 and 100'
                        }
                    } else if (key.includes('power_kw') || key.includes('sek') || key.includes('kwh')) {
                        if (num < 0) {
                            errors[key] = 'Must be positive'
                        }
                    }
                }
            }

            // Cross-field validation for SoC
            const minKey = 'battery.min_soc_percent'
            const maxKey = 'battery.max_soc_percent'
            if (key === minKey || key === maxKey) {
                const minVal = Number(key === minKey ? trimmed : currentForm[minKey])
                const maxVal = Number(key === maxKey ? trimmed : currentForm[maxKey])
                if (!Number.isNaN(minVal) && !Number.isNaN(maxVal)) {
                    if (minVal >= maxVal) {
                        errors[minKey] = 'Min SoC must be less than max SoC'
                        errors[maxKey] = 'Max SoC must be greater than min SoC'
                    }
                }
            }

            return errors
        },
        [fields, config],
    )

    const handleChange = useCallback(
        (key: string, value: string) => {
            setForm((prev) => {
                const next = { ...prev, [key]: value }
                const newErrors = validateField(key, value, next)
                setFieldErrors((errs) => {
                    const updated = { ...errs, ...newErrors }
                    if (!newErrors[key]) delete updated[key]
                    if (key === 'water_heaters') {
                        // Heater edits invalidate earlier server-side heater errors.
                        for (const k of Object.keys(updated)) {
                            if (k.startsWith(HEATER_ERROR_PREFIX)) delete updated[k]
                        }
                    }
                    // If it was a min/max SoC check, we might have cleared the other one too
                    if (key === 'battery.min_soc_percent' && !newErrors['battery.min_soc_percent'])
                        delete updated['battery.max_soc_percent']
                    if (key === 'battery.max_soc_percent' && !newErrors['battery.max_soc_percent'])
                        delete updated['battery.min_soc_percent']
                    return updated
                })
                return next
            })
            setStatusMessage(null)
            if (key === 'water_heaters' && hasPendingHeaterErrors()) setPendingHeaterErrors({})
        },
        [validateField],
    )

    const reset = useCallback(() => {
        if (config) {
            setForm(buildFormState(config as unknown as Record<string, unknown>, fields))
            setFieldErrors({})
            setStatusMessage(null)
            setFormInitialized(true)
        }
    }, [config, fields])

    const save = useCallback(
        async (extraPatch?: Record<string, unknown>) => {
            if (!config) return false

            const efficiencyErrors = {
                ...validateField('battery.charge_efficiency', form['battery.charge_efficiency'] ?? '', form),
                ...validateField('battery.discharge_efficiency', form['battery.discharge_efficiency'] ?? '', form),
            }
            if (Object.keys(efficiencyErrors).length > 0) {
                setFieldErrors((prev) => ({ ...prev, ...efficiencyErrors }))
                setStatusMessage('Please fix validation errors before saving.')
                return false
            }

            const endpointKey = 'installation_stats.endpoint'
            const endpointErrors = validateField(endpointKey, form[endpointKey] ?? '', form)
            if (endpointErrors[endpointKey]) {
                setFieldErrors((prev) => ({ ...prev, ...endpointErrors }))
                setStatusMessage('Please fix validation errors before saving.')
                return false
            }

            // Validate ALL required fields before saving (not just touched ones)
            const allRequiredErrors: Record<string, string> = {}
            fields.forEach((field) => {
                if (field.required && !form[field.key]?.trim()) {
                    allRequiredErrors[field.key] = 'Required'
                }
            })

            if (Object.keys(allRequiredErrors).length > 0) {
                // REV UI23: Don't block save - show warning but allow save
                // The global banner will handle persistent "incomplete config" warnings
                setFieldErrors(allRequiredErrors)
                const missingCount = Object.keys(allRequiredErrors).length
                const missingFields = fields
                    .filter((f) => allRequiredErrors[f.key])
                    .map((f) => f.label)
                    .join(', ')
                toast({
                    message: `${missingCount} required field${missingCount > 1 ? 's' : ''} missing`,
                    description: missingFields,
                    variant: 'warning', // Changed from 'error' - don't block save
                })
                // Don't return false - allow save to proceed
            }

            // Blocking EV charger checks run on save too, not only when the field was edited
            const evArrayErrors: Record<string, string> = {}
            fields.forEach((field) => {
                if (field.type === 'entity_array' && field.entityType === 'ev_charger') {
                    const evError = evChargerArrayError(form[field.key] ?? '')
                    if (evError) evArrayErrors[field.key] = evError
                }
            })
            if (Object.keys(evArrayErrors).length > 0) {
                setFieldErrors((prev) => ({ ...prev, ...evArrayErrors }))
                setStatusMessage('Please fix validation errors before saving.')
                return false
            }

            // REV UI23: Only block on actual validation errors, not missing required fields
            // Missing required fields show a warning but don't block saves
            // Server-side heater errors are advisory here: the server re-validates every save, so a
            // stale one (heater disabled/removed, has_water_heater off) must never trap the user.
            const nonRequiredErrors = Object.entries(fieldErrors).filter(
                ([key, msg]) => msg !== 'Required' && !key.startsWith(HEATER_ERROR_PREFIX),
            )
            if (nonRequiredErrors.length > 0) {
                setStatusMessage('Please fix validation errors before saving.')
                return false
            }

            const patch = {
                ...buildPatch(config as unknown as Record<string, unknown>, form, fields),
                ...extraPatch,
            }
            console.warn('[CONFIG_SAVE] Generated patch:', patch)

            if (Object.keys(patch).length === 0) {
                setStatusMessage('No changes detected.')
                return false
            }

            setSaving(true)
            setStatusMessage(null)
            // Drop earlier server heater errors; a rejected save repopulates them.
            setFieldErrors((prev) => {
                const kept = Object.fromEntries(
                    Object.entries(prev).filter(([k]) => !k.startsWith(HEATER_ERROR_PREFIX)),
                )
                return Object.keys(kept).length === Object.keys(prev).length ? prev : kept
            })
            const applyServerErrors = (errors: ConfigSaveError[] | undefined, fallback = 'Save failed') => {
                const apiErrors: Record<string, string> = {}
                errors?.forEach((err) => {
                    if (err.field) apiErrors[err.field] = err.message
                })
                const ownsHeaters = fields.some((f) => f.key === 'water_heaters')
                // Another tab cannot fix heater errors, so they must not block its own saves.
                const localErrors = Object.fromEntries(
                    Object.entries(apiErrors).filter(([k]) => ownsHeaters || !k.startsWith(HEATER_ERROR_PREFIX)),
                )
                setFieldErrors((prev) => ({ ...prev, ...localErrors }))
                const heaterErrors = Object.fromEntries(
                    Object.entries(apiErrors).filter(([k]) => k.startsWith(HEATER_ERROR_PREFIX)),
                )
                setPendingHeaterErrors(heaterErrors)
                const firstMessage = errors?.[0]?.message || fallback
                setStatusMessage(
                    Object.keys(heaterErrors).length > 0 && !ownsHeaters
                        ? `${firstMessage} (fix in the Heating tab)`
                        : firstMessage,
                )
            }

            try {
                const result = await Api.configSave(patch as Record<string, unknown>)
                if (result.status === 'success') {
                    // REV LCL01: Show warnings if any exist
                    if (result.warnings && result.warnings.length > 0) {
                        result.warnings.forEach((w) => {
                            toast({
                                message: w.message,
                                description: w.guidance,
                                variant: 'warning',
                            })
                        })
                    } else {
                        toast({ message: 'Settings saved successfully', variant: 'success' })
                    }
                    setPendingHeaterErrors({})
                    await reload()
                    // REV UI23: Notify App.tsx to refresh config validation banner
                    window.dispatchEvent(new Event('config-changed'))
                    return true
                } else {
                    applyServerErrors(result.errors)
                    toast({ message: 'Save failed', variant: 'error' })
                }
            } catch (err: unknown) {
                console.error('Save failed', err)
                // REV LCL01: Show actual error message from config validation
                const errMsg = err instanceof Error ? err.message : 'Unknown error'
                const detail = err instanceof ApiError ? (err.detail as { errors?: unknown } | undefined) : undefined
                if (Array.isArray(detail?.errors)) {
                    // A 400 carries per-field errors; show them next to their fields.
                    applyServerErrors(detail.errors as ConfigSaveError[], errMsg)
                } else {
                    setStatusMessage(errMsg)
                }
                toast({
                    message: 'Save failed',
                    description: errMsg,
                    variant: 'error',
                })
            } finally {
                setSaving(false)
            }
            return false
        },
        [config, form, fields, fieldErrors, reload, toast, validateField],
    )

    const isDirty = useMemo(() => {
        if (!config || !formInitialized) return false
        const patch = buildPatch(config as unknown as Record<string, unknown>, form, fields)
        return Object.keys(patch).length > 0
    }, [config, form, fields, formInitialized])

    return {
        config,
        form,
        fields,
        fieldErrors,
        loading,
        saving,
        statusMessage,
        isDirty,
        haEntities,
        haLoading,
        handleChange,
        save,
        reset,
        reload,
        reloadEntities,
    }
}
