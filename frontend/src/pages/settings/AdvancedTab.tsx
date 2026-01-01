import React, { useState } from 'react'
import { Api } from '../../lib/api'
import { useToast } from '../../lib/useToast'
import Card from '../../components/Card'
import Modal from '../../components/ui/Modal'
import { useSettingsForm } from './hooks/useSettingsForm'
import { SettingsField } from './components/SettingsField'
import { advancedFieldList, advancedSections } from './types'

export const AdvancedTab: React.FC = () => {
    const { toast } = useToast()
    const { form, fieldErrors, loading, saving, statusMessage, handleChange, save, reload } =
        useSettingsForm(advancedFieldList)

    const [resetModalOpen, setResetModalOpen] = useState(false)
    const [resetLoading, setResetLoading] = useState(false)

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
            {advancedSections.map((section) => (
                <Card key={section.title} className="p-6">
                    <div className="flex items-baseline justify-between gap-2">
                        <div>
                            <div className="text-sm font-semibold">{section.title}</div>
                            <p className="text-xs text-muted mt-1">{section.description}</p>
                        </div>
                        <span className="text-[10px] uppercase text-muted tracking-wide">Advanced</span>
                    </div>

                    {section.title === 'Danger Zone' ? (
                        <div className="mt-5 border border-red-500/20 bg-red-500/5 rounded-xl p-4">
                            <div className="flex items-center justify-between gap-4">
                                <div>
                                    <h4 className="text-xs font-bold text-red-100 italic uppercase tracking-wider">
                                        Reset All Settings
                                    </h4>
                                    <p className="text-[11px] text-red-400/80 mt-1">
                                        Permanently delete all custom configurations and return to project factory
                                        defaults. This action cannot be undone.
                                    </p>
                                </div>
                                <button
                                    onClick={() => setResetModalOpen(true)}
                                    className="rounded-lg bg-red-500/20 border border-red-500/30 px-3 py-1.5 text-[10px] font-bold text-red-400 uppercase tracking-wider hover:bg-red-500/30 transition"
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
                                ? 'bg-red-500/10 border border-red-500/30 text-red-400'
                                : 'bg-green-500/10 border border-green-500/30 text-green-400'
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
                            className="bg-red-500 hover:bg-red-600 px-4 py-2 rounded-xl text-xs font-bold text-white transition disabled:opacity-50"
                        >
                            {resetLoading ? 'Resetting...' : 'Yes, Reset Everything'}
                        </button>
                    </div>
                </div>
            </Modal>
        </div>
    )
}
