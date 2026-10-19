import { useEffect, useState } from 'react'
import { Api } from './api'

/** Notice id for the "Couldn't verify program times" info of a profile. */
export const programTimesNoticeId = (profileName: string) => `${profileName}.program_times_unverified`

/**
 * Loads persisted notice dismissals (onboarding state) and persists new ones.
 * Only fetches while `enabled`, i.e. when a notice is actually shown.
 */
export function useDismissedNotices(enabled = true): [string[], (id: string) => void] {
    const [dismissed, setDismissed] = useState<string[]>([])

    useEffect(() => {
        if (!enabled) return
        let active = true
        Api.setup
            .onboarding()
            .then((state) => {
                if (active) setDismissed(state.dismissed_notices ?? [])
            })
            .catch(() => undefined)
        return () => {
            active = false
        }
    }, [enabled])

    const dismiss = (id: string) => {
        setDismissed((current) => (current.includes(id) ? current : [...current, id]))
        Api.setup
            .dismissNotice(id)
            .then((state) => setDismissed(state.dismissed_notices ?? []))
            .catch((error: unknown) => console.error('Failed to persist notice dismissal:', error))
    }

    return [dismissed, dismiss]
}
