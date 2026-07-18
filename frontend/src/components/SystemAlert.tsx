/**
 * SystemAlert Component
 *
 * Displays critical and warning banners at the top of the app
 * when system health issues are detected.
 *
 * Styles are in index.css under @layer components.
 */

import React, { useEffect, useState } from 'react'
import { ChevronDown, ChevronUp } from 'lucide-react'
import { PlannerErrorDetails } from './PlannerErrorDetails'

export interface HealthIssue {
    category: string
    severity: 'critical' | 'warning' | 'info'
    message: string
    guidance: string
    entity_id?: string | null
    code?: string | null
    details?: Record<string, unknown> | null
    retry_in_s?: number | null
    config_blocking?: boolean
}

export interface HealthStatus {
    healthy: boolean
    issues: HealthIssue[]
    checked_at: string
    critical_count: number
    warning_count: number
}

interface SystemAlertProps {
    health: HealthStatus | null
}

const SNOOZE_STORAGE_KEY = 'darkstar-snoozed-issues'
const SNOOZE_DURATION_MS = 24 * 60 * 60 * 1000

type SnoozeMap = Record<string, number>

// Stable identifier only — never message text, which contains live numbers
// (e.g. "98.64 %") that change every evaluation and would defeat snoozing.
function issueKey(issue: HealthIssue): string {
    return issue.code || issue.category
}

function loadSnoozeMap(): SnoozeMap {
    try {
        const raw = localStorage.getItem(SNOOZE_STORAGE_KEY)
        if (!raw) return {}
        const parsed: unknown = JSON.parse(raw)
        return parsed && typeof parsed === 'object' ? (parsed as SnoozeMap) : {}
    } catch (e) {
        console.error('Failed to read snoozed issues from localStorage', e)
        return {}
    }
}

function saveSnoozeMap(map: SnoozeMap): void {
    try {
        localStorage.setItem(SNOOZE_STORAGE_KEY, JSON.stringify(map))
    } catch (e) {
        console.error('Failed to save snoozed issues to localStorage', e)
    }
}

