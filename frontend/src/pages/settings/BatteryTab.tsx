import React, { useState, useEffect, useMemo } from 'react'
import { useNavigate } from 'react-router-dom'
import Card from '../../components/Card'
import { useSettingsForm } from './hooks/useSettingsForm'
import { SettingsField } from './components/SettingsField'
import { batteryFieldList, batterySections, InverterProfile, BaseField, generateProfileEntityFields } from './types'
import { listChangedFields } from './utils'
import { shouldRenderField } from './logic'
import { motion, AnimatePresence } from 'framer-motion'
import { AdditionalAdvancedNotice, GlobalAdvancedLockedNotice } from './components/AdvancedLockedNotice'
import { UnsavedChangesBanner } from './components/UnsavedChangesBanner'
import { NavigationBlockerDialog } from './components/NavigationBlockerDialog'
import { useUnsavedChangesGuard } from './hooks/useUnsavedChangesGuard'
import { Api, ConfigResponse } from '../../lib/api'

export const BatteryTab: React.FC<{ advancedMode?: boolean }> = ({ advancedMode }) => {
    const navigate = useNavigate()
    const [profiles, setProfiles] = useState<InverterProfile[]>([])

    // Load profiles on mount
    useEffect(() => {
        Api.listProfiles()
            .then((data) => setProfiles(data))
            .catch((err) => console.error('Failed to load profiles:', err))
    }, [])

    const {
        config,
        form,
        fields,
        fieldErrors,
        loading,
        saving,
        statusMessage,
        handleChange,
        save,
        isDirty,
        haEntities,
        haLoading,
    } = useSettingsForm(batteryFieldList, profiles)

    const blocker = useUnsavedChangesGuard(isDirty)
    const hasHiddenSections = batterySections.some((s) => s.fields.every((f) => f.isAdvanced))

    // Generate dynamic sections with profile entities
    const dynamicSections = useMemo(() => {
        const selectedProfileName = (config as ConfigResponse)?.system?.inverter_profile
        const selectedProfile = profiles.find((p) => p.name === selectedProfileName)

        return batterySections.map((section) => {
            // Replace hardcoded "HA Control Entities" with dynamic fields from profile (battery category)
            if (section.title === 'HA Control Entities' && selectedProfile) {
                return {
                    ...section,
                    fields: generateProfileEntityFields(selectedProfile, 'battery'),
                }
            }
            return section
        })
    }, [profiles, config])

    if (loading || profiles.length === 0) {
        return <Card className="p-6 text-sm text-muted">Loading battery configuration…</Card>
    }

    const fieldVariants = {
        initial: { opacity: 0, y: -10, height: 0 },
        animate: { opacity: 1, y: 0, height: 'auto' },
        exit: { opacity: 0, y: -10, height: 0 },
    }

    return (
        <div className="space-y-4">
            <UnsavedChangesBanner visible={isDirty} onSave={() => save()} saving={saving} />

            {dynamicSections.map((section) => {
                // Check section-level showIf
                let sectionEnabled = true
                if (section.showIf) {
                    const configValue = form[section.showIf.configKey]
                    if (section.showIf.value !== undefined) {
                        if (Array.isArray(section.showIf.value)) {
                            sectionEnabled = section.showIf.value.includes(configValue as string | boolean | number)
                        } else {
                            sectionEnabled = configValue === String(section.showIf.value)
                        }
                    } else {
                        sectionEnabled = Boolean(configValue)
                    }
                }

                if (!sectionEnabled) return null

                const isEntirelyAdvanced = section.fields.every((f) => f.isAdvanced)
                const shouldShowCard = advancedMode || !isEntirelyAdvanced

                if (!shouldShowCard) return null

                return (
                    <AnimatePresence key={section.title} initial={false}>
                        <motion.div
                            variants={fieldVariants}
                            initial="initial"
                            animate="animate"
                            exit="exit"
                            transition={{ duration: 0.2 }}
                        >
                            <Card className="overflow-hidden">
                                <div className="px-6 py-4">
                                    <h2 className="text-lg font-semibold text-foreground">{section.title}</h2>
                                    {section.description && (
                                        <p className="mt-1 text-sm text-muted">{section.description}</p>
                                    )}
                                </div>
                                <div className="grid grid-cols-1 gap-4 p-6 md:grid-cols-2">
                                    {section.fields.map((field) => {
                                        const shouldRender = shouldRenderField(
                                            field as BaseField,
                                            form,
                                            config as unknown as Record<string, unknown>,
                                        )
                                        if (!shouldRender) return null
                                        return (
                                            <SettingsField
                                                key={field.key}
                                                field={field as BaseField}
                                                value={form[field.key]}
                                                onChange={handleChange}
                                                error={fieldErrors[field.key]}
                                                haEntities={haEntities}
                                                haLoading={haLoading}
                                                fullForm={form}
                                                config={config as unknown as Record<string, unknown>}
                                            />
                                        )
                                    })}
                                </div>
                            </Card>
                        </motion.div>
                    </AnimatePresence>
                )
            })}

            <AdditionalAdvancedNotice visible={!advancedMode} />

            <div className="flex flex-wrap items-center gap-3">
                <button
                    disabled={saving}
                    onClick={() => save()}
                    className="flex items-center justify-center gap-2 rounded-xl px-3 py-2.5 text-[11px] font-semibold transition btn-glow-primary bg-accent hover:bg-accent2 text-[#100f0e] disabled:opacity-50"
                >
                    {saving ? 'Saving…' : 'Save Battery Settings'}
                </button>
                {statusMessage && (
                    <div
                        className={`rounded-lg p-3 text-sm ${
                            statusMessage.startsWith('Please fix') ||
                            statusMessage.startsWith('Save failed') ||
                            statusMessage.startsWith('Failed to load')
                                ? 'bg-bad/10 border border-bad/30 text-bad'
                                : 'bg-good/10 border border-good/30 text-good'
                        }`}
                    >
                        {statusMessage}
                    </div>
                )}
            </div>

            <NavigationBlockerDialog
                visible={blocker.state === 'blocked'}
                onStay={() => blocker.reset?.()}
                onLeave={() => {
                    if (blocker.location) {
                        navigate(blocker.location.pathname + blocker.location.search, {
                            state: { ...blocker.location.state, ignoreUnsavedChangesGuard: true },
                        })
                    }
                }}
                changes={config ? listChangedFields(config as unknown as Record<string, unknown>, form, fields) : []}
            />

            {!advancedMode && hasHiddenSections && <GlobalAdvancedLockedNotice />}
        </div>
    )
}
