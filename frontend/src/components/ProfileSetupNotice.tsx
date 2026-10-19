import { useEffect, useState } from 'react'
import { Api, type ProgramTimesStatus } from '../lib/api'
import { programTimesNoticeId } from '../lib/useDismissedNotices'
import type { InverterProfile } from '../pages/settings/types'

/** Profiles whose setup notice includes the Time of Use program-time check. */
const PROGRAM_TIME_PROFILES = new Set(['deye'])

interface ProfileSetupNoticeProps {
    profile: InverterProfile | undefined
    /** Current soc_target entity (form value); falls back to the saved config when empty. */
    socTarget?: string
    dismissedNotices: string[]
    onDismissNotice: (id: string) => void
}

/**
 * Renders a profile's `setup_notice` (plain text lines) and, for profiles with
 * Time of Use programs, a dismissible "Couldn't verify program times" info line.
 */
export function ProfileSetupNotice({ profile, socTarget, dismissedNotices, onDismissNotice }: ProfileSetupNoticeProps) {
    const notice = profile?.setup_notice
    const profileName = profile?.name ?? ''
    const checksProgramTimes = Boolean(notice) && PROGRAM_TIME_PROFILES.has(profileName)
    const [verify, setVerify] = useState<{ key: string; result: ProgramTimesStatus | null } | null>(null)
    const verifyKey = `${profileName}|${socTarget ?? ''}`

    useEffect(() => {
        if (!checksProgramTimes) return
        let active = true
        Api.setup
            .programTimes(socTarget || undefined)
            .then((result) => {
                if (active) setVerify({ key: verifyKey, result })
            })
            .catch(() => {
                if (active) setVerify({ key: verifyKey, result: null })
            })
        return () => {
            active = false
        }
    }, [checksProgramTimes, socTarget, verifyKey])

    if (!notice) return null

    const noticeId = programTimesNoticeId(profileName)
    const current = verify?.key === verifyKey ? verify : null
    const unverified =
        checksProgramTimes &&
        current !== null &&
        (current.result === null || current.result.status === 'unverifiable') &&
        !dismissedNotices.includes(noticeId)

    return (
        <div className="space-y-2">
            <div className={`banner banner-${notice.severity} space-y-2`} role="note" aria-label={notice.title}>
                <div className="text-sm font-semibold">{notice.title}</div>
                <ul className="list-disc space-y-1 pl-5 text-xs">
                    {notice.items.map((item) => (
                        <li key={item}>{item}</li>
                    ))}
                </ul>
            </div>
            {unverified && (
                <div className="banner banner-info flex flex-wrap items-center justify-between gap-2 text-xs">
                    <span>
                        Couldn't verify program times. Check on the inverter that all six program times are 00:00.
                    </span>
                    <button className="btn btn-ghost px-2 py-1" type="button" onClick={() => onDismissNotice(noticeId)}>
                        Dismiss
                    </button>
                </div>
            )}
        </div>
    )
}
