import { act, fireEvent, render, screen, waitFor } from '@testing-library/react'
import { beforeEach, describe, expect, it, vi } from 'vitest'

const state = vi.hoisted(() => ({ profile: null as string | null }))
vi.mock('./lib/api', () => ({
    Api: {
        config: vi.fn(async () => ({ system: { inverter_profile: state.profile } })),
        configValidate: vi.fn(async () => ({ warnings: [] })),
        status: vi.fn(async () => ({})),
        health: vi.fn(async () => ({ issues: [] })),
    },
}))
vi.mock('./lib/socket', () => ({ getSocket: vi.fn() }))
vi.mock('./components/Sidebar', () => ({ default: () => null }))
vi.mock('./pages/Dashboard', () => ({ default: () => <div>Dashboard content</div> }))
vi.mock('./components/startup/StartupWizard', () => ({
    StartupWizard: ({ onComplete }: { onComplete: () => void }) => (
        <>
            <button onClick={onComplete}>Skip wizard</button>
            <button
                onClick={() => {
                    state.profile = 'deye'
                    onComplete()
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
})