export function SystemAlert({ health }: SystemAlertProps) {
    const [selectedIssue, setSelectedIssue] = useState<HealthIssue | null>(null)
    const [collapsed, setCollapsed] = useState(false)
    const [snoozeMap, setSnoozeMap] = useState<SnoozeMap>(() => loadSnoozeMap())
    // purity: Date.now() may not be read during render — track it in state,
    // refreshed periodically so an expired snooze reappears without reload.
    const [now, setNow] = useState<number>(() => Date.now())

    useEffect(() => {
        const id = setInterval(() => setNow(Date.now()), 60000)
        return () => clearInterval(id)
    }, [])

    if (!health || health.issues.length === 0) {
        return null
    }

    const isSnoozed = (issue: HealthIssue): boolean => {
        const expiry = snoozeMap[issueKey(issue)]
        return typeof expiry === 'number' && expiry > now
    }

    const snoozeIssue = (issue: HealthIssue) => {
        const next = { ...snoozeMap, [issueKey(issue)]: now + SNOOZE_DURATION_MS }
        setSnoozeMap(next)
        saveSnoozeMap(next)
    }

    const snoozedIssues = health.issues.filter(isSnoozed)
    const visibleIssues = health.issues.filter((i) => !isSnoozed(i))

    const unsnoozeAll = () => {
        const next = { ...snoozeMap }
        for (const issue of snoozedIssues) {
            delete next[issueKey(issue)]
        }
        setSnoozeMap(next)
        saveSnoozeMap(next)
    }

    const criticalIssues = visibleIssues.filter((i) => i.severity === 'critical')
    const warningIssues = visibleIssues.filter((i) => i.severity === 'warning')
    const allIssues = [...criticalIssues, ...warningIssues]

    if (allIssues.length === 0 && snoozedIssues.length === 0) {
        return null
    }

    return (
        <div className="space-y-2">
            {snoozedIssues.length > 0 && (
                <div className="flex items-center gap-2">
                    <button
                        onClick={unsnoozeAll}
                        className="inline-flex items-center gap-1.5 text-[10px] px-2 py-1 rounded-md cursor-pointer bg-white/10 opacity-70 hover:opacity-100 transition-opacity"
                        title="Show snoozed issues"
                    >
                        <span>💤</span>
                        <span>{snoozedIssues.length} snoozed</span>
                    </button>
                </div>
            )}

            {allIssues.length > 0 &&
                (collapsed ? (
                    /* Collapsed indicator */
                    <div className="flex items-center gap-2">
                        {allIssues.map((issue, idx) => (
                            <button
                                key={`indicator-${idx}`}
                                onClick={() => setCollapsed(false)}
                                className={`inline-flex items-center gap-1.5 text-[10px] px-2 py-1 rounded-md cursor-pointer transition-colors ${
                                    issue.severity === 'critical'
                                        ? 'bg-bad/20 text-bad hover:bg-bad/30'
                                        : 'bg-yellow-500/20 text-yellow-400 hover:bg-yellow-500/30'
                                }`}
                            >
                                <span>⚠️</span>
                                <code className="font-mono">{issue.code || issue.category}</code>
                                <ChevronDown className="h-3 w-3" />
                            </button>
                        ))}
                    </div>
                ) : (
                    <>
                        {/* Critical Errors */}
                        {criticalIssues.map((issue, idx) => (
                            <div
                                key={`critical-${idx}`}
                                className="banner banner-error px-4 py-3 flex items-center justify-between"
                            >
                                <div className="flex items-center gap-2">
                                    <span>⚠️</span>
                                    <span className="font-medium">{issue.message}</span>
                                    {issue.entity_id && (
                                        <code className="text-[10px] bg-white/20 px-1.5 py-0.5 rounded">
                                            {issue.entity_id}
                                        </code>
                                    )}
                                    <span className="opacity-70 text-xs">— {issue.guidance}</span>
                                    {issue.details && (
                                        <button
                                            onClick={() => setSelectedIssue(issue)}
                                            className="text-[10px] px-2 py-0.5 rounded bg-white/20 hover:bg-white/30 transition-colors"
                                        >
                                            View details
                                        </button>
                                    )}
                                </div>
                                <div className="flex items-center gap-1">
                                    <button
                                        onClick={() => snoozeIssue(issue)}
                                        className="opacity-60 hover:opacity-100 text-xs px-2 py-1"
                                        title="Snooze for 24 hours"
                                    >
                                        ✕
                                    </button>
                                    <button
                                        onClick={() => setCollapsed(true)}
                                        className="opacity-60 hover:opacity-100 text-xs px-1 py-1"
                                        title="Collapse"
                                    >
                                        <ChevronUp className="h-3.5 w-3.5" />
                                    </button>
                                </div>
                            </div>
                        ))}

                        {/* Warnings */}
                        {warningIssues.map((issue, idx) => (
                            <div
                                key={`warning-${idx}`}
                                className="banner banner-warning px-4 py-3 flex items-center justify-between"
                            >
                                <div className="flex items-center gap-2">
                                    <span>⚡</span>
                                    <span className="font-medium">{issue.message}</span>
                                    <span className="opacity-70 text-xs ml-2">— {issue.guidance}</span>
                                    {issue.details && (
                                        <button
                                            onClick={() => setSelectedIssue(issue)}
                                            className="text-[10px] px-2 py-0.5 rounded bg-white/20 hover:bg-white/30 transition-colors"
                                        >
                                            View details
                                        </button>
                                    )}
                                </div>
                                <div className="flex items-center gap-1">
                                    <button
                                        onClick={() => snoozeIssue(issue)}
                                        className="opacity-60 hover:opacity-100 text-xs px-2 py-1"
                                        title="Snooze for 24 hours"
                                    >
                                        ✕
                                    </button>
                                    <button
                                        onClick={() => setCollapsed(true)}
                                        className="opacity-60 hover:opacity-100 text-xs px-1 py-1"
                                        title="Collapse"
                                    >
                                        <ChevronUp className="h-3.5 w-3.5" />
                                    </button>
                                </div>
                            </div>
                        ))}
                    </>
                ))}

            {/* Details drawer */}
            {selectedIssue && (
                <PlannerErrorDetails
                    issue={selectedIssue}
                    open={!!selectedIssue}
                    onClose={() => setSelectedIssue(null)}
                />
            )}
        </div>
    )
}

export default SystemAlert
