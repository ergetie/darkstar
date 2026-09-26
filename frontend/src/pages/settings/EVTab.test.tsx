import { fireEvent, render, screen } from '@testing-library/react'
import { MemoryRouter } from 'react-router-dom'
import { describe, it, expect, vi } from 'vitest'
import { EVTab } from './EVTab'
import { evFieldList } from './types'

vi.mock('./hooks/useSettingsForm', () => ({
    useSettingsForm: () => ({
        config: {},
        form: Object.fromEntries(evFieldList.map((f) => [f.key, ''])),
        fields: evFieldList,
        fieldErrors: {},
        loading: false,
        saving: false,
        statusMessage: null,
        handleChange: vi.fn(),
        save: vi.fn(),
        isDirty: false,
        haEntities: [],
        haLoading: false,
    }),
}))

vi.mock('./hooks/useUnsavedChangesGuard', () => ({
    useUnsavedChangesGuard: () => ({ state: 'unblocked', reset: vi.fn(), location: null }),
}))

describe('EVTab Goal Planning info box', () => {
    it('explains charge-now vs wait, the risk margin and the shortfall penalty', () => {
        render(
            <MemoryRouter>
                <EVTab />
            </MemoryRouter>,
        )
        const note = screen.getByRole('note')
        expect(note).toHaveTextContent('How Darkstar decides: charge now or wait?')
        expect(note).toHaveTextContent(/risk margin/i)
        expect(note).toHaveTextContent(/ramp/i)
        expect(note).toHaveTextContent(/shortfall penalty/i)
    })

    it('is collapsed to a one-line summary by default and expands on click', () => {
        render(
            <MemoryRouter>
                <EVTab />
            </MemoryRouter>,
        )
        const toggle = screen.getByRole('button', { name: /How Darkstar decides/i })
        expect(toggle).toHaveAttribute('aria-expanded', 'false')
        expect(toggle).toHaveTextContent(/cheapest known hours/i)
        const details = document.getElementById(toggle.getAttribute('aria-controls')!)!
        expect(details).not.toBeVisible()

        fireEvent.click(toggle)
        expect(toggle).toHaveAttribute('aria-expanded', 'true')
        expect(details).toBeVisible()
        expect(details).toHaveTextContent(/shortfall penalty/i)

        fireEvent.click(toggle)
        expect(toggle).toHaveAttribute('aria-expanded', 'false')
        expect(details).not.toBeVisible()
    })
})
