import { useEffect, useMemo, useState } from 'react'
import Card from '../components/Card'
import { Api } from '../lib/api'

const tabs = [
    { id: 'system', label: 'System' },
    { id: 'parameters', label: 'Parameters' },
    { id: 'ui', label: 'UI' },
]

const sectionMap: Record<string, Array<{ title: string; description: string; items: string[] }>> = {
    system: [
        {
            title: 'Battery & Grid',
            description: 'Capacity, max power, and SoC limits define safe operating bands.',
            items: ['system.battery.capacity_kwh', 'system.battery.max_charge_power_kw', 'system.battery.min_soc_percent', 'system.grid.max_power_kw'],
        },
        {
            title: 'Home Assistant & Learning Storage',
            description: 'Entity IDs plus the sqlite path that backs the planner learning store.',
            items: ['learning.sqlite_path'],
        },
        {
            title: 'Pricing & Timing',
            description: 'Nordpool zone, resolution, currency, and timezone for all calculations.',
            items: ['nordpool.price_area', 'nordpool.resolution_minutes', 'timezone'],
        },
    ],
    parameters: [
        {
            title: 'Charging Strategy',
            description: 'Price smoothing, consolidation tolerances, and gap settings that govern charge windows.',
            items: ['charging_strategy.price_smoothing_sek_kwh', 'charging_strategy.block_consolidation_tolerance_sek', 'charging_strategy.consolidation_max_gap_slots'],
        },
        {
            title: 'Arbitrage & Export',
            description: 'Export thresholds, peak-only export, and future guard buffers.',
            items: ['arbitrage.export_percentile_threshold', 'arbitrage.enable_peak_only_export', 'arbitrage.export_future_price_guard', 'arbitrage.future_price_guard_buffer_sek'],
        },
        {
            title: 'Water Heating',
            description: 'Quota, deferral, and sizing controls for the water heater scheduler.',
            items: ['water_heating.power_kw', 'water_heating.defer_up_to_hours', 'water_heating.schedule_future_only'],
        },
        {
            title: 'Learning Parameter Limits',
            description: 'Limits that keep learning adjustments conservative.',
            items: ['learning.max_daily_param_change.*', 'learning.min_sample_threshold', 'learning.min_improvement_threshold'],
        },
        {
            title: 'S-Index Safety',
            description: 'Base/max factors, weights, and time horizon shaping the S-index guard.',
            items: ['s_index.mode', 's_index.base_factor', 's_index.max_factor', 's_index.pv_deficit_weight', 's_index.temp_weight'],
        },
    ],
    ui: [
        {
            title: 'Theme & Appearance',
            description: 'Current theme and accent color controls shared with Dashboard & Planning.',
            items: ['ui.theme', 'ui.theme_accent_index'],
        },
        {
            title: 'Dashboard Defaults',
            description: 'Overlay and refresh toggles that control the default dashboard experience.',
            items: ['dashboard.overlay_defaults', 'dashboard.auto_refresh_enabled'],
        },
    ],
}

type SystemField = {
    key: string
    label: string
    helper?: string
    path: string[]
    type: 'number' | 'text'
}

const systemSections = [
    {
        title: 'Battery & Grid',
        description: 'Capacity, max power, and SoC limits define safe operating bands.',
        fields: [
            { key: 'system.battery.capacity_kwh', label: 'Battery capacity (kWh)', path: ['system', 'battery', 'capacity_kwh'], type: 'number' },
            { key: 'system.battery.max_charge_power_kw', label: 'Max charge power (kW)', path: ['system', 'battery', 'max_charge_power_kw'], type: 'number' },
            { key: 'system.battery.max_discharge_power_kw', label: 'Max discharge power (kW)', path: ['system', 'battery', 'max_discharge_power_kw'], type: 'number' },
            { key: 'system.battery.min_soc_percent', label: 'Min SoC (%)', path: ['system', 'battery', 'min_soc_percent'], type: 'number' },
            { key: 'system.battery.max_soc_percent', label: 'Max SoC (%)', path: ['system', 'battery', 'max_soc_percent'], type: 'number' },
            { key: 'system.grid.max_power_kw', label: 'Grid max power (kW)', path: ['system', 'grid', 'max_power_kw'], type: 'number' },
        ],
    },
    {
        title: 'Home Assistant & Learning Storage',
        description: 'Additionally track the learning database path for telemetry.',
        fields: [
            { key: 'learning.sqlite_path', label: 'Learning SQLite path', helper: 'Directory must exist and be writable.', path: ['learning', 'sqlite_path'], type: 'text' },
        ],
    },
    {
        title: 'Pricing & Timing',
        description: 'Nordpool zone, resolution, and timezone for planner calculations.',
        fields: [
            { key: 'nordpool.price_area', label: 'Price area', path: ['nordpool', 'price_area'], type: 'text' },
            { key: 'nordpool.resolution_minutes', label: 'Price resolution (minutes)', path: ['nordpool', 'resolution_minutes'], type: 'number' },
            { key: 'timezone', label: 'Timezone', path: ['timezone'], type: 'text' },
        ],
    },
]

