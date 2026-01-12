import React from 'react'
import Card from '../../components/Card'
import { useSettingsForm } from './hooks/useSettingsForm'
import { SettingsField } from './components/SettingsField'
import { parameterFieldList, parameterSections } from './types'

export const ParametersTab: React.FC = () => {
    const { form, fieldErrors, loading, saving, statusMessage, handleChange, save } =
        useSettingsForm(parameterFieldList)

    if (loading) {
        return <Card className="p-6 text-sm text-muted">Loading optimization parameters…</Card>
    }

    return (
        <div className="space-y-4">
            {parameterSections.map((section) => (
                <Card key={section.title} className="p-6">
                    <div className="flex items-baseline justify-between gap-2">
                        <div>
                            <div className="text-sm font-semibold">{section.title}</div>
                            <p className="text-xs text-muted mt-1">{section.description}</p>
                        </div>
                        <span className="text-[10px] uppercase text-muted tracking-wide">Optimization</span>
                    </div>
                    <div className="mt-5 grid gap-4 sm:grid-cols-2">
                        {section.fields.map((field) => (
                            <SettingsField
                                key={field.key}
                                field={field}
                                value={form[field.key] ?? ''}
                                onChange={handleChange}
                                error={fieldErrors[field.key]}
                                fullForm={form}
                            />
                        ))}
                    </div>
                </Card>
            ))}
            <div className="flex flex-wrap items-center gap-3">
                <button
                    disabled={saving}
                    onClick={() => save()}
                    className="flex items-center justify-center gap-2 rounded-xl px-3 py-2.5 text-[11px] font-semibold transition btn-glow-primary bg-accent hover:bg-accent2 text-[#100f0e] disabled:opacity-50"
                >
                    {saving ? 'Saving…' : 'Save Parameters'}
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
