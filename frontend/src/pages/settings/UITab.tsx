import React, { useState, useEffect } from 'react'
import { Api, ThemeInfo } from '../../lib/api'
import Card from '../../components/Card'
import { useSettingsForm } from './hooks/useSettingsForm'
import { SettingsField } from './components/SettingsField'
import { uiFieldList, uiSections } from './types'

export const UITab: React.FC = () => {
    const { config, form, fieldErrors, loading, saving, statusMessage, handleChange, save } =
        useSettingsForm(uiFieldList)

    const [themes, setThemes] = useState<ThemeInfo[]>([])

    useEffect(() => {
        Api.theme().then((res) => setThemes(res.themes))
    }, [])

    if (loading) {
        return <Card className="p-6 text-sm text-muted">Loading UI configuration…</Card>
    }

    const currentThemeIdx = config?.ui?.theme_accent_index ?? 0
    const overlayDefaults = form['dashboard.overlay_defaults']
        ? (JSON.parse(form['dashboard.overlay_defaults']) as Record<string, boolean>)
        : {}

    const toggleOverlay = (key: string) => {
        const next = { ...overlayDefaults, [key]: !overlayDefaults[key] }
        handleChange('dashboard.overlay_defaults', JSON.stringify(next))
    }

    return (
        <div className="space-y-4">
            <Card className="p-6">
                <div className="flex items-baseline justify-between gap-2">
                    <div>
                        <div className="text-sm font-semibold">Accent Theme</div>
                        <p className="text-xs text-muted mt-1">Select the primary accent color for the Darkstar UI.</p>
                    </div>
                    <span className="text-[10px] uppercase text-muted tracking-wide">Appearance</span>
                </div>
                <div className="mt-5 flex flex-wrap gap-3">
                    {themes.map((theme, idx) => (
                        <button
                            key={theme.name}
                            onClick={() => save({ ui: { theme_accent_index: idx } })}
                            disabled={saving}
                            className={`group relative h-12 w-12 rounded-xl transition duration-300 ${
                                currentThemeIdx === idx
                                    ? 'ring-2 ring-accent ring-offset-4 ring-offset-[#0a0a0a]'
                                    : 'hover:rotate-3 hover:scale-105'
                            }`}
                            style={{ backgroundColor: theme.palette[0] }}
                        >
                            <span className="absolute -bottom-6 left-1/2 -translate-x-1/2 scale-0 text-[10px] text-muted transition group-hover:scale-100 whitespace-nowrap">
                                {theme.name}
                            </span>
                            {currentThemeIdx === idx && (
                                <div className="absolute inset-0 flex items-center justify-center bg-black/10 rounded-xl">
                                    <div className="h-1.5 w-1.5 rounded-full bg-white shadow-[0_0_8px_white]" />
                                </div>
                            )}
                        </button>
                    ))}
                </div>
            </Card>

            {uiSections.map((section) => (
                <Card key={section.title} className="p-6">
                    <div className="flex items-baseline justify-between gap-2">
                        <div>
                            <div className="text-sm font-semibold">{section.title}</div>
                            <p className="text-xs text-muted mt-1">{section.description}</p>
                        </div>
                        <span className="text-[10px] uppercase text-muted tracking-wide">Interface</span>
                    </div>
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
                    {section.title === 'Dashboard Defaults' && (
                        <div className="mt-6 border-t border-line/30 pt-4">
                            <div className="text-[10px] uppercase tracking-widest text-muted font-bold mb-3">
                                Overlay Defaults
                            </div>
                            <div className="flex flex-wrap gap-2">
                                {['solar', 'battery', 'load', 'grid', 'water', 'forecast'].map((key) => (
                                    <button
                                        key={key}
                                        onClick={() => toggleOverlay(key)}
                                        className={`rounded-lg px-2.5 py-1.5 text-[10px] font-bold uppercase tracking-wider transition ${
                                            overlayDefaults[key]
                                                ? 'bg-accent/20 text-accent border border-accent/30'
                                                : 'bg-surface2 text-muted border border-line/50 hover:border-line'
                                        }`}
                                    >
                                        {key}
                                    </button>
                                ))}
                            </div>
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
                    {saving ? 'Saving…' : 'Save UI Settings'}
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
        </div>
    )
}
