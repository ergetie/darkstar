import type { UpdaterStatus } from './api'

/** An update that can actually be applied (available and not blocked by the DB gate). */
export function updateReady(status: UpdaterStatus | null): boolean {
    return Boolean(status?.reachable && status.update_available && !status.blocked && status.target)
}

const DISMISSED_KEY = 'darkstar-dismissed-update'

export function isUpdateDismissed(targetVersion: string): boolean {
    try {
        return window.localStorage.getItem(DISMISSED_KEY) === targetVersion
    } catch {
        return false
    }
}

export function dismissUpdate(targetVersion: string): void {
    try {
        window.localStorage.setItem(DISMISSED_KEY, targetVersion)
    } catch {
        // Storage unavailable: the banner simply shows again next load.
    }
}
