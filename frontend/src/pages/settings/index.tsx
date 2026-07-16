import React, { useState, useEffect, useMemo, useCallback } from 'react'
import { useSearchParams } from 'react-router-dom'
import {
    Settings as SettingsIcon,
    Sliders,
    Palette,
    Zap,
    ShieldAlert,
    Bug,
    Sun,
    Battery,
    Zap as EvIcon,
    Droplets,
    Gauge,
} from 'lucide-react'

import { SystemTab } from './SystemTab'
import { ParametersTab } from './ParametersTab'
import { SolarTab } from './SolarTab'
import { BatteryTab } from './BatteryTab'
import { EVTab } from './EVTab'
import { WaterTab } from './WaterTab'
import { LoadBalancingTab } from './LoadBalancingTab'
import { UITab } from './UITab'
import { AdvancedTab } from './AdvancedTab'
import { DebugContent } from '../Debug'
import { Api } from '../../lib/api'

interface SystemFlags {
    has_solar?: boolean
    has_battery?: boolean
    has_water_heater?: boolean
    has_ev_charger?: boolean
}

const ALL_TABS = [
    { id: 'system', label: 'System', icon: <SettingsIcon size={16} /> },
    { id: 'parameters', label: 'Parameters', icon: <Sliders size={16} /> },
    { id: 'solar', label: 'Solar', icon: <Sun size={16} />, showIf: 'system.has_solar' },
    { id: 'battery', label: 'Battery', icon: <Battery size={16} />, showIf: 'system.has_battery' },
    { id: 'ev', label: 'EV', icon: <EvIcon size={16} />, showIf: 'system.has_ev_charger' },
    { id: 'water', label: 'Heating', icon: <Droplets size={16} />, showIf: 'system.has_water_heater' },
    {
        id: 'load-balancing',
        label: 'Load Balancing',
        icon: <Gauge size={16} />,
        showIf: 'system.has_ev_charger',
    },
    { id: 'ui', label: 'UI', icon: <Palette size={16} /> },
    { id: 'advanced', label: 'Advanced', icon: <Zap size={16} />, advancedOnly: true },
    { id: 'debug', label: 'Debug', icon: <Bug size={16} />, advancedOnly: true },
]

const STORAGE_KEY = 'darkstar_ui_advanced_mode'

