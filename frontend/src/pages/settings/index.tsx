import React from 'react'
import { useSearchParams } from 'react-router-dom'
import { Settings as SettingsIcon, Sliders, Palette, Zap } from 'lucide-react'

import { SystemTab } from './SystemTab'
import { ParametersTab } from './ParametersTab'
import { UITab } from './UITab'
import { AdvancedTab } from './AdvancedTab'

const tabs = [
    { id: 'system', label: 'System', icon: <SettingsIcon size={16} /> },
    { id: 'parameters', label: 'Parameters', icon: <Sliders size={16} /> },
    { id: 'ui', label: 'UI & Theme', icon: <Palette size={16} /> },
    { id: 'advanced', label: 'Advanced', icon: <Zap size={16} /> },
]

export default function Settings() {
    const [searchParams, setSearchParams] = useSearchParams()
    const activeTab = searchParams.get('tab') || 'system'

    const setActiveTab = (tab: string) => {
        setSearchParams({ tab })
    }

    const renderTabContent = () => {
        switch (activeTab) {
            case 'parameters':
                return <ParametersTab />
            case 'ui':
                return <UITab />
            case 'advanced':
                return <AdvancedTab />
            case 'system':
            default:
                return <SystemTab />
        }
    }

    return (
        <>


            <main className="p-4 lg:p-8">
                <div className="mx-auto max-w-5xl">
                    <div className="mb-6 flex flex-wrap gap-2">
                        {tabs.map((tab) => (
                            <button
                                key={tab.id}
                                onClick={() => setActiveTab(tab.id)}
                                className={`flex items-center gap-2 rounded-xl px-4 py-2.5 text-xs font-bold uppercase tracking-wider transition duration-300 ${activeTab === tab.id
                                        ? 'bg-accent text-[#100f0e] shadow-[0_0_20px_rgba(var(--color-accent-rgb),0.3)]'
                                        : 'bg-surface2 text-muted hover:bg-surface3 hover:text-white'
                                    }`}
                            >
                                {tab.icon}
                                {tab.label}
                            </button>
                        ))}
                    </div>

                    <div className="animate-in fade-in slide-in-from-bottom-2 duration-500">{renderTabContent()}</div>
                </div>
            </main>
        </>
    )
}
