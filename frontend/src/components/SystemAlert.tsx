/**
 * SystemAlert Component
 *
 * Displays critical and warning banners at the top of the app
 * when system health issues are detected.
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
                                    {issue.entity_id && (
                                        <code className="system-alert__entity">{issue.entity_id}</code>
                                    )}
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
                        <div className="system-alert__title">
                            Warning{warningIssues.length > 1 ? 's' : ''}
                        </div>
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

            <style>{`
                .system-alert-container {
                    position: sticky;
                    top: 0;
                    z-index: 1000;
                    width: 100%;
                }

                .system-alert {
                    display: flex;
                    align-items: flex-start;
                    gap: 12px;
                    padding: 12px 16px;
                    font-size: 14px;
                    border-bottom: 1px solid rgba(0, 0, 0, 0.1);
                }

                .system-alert--critical {
                    background: linear-gradient(135deg, #ff4444 0%, #cc0000 100%);
                    color: white;
                }

                .system-alert--warning {
                    background: linear-gradient(135deg, #ffaa00 0%, #ff8800 100%);
                    color: #1a1a1a;
                }

                .system-alert__icon {
                    font-size: 20px;
                    flex-shrink: 0;
                }

                .system-alert__content {
                    flex: 1;
                    min-width: 0;
                }

                .system-alert__title {
                    font-weight: 600;
                    margin-bottom: 4px;
                }

                .system-alert__list {
                    margin: 0;
                    padding-left: 20px;
                }

                .system-alert__item {
                    margin-bottom: 4px;
                }

                .system-alert__item:last-child {
                    margin-bottom: 0;
                }

                .system-alert__entity {
                    display: inline-block;
                    margin-left: 8px;
                    padding: 2px 6px;
                    background: rgba(0, 0, 0, 0.2);
                    border-radius: 4px;
                    font-size: 12px;
                    font-family: monospace;
                }

                .system-alert__guidance {
                    font-size: 12px;
                    opacity: 0.9;
                    margin-top: 2px;
                }

                .system-alert--critical .system-alert__guidance {
                    color: rgba(255, 255, 255, 0.9);
                }

                .system-alert__dismiss {
                    flex-shrink: 0;
                    background: rgba(255, 255, 255, 0.2);
                    border: none;
                    color: inherit;
                    font-size: 20px;
                    width: 28px;
                    height: 28px;
                    border-radius: 4px;
                    cursor: pointer;
                    display: flex;
                    align-items: center;
                    justify-content: center;
                    transition: background 0.2s;
                }

                .system-alert__dismiss:hover {
                    background: rgba(255, 255, 255, 0.3);
                }
            `}</style>
        </div>
    )
}

export default SystemAlert
