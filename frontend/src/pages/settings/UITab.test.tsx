import { render, screen, fireEvent, waitFor } from '@testing-library/react'
import { MemoryRouter } from 'react-router-dom'
import { describe, it, expect, vi, beforeEach } from 'vitest'
import { UITab } from './UITab'
import { uiFieldList } from './types'
import { Api } from '../../lib/api'

const mockUseSettingsForm = vi.fn()

vi.mock('./hooks/useSettingsForm', () => ({
    useSettingsForm: (...args: unknown[]) => mockUseSettingsForm(...args),
}))

vi.mock('./hooks/useUnsavedChangesGuard', () => ({
    useUnsavedChangesGuard: () => ({ state: 'unblocked', reset: vi.fn(), location: null }),
}))

vi.mock('../../lib/api', () => ({
    Api: {
        executor: {
            testNotification: vi.fn(),
        },
    },
}))

function makeFormState(): Record<string, string> {
    const form: Record<string, string> = {}
    uiFieldList.forEach((field) => {
        form[field.key] = field.type === 'boolean' ? 'false' : field.type === 'solar_arrays' ? '[]' : ''
    })
    return form
}

function renderTab() {
    return render(
        <MemoryRouter>
            <UITab />
        </MemoryRouter>,
    )
}

describe('UITab test-notification button', () => {
    beforeEach(() => {
        vi.mocked(Api.executor.testNotification).mockReset()
        mockUseSettingsForm.mockReturnValue({
            config: {},
            form: makeFormState(),
            fields: uiFieldList,
            fieldErrors: {},
            loading: false,
            saving: false,
            statusMessage: null,
            handleChange: vi.fn(),
            save: vi.fn(),
            isDirty: false,
        })
    })

    it('shows a busy state while the request is in flight', async () => {
        let resolveTest: (value: { status: string; message: string }) => void = () => {}
        vi.mocked(Api.executor.testNotification).mockReturnValue(
            new Promise((resolve) => {
                resolveTest = resolve
            }),
        )
        renderTab()

        fireEvent.click(screen.getByRole('button', { name: /Send Test Notification/i }))
        expect(await screen.findByText('Sending…')).toBeInTheDocument()

        resolveTest({ status: 'success', message: 'Test notification sent' })
        await waitFor(() => expect(screen.getByText('Test notification sent')).toBeInTheDocument())
    })

    it('shows a success indication when the endpoint returns success', async () => {
        vi.mocked(Api.executor.testNotification).mockResolvedValue({
            status: 'success',
            message: 'Test notification sent',
        })
        renderTab()

        fireEvent.click(screen.getByRole('button', { name: /Send Test Notification/i }))

        const result = await screen.findByText('Test notification sent')
        expect(result).toHaveClass('text-good')
    })

    it('shows a failure indication and returns to idle when the endpoint errors', async () => {
        vi.mocked(Api.executor.testNotification).mockRejectedValue(new Error('Notify service unavailable'))
        renderTab()

        fireEvent.click(screen.getByRole('button', { name: /Send Test Notification/i }))

        const result = await screen.findByText('Notify service unavailable')
        expect(result).toHaveClass('text-bad')
        expect(screen.getByRole('button', { name: /Send Test Notification/i })).not.toBeDisabled()
    })
})
