/**
 * PlannerErrorDetails Component
 *
 * Right-side drawer showing detailed planner error diagnostics.
 * Uses the project's existing Modal component as a drawer.
 */

import React, { useState, useEffect, useCallback } from 'react'
import { Copy, ExternalLink } from 'lucide-react'
import Modal from './ui/Modal'
import type { HealthIssue } from './SystemAlert'

interface PlannerErrorDetailsProps {
    issue: HealthIssue
    open: boolean
    onClose: () => void
}

function redactSecrets(obj: Record<string, unknown>, seen = new WeakSet()): Record<string, unknown> {
    const result: Record<string, unknown> = {}
    for (const [key, value] of Object.entries(obj)) {
        if (/token|api_key|password|secret/i.test(key)) {
            result[key] = '***'
        } else if (typeof value === 'object' && value !== null && !Array.isArray(value)) {
            if (seen.has(value as object)) {
                result[key] = '[circular]'
            } else {
                seen.add(value as object)
                result[key] = redactSecrets(value as Record<string, unknown>, seen)
            }
        } else if (Array.isArray(value)) {
            result[key] = value.map((v) =>
                typeof v === 'object' && v !== null ? redactSecrets(v as Record<string, unknown>, seen) : v,
            )
        } else {
            result[key] = value
        }
    }
    return result
}

function useRetryCountdown(retryInS: number | null | undefined): number | null {
    const [remaining, setRemaining] = useState<number | null>(retryInS ?? null)

    useEffect(() => {
        const initialVal = retryInS ?? null

        setRemaining(initialVal)

        if (initialVal === null) {
            return
        }

        const interval = setInterval(() => {
            setRemaining((prev) => {
                if (prev === null || prev <= 1) {
                    clearInterval(interval)
                    return 0
                }
                return prev - 1
            })
        }, 1000)
        return () => clearInterval(interval)
    }, [retryInS])

    return remaining
}

function formatCountdown(seconds: number | null): string {
    if (seconds === null) return 'Suspended — fix configuration'
    if (seconds <= 0) return 'Retrying now...'
    const m = Math.floor(seconds / 60)
    const s = seconds % 60
    return m > 0 ? `${m}m ${s}s` : `${s}s`
}

function truncate(str: string, maxLen: number = 60): string {
    return str.length > maxLen ? str.slice(0, maxLen) + '...' : str
}

export function PlannerErrorDetails({ issue, open, onClose }: PlannerErrorDetailsProps) {
    const countdown = useRetryCountdown(issue.retry_in_s)
    const [copied, setCopied] = useState(false)
    const [expandedKeys, setExpandedKeys] = useState<Set<string>>(new Set())

    const handleCopy = useCallback(async () => {
        const bundle = {
            code: issue.code,
            message: issue.message,
            guidance: issue.guidance,
            entity_id: issue.entity_id,
            details: issue.details ? redactSecrets(issue.details) : undefined,
            retry_in_s: issue.retry_in_s,
            timestamp: new Date().toISOString(),
        }
        try {
            await navigator.clipboard.writeText(JSON.stringify(bundle, null, 2))
            setCopied(true)
            setTimeout(() => setCopied(false), 2000)
        } catch {
            // clipboard not available
        }
    }, [issue])

    const toggleKey = (key: string) => {
        setExpandedKeys((prev) => {
            const next = new Set(prev)
            if (next.has(key)) next.delete(key)
            else next.add(key)
            return next
        })
    }

    const details = issue.details || {}
    const isConfigBlocking = issue.config_blocking === true

    return (
        <Modal open={open} onOpenChange={() => onClose()} title="Planner Error Details" size="md">
            <div className="space-y-4">
                {/* Error code chip */}
                <div className="flex items-center gap-3">
                    <code className="text-xs font-mono bg-bad/20 text-bad px-2 py-1 rounded-md">
                        {issue.code || 'UNKNOWN'}
                    </code>
                    <span className={`text-xs ${issue.severity === 'critical' ? 'text-bad' : 'text-yellow-400'}`}>
                        {issue.severity}
                    </span>
                </div>

                {/* Human message */}
                <div>
                    <h4 className="text-xs font-medium text-muted mb-1">Message</h4>
                    <p className="text-sm text-text">{issue.message}</p>
                </div>

                {/* Fix hint */}
                {issue.guidance && (
                    <div>
                        <h4 className="text-xs font-medium text-muted mb-1">How to fix</h4>
                        <p className="text-sm text-text">{issue.guidance}</p>
                    </div>
                )}

                {/* Retry countdown */}
                {issue.retry_in_s != null && (
                    <div>
                        <h4 className="text-xs font-medium text-muted mb-1">Next retry</h4>
                        <p className="text-sm font-mono text-text">{formatCountdown(countdown)}</p>
                    </div>
                )}

                {/* Diagnostics table */}
                {Object.keys(details).length > 0 && (
                    <div>
                        <h4 className="text-xs font-medium text-muted mb-2">Diagnostics</h4>
                        <div className="bg-surface2/50 rounded-lg border border-line overflow-hidden">
                            <table className="w-full text-xs">
                                <tbody>
                                    {Object.entries(details).map(([key, value]) => {
                                        const strVal = String(value)
                                        const isLong = strVal.length > 60
                                        const expanded = expandedKeys.has(key)
                                        return (
                                            <tr key={key} className="border-b border-line/50 last:border-0">
                                                <td className="px-3 py-2 font-medium text-muted whitespace-nowrap align-top">
                                                    {key}
                                                </td>
                                                <td className="px-3 py-2 text-text">
                                                    <span
                                                        className="font-mono cursor-pointer"
                                                        onClick={() => {
                                                            if (isLong) toggleKey(key)
                                                        }}
                                                    >
                                                        {expanded || !isLong ? strVal : truncate(strVal)}
                                                    </span>
                                                </td>
                                            </tr>
                                        )
                                    })}
                                </tbody>
                            </table>
                        </div>
                    </div>
                )}

                {/* Actions */}
                <div className="flex items-center gap-3 pt-2">
                    <button
                        onClick={handleCopy}
                        className="flex items-center gap-1.5 text-xs px-3 py-1.5 rounded-md bg-surface2 hover:bg-surface2/80 text-text transition-colors"
                    >
                        <Copy className="h-3.5 w-3.5" />
                        {copied ? 'Copied!' : 'Copy diagnostic bundle'}
                    </button>
                    {isConfigBlocking && (
                        <a
                            href="/settings"
                            className="flex items-center gap-1.5 text-xs px-3 py-1.5 rounded-md bg-accent/20 hover:bg-accent/30 text-accent transition-colors"
                        >
                            <ExternalLink className="h-3.5 w-3.5" />
                            Open Settings
                        </a>
                    )}
                </div>
            </div>
        </Modal>
    )
}

export default PlannerErrorDetails
