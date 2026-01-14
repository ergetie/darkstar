import React, { useState } from 'react'
import { Api } from '../../lib/api'
import Card from '../../components/Card'
import { useSettingsForm } from './hooks/useSettingsForm'
import { SettingsField } from './components/SettingsField'
import { systemFieldList, systemSections } from './types'

export const SystemTab: React.FC = () => {
    const {
        form,
        fieldErrors,
        loading,
        saving,
        statusMessage,
        haEntities,
        haLoading,
        handleChange,
        save,
        reloadEntities,
    } = useSettingsForm(systemFieldList)

    const [haTestStatus, setHaTestStatus] = useState<string | null>(null)

    const handleTestConnection = async () => {
        setHaTestStatus('Testing...')
        try {
            const url = form['home_assistant.url']
            const token = form['home_assistant.token']
            const data = await Api.haTest({ url, token })

            if (data.success) {
                setHaTestStatus('Success: Connected!')
                reloadEntities()
            } else {
                setHaTestStatus(`Error: ${data.message}`)
            }
        } catch (e: unknown) {
            setHaTestStatus(`Error: ${e instanceof Error ? e.message : 'Unknown error'}`)
        }
    }

    if (loading) {
        return <Card className="p-6 text-sm text-muted">Loading system configuration…</Card>
    }

    return (
        <div className="space-y-4">
            {/* HA Add-on Guidance Banner */}
            <Card className="p-4 bg-accent/5 border border-accent/20">
                <div className="flex items-start gap-3">
                    <div className="text-xl">🔌</div>
                    <div>
                        <div className="text-sm font-semibold text-accent">HA Add-on User?</div>
                        <p className="text-xs text-muted mt-1 leading-relaxed">
                            If you are running as a Home Assistant Add-on, connection settings are managed
                            automatically.
                            <strong> Manually entering them here is not required</strong> and they will be reset to
                            match your add-on configuration on next save.
                        </p>
                    </div>
                </div>
            </Card>

            {systemSections.map((section, idx) => {
                const prevSection = idx > 0 ? systemSections[idx - 1] : null
                const showDivider = section.isHA && prevSection && !prevSection.isHA

                return (
                    <div key={section.title}>
                        {showDivider && (
                            <div className="py-8 flex items-center gap-4">
                                <div className="h-px flex-1 bg-line/30" />
                                <span className="text-[11px] font-bold uppercase tracking-[0.2em] text-muted whitespace-nowrap">
                                    Home Assistant Integration
                                </span>
                                <div className="h-px flex-1 bg-line/30" />
                            </div>
                        )}
                        <Card className="p-6">
                            <div className="flex items-baseline justify-between gap-2">
                                <div>
                                    <div className="text-sm font-semibold">{section.title}</div>
                                    <p className="text-xs text-muted mt-1">{section.description}</p>
                                </div>
                                <span className="text-[10px] uppercase text-muted tracking-wide">System</span>
                            </div>
                            <div className="mt-5 grid gap-4 sm:grid-cols-2">
                                {section.fields.map((field) => (
                                    <SettingsField
                                        key={field.key}
                                        field={field}
                                        value={form[field.key] ?? ''}
                                        onChange={handleChange}
                                        error={fieldErrors[field.key]}
                                        haEntities={haEntities}
                                        haLoading={haLoading}
                                        fullForm={form}
                                    />
                                ))}
                            </div>
                            {section.title === 'Home Assistant Connection' && (
                                <div className="mt-4 flex items-center gap-3">
                                    <button
                                        type="button"
                                        onClick={handleTestConnection}
                                        className="rounded-xl px-4 py-2 text-[11px] font-semibold bg-neutral hover:bg-neutral/80 text-white transition"
                                    >
                                        {haTestStatus && haTestStatus.startsWith('Testing')
                                            ? 'Testing...'
                                            : 'Test Connection'}
                                    </button>
                                    {haTestStatus && (
                                        <span
                                            className={`text-xs ${haTestStatus.startsWith('Success') ? 'text-good' : 'text-bad'}`}
                                        >
                                            {haTestStatus}
                                        </span>
                                    )}
                                </div>
                            )}
                        </Card>
                    </div>
                )
            })}
            <div className="flex flex-wrap items-center gap-3">
                <button
                    disabled={saving}
                    onClick={() => save()}
                    className="flex items-center justify-center gap-2 rounded-xl px-3 py-2.5 text-[11px] font-semibold transition btn-glow-primary bg-accent hover:bg-accent2 text-[#100f0e] disabled:opacity-50"
                >
                    {saving ? 'Saving…' : 'Save System Settings'}
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
        </div>
    )
}