const systemFieldList: SystemField[] = systemSections.flatMap((section) => section.fields)
const systemFieldMap: Record<string, SystemField> = systemFieldList.reduce((acc, field) => {
    acc[field.key] = field
    return acc
}, {} as Record<string, SystemField>)

function getDeepValue(source: any, path: string[]): any {
    return path.reduce((current, key) => (current && typeof current === 'object' ? current[key] : undefined), source)
}

function setDeepValue(target: Record<string, any>, path: string[], value: any) {
    let cursor: Record<string, any> = target
    path.forEach((key, index) => {
        if (index === path.length - 1) {
            cursor[key] = value
            return
        }
        if (!cursor[key] || typeof cursor[key] !== 'object') {
            cursor[key] = {}
        }
        cursor = cursor[key]
    })
}

function buildSystemFormState(config: Record<string, any> | null): Record<string, string> {
    const state: Record<string, string> = {}
    systemFieldList.forEach((field) => {
        const value = config ? getDeepValue(config, field.path) : undefined
        state[field.key] = value !== undefined && value !== null ? String(value) : ''
    })
    return state
}

function parseFieldInput(field: SystemField, raw: string): number | string | null | undefined {
    const trimmed = raw.trim()
    if (field.type === 'number') {
        if (trimmed === '') return null
        const parsed = Number(trimmed)
        return Number.isNaN(parsed) ? undefined : parsed
    }
    return trimmed
}

function buildSystemPatch(original: Record<string, any>, form: Record<string, string>): Record<string, any> {
    const patch: Record<string, any> = {}
    systemFieldList.forEach((field) => {
        const raw = form[field.key] ?? ''
        const parsed = parseFieldInput(field, raw)
        if (parsed === undefined) return
        if (field.type === 'number' && parsed === null) return
        const currentValue = getDeepValue(original, field.path)
        if (parsed === currentValue) return
        setDeepValue(patch, field.path, parsed)
    })
    return patch
}

function SectionCard({ title, description, items }: { title: string; description: string; items: string[] }) {
    return (
        <Card className="p-6">
            <div className="text-sm font-semibold">{title}</div>
            <p className="text-xs text-muted mt-1 mb-3">{description}</p>
            <div className="flex flex-wrap gap-2">
                {items.map((item) => (
                    <span key={item} className="text-[11px] uppercase tracking-wide text-muted px-2 py-1 rounded-full border border-line/40">
                        {item}
                    </span>
                ))}
            </div>
        </Card>
    )
}

