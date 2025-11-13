import { useMemo, useState } from 'react'
import Card from '../components/Card'

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
            items: ['secrets.battery_soc_entity_id', 'secrets.water_heater_daily_entity_id', 'learning.sqlite_path'],
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
    const sections = useMemo(() => sectionMap[activeTab], [activeTab])

    return (
        <main className="mx-auto max-w-7xl px-6 pb-24 pt-10 lg:pt-12 space-y-6">
            <div>
                <p className="text-base text-muted">Rev 43 · Settings & Configuration</p>
                <h1 className="text-3xl font-semibold">Settings</h1>
                <p className="text-sm text-muted">System, parameters, and UI preferences collected into one modern surface.</p>
            </div>

            <div className="flex gap-2">
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

            <div className="grid gap-6 md:grid-cols-2">
                {sections.map((section) => (
                    <SectionCard key={section.title} {...section} />
                ))}
            </div>
        </main>
    )
}
