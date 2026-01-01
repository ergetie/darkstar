import { renderHook, waitFor, act } from '@testing-library/react'
import { describe, it, expect, vi, beforeEach } from 'vitest'
import { useSettingsForm } from '../hooks/useSettingsForm'
import { Api } from '../../../lib/api'
import { BaseField } from '../types'

// Mock API
vi.mock('../../../lib/api', () => ({
    Api: {
        config: vi.fn(),
        haEntities: vi.fn(),
        configSave: vi.fn(),
    },
}))

// Mock Toast
vi.mock('../../../lib/useToast', () => ({
    useToast: () => ({
        toast: vi.fn(),
    }),
}))

describe('useSettingsForm Hook', () => {
    const mockFields: BaseField[] = [
        { key: 'test.field', label: 'Test', path: ['test', 'field'], type: 'number' },
        { key: 'battery.min_soc_percent', label: 'Min', path: ['battery', 'min_soc_percent'], type: 'number' },
        { key: 'battery.max_soc_percent', label: 'Max', path: ['battery', 'max_soc_percent'], type: 'number' },
    ]

    beforeEach(() => {
        vi.clearAllMocks()
        vi.mocked(Api.config).mockResolvedValue({
            test: { field: 10 },
            battery: { min_soc_percent: 10, max_soc_percent: 90 },
        })
        vi.mocked(Api.haEntities).mockResolvedValue({ entities: [] })
    })

    it('loads config and initializes form state', async () => {
        const { result } = renderHook(() => useSettingsForm(mockFields))

        expect(result.current.loading).toBe(true)

        await waitFor(() => expect(result.current.loading).toBe(false))

        expect(result.current.form['test.field']).toBe('10')
        expect(result.current.isDirty).toBe(false)
    })

    it('tracks dirty state on change', async () => {
        const { result } = renderHook(() => useSettingsForm(mockFields))
        await waitFor(() => expect(result.current.loading).toBe(false))

        act(() => {
            result.current.handleChange('test.field', '20')
        })

        expect(result.current.form['test.field']).toBe('20')
        expect(result.current.isDirty).toBe(true)
    })

    it('performs cross-field validation for SoC', async () => {
        const { result } = renderHook(() => useSettingsForm(mockFields))
        await waitFor(() => expect(result.current.loading).toBe(false))

        act(() => {
            result.current.handleChange('battery.min_soc_percent', '95') // Now > max (90)
        })

        expect(result.current.fieldErrors['battery.min_soc_percent']).toBeDefined()
        expect(result.current.fieldErrors['battery.max_soc_percent']).toBeDefined()
    })

    it('resets form to original state', async () => {
        const { result } = renderHook(() => useSettingsForm(mockFields))
        await waitFor(() => expect(result.current.loading).toBe(false))

        act(() => {
            result.current.handleChange('test.field', '999')
            result.current.reset()
        })

        expect(result.current.form['test.field']).toBe('10')
        expect(result.current.isDirty).toBe(false)
    })
})
