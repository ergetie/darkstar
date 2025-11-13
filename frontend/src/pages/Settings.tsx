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

type ParameterField = {
    key: string
    label: string
    helper?: string
    path: string[]
    type: 'number' | 'text' | 'boolean' | 'select' | 'array'
    options?: { label: string; value: string }[]
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

const parameterSections = [
    {
        title: 'Charging Strategy',
        description: 'Price smoothing, consolidation tolerances, and gap settings that govern charge windows.',
        fields: [
            { key: 'charging_strategy.price_smoothing_sek_kwh', label: 'Price smoothing (SEK/kWh)', path: ['charging_strategy', 'price_smoothing_sek_kwh'], type: 'number' },
            { key: 'charging_strategy.block_consolidation_tolerance_sek', label: 'Consolidation tolerance (SEK)', path: ['charging_strategy', 'block_consolidation_tolerance_sek'], type: 'number' },
            { key: 'charging_strategy.consolidation_max_gap_slots', label: 'Max gap slots', path: ['charging_strategy', 'consolidation_max_gap_slots'], type: 'number' },
            { key: 'charging_strategy.charge_threshold_percentile', label: 'Charge threshold (percentile)', path: ['charging_strategy', 'charge_threshold_percentile'], type: 'number' },
            { key: 'charging_strategy.cheap_price_tolerance_sek', label: 'Cheap price tolerance (SEK)', path: ['charging_strategy', 'cheap_price_tolerance_sek'], type: 'number' },
        ],
    },
    {
        title: 'Arbitrage & Export',
        description: 'Export thresholds, peak-only export, and future guard buffers.',
        fields: [
            { key: 'arbitrage.export_percentile_threshold', label: 'Export percentile threshold', path: ['arbitrage', 'export_percentile_threshold'], type: 'number' },
            { key: 'arbitrage.enable_peak_only_export', label: 'Enable peak-only export', path: ['arbitrage', 'enable_peak_only_export'], type: 'boolean', helper: 'Override to only export when we hit the percentile threshold.' },
            { key: 'arbitrage.export_future_price_guard', label: 'Future price guard', path: ['arbitrage', 'export_future_price_guard'], type: 'boolean' },
            { key: 'arbitrage.future_price_guard_buffer_sek', label: 'Future guard buffer (SEK)', path: ['arbitrage', 'future_price_guard_buffer_sek'], type: 'number' },
            { key: 'arbitrage.export_profit_margin_sek', label: 'Export profit margin (SEK)', path: ['arbitrage', 'export_profit_margin_sek'], type: 'number' },
        ],
    },
    {
        title: 'Water Heating',
        description: 'Quota, deferral, and sizing controls for the water heater scheduler.',
        fields: [
            { key: 'water_heating.power_kw', label: 'Water heater power (kW)', path: ['water_heating', 'power_kw'], type: 'number' },
            { key: 'water_heating.defer_up_to_hours', label: 'Max defer hours', path: ['water_heating', 'defer_up_to_hours'], type: 'number' },
            { key: 'water_heating.max_blocks_per_day', label: 'Max blocks per day', path: ['water_heating', 'max_blocks_per_day'], type: 'number' },
            { key: 'water_heating.min_kwh_per_day', label: 'Min kWh/day', path: ['water_heating', 'min_kwh_per_day'], type: 'number' },
            { key: 'water_heating.schedule_future_only', label: 'Schedule future only', path: ['water_heating', 'schedule_future_only'], type: 'boolean' },
        ],
    },
    {
        title: 'Learning Parameter Limits',
        description: 'Limits that keep learning adjustments conservative.',
        fields: [
            { key: 'learning.min_sample_threshold', label: 'Min sample threshold', path: ['learning', 'min_sample_threshold'], type: 'number' },
            { key: 'learning.min_improvement_threshold', label: 'Min improvement (%)', path: ['learning', 'min_improvement_threshold'], type: 'number' },
            { key: 'learning.max_daily_param_change.battery_use_margin_sek', label: 'Battery margin change (SEK)', path: ['learning', 'max_daily_param_change', 'battery_use_margin_sek'], type: 'number' },
            { key: 'learning.max_daily_param_change.export_profit_margin_sek', label: 'Export margin change (SEK)', path: ['learning', 'max_daily_param_change', 'export_profit_margin_sek'], type: 'number' },
            { key: 'learning.max_daily_param_change.future_price_guard_buffer_sek', label: 'Future guard buffer change (SEK)', path: ['learning', 'max_daily_param_change', 'future_price_guard_buffer_sek'], type: 'number' },
            { key: 'learning.max_daily_param_change.load_safety_margin_percent', label: 'Load safety change (%)', path: ['learning', 'max_daily_param_change', 'load_safety_margin_percent'], type: 'number' },
            { key: 'learning.max_daily_param_change.pv_confidence_percent', label: 'PV confidence change (%)', path: ['learning', 'max_daily_param_change', 'pv_confidence_percent'], type: 'number' },
            { key: 'learning.max_daily_param_change.s_index_base_factor', label: 'S-index base change', path: ['learning', 'max_daily_param_change', 's_index_base_factor'], type: 'number' },
            { key: 'learning.max_daily_param_change.s_index_pv_deficit_weight', label: 'S-index PV weight change', path: ['learning', 'max_daily_param_change', 's_index_pv_deficit_weight'], type: 'number' },
            { key: 'learning.max_daily_param_change.s_index_temp_weight', label: 'S-index temp weight change', path: ['learning', 'max_daily_param_change', 's_index_temp_weight'], type: 'number' },
        ],
    },
    {
        title: 'S-Index Safety',
        description: 'Base/max factors, weights, and time horizon shaping the S-index guard.',
        fields: [
            { key: 's_index.mode', label: 'Mode', path: ['s_index', 'mode'], type: 'select', options: [{ label: 'Static', value: 'static' }, { label: 'Dynamic', value: 'dynamic' }] },
            { key: 's_index.base_factor', label: 'Base factor', path: ['s_index', 'base_factor'], type: 'number' },
            { key: 's_index.max_factor', label: 'Max factor', path: ['s_index', 'max_factor'], type: 'number' },
            { key: 's_index.static_factor', label: 'Static fallback factor', path: ['s_index', 'static_factor'], type: 'number' },
            { key: 's_index.pv_deficit_weight', label: 'PV deficit weight', path: ['s_index', 'pv_deficit_weight'], type: 'number' },
            { key: 's_index.temp_weight', label: 'Temp weight', path: ['s_index', 'temp_weight'], type: 'number' },
            { key: 's_index.temp_baseline_c', label: 'Temp baseline (°C)', path: ['s_index', 'temp_baseline_c'], type: 'number' },
            { key: 's_index.temp_cold_c', label: 'Cold temp (°C)', path: ['s_index', 'temp_cold_c'], type: 'number' },
            { key: 's_index.days_ahead_for_sindex', label: 'Days ahead (comma list)', path: ['s_index', 'days_ahead_for_sindex'], type: 'array', helper: 'Comma-separated integers (e.g. 2,3,4).', },
        ],
    },
]

const systemFieldList: SystemField[] = systemSections.flatMap((section) => section.fields)
const systemFieldMap: Record<string, SystemField> = systemFieldList.reduce((acc, field) => {
    acc[field.key] = field
    return acc
}, {} as Record<string, SystemField>)

const parameterFieldList: ParameterField[] = parameterSections.flatMap((section) => section.fields)
const parameterFieldMap: Record<string, ParameterField> = parameterFieldList.reduce((acc, field) => {
    acc[field.key] = field
    return acc
}, {} as Record<string, ParameterField>)

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

function buildParameterFormState(config: Record<string, any> | null): Record<string, string> {
    const state: Record<string, string> = {}
    parameterFieldList.forEach((field) => {
        const value = config ? getDeepValue(config, field.path) : undefined
        if (field.type === 'boolean') {
            state[field.key] = value === true ? 'true' : 'false'
        } else if (field.type === 'array' && Array.isArray(value)) {
            state[field.key] = value.join(', ')
        } else {
            state[field.key] = value !== undefined && value !== null ? String(value) : ''
        }
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

function parseParameterFieldInput(field: ParameterField, raw: string): any {
    const trimmed = raw.trim()
    if (field.type === 'number') {
        if (trimmed === '') return null
        const parsed = Number(trimmed)
        return Number.isNaN(parsed) ? undefined : parsed
    }
    if (field.type === 'boolean') {
        return trimmed === 'true'
    }
    if (field.type === 'array') {
        if (!trimmed) return []
        const parts = trimmed.split(',').map((part) => part.trim()).filter(Boolean)
        const parsed = parts.map((value) => Number(value)).filter((value) => !Number.isNaN(value))
        return parsed
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

function buildParameterPatch(original: Record<string, any>, form: Record<string, string>): Record<string, any> {
    const patch: Record<string, any> = {}
    parameterFieldList.forEach((field) => {
        const raw = form[field.key] ?? ''
        const parsed = parseParameterFieldInput(field, raw)
        if (parsed === undefined) return
        const currentValue = getDeepValue(original, field.path)
        const equal = (() => {
            if (field.type === 'array') {
                if (!Array.isArray(parsed)) return false
                if (!Array.isArray(currentValue)) return false
                if (parsed.length !== currentValue.length) return false
                for (let i = 0; i < parsed.length; i += 1) {
                    if (parsed[i] !== currentValue[i]) return false
                }
                return true
            }
            return parsed === currentValue
        })()
        if (equal) return
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
    const [parameterForm, setParameterForm] = useState<Record<string, string>>(() => buildParameterFormState(null))
    const [systemFieldErrors, setSystemFieldErrors] = useState<Record<string, string>>({})
    const [parameterFieldErrors, setParameterFieldErrors] = useState<Record<string, string>>({})
    const [loadingConfig, setLoadingConfig] = useState(true)
    const [configError, setConfigError] = useState<string | null>(null)
    const [systemSaving, setSystemSaving] = useState(false)
    const [parameterSaving, setParameterSaving] = useState(false)
    const [systemStatusMessage, setSystemStatusMessage] = useState<string | null>(null)
    const [parameterStatusMessage, setParameterStatusMessage] = useState<string | null>(null)
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
                setParameterForm(buildParameterFormState(cfg))
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
        setSystemStatusMessage(null)
        if (field.type === 'number') {
            const trimmed = value.trim()
            setSystemFieldErrors((prev) => {
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

    const handleParameterFieldChange = (key: string, value: string) => {
        const field = parameterFieldMap[key]
        if (!field) return
        setParameterForm((prev) => ({ ...prev, [key]: value }))
        setParameterStatusMessage(null)
        if (field.type === 'number') {
            const trimmed = value.trim()
            setParameterFieldErrors((prev) => {
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

    const systemErrors = Object.values(systemFieldErrors).filter(Boolean).length
    const hasSystemValidationErrors = systemErrors > 0

    const parameterErrors = Object.values(parameterFieldErrors).filter(Boolean).length
    const hasParameterValidationErrors = parameterErrors > 0

    const handleSaveSystem = async () => {
        if (!config) return
        if (hasSystemValidationErrors) {
            setSystemStatusMessage('Fix validation errors before saving.')
            return
        }
        const patch = buildSystemPatch(config, systemForm)
        if (!Object.keys(patch).length) {
            setSystemStatusMessage('No changes detected.')
            return
        }
        setSystemSaving(true)
        setSystemStatusMessage(null)
        try {
            await Api.configSave(patch)
            const fresh = await Api.config()
            setConfig(fresh)
            setSystemForm(buildSystemFormState(fresh))
            setParameterForm(buildParameterFormState(fresh))
            setSystemFieldErrors({})
            setSystemStatusMessage('System settings saved.')
        } catch (err: any) {
            setSystemStatusMessage(err?.message ? `Failed to save: ${err.message}` : 'Save failed.')
        } finally {
            setSystemSaving(false)
        }
    }

    const handleSaveParameters = async () => {
        if (!config) return
        if (hasParameterValidationErrors) {
            setParameterStatusMessage('Fix validation errors before saving.')
            return
        }
        const patch = buildParameterPatch(config, parameterForm)
        if (!Object.keys(patch).length) {
            setParameterStatusMessage('No changes detected.')
            return
        }
        setParameterSaving(true)
        setParameterStatusMessage(null)
        try {
            await Api.configSave(patch)
            const fresh = await Api.config()
            setConfig(fresh)
            setSystemForm(buildSystemFormState(fresh))
            setParameterForm(buildParameterFormState(fresh))
            setParameterFieldErrors({})
            setParameterStatusMessage('Parameters saved.')
        } catch (err: any) {
            setParameterStatusMessage(err?.message ? `Failed to save: ${err.message}` : 'Save failed.')
        } finally {
            setParameterSaving(false)
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
                                    {systemFieldErrors[field.key] && (
                                        <p className="text-[11px] text-red-400">{systemFieldErrors[field.key]}</p>
                                    )}
                                </div>
                            ))}
                        </div>
                    </Card>
                ))}
                <div className="flex flex-wrap items-center gap-3">
                    <button
                        disabled={systemSaving || loadingConfig}
                        onClick={handleSaveSystem}
                        className="rounded-pill bg-accent px-4 py-2 text-sm font-semibold text-[#100f0e] shadow-sm transition hover:bg-accent2 disabled:opacity-50"
                    >
                        {systemSaving ? 'Saving…' : 'Save System Settings'}
                    </button>
                    {systemStatusMessage && (
                        <p className={`text-sm ${systemStatusMessage.startsWith('Failed') ? 'text-red-400' : 'text-muted'}`}>
                            {systemStatusMessage}
                        </p>
                    )}
                </div>
            </div>
        )
    }

    const renderParameterForm = () => {
        if (loadingConfig) {
            return (
                <Card className="p-6 text-sm text-muted">
                    Loading parameter configuration…
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
                {parameterSections.map((section) => (
                    <Card key={section.title} className="p-6">
                        <div className="flex items-baseline justify-between gap-2">
                            <div>
                                <div className="text-sm font-semibold">{section.title}</div>
                                <p className="text-xs text-muted mt-1">{section.description}</p>
                            </div>
                            <span className="text-[10px] uppercase text-muted tracking-wide">Parameters</span>
                        </div>
                        <div className="mt-5 grid gap-4 sm:grid-cols-2">
                            {section.fields.map((field) => (
                                <div key={field.key} className="space-y-1">
                                    {field.type === 'boolean' ? (
                                        <label className="flex items-center gap-2 text-sm">
                                            <input
                                                type="checkbox"
                                                checked={parameterForm[field.key] === 'true'}
                                                onChange={(event) => handleParameterFieldChange(field.key, event.target.checked ? 'true' : 'false')}
                                                className="h-4 w-4 rounded border border-line/60 text-accent focus:ring-0"
                                            />
                                            <span className="font-semibold">{field.label}</span>
                                        </label>
                                    ) : field.type === 'select' ? (
                                        <>
                                            <label className="text-[10px] uppercase tracking-wide text-muted">{field.label}</label>
                                            <select
                                                value={parameterForm[field.key] ?? ''}
                                                onChange={(event) => handleParameterFieldChange(field.key, event.target.value)}
                                                className="w-full rounded-lg border border-line/50 bg-surface2 px-3 py-2 text-sm text-white focus:border-accent focus:outline-none"
                                            >
                                                <option value="">Select</option>
                                                {field.options?.map((option) => (
                                                    <option key={option.value} value={option.value}>
                                                        {option.label}
                                                    </option>
                                                ))}
                                            </select>
                                        </>
                                    ) : (
                                        <>
                                            <label className="text-[10px] uppercase tracking-wide text-muted">{field.label}</label>
                                            <input
                                                type={field.type === 'number' ? 'number' : 'text'}
                                                inputMode={field.type === 'number' ? 'decimal' : undefined}
                                                value={parameterForm[field.key] ?? ''}
                                                onChange={(event) => handleParameterFieldChange(field.key, event.target.value)}
                                                className="w-full rounded-lg border border-line/50 bg-surface2 px-3 py-2 text-sm text-white focus:border-accent focus:outline-none"
                                            />
                                        </>
                                    )}
                                    {field.helper && (
                                        <p className="text-[11px] text-muted">{field.helper}</p>
                                    )}
                                    {parameterFieldErrors[field.key] && (
                                        <p className="text-[11px] text-red-400">{parameterFieldErrors[field.key]}</p>
                                    )}
                                </div>
                            ))}
                        </div>
                    </Card>
                ))}
                <div className="flex flex-wrap items-center gap-3">
                    <button
                        disabled={parameterSaving || loadingConfig}
                        onClick={handleSaveParameters}
                        className="rounded-pill bg-accent px-4 py-2 text-sm font-semibold text-[#100f0e] shadow-sm transition hover:bg-accent2 disabled:opacity-50"
                    >
                        {parameterSaving ? 'Saving…' : 'Save Parameters'}
                    </button>
                    {parameterStatusMessage && (
                        <p className={`text-sm ${parameterStatusMessage.startsWith('Failed') ? 'text-red-400' : 'text-muted'}`}>
                            {parameterStatusMessage}
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

            {activeTab === 'system'
                ? renderSystemForm()
                : activeTab === 'parameters'
                    ? renderParameterForm()
                    : (
                        <div className="grid gap-6 md:grid-cols-2">
                            {sections.map((section) => (
                                <SectionCard key={section.title} {...section} />
                            ))}
                        </div>
                    )}
        </main>
    )
}
