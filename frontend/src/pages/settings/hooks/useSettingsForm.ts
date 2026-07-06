import { useState, useEffect, useCallback, useMemo } from 'react'
import { Api, ConfigResponse } from '../../../lib/api'
import { useToast } from '../../../lib/useToast'
import { BaseField, HaEntity, InverterProfile, standardInverterKeys } from '../types'
import { buildFormState, buildPatch } from '../utils'

export interface UseSettingsFormReturn {
    config: ConfigResponse | null
    form: Record<string, string>
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

export function useSettingsForm(baseFields: BaseField[], profiles: InverterProfile[] = []): UseSettingsFormReturn {
    const { toast } = useToast()
    const [config, setConfig] = useState<ConfigResponse | null>(null)
    const [form, setForm] = useState<Record<string, string>>({})
    const [fieldErrors, setFieldErrors] = useState<Record<string, string>>({})
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
        reload()
        reloadEntities()
    }, [reload, reloadEntities])

    // Rebuild form state when fields change (for dynamic profile fields)
    useEffect(() => {
        if (config && fields.length > 0) {
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
                } else if (!Number.isNaN(num)) {
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
        [fields],
    )

    const handleChange = useCallback(
        (key: string, value: string) => {
            setForm((prev) => {
                const next = { ...prev, [key]: value }
                const newErrors = validateField(key, value, next)
                setFieldErrors((errs) => {
                    const updated = { ...errs, ...newErrors }
                    if (!newErrors[key]) delete updated[key]
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

            // REV UI23: Only block on actual validation errors, not missing required fields
            // Missing required fields show a warning but don't block saves
            const nonRequiredErrors = Object.entries(fieldErrors).filter(([_, msg]) => msg !== 'Required')
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
                    await reload()
                    // REV UI23: Notify App.tsx to refresh config validation banner
                    window.dispatchEvent(new Event('config-changed'))
                    return true
                } else {
                    const apiErrors: Record<string, string> = {}
                    result.errors?.forEach((err) => {
                        if (err.field) apiErrors[err.field] = err.message
                    })
                    setFieldErrors((prev) => ({ ...prev, ...apiErrors }))
                    setStatusMessage(result.errors?.[0]?.message || 'Save failed')
                    toast({ message: 'Save failed', variant: 'error' })
                }
            } catch (err: unknown) {
                console.error('Save failed', err)
                // REV LCL01: Show actual error message from config validation
                const errMsg = err instanceof Error ? err.message : 'Unknown error'
                setStatusMessage(errMsg)
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
        [config, form, fields, fieldErrors, reload, toast],
    )

    const isDirty = useMemo(() => {
        if (!config || !formInitialized) return false
        const patch = buildPatch(config as unknown as Record<string, unknown>, form, fields)
        return Object.keys(patch).length > 0
    }, [config, form, fields, formInitialized])

    return {
        config,
        form,
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
