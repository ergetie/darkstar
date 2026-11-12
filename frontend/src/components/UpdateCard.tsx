import { useEffect, useRef, useState } from 'react'
import { X } from 'lucide-react'
import { Api, type UpdaterChannel } from '../lib/api'
import type { UseUpdater } from '../lib/useUpdater'
import { updateReady } from '../lib/updateReady'

const POLL_MS = 2000
const RESTART_TIMEOUT_MS = 5 * 60 * 1000

/** Small floating card: versions, channel, check, update with confirm, live log, reconnect. */
export function UpdateCard({ updater, onClose }: { updater: UseUpdater; onClose: () => void }) {
    const { status, refresh } = updater
    const [confirming, setConfirming] = useState(false)
    const [awaiting, setAwaiting] = useState(false)
    const [reconnecting, setReconnecting] = useState(false)
    const [timedOut, setTimedOut] = useState(false)
    const [log, setLog] = useState('')
    const logOffset = useRef(0)
    const startedAt = useRef(0)
    const logBox = useRef<HTMLPreElement>(null)

    const applyState = status?.apply?.state
    const inProgress = awaiting || applyState === 'building' || applyState === 'restarting'
    const targetVersion = status?.apply?.target_version ?? status?.target?.version

    useEffect(() => {
        const onKey = (e: KeyboardEvent) => e.key === 'Escape' && onClose()
        window.addEventListener('keydown', onKey)
        return () => window.removeEventListener('keydown', onKey)
    }, [onClose])

    useEffect(() => {
        if (logBox.current) logBox.current.scrollTop = logBox.current.scrollHeight
    }, [log])

    // While an update runs: stream the log, follow the status, and reload once the
    // restarted Darkstar reports the target version.
    useEffect(() => {
        if (!inProgress || timedOut) return
        if (!startedAt.current) startedAt.current = Date.now()
        let cancelled = false
        const tick = async () => {
            try {
                const chunk = await Api.updater.log(logOffset.current)
                if (!cancelled && chunk.offset >= logOffset.current) {
                    logOffset.current = chunk.offset
                    if (chunk.text) setLog((current) => current + chunk.text)
                }
            } catch {
                // Backend restarting.
            }
            let next = null
            try {
                next = await refresh()
            } catch {
                next = null
            }
            if (cancelled) return
            setReconnecting(next === null)
            const state = next?.apply?.state
            if (state === 'failed') {
                setAwaiting(false)
                return
            }
            if (next === null || state === 'done') {
                try {
                    const running = await Api.version()
                    if (!cancelled && targetVersion && running.version === targetVersion) {
                        window.location.reload()
                        return
                    }
                } catch {
                    // Still restarting.
                }
            }
            if (!cancelled && Date.now() - startedAt.current > RESTART_TIMEOUT_MS) {
                setAwaiting(false)
                setTimedOut(true)
            }
        }
        const id = window.setInterval(() => void tick(), POLL_MS)
        return () => {
            cancelled = true
            window.clearInterval(id)
        }
    }, [inProgress, timedOut, targetVersion, refresh])

    const startUpdate = async () => {
        setConfirming(false)
        setLog('')
        setTimedOut(false)
        logOffset.current = 0
        startedAt.current = Date.now()
        if (await updater.apply()) setAwaiting(true)
    }

    const ready = updateReady(status)
    const channel = status?.channel
    const dirty = status?.dirty_files ?? []
    const lastChecked = status?.last_success_at ? new Date(status.last_success_at).toLocaleString() : 'never'
    const failedTail = applyState === 'failed' && !inProgress ? (status?.apply?.log_tail ?? []) : []

    const blockedReason =
        dirty.length > 0
            ? 'Update unavailable: local changes block updates.'
            : status?.blocked
              ? `Update unavailable: ${status.blocked}`
              : !status?.update_available
                ? 'Already up to date.'
                : null

    return (
        <>
            <div className="qa-backdrop z-[69]" onClick={onClose} aria-hidden="true" />
            <div
                role="dialog"
                aria-label="Update Darkstar"
                className="fixed z-[70] left-4 right-4 top-1/2 -translate-y-1/2 lg:translate-y-0 lg:top-auto lg:left-24 lg:right-auto lg:bottom-6 lg:w-80 rounded-2xl bg-surface border border-line ring-1 ring-black/10 shadow-[0_12px_32px_rgba(0,0,0,0.45)] p-4 flex flex-col gap-3 text-xs max-h-[85vh] overflow-auto"
            >
                <div className="flex items-center justify-between">
                    <span className="text-sm font-semibold text-text">Updates</span>
                    <button
                        type="button"
                        aria-label="Close update card"
                        className="text-muted hover:text-text"
                        onClick={onClose}
                    >
                        <X className="h-4 w-4" />
                    </button>
                </div>

                {status && !status.reachable && !inProgress && !reconnecting ? (
                    <div className="banner banner-warning flex-col items-start mb-0">
                        <span className="font-semibold">Updater unavailable</span>
                        <span>
                            Run <code className="font-mono">docker compose up -d updater</code> on the host.
                        </span>
                        {status.error && <span className="opacity-70">{status.error}</span>}
                    </div>
                ) : (
                    <>
                        <dl className="grid grid-cols-[auto_1fr] gap-x-3 gap-y-1">
                            <dt className="text-muted">Current</dt>
                            <dd className="font-mono text-text">{status?.current?.version ?? '...'}</dd>
                            <dt className="text-muted">Latest</dt>
                            <dd className="font-mono text-text">{status?.target?.version ?? 'unknown'}</dd>
                            <dt className="text-muted">Checked</dt>
                            <dd className="text-text">{lastChecked}</dd>
                        </dl>

                        <label className="flex items-center justify-between gap-3">
                            <span className="text-muted">Channel</span>
                            <select
                                className="input !w-auto"
                                value={channel ?? 'dev'}
                                disabled={updater.busy || inProgress}
                                onChange={(e) => void updater.setChannel(e.target.value as UpdaterChannel)}
                            >
                                <option value="dev">Dev (latest main)</option>
                                <option value="stable">Stable (latest release)</option>
                            </select>
                        </label>

                        {status?.last_check && !status.last_check.ok && (
                            <div className="banner banner-warning mb-0">Check failed: {status.last_check.error}</div>
                        )}
                        {status?.update_available && status.blocked && (
                            <div className="banner banner-warning mb-0">{status.blocked}</div>
                        )}
                        {dirty.length > 0 && (
                            <div className="banner banner-warning mb-0 flex-col items-start">
                                <span>Local changes block updates:</span>
                                <span className="font-mono">{dirty.join(', ')}</span>
                            </div>
                        )}
                        {status?.updater_outdated && (
                            <div className="banner banner-info mb-0 flex-col items-start gap-1">
                                <span>The updater itself is outdated. Run:</span>
                                <code className="font-mono break-all">docker compose up -d --build updater</code>
                            </div>
                        )}
                        {updater.error && <div className="banner banner-error mb-0">{updater.error}</div>}
                        {timedOut && (
                            <div className="banner banner-error mb-0">
                                Darkstar did not come back within 5 minutes. Check the updater log and run{' '}
                                <code className="font-mono">docker compose logs darkstar</code>.
                            </div>
                        )}
                        {applyState === 'failed' && !inProgress && (
                            <div className="banner banner-error mb-0 flex-col items-start">
                                <span>{status?.apply?.message ?? 'Update failed'}</span>
                                {failedTail.length > 0 && (
                                    <pre className="font-mono text-[10px] max-h-32 overflow-auto whitespace-pre-wrap">
                                        {failedTail.join('\n')}
                                    </pre>
                                )}
                            </div>
                        )}

                        {status?.commits && status.commits.length > 0 && !inProgress && (
                            <ul className="list-disc pl-4 text-muted max-h-24 overflow-auto">
                                {status.commits.map((subject, i) => (
                                    <li key={i}>{subject}</li>
                                ))}
                            </ul>
                        )}

                        {inProgress && (
                            <div className="flex flex-col gap-2">
                                <span className="text-text font-semibold">
                                    {reconnecting || applyState === 'restarting' || applyState === 'done'
                                        ? 'Restarting...'
                                        : 'Building...'}
                                </span>
                                <pre
                                    ref={logBox}
                                    className="font-mono text-[10px] max-h-40 overflow-auto whitespace-pre-wrap rounded-lg bg-surface2 border border-line/60 p-2"
                                >
                                    {log || 'Waiting for output...'}
                                </pre>
                            </div>
                        )}

                        {!inProgress && (
                            <div className="flex items-center gap-2">
                                {confirming ? (
                                    <>
                                        <span className="text-muted flex-1">Update and restart Darkstar?</span>
                                        <button
                                            type="button"
                                            className="btn btn-primary"
                                            onClick={() => void startUpdate()}
                                        >
                                            Confirm
                                        </button>
                                        <button
                                            type="button"
                                            className="btn btn-ghost"
                                            onClick={() => setConfirming(false)}
                                        >
                                            Cancel
                                        </button>
                                    </>
                                ) : (
                                    <>
                                        <button
                                            type="button"
                                            className="btn btn-secondary"
                                            disabled={updater.busy}
                                            onClick={() => void updater.check()}
                                        >
                                            {updater.busy ? 'Checking...' : 'Check now'}
                                        </button>
                                        <button
                                            type="button"
                                            className="btn btn-primary"
                                            disabled={updater.busy || !ready || dirty.length > 0}
                                            title={blockedReason ?? undefined}
                                            onClick={() => setConfirming(true)}
                                        >
                                            Update
                                        </button>
                                    </>
                                )}
                            </div>
                        )}
                        {!inProgress && !confirming && !ready && blockedReason && (
                            <span className="text-muted">{blockedReason}</span>
                        )}
                    </>
                )}
            </div>
        </>
    )
}
