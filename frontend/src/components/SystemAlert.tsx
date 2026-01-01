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
        <div className="system-alert-container">
            {criticalIssues.length > 0 && (
                <div className="system-alert system-alert--critical">
                    <div className="system-alert__icon">⚠️</div>
                    <div className="system-alert__content">
                        <div className="system-alert__title">
                            System Error{criticalIssues.length > 1 ? 's' : ''} Detected
                        </div>
                        <ul className="system-alert__list">
                            {criticalIssues.map((issue, idx) => (
                                <li key={idx} className="system-alert__item">
                                    <strong>{issue.message}</strong>
                                    {issue.entity_id && <code className="system-alert__entity">{issue.entity_id}</code>}
                                    <div className="system-alert__guidance">{issue.guidance}</div>
                                </li>
                            ))}
                        </ul>
                    </div>
                    {onDismiss && (
                        <button
                            className="system-alert__dismiss"
                            onClick={onDismiss}
                            title="Dismiss (will reappear on next check)"
                        >
                            ×
                        </button>
                    )}
                </div>
            )}

            {warningIssues.length > 0 && (
                <div className="system-alert system-alert--warning">
                    <div className="system-alert__icon">⚡</div>
                    <div className="system-alert__content">
                        <div className="system-alert__title">Warning{warningIssues.length > 1 ? 's' : ''}</div>
                        <ul className="system-alert__list">
                            {warningIssues.map((issue, idx) => (
                                <li key={idx} className="system-alert__item">
                                    <strong>{issue.message}</strong>
                                    <div className="system-alert__guidance">{issue.guidance}</div>
                                </li>
                            ))}
                        </ul>
                    </div>
                </div>
            )}
        </div>
    )
}

export default SystemAlert
