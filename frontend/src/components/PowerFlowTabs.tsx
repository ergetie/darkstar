import { useEffect, useRef, useState } from 'react'
import Card from './Card'
import PowerFlowCard from './PowerFlowCard'
import LoadBalancerCompactView from './LoadBalancerCompactView'
import { Api, type ConfigResponse, type LoadBalancerStatusResponse } from '../lib/api'
import type { PowerFlowData } from './PowerFlowRegistry'
import { useSocket } from '../lib/hooks'

const INTERVENING_STATES = new Set(['throttling', 'shedding', 'stale_fallback'])

interface PowerFlowTabsProps {
    data: PowerFlowData
    systemConfig?: ConfigResponse | null
}

type Tab = 'flow' | 'lb'

export default function PowerFlowTabs({ data, systemConfig }: PowerFlowTabsProps) {
    const [status, setStatus] = useState<LoadBalancerStatusResponse | null>(null)
    const [activeTab, setActiveTab] = useState<Tab>(() => {
        try {
            const val = localStorage.getItem('darkstar-powerflow-tab')
            if (val === 'lb' || val === 'flow') return val
        } catch (e) {
            console.error('Failed to read active tab from localStorage', e)
        }
        return 'flow'
    })
    const prevStateRef = useRef<string | null>(null)

    useEffect(() => {
        let active = true
        Api.executor
            .loadBalancerStatus()
            .then((s) => {
                if (active) setStatus(s)
            })
            .catch((err) => console.error('Failed to fetch load balancer status', err))
        return () => {
            active = false
        }
    }, [])

    useSocket('live_metrics', (data: unknown) => {
        const payload = data as { load_balancing?: LoadBalancerStatusResponse }
        if (payload.load_balancing) setStatus(payload.load_balancing)
    })

    const lbAvailable = !!status?.enabled && status.state !== 'disabled'
    const effectiveTab: Tab = lbAvailable ? activeTab : 'flow'

    // Auto-switch to the Load Balancer tab once per intervention episode: only on
    // the edge from a non-intervening to an intervening state, never re-forced
    // while already intervening or after the user has switched away mid-episode.
    useEffect(() => {
        if (!status) return
        const prev = prevStateRef.current
        const curr = status.state
        if (prev !== null && !INTERVENING_STATES.has(prev) && INTERVENING_STATES.has(curr)) {
            setActiveTab('lb')
        }
        prevStateRef.current = curr
    }, [status])

    const handleTabChange = (tab: Tab) => {
        setActiveTab(tab)
        try {
            localStorage.setItem('darkstar-powerflow-tab', tab)
        } catch (e) {
            console.error('Failed to save active tab to localStorage', e)
        }
    }

    const showWarningDot = !!status && INTERVENING_STATES.has(status.state) && effectiveTab !== 'lb'

    return (
        <Card className="h-full flex flex-col overflow-hidden">
            {lbAvailable && (
                <div className="flex items-center justify-end p-2 pb-0">
                    <div className="flex items-center bg-surface-elevated rounded-lg p-0.5 text-[10px] font-medium border border-line/20">
                        <button
                            onClick={() => handleTabChange('flow')}
                            className={`px-2 py-1 rounded-md transition-all ${
                                effectiveTab === 'flow'
                                    ? 'bg-accent text-surface-elevated font-semibold'
                                    : 'text-muted hover:text-text'
                            }`}
                        >
                            Flow
                        </button>
                        <button
                            onClick={() => handleTabChange('lb')}
                            className={`relative px-2 py-1 rounded-md transition-all ${
                                effectiveTab === 'lb'
                                    ? 'bg-accent text-surface-elevated font-semibold'
                                    : 'text-muted hover:text-text'
                            }`}
                        >
                            Load Balancer
                            {showWarningDot && (
                                <span className="absolute -top-0.5 -right-0.5 h-1.5 w-1.5 rounded-full bg-bad" />
                            )}
                        </button>
                    </div>
                </div>
            )}
            <div className="flex-1 flex items-center justify-center overflow-hidden">
                {effectiveTab === 'flow' ? (
                    <PowerFlowCard data={data} systemConfig={systemConfig} />
                ) : (
                    <LoadBalancerCompactView status={status} />
                )}
            </div>
        </Card>
    )
}
