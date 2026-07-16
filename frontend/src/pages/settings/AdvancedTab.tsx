import React, { useState } from 'react'
import { useNavigate } from 'react-router-dom'
import { Api } from '../../lib/api'
import { useToast } from '../../lib/useToast'
import Card from '../../components/Card'
import Modal from '../../components/ui/Modal'
import { useSettingsForm } from './hooks/useSettingsForm'
import { SettingsField } from './components/SettingsField'
import { advancedFieldList, advancedSections } from './types'
import { listChangedFields } from './utils'
import { UnsavedChangesBanner } from './components/UnsavedChangesBanner'
import { NavigationBlockerDialog } from './components/NavigationBlockerDialog'
import { useUnsavedChangesGuard } from './hooks/useUnsavedChangesGuard'

export const AdvancedTab: React.FC<{ advancedMode?: boolean }> = ({ advancedMode }) => {
    const navigate = useNavigate()
    const { toast } = useToast()
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
        reload,
        isDirty,
        haEntities,
        haLoading,
    } = useSettingsForm(advancedFieldList, [])

    const blocker = useUnsavedChangesGuard(isDirty)

    const [resetModalOpen, setResetModalOpen] = useState(false)
    const [resetLoading, setResetLoading] = useState(false)

    const isSectionEnabled = (section: (typeof advancedSections)[0]) => {
        if (!section.showIf) return true

        // For system-level showIf checks, use config directly (form may not have these fields)
        if (section.showIf.configKey.startsWith('system.')) {
            const systemKey = section.showIf.configKey.replace('system.', '')
            const configValue = (config as unknown as { system?: Record<string, unknown> })?.system?.[systemKey]
            if (section.showIf.value !== undefined) {
                if (Array.isArray(section.showIf.value)) {
                    return section.showIf.value.includes(configValue as string | boolean | number)
                }
                return configValue === section.showIf.value
            }
            return configValue === true
        }

        // For non-system fields, use form state
        const configValue = form[section.showIf.configKey]
        if (section.showIf.value !== undefined) {
            if (Array.isArray(section.showIf.value)) {
                return section.showIf.value.includes(configValue as string | boolean | number)
            }
            return configValue === String(section.showIf.value)
        }
        return configValue === 'true'
    }

    const handleResetAll = async () => {
        setResetLoading(true)
        try {
            await Api.configReset()
            toast({ message: 'Settings reset to factory defaults', variant: 'success' })
            await reload()
            setResetModalOpen(false)
        } catch (e: unknown) {
            toast({ message: 'Reset failed: ' + (e instanceof Error ? e.message : 'Unknown error'), variant: 'error' })
        } finally {
            setResetLoading(false)
        }
    }

    if (loading) {
        return <Card className="p-6 text-sm text-muted">Loading advanced configuration…</Card>
    }

    return (
        <div className="space-y-4">
            <UnsavedChangesBanner visible={isDirty} onSave={() => save()} saving={saving} />

            <Card className="p-6">
                <div className="flex items-center justify-between gap-4">
                    <div>
                        <h3 className="text-sm font-bold text-text mb-1">System Setup Wizard</h3>
                        <p className="text-xs text-muted">
                            Relaunch the initial setup wizard to re-configure your hardware profile, equipment specs,
                            and baseline consumption. This will open the wizard without deleting your current settings.
                        </p>
                    </div>
                    <button
                        type="button"
                        className="whitespace-nowrap rounded-lg bg-surface2 border border-line/20 px-4 py-2 text-xs font-semibold text-text hover:bg-surface0 transition shrink-0"
                        onClick={() => {
                            window.location.href = '/?setup_wizard=true'
                        }}
                    >
                        Relaunch Setup Wizard
                    </button>
                </div>
            </Card>

            {advancedSections
                .filter((section) => isSectionEnabled(section))
                .map((section) => (
                    <Card key={section.title} className="p-6">
                        <div className="flex items-baseline justify-between gap-2">
                            <div>
                                <div className="text-sm font-semibold">{section.title}</div>
                                <p className="text-xs text-muted mt-1">{section.description}</p>
                            </div>
                            <span className="text-[10px] uppercase text-muted tracking-wide">Advanced</span>
                        </div>

                        {section.title === 'Danger Zone' ? (
                            <div className="mt-5 border border-bad/20 bg-bad/5 rounded-xl p-4">
                                <div className="flex items-center justify-between gap-4">
                                    <div>
                                        <h4 className="text-xs font-bold text-bad italic uppercase tracking-wider">
                                            Reset All Settings
                                        </h4>
                                        <p className="text-[11px] text-bad/80 mt-1">
                                            Permanently delete all custom configurations and return to project factory
                                            defaults. This action cannot be undone.
                                        </p>
                                    </div>
                                    <button
                                        onClick={() => setResetModalOpen(true)}
                                        className="rounded-lg bg-bad/20 border border-bad/30 px-3 py-1.5 text-[10px] font-bold text-bad uppercase tracking-wider hover:bg-bad/30 transition"
                                    >
                                        Reset to Defaults
                                    </button>
                                </div>
                            </div>
                        ) : (
                            <div className="mt-5 grid gap-4 sm:grid-cols-2">
                                {section.fields.map((field) => (
                                    <SettingsField
                                        key={field.key}
                                        field={field}
                                        value={form[field.key] ?? ''}
                                        onChange={handleChange}
                                        error={fieldErrors[field.key]}
                                        fullForm={form}
                                        config={config as unknown as Record<string, unknown>}
                                        advancedMode={advancedMode}
                                        haEntities={haEntities}
                                        haLoading={haLoading}
                                    />
                                ))}
                            </div>
                        )}
                    </Card>
                ))}

            <div className="flex flex-wrap items-center gap-3">
                <button
                    disabled={saving}
                    onClick={() => save()}
                    className="flex items-center justify-center gap-2 rounded-xl px-3 py-2.5 text-[11px] font-semibold transition btn-glow-primary bg-accent hover:bg-accent2 text-[#100f0e] disabled:opacity-50"
                >
                    {saving ? 'Saving…' : 'Save Advanced Settings'}
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

            <Modal open={resetModalOpen} onOpenChange={setResetModalOpen} title="Reset to factory defaults?">
                <div className="space-y-4">
                    <p className="text-sm text-muted">
                        This will clear your location, battery specs, HA tokens, and all optimization parameters. The
                        system will return to the initial state defined in{' '}
                        <code className="text-accent">config.yaml</code>.
                    </p>
                    <div className="flex justify-end gap-3 mt-6">
                        <button
                            onClick={() => setResetModalOpen(false)}
                            className="px-4 py-2 text-xs font-semibold text-white/70 hover:text-white transition"
                        >
                            Cancel
                        </button>
                        <button
                            onClick={handleResetAll}
                            disabled={resetLoading}
                            className="bg-bad hover:bg-bad/80 px-4 py-2 rounded-xl text-xs font-bold text-white transition disabled:opacity-50"
                        >
                            {resetLoading ? 'Resetting...' : 'Yes, Reset Everything'}
                        </button>
                    </div>
                </div>
            </Modal>

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
        </div>
    )
}
