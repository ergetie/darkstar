import { act, fireEvent, render, screen, waitFor } from '@testing-library/react'
import { beforeEach, describe, expect, it, vi } from 'vitest'

const state = vi.hoisted(() => ({
    profile: null as string | null,
    onboardingStatus: 'not_started' as 'not_started' | 'in_progress' | 'dismissed' | 'completed',
}))
vi.mock('./lib/api', () => ({
    Api: {
        config: vi.fn(async () => ({ system: { inverter_profile: state.profile } })),
        configValidate: vi.fn(async () => ({ warnings: [] })),
        setup: {
            onboarding: vi.fn(async () => ({
                status: state.onboardingStatus,
                current_step: null,
                completed_steps: [],
            })),
        },
        status: vi.fn(async () => ({})),
        health: vi.fn(async () => ({ issues: [] })),
    },
}))
vi.mock('./lib/socket', () => ({ getSocket: vi.fn() }))
vi.mock('./components/Sidebar', () => ({ default: () => null }))
vi.mock('./pages/Dashboard', () => ({ default: () => <div>Dashboard content</div> }))
vi.mock('./components/onboarding/OnboardingWizard', () => ({
    OnboardingWizard: ({ onClose }: { onClose: () => void }) => (
        <>
            <button onClick={onClose}>Skip wizard</button>
            <button
                onClick={() => {
                    state.profile = 'deye'
                    onClose()
                }}
            >
                Save wizard
            </button>
        </>
    ),
}))
import App from './App'

describe('saved inverter profile state', () => {
    beforeEach(() => {
        state.profile = null
        state.onboardingStatus = 'not_started'
    })

    it('clears the warning after a wizard save without reloading', async () => {
        render(<App />)
        fireEvent.click(await screen.findByText('Save wizard'))
        await screen.findByText('Dashboard content')
        await waitFor(() => expect(screen.queryByText(/Missing Hardware Profile/)).not.toBeInTheDocument())
    })

    it('clears the warning when Settings announces a successful save', async () => {
        render(<App />)
        fireEvent.click(await screen.findByText('Skip wizard'))
        await screen.findByText(/Missing Hardware Profile/)
        state.profile = 'deye'
        await act(async () => {
            window.dispatchEvent(new Event('config-changed'))
        })
        await waitFor(() => expect(screen.queryByText(/Missing Hardware Profile/)).not.toBeInTheDocument())
        expect(screen.getByText('Dashboard content')).toBeInTheDocument()
    })

    it('keeps dismissed onboarding closed on load and supports manual relaunch', async () => {
        state.onboardingStatus = 'dismissed'
        render(<App />)

        expect(await screen.findByText('Dashboard content')).toBeInTheDocument()
        expect(screen.queryByText('Skip wizard')).not.toBeInTheDocument()

        await act(async () => {
            window.dispatchEvent(new Event('open-onboarding'))
        })
        expect(await screen.findByText('Skip wizard')).toBeInTheDocument()
    })
})