export default function Settings() {
    const [searchParams, setSearchParams] = useSearchParams()
    const activeTab = searchParams.get('tab') || 'system'

    const [advancedMode, setAdvancedMode] = useState<boolean>(() => {
        const saved = localStorage.getItem(STORAGE_KEY)
        return saved === 'true'
    })

    const [systemFlags, setSystemFlags] = useState<SystemFlags>({})
    const [configLoading, setConfigLoading] = useState(true)

    useEffect(() => {
        localStorage.setItem(STORAGE_KEY, String(advancedMode))
    }, [advancedMode])

    // Load system flags on mount and when config changes
    const loadSystemFlags = useCallback(() => {
        Api.config()
            .then((config) => {
                const system = ((config as Record<string, unknown>).system as Record<string, unknown>) || {}
                setSystemFlags({
                    has_solar: Boolean(system.has_solar),
                    has_battery: Boolean(system.has_battery),
                    has_water_heater: Boolean(system.has_water_heater),
                    has_ev_charger: Boolean(system.has_ev_charger),
                })
            })
            .catch((err) => console.error('Failed to load config for tab visibility:', err))
            .finally(() => setConfigLoading(false))
    }, [])

    useEffect(() => {
        loadSystemFlags()
    }, [loadSystemFlags])

    // Listen for config changes to update tab visibility instantly
    useEffect(() => {
        const handleConfigChanged = () => {
            loadSystemFlags()
        }

        window.addEventListener('config-changed', handleConfigChanged)
        return () => window.removeEventListener('config-changed', handleConfigChanged)
    }, [loadSystemFlags])

    const setActiveTab = React.useCallback(
        (tab: string) => {
            setSearchParams({ tab })
        },
        [setSearchParams],
    )

    // Force redirect if on advanced tab but mode is off
    useEffect(() => {
        if (activeTab === 'advanced' && !advancedMode) {
            setActiveTab('system')
        }
    }, [activeTab, advancedMode, setActiveTab])

    // Filter tabs based on system flags
    const tabs = useMemo(() => {
        return ALL_TABS.filter((t) => {
            if (t.advancedOnly && !advancedMode) return false
            if (!t.showIf) return true
            const flagKey = t.showIf.replace('system.', '') as keyof SystemFlags
            return systemFlags[flagKey] === true
        })
    }, [advancedMode, systemFlags])

    const renderTabContent = () => {
        switch (activeTab) {
            case 'parameters':
                return <ParametersTab advancedMode={advancedMode} />
            case 'solar':
                return <SolarTab advancedMode={advancedMode} />
            case 'battery':
                return <BatteryTab advancedMode={advancedMode} />
            case 'ev':
                return <EVTab advancedMode={advancedMode} />
            case 'water':
                return <WaterTab advancedMode={advancedMode} />
            case 'load-balancing':
                return <LoadBalancingTab advancedMode={advancedMode} />
            case 'ui':
                return <UITab advancedMode={advancedMode} />
            case 'advanced':
                return <AdvancedTab advancedMode={advancedMode} />
            case 'debug':
                return <DebugContent className="" />
            case 'system':
            default:
                return <SystemTab advancedMode={advancedMode} />
        }
    }

    // Show loading while fetching system flags
    if (configLoading) {
        return (
            <main className="p-4 lg:p-8">
                <div className="mx-auto max-w-5xl">
                    <div className="flex items-center justify-center p-8">
                        <div className="animate-pulse text-muted">Loading...</div>
                    </div>
                </div>
            </main>
        )
    }

    return (
        <>
            <main className="p-4 lg:p-8">
                <div
                    className={`mx-auto ${activeTab === 'debug' ? 'max-w-7xl' : 'max-w-5xl'} transition-all duration-300`}
                >
                    <div className="mb-6 flex flex-col sm:flex-row sm:items-center justify-between gap-4">
                        <div className="flex flex-wrap gap-2">
                            {tabs.map((tab) => (
                                <button
                                    key={tab.id}
                                    onClick={() => setActiveTab(tab.id)}
                                    className={`flex items-center gap-2 rounded-xl px-4 py-2.5 text-xs font-bold uppercase tracking-wider transition duration-300 ${
                                        activeTab === tab.id
                                            ? 'bg-accent text-[#100f0e] shadow-[0_0_20px_rgba(var(--color-accent-rgb),0.3)]'
                                            : 'bg-surface2 text-muted hover:bg-surface3 hover:text-white'
                                    }`}
                                >
                                    {tab.icon}
                                    {tab.label}
                                </button>
                            ))}
                        </div>

                        <button
                            onClick={() => setAdvancedMode(!advancedMode)}
                            className={`flex items-center gap-2 rounded-xl px-4 py-2.5 text-[10px] font-bold uppercase tracking-wider transition duration-300 self-end sm:self-auto ${
                                advancedMode
                                    ? 'bg-bad text-white shadow-[0_0_20px_rgba(var(--color-bad-rgb),0.3)]'
                                    : 'bg-good text-white shadow-[0_0_20px_rgba(var(--color-good-rgb),0.3)]'
                            }`}
                        >
                            {advancedMode ? <ShieldAlert size={14} /> : <Zap size={14} />}
                            {advancedMode ? 'Advanced Mode' : 'Standard Mode'}
                        </button>
                    </div>

                    <div className="animate-in fade-in slide-in-from-bottom-2 duration-500">{renderTabContent()}</div>
                </div>
            </main>
        </>
    )
}
