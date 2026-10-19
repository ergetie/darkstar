import { act, fireEvent, render, renderHook, screen, waitFor } from '@testing-library/react'
import { beforeEach, describe, expect, it, vi } from 'vitest'

const api = vi.hoisted(() => ({
    programTimes: vi.fn(),
    onboarding: vi.fn(),
    dismissNotice: vi.fn(),
}))

vi.mock('../lib/api', () => ({
    Api: {
        setup: {
            programTimes: api.programTimes,
            onboarding: api.onboarding,
            dismissNotice: api.dismissNotice,
        },
    },
}))

import { ProfileSetupNotice } from './ProfileSetupNotice'
import { programTimesNoticeId, useDismissedNotices } from '../lib/useDismissedNotices'
import type { InverterProfile } from '../pages/settings/types'

const baseProfile = {
    description: '',
    supported_brands: [],
    version: '2.0.0',
    schema_version: 2,
    entities: {},
    modes: {},
    behavior: { control_unit: 'A' as const },
}

const deye: InverterProfile = {
    ...baseProfile,
    name: 'deye',
    setup_notice: {
        title: 'Deye inverter setup',
        severity: 'info',
        items: ['Set all six program times to 00:00.', 'Darkstar controls program 6 SoC.'],
    },
}

const generic: InverterProfile = { ...baseProfile, name: 'generic', setup_notice: null }

const UNVERIFIED = /Couldn't verify program times/

describe('ProfileSetupNotice', () => {
    beforeEach(() => {
        vi.clearAllMocks()
        api.programTimes.mockResolvedValue({ status: 'ok', entities: [], mismatches: [] })
    })

    it('renders the notice for Deye', async () => {
        render(<ProfileSetupNotice profile={deye} dismissedNotices={[]} onDismissNotice={vi.fn()} />)
        expect(screen.getByText('Deye inverter setup')).toBeInTheDocument()
        expect(screen.getByText('Set all six program times to 00:00.')).toBeInTheDocument()
        await waitFor(() => expect(api.programTimes).toHaveBeenCalled())
        expect(screen.queryByText(UNVERIFIED)).not.toBeInTheDocument()
    })

    it('renders nothing for a profile without a notice', () => {
        const { container } = render(
            <ProfileSetupNotice profile={generic} dismissedNotices={[]} onDismissNotice={vi.fn()} />,
        )
        expect(container).toBeEmptyDOMElement()
        expect(api.programTimes).not.toHaveBeenCalled()
    })

    it('shows a dismissible info when program times cannot be verified', async () => {
        api.programTimes.mockResolvedValue({ status: 'unverifiable', entities: [], mismatches: [] })
        const onDismiss = vi.fn()
        render(
            <ProfileSetupNotice
                profile={deye}
                socTarget="input_number.master_soc_target"
                dismissedNotices={[]}
                onDismissNotice={onDismiss}
            />,
        )
        expect(await screen.findByText(UNVERIFIED)).toBeInTheDocument()
        expect(api.programTimes).toHaveBeenCalledWith('input_number.master_soc_target')
        fireEvent.click(screen.getByRole('button', { name: 'Dismiss' }))
        expect(onDismiss).toHaveBeenCalledWith(programTimesNoticeId('deye'))
    })

    it('stays hidden once dismissed', async () => {
        api.programTimes.mockResolvedValue({ status: 'unverifiable', entities: [], mismatches: [] })
        render(
            <ProfileSetupNotice
                profile={deye}
                dismissedNotices={[programTimesNoticeId('deye')]}
                onDismissNotice={vi.fn()}
            />,
        )
        await waitFor(() => expect(api.programTimes).toHaveBeenCalled())
        expect(screen.queryByText(UNVERIFIED)).not.toBeInTheDocument()
    })
})

describe('useDismissedNotices', () => {
    beforeEach(() => vi.clearAllMocks())

    it('loads persisted dismissals and persists new ones', async () => {
        const id = programTimesNoticeId('deye')
        api.onboarding.mockResolvedValue({ status: 'completed', current_step: null, completed_steps: [] })
        api.dismissNotice.mockResolvedValue({
            status: 'completed',
            current_step: null,
            completed_steps: [],
            dismissed_notices: [id],
        })
        const { result } = renderHook(() => useDismissedNotices())
        await waitFor(() => expect(api.onboarding).toHaveBeenCalled())
        expect(result.current[0]).toEqual([])
        act(() => result.current[1](id))
        expect(result.current[0]).toEqual([id])
        await waitFor(() => expect(api.dismissNotice).toHaveBeenCalledWith(id))

        // A fresh mount (page reload) reads the persisted state.
        api.onboarding.mockResolvedValue({
            status: 'completed',
            current_step: null,
            completed_steps: [],
            dismissed_notices: [id],
        })
        const reloaded = renderHook(() => useDismissedNotices())
        await waitFor(() => expect(reloaded.result.current[0]).toEqual([id]))
    })
})
