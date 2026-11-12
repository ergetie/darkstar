import { useState } from 'react'
import type { UseUpdater } from '../lib/useUpdater'
import { dismissUpdate, isUpdateDismissed, updateReady } from '../lib/updateReady'

/** Dismissible "update ready" banner; dismissal is remembered per target version. */
export function UpdateBanner({ updater, onOpen }: { updater: UseUpdater; onOpen: () => void }) {
    const [dismissedVersion, setDismissedVersion] = useState<string | null>(null)
    const target = updater.status?.target?.version
    if (!updater.available || !target || !updateReady(updater.status)) return null
    if (dismissedVersion === target || isUpdateDismissed(target)) return null

    return (
        <div className="banner banner-info ml-16 mr-4 lg:mx-4 mt-4 justify-between" role="status">
            <span>Darkstar {target} is available.</span>
            <span className="flex items-center gap-2">
                <button type="button" className="btn btn-secondary" onClick={onOpen}>
                    View update
                </button>
                <button
                    type="button"
                    aria-label="Dismiss update banner"
                    className="opacity-70 hover:opacity-100 text-xs px-2 py-1"
                    onClick={() => {
                        dismissUpdate(target)
                        setDismissedVersion(target)
                    }}
                >
                    ✕
                </button>
            </span>
        </div>
    )
}
