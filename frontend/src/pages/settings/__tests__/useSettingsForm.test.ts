import { renderHook, waitFor, act } from '@testing-library/react'
import { describe, it, expect, vi, beforeEach } from 'vitest'
import { useSettingsForm } from '../hooks/useSettingsForm'
import { Api } from '../../../lib/api'
import { BaseField, batteryFieldList } from '../types'

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

// Mock Types
vi.mock('../types', async (importOriginal) => {
    const actual = await importOriginal<typeof import('../types')>()
    return {
        ...actual,
        allFields: [
            { key: 'test.field', label: 'Test', path: ['test', 'field'], type: 'number' },
            { key: 'battery.min_soc_percent', label: 'Min', path: ['battery', 'min_soc_percent'], type: 'number' },
            { key: 'battery.max_soc_percent', label: 'Max', path: ['battery', 'max_soc_percent'], type: 'number' },
        ],
    }
})

describe('useSettingsForm Hook', () => {
    const efficiencyFields = batteryFieldList.filter((field) => field.key.endsWith('_efficiency'))
    const statisticsFields: BaseField[] = [
        {
            key: 'installation_stats.enabled',
            label: 'Report installation statistics',
            path: ['installation_stats', 'enabled'],
            type: 'boolean',
        },
        {
            key: 'installation_stats.endpoint',
            label: 'Receiver endpoint',
            path: ['installation_stats', 'endpoint'],
            type: 'text',
        },
    ]
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

    it('saves battery efficiency percentages as fractions and reloads without becoming dirty', async () => {
        vi.mocked(Api.config).mockResolvedValue({ battery: { charge_efficiency: 0.92, discharge_efficiency: 0.95 } })
        vi.mocked(Api.configSave).mockResolvedValue({ status: 'success' })
        const { result } = renderHook(() => useSettingsForm(efficiencyFields))
        await waitFor(() => expect(result.current.loading).toBe(false))
        expect(result.current.form['battery.charge_efficiency']).toBe('92')
        expect(result.current.isDirty).toBe(false)
        act(() => result.current.handleChange('battery.charge_efficiency', '94.5'))
        vi.mocked(Api.config).mockResolvedValue({ battery: { charge_efficiency: 0.945, discharge_efficiency: 0.95 } })
        await act(async () => expect(await result.current.save()).toBe(true))
        expect(Api.configSave).toHaveBeenCalledWith({ battery: { charge_efficiency: 0.945 } })
        expect(result.current.form['battery.charge_efficiency']).toBe('94.5')
        expect(result.current.isDirty).toBe(false)
    })

    it('keeps missing efficiency keys omitted when saving unrelated settings', async () => {
        vi.mocked(Api.configSave).mockResolvedValue({ status: 'success' })
        const fields = [...mockFields, ...efficiencyFields]
        const { result } = renderHook(() => useSettingsForm(fields))
        await waitFor(() => expect(result.current.loading).toBe(false))
        expect(result.current.form['battery.charge_efficiency']).toBe('')
        expect(result.current.form['battery.discharge_efficiency']).toBe('')
        expect(result.current.isDirty).toBe(false)
        act(() => result.current.handleChange('test.field', '20'))
        await act(async () => expect(await result.current.save()).toBe(true))
        expect(Api.configSave).toHaveBeenCalledWith({ test: { field: 20 } })
    })

    describe.each(['battery.charge_efficiency', 'battery.discharge_efficiency'])('%s', (key) => {
        it.each(['', '0', '-1', '105', 'NaN', 'Infinity', '-Infinity', 'true'])(
            'blocks invalid percentage %s on edit and save',
            async (value) => {
                vi.mocked(Api.config).mockResolvedValue({
                    battery: { charge_efficiency: 0.92, discharge_efficiency: 0.95 },
                })
                const { result } = renderHook(() => useSettingsForm(efficiencyFields))
                await waitFor(() => expect(result.current.loading).toBe(false))
                act(() => result.current.handleChange(key, value))
                expect(result.current.fieldErrors[key]).toMatch(/greater than 0 and at most 100/)
                await act(async () => expect(await result.current.save()).toBe(false))
                expect(Api.configSave).not.toHaveBeenCalled()
            },
        )

        it.each(['0.01', '100'])('accepts percentage %s', async (value) => {
            vi.mocked(Api.config).mockResolvedValue({
                battery: { charge_efficiency: 0.92, discharge_efficiency: 0.95 },
            })
            const { result } = renderHook(() => useSettingsForm(efficiencyFields))
            await waitFor(() => expect(result.current.loading).toBe(false))
            act(() => result.current.handleChange(key, value))
            expect(result.current.fieldErrors[key]).toBeUndefined()
        })

        it('blocks saving an invalid loaded value without editing it', async () => {
            vi.mocked(Api.config).mockResolvedValue({
                battery: { charge_efficiency: 0.92, discharge_efficiency: 0.95, [key.split('.')[1]]: 1.05 },
            })
            const { result } = renderHook(() => useSettingsForm(efficiencyFields))
            await waitFor(() => expect(result.current.loading).toBe(false))
            expect(result.current.fieldErrors).toEqual({})
            await act(async () => expect(await result.current.save()).toBe(false))
            expect(result.current.fieldErrors[key]).toMatch(/greater than 0 and at most 100/)
            expect(Api.configSave).not.toHaveBeenCalled()
        })
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

    it('defaults and validates installation statistics settings through the shared save flow', async () => {
        vi.mocked(Api.config).mockResolvedValue({
            installation_stats: { enabled: true, endpoint: 'https://telemetry.wxl.se/api/ping' },
        })
        const { result } = renderHook(() => useSettingsForm(statisticsFields))
        await waitFor(() => expect(result.current.loading).toBe(false))

        expect(result.current.form['installation_stats.enabled']).toBe('true')
        act(() => result.current.handleChange('installation_stats.endpoint', 'http://example.com/ping'))
        expect(result.current.fieldErrors['installation_stats.endpoint']).toMatch(/absolute HTTPS URL/i)
        expect(await result.current.save()).toBe(false)
        expect(Api.configSave).not.toHaveBeenCalled()

        vi.mocked(Api.configSave).mockResolvedValue({ status: 'success' })
        act(() => result.current.handleChange('installation_stats.endpoint', 'https://stats.example/ping'))
        expect(await result.current.save()).toBe(true)
        expect(Api.configSave).toHaveBeenCalledWith({
            installation_stats: { endpoint: 'https://stats.example/ping' },
        })
    })

    it.each([
        '/api/ping',
        'https://user:secret@stats.example/ping',
        'https://@stats.example/ping',
        'https://stats.example:invalid/ping',
        'https://stats.example:65536/ping',
        'https://stats.example\\private/ping',
        'https://stats.example/ping?secret=1',
        'https://stats.example/ping#fragment',
    ])('rejects invalid reporting endpoint %s before save', async (endpoint) => {
        vi.mocked(Api.config).mockResolvedValue({
            installation_stats: { enabled: false, endpoint: 'https://telemetry.wxl.se/api/ping' },
        })
        const { result } = renderHook(() => useSettingsForm(statisticsFields))
        await waitFor(() => expect(result.current.loading).toBe(false))
        act(() => result.current.handleChange('installation_stats.endpoint', endpoint))
        expect(result.current.fieldErrors['installation_stats.endpoint']).toMatch(/absolute HTTPS URL/i)
        expect(await result.current.save()).toBe(false)
        expect(Api.configSave).not.toHaveBeenCalled()
    })

    it('persists opt-out through reload and saves endpoint edits while disabled', async () => {
        vi.mocked(Api.config).mockResolvedValue({
            installation_stats: { enabled: true, endpoint: 'https://telemetry.wxl.se/api/ping' },
        })
        vi.mocked(Api.configSave).mockResolvedValue({ status: 'success' })
        const { result } = renderHook(() => useSettingsForm(statisticsFields))
        await waitFor(() => expect(result.current.loading).toBe(false))
        act(() => result.current.handleChange('installation_stats.enabled', 'false'))
        expect(result.current.isDirty).toBe(true)
        vi.mocked(Api.config).mockResolvedValue({
            installation_stats: { enabled: false, endpoint: 'https://telemetry.wxl.se/api/ping' },
        })
        await act(async () => {
            expect(await result.current.save()).toBe(true)
        })
        expect(Api.configSave).toHaveBeenLastCalledWith({ installation_stats: { enabled: false } })
        expect(result.current.form['installation_stats.enabled']).toBe('false')
        expect(result.current.isDirty).toBe(false)
        act(() => result.current.handleChange('installation_stats.endpoint', 'https://stats.example/ping'))
        expect(result.current.isDirty).toBe(true)
        vi.mocked(Api.config).mockResolvedValue({
            installation_stats: { enabled: false, endpoint: 'https://stats.example/ping' },
        })
        await act(async () => {
            expect(await result.current.save()).toBe(true)
        })
        expect(Api.configSave).toHaveBeenLastCalledWith({
            installation_stats: { endpoint: 'https://stats.example/ping' },
        })
        expect(result.current.form['installation_stats.enabled']).toBe('false')
        expect(result.current.isDirty).toBe(false)
    })
})
