/**
 * SystemAlert Component
 *
 * Displays critical and warning banners at the top of the app
 * when system health issues are detected.
 *
 * Styles are in index.css under @layer components.
 */

import React from 'react'

export interface HealthIssue {
    category: string
    severity: 'critical' | 'warning' | 'info'
    message: string
    guidance: string
    entity_id?: string | null
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
    onDismiss?: () => void
}

export function SystemAlert({ health, onDismiss }: SystemAlertProps) {
    if (!health || health.healthy) {
        return null
    }

    const criticalIssues = health.issues.filter((i) => i.severity === 'critical')
    const warningIssues = health.issues.filter((i) => i.severity === 'warning')

    return (
        <div className="space-y-2">
            {/* Critical Errors - same style as shadow mode banner */}
            {criticalIssues.map((issue, idx) => (
                <div key={`critical-${idx}`} className="banner banner-error px-4 py-3 flex items-center justify-between">
                    <div className="flex items-center gap-2">
                        <span>⚠️</span>
                        <span className="font-medium">{issue.message}</span>
                        {issue.entity_id && (
                            <code className="text-[10px] bg-white/20 px-1.5 py-0.5 rounded">{issue.entity_id}</code>
                        )}
                        <span className="opacity-70 text-xs">— {issue.guidance}</span>
                    </div>
                    {onDismiss && (
                        <button
                            onClick={onDismiss}
                            className="opacity-60 hover:opacity-100 text-xs px-2 py-1"
                            title="Dismiss"
                        >
                            ✕
                        </button>
                    )}
                </div>
            ))}

            {/* Warnings - same style as vacation mode banner */}
            {warningIssues.map((issue, idx) => (
                <div key={`warning-${idx}`} className="banner banner-warning px-4 py-3">
                    <span>⚡</span>
                    <span className="font-medium">{issue.message}</span>
                    <span className="opacity-70 text-xs ml-2">— {issue.guidance}</span>
                </div>
            ))}
        </div>
    )
}

export default SystemAlert
