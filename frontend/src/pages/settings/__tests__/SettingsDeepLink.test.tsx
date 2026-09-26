import { render, screen, waitFor } from '@testing-library/react'
import { MemoryRouter, Route, Routes, useLocation } from 'react-router-dom'
import { beforeEach, describe, expect, it, vi } from 'vitest'

const jumpToField = vi.fn((_key: string, _onSettled?: () => void) => () => {})

vi.mock('../search/jump', () => ({
    jumpToField: (key: string, onSettled?: () => void) => jumpToField(key, onSettled),
}))
vi.mock('../../../lib/api', () => ({
    Api: { config: vi.fn().mockResolvedValue({ system: { has_ev_charger: true } }) },
}))
vi.mock('../search/SettingsSearch', () => ({ SettingsSearch: () => null }))
vi.mock('../SystemTab', () => ({ SystemTab: () => <div>system-tab</div> }))
vi.mock('../ParametersTab', () => ({ ParametersTab: () => null }))
vi.mock('../SolarTab', () => ({ SolarTab: () => null }))
vi.mock('../BatteryTab', () => ({ BatteryTab: () => null }))
vi.mock('../EVTab', () => ({ EVTab: () => null }))
vi.mock('../WaterTab', () => ({ WaterTab: () => null }))
vi.mock('../LoadBalancingTab', () => ({ LoadBalancingTab: () => null }))
vi.mock('../UITab', () => ({ UITab: () => null }))
vi.mock('../AdvancedTab', () => ({ AdvancedTab: () => <div>advanced-tab</div> }))
vi.mock('../../Debug', () => ({ DebugContent: () => null }))

import Settings from '../index'

// jsdom's localStorage is shadowed by Node's disabled global one; stub it.
function makeMemoryStorage(): Storage {
    const store = new Map<string, string>()
    return {
        getItem: (key: string) => store.get(key) ?? null,
        setItem: (key: string, value: string) => void store.set(key, value),
        removeItem: (key: string) => void store.delete(key),
        clear: () => store.clear(),
        key: (i: number) => Array.from(store.keys())[i] ?? null,
        get length() {
            return store.size
        },
    }
}

function LocationProbe() {
    const loc = useLocation()
    return <div data-testid="loc">{loc.search}</div>
}

function renderAt(url: string) {
    return render(
        <MemoryRouter initialEntries={[url]}>
            <Routes>
                <Route
                    path="/settings"
                    element={
                        <>
                            <Settings />
                            <LocationProbe />
                        </>
                    }
                />
            </Routes>
        </MemoryRouter>,
    )
}

describe('Settings deep link (?tab=&field=)', () => {
    beforeEach(() => {
        vi.stubGlobal('localStorage', makeMemoryStorage())
        jumpToField.mockClear()
    })

    it('opens the Advanced tab in standard mode and jumps to the linked field', async () => {
        renderAt('/settings?tab=advanced&field=executor.excess_pv.priority')
        expect(await screen.findByText('advanced-tab')).toBeInTheDocument()
        await waitFor(() =>
            expect(jumpToField).toHaveBeenCalledWith('executor.excess_pv.priority', expect.any(Function)),
        )
        expect(screen.getByLabelText('Advanced Mode')).toBeInTheDocument()
    })

    it('still redirects a plain advanced-tab URL away when Advanced mode is off', async () => {
        renderAt('/settings?tab=advanced')
        expect(await screen.findByText('system-tab')).toBeInTheDocument()
        expect(screen.getByTestId('loc')).toHaveTextContent('?tab=system')
        expect(jumpToField).not.toHaveBeenCalled()
    })
})