export default function Settings(){
    const [activeTab, setActiveTab] = useState('system')
    const [config, setConfig] = useState<Record<string, any> | null>(null)
    const [systemForm, setSystemForm] = useState<Record<string, string>>(() => buildSystemFormState(null))
    const [fieldErrors, setFieldErrors] = useState<Record<string, string>>({})
    const [loadingConfig, setLoadingConfig] = useState(true)
    const [configError, setConfigError] = useState<string | null>(null)
    const [saving, setSaving] = useState(false)
    const [statusMessage, setStatusMessage] = useState<string | null>(null)
    const sections = useMemo(() => sectionMap[activeTab], [activeTab])

    useEffect(() => {
        let cancelled = false
        setLoadingConfig(true)
        setConfigError(null)
        Api.config()
            .then((cfg) => {
                if (cancelled) return
                setConfig(cfg)
                setSystemForm(buildSystemFormState(cfg))
            })
            .catch((err) => {
                if (cancelled) return
                setConfigError(err.message || 'Failed to load configuration')
            })
            .finally(() => {
                if (cancelled) return
                setLoadingConfig(false)
            })
        return () => {
            cancelled = true
        }
    }, [])

    const handleFieldChange = (key: string, value: string) => {
        const field = systemFieldMap[key]
        if (!field) return
        setSystemForm((prev) => ({ ...prev, [key]: value }))
        setStatusMessage(null)
        if (field.type === 'number') {
            const trimmed = value.trim()
            setFieldErrors((prev) => {
                const next = { ...prev }
                if (trimmed === '') {
                    next[key] = 'Required'
                } else if (Number.isNaN(Number(trimmed))) {
                    next[key] = 'Must be a number'
                } else {
                    delete next[key]
                }
                return next
            })
        }
    }

    const fieldErrorCount = Object.values(fieldErrors).filter(Boolean).length
    const hasValidationErrors = fieldErrorCount > 0

    const handleSaveSystem = async () => {
        if (!config) return
        if (hasValidationErrors) {
            setStatusMessage('Fix validation errors before saving.')
            return
        }
        const patch = buildSystemPatch(config, systemForm)
        if (!Object.keys(patch).length) {
            setStatusMessage('No changes detected.')
            return
        }
        setSaving(true)
        setStatusMessage(null)
        try {
            await Api.configSave(patch)
            const fresh = await Api.config()
            setConfig(fresh)
            setSystemForm(buildSystemFormState(fresh))
            setFieldErrors({})
            setStatusMessage('System settings saved.')
        } catch (err: any) {
            setStatusMessage(err?.message ? `Failed to save: ${err.message}` : 'Save failed.')
        } finally {
            setSaving(false)
        }
    }

    const renderSystemForm = () => {
        if (loadingConfig) {
            return (
                <Card className="p-6 text-sm text-muted">
                    Loading system configuration…
                </Card>
            )
        }
        if (configError) {
            return (
                <Card className="p-6 text-sm text-red-400">
                    {configError}
                </Card>
            )
        }
        return (
            <div className="space-y-4">
                {systemSections.map((section) => (
                    <Card key={section.title} className="p-6">
                        <div className="flex items-baseline justify-between gap-2">
                            <div>
                                <div className="text-sm font-semibold">{section.title}</div>
                                <p className="text-xs text-muted mt-1">{section.description}</p>
                            </div>
                            <span className="text-[10px] uppercase text-muted tracking-wide">System</span>
                        </div>
                        <div className="mt-5 grid gap-4 sm:grid-cols-2">
                            {section.fields.map((field) => (
                                <div key={field.key} className="space-y-1">
                                    <label className="text-[10px] uppercase tracking-wide text-muted">{field.label}</label>
                                    <input
                                        type={field.type === 'number' ? 'number' : 'text'}
                                        inputMode={field.type === 'number' ? 'decimal' : undefined}
                                        value={systemForm[field.key] ?? ''}
                                        onChange={(event) => handleFieldChange(field.key, event.target.value)}
                                        className="w-full rounded-lg border border-line/50 bg-surface2 px-3 py-2 text-sm text-white focus:border-accent focus:outline-none"
                                    />
                                    {field.helper && (
                                        <p className="text-[11px] text-muted">{field.helper}</p>
                                    )}
                                    {fieldErrors[field.key] && (
                                        <p className="text-[11px] text-red-400">{fieldErrors[field.key]}</p>
                                    )}
                                </div>
                            ))}
                        </div>
                    </Card>
                ))}
                <div className="flex flex-wrap items-center gap-3">
                    <button
                        disabled={saving || loadingConfig}
                        onClick={handleSaveSystem}
                        className="rounded-pill bg-accent px-4 py-2 text-sm font-semibold text-[#100f0e] shadow-sm transition hover:bg-accent2 disabled:opacity-50"
                    >
                        {saving ? 'Saving…' : 'Save System Settings'}
                    </button>
                    {statusMessage && (
                        <p className={`text-sm ${statusMessage.startsWith('Failed') ? 'text-red-400' : 'text-muted'}`}>
                            {statusMessage}
                        </p>
                    )}
                </div>
            </div>
        )
    }

    return (
        <main className="mx-auto max-w-7xl px-6 pb-24 pt-10 lg:pt-12 space-y-6">
            <div>
                <p className="text-base text-muted">Rev 43 · Settings & Configuration</p>
                <h1 className="text-3xl font-semibold">Settings</h1>
                <p className="text-sm text-muted">System, parameters, and UI preferences collected into one modern surface.</p>
            </div>

            <div className="flex flex-wrap gap-2">
                {tabs.map((tab) => {
                    const active = activeTab === tab.id
                    return (
                        <button
                            key={tab.id}
                            onClick={() => setActiveTab(tab.id)}
                            className={`rounded-full px-4 py-2 text-sm font-semibold transition ${
                                active ? 'bg-accent text-[#0F1216] shadow-sm' : 'bg-surface border border-line/50 text-muted'
                            }`}
                        >
                            {tab.label}
                        </button>
                    )
                })}
            </div>

            {activeTab === 'system' ? (
                renderSystemForm()
            ) : (
                <div className="grid gap-6 md:grid-cols-2">
                    {sections.map((section) => (
                        <SectionCard key={section.title} {...section} />
                    ))}
                </div>
            )}
        </main>
    )
}
