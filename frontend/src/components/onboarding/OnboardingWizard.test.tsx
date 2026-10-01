import { act, fireEvent, render, screen, waitFor } from '@testing-library/react'
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'

const api = vi.hoisted(() => {
    class MockApiError extends Error {
        status = 400
        detail: unknown

        constructor(message: string, detail?: unknown) {
            super(message)
            this.detail = detail
        }
    }

    return {
        ApiError: MockApiError,
        config: vi.fn(),
        configSave: vi.fn(),
        listProfiles: vi.fn(),
        profileSuggestions: vi.fn(),
        haSaveConnection: vi.fn(),
        haDiscovery: vi.fn(),
        haCoreConfig: vi.fn(),
        suggestions: vi.fn(),
        readiness: vi.fn(),
        onboarding: vi.fn(),
        saveOnboarding: vi.fn(),
        executorRun: vi.fn(),
    }
})

vi.mock('../../lib/api', () => ({
    Api: {
        config: api.config,
        configSave: api.configSave,
        listProfiles: api.listProfiles,
        profileSuggestions: api.profileSuggestions,
        haSaveConnection: api.haSaveConnection,
        haDiscovery: api.haDiscovery,
        haCoreConfig: api.haCoreConfig,
        setup: {
            suggestions: api.suggestions,
            readiness: api.readiness,
            onboarding: api.onboarding,
            saveOnboarding: api.saveOnboarding,
        },
        executor: { run: api.executorRun },
    },
    ApiError: api.ApiError,
}))

import { OnboardingWizard } from './OnboardingWizard'

const profile = {
    name: 'generic',
    description: 'Generic inverter',
    supported_brands: [],
    version: '1',
    schema_version: 2,
    entities: {},
    modes: {},
    behavior: { control_unit: 'W' as const },
}

const baseConfig = () => ({
    system: {
        inverter_profile: 'generic',
        has_solar: false,
        has_battery: false,
        has_water_heater: false,
        has_ev_charger: false,
        grid_meter_type: 'net',
        grid: { max_power_kw: 5, main_fuse_a: 25 },
        location: { latitude: 59.3, longitude: 18 },
    },
    nordpool: { price_area: 'SE3', currency: 'SEK' },
    timezone: 'Europe/Stockholm',
    pricing: { vat_percent: 25, energy_tax_sek: 0.5, grid_transfer_fee_sek: 0.1 },
    battery: { capacity_kwh: 8, min_soc_percent: 10, max_soc_percent: 90, max_charge_w: 4000, max_discharge_w: 4000 },
    input_sensors: {},
    executor: { shadow_mode: true },
})

const close = vi.fn<() => void>()
let resolveReadiness!: (value: { ready: boolean; checks: unknown[] }) => void
let confirmSpy: ReturnType<typeof vi.spyOn>
let originalPath = '/'

function setup(
    currentStep = 'connect',
    options: {
        profiles?: (typeof profile)[]
        readiness?: { ready: boolean; checks: unknown[] }
        config?: Record<string, unknown>
        setupSuggestions?: Record<string, unknown>
        profileSuggestionResult?: Record<string, unknown>
        haCoreConfig?: { latitude: number; longitude: number; time_zone: string; currency: string }
        discoveryEntities?: {
            entity_id: string
            friendly_name: string
            domain: string
            state?: string
            unit_of_measurement?: string
        }[]
        failDiscoveryInitially?: boolean
        failSuggestionsInitially?: boolean
        deferReadiness?: boolean
        failReadiness?: boolean
        progress?: {
            status: 'not_started' | 'in_progress' | 'dismissed' | 'completed'
            current_step: string | null
            completed_steps: string[]
        }
    } = {},
) {
    api.config.mockResolvedValue(options.config ?? baseConfig())
    api.configSave.mockResolvedValue({ warnings: [] })
    api.listProfiles.mockResolvedValue(options.profiles ?? [profile])
    api.profileSuggestions.mockResolvedValue(
        options.profileSuggestionResult ?? { patch: {}, candidates: {}, current: {}, missing_required: [] },
    )
    api.haSaveConnection.mockResolvedValue({ status: 'ok', message: 'Credentials tested and saved.' })
    api.haDiscovery.mockResolvedValue({ entities: options.discoveryEntities ?? [], registry_available: true })
    api.haCoreConfig.mockResolvedValue({
        latitude: options.haCoreConfig?.latitude ?? 59.3,
        longitude: options.haCoreConfig?.longitude ?? 18,
        time_zone: options.haCoreConfig?.time_zone ?? 'Europe/Stockholm',
        currency: options.haCoreConfig?.currency ?? 'SEK',
    })
    api.suggestions.mockResolvedValue(
        options.setupSuggestions ?? { patch: {}, candidates: {}, missing_required: [], brands: [] },
    )
    if (options.failDiscoveryInitially)
        api.haDiscovery
            .mockRejectedValueOnce(new Error('No saved Home Assistant connection'))
            .mockResolvedValue({ entities: options.discoveryEntities ?? [], registry_available: true })
    if (options.failSuggestionsInitially) {
        api.suggestions
            .mockRejectedValueOnce(new Error('Home Assistant discovery is unavailable'))
            .mockResolvedValue(
                options.setupSuggestions ?? { patch: {}, candidates: {}, missing_required: [], brands: [] },
            )
        api.profileSuggestions
            .mockRejectedValueOnce(new Error('Home Assistant discovery is unavailable'))
            .mockResolvedValue(
                options.profileSuggestionResult ?? { patch: {}, candidates: {}, current: {}, missing_required: [] },
            )
    }
    api.readiness.mockResolvedValue(options.readiness ?? { ready: true, checks: [] })
    if (options.deferReadiness) {
        api.readiness.mockImplementation(
            () =>
                new Promise((resolve) => {
                    resolveReadiness = resolve
                }),
        )
    }
    if (options.failReadiness) api.readiness.mockRejectedValueOnce(new Error('Readiness service is unavailable'))
    api.onboarding.mockResolvedValue(
        options.progress ?? { status: 'in_progress', current_step: currentStep, completed_steps: [] },
    )
    api.saveOnboarding.mockImplementation(async (value) => value)
    api.executorRun.mockResolvedValue({})
    close.mockReset()
    render(<OnboardingWizard onClose={close} />)
}

describe('OnboardingWizard', () => {
    beforeEach(() => {
        vi.clearAllMocks()
        Element.prototype.scrollIntoView = vi.fn()
        originalPath = window.location.pathname
        window.history.pushState({}, '', '/')
        confirmSpy = vi.spyOn(window, 'confirm').mockReturnValue(true)
    })

    afterEach(() => {
        confirmSpy.mockRestore()
        window.history.pushState({}, '', originalPath)
    })

    it('resumes at the saved step, edits a prior value, and saves that edit', async () => {
        setup('pricing')
        expect(await screen.findByRole('heading', { name: 'Location & pricing' })).toBeInTheDocument()

        fireEvent.click(screen.getByRole('button', { name: 'Back' }))

        expect(await screen.findByRole('heading', { name: 'My system' })).toBeInTheDocument()
        fireEvent.change(screen.getByLabelText(/Maximum grid import/), { target: { value: '8' } })
        fireEvent.click(screen.getByRole('button', { name: 'Next' }))

        await waitFor(() =>
            expect(api.configSave).toHaveBeenCalledWith(
                expect.objectContaining({
                    system: expect.objectContaining({
                        grid: expect.objectContaining({ max_power_kw: 8 }),
                    }),
                }),
            ),
        )
        await waitFor(() =>
            expect(api.saveOnboarding).toHaveBeenLastCalledWith(expect.objectContaining({ current_step: 'pricing' })),
        )
    })

    it('shows backend validation guidance inline and stays on the invalid step', async () => {
        setup('system')
        api.configSave.mockRejectedValueOnce(
            new api.ApiError('Configuration is invalid', {
                errors: [{ message: 'Grid limit is invalid', guidance: 'Enter a positive value in kW.' }],
            }),
        )

        fireEvent.click(await screen.findByRole('button', { name: 'Next' }))

        expect(await screen.findByRole('alert')).toHaveTextContent(
            'Grid limit is invalid: Enter a positive value in kW.',
        )
        expect(screen.getByRole('heading', { name: 'My system' })).toBeInTheDocument()
        expect(api.saveOnboarding).not.toHaveBeenCalledWith(expect.objectContaining({ current_step: 'pricing' }))
    })

    it.each([
        ['Skip setup', 'Skip setup for now? You can reopen it from Settings.'],
        ['Close setup', 'Close setup and save your progress?'],
    ])('%s dismisses onboarding while preserving saved progress', async (action, confirmation) => {
        setup('pricing', {
            progress: { status: 'in_progress', current_step: 'pricing', completed_steps: ['connect'] },
        })
        fireEvent.click(await screen.findByRole('button', { name: action }))

        await waitFor(() => expect(close).toHaveBeenCalledOnce())
        expect(confirmSpy).toHaveBeenCalledWith(confirmation)
        expect(api.saveOnboarding).toHaveBeenLastCalledWith({
            status: 'dismissed',
            current_step: 'pricing',
            completed_steps: ['connect'],
        })
    })

    it('resumes a dismissed setup from the saved step when reopened manually', async () => {
        setup('connect', {
            progress: { status: 'dismissed', current_step: 'pricing', completed_steps: ['connect'] },
        })

        expect(await screen.findByRole('heading', { name: 'Location & pricing' })).toBeInTheDocument()
        expect(api.saveOnboarding).toHaveBeenLastCalledWith({
            status: 'in_progress',
            current_step: 'pricing',
            completed_steps: ['connect'],
        })
    })

    it('uses profiles returned by the API instead of a hardcoded list', async () => {
        setup('inverter', {
            profiles: [profile, { ...profile, name: 'sungrow', description: 'Sungrow inverter' }],
        })
        fireEvent.click(await screen.findByText('generic — Generic inverter'))

        expect(await screen.findByText('sungrow — Sungrow inverter')).toBeInTheDocument()
        expect(api.listProfiles).toHaveBeenCalledOnce()
    })

    it('preselects the shipped suggested profile only when the profile field is empty', async () => {
        const defaults = baseConfig()
        const freshConfig = { ...defaults, system: { ...defaults.system, inverter_profile: null } }
        setup('inverter', {
            config: freshConfig,
            setupSuggestions: {
                patch: {},
                candidates: {},
                missing_required: [],
                brands: [],
                suggested_profile: 'generic',
            },
        })
        expect(await screen.findByText('generic — Generic inverter')).toBeInTheDocument()
    })

    it('preserves configured zero latitude and longitude when Home Assistant reports another location', async () => {
        const defaults = baseConfig()
        setup('pricing', {
            config: {
                ...defaults,
                system: { ...defaults.system, location: { latitude: 0, longitude: 0 } },
            },
            haCoreConfig: {
                latitude: 59.3,
                longitude: 18,
                time_zone: 'Europe/Stockholm',
                currency: 'SEK',
            },
        })

        expect(await screen.findByLabelText(/Latitude/)).toHaveValue(0)
        expect(screen.getByLabelText(/Longitude/)).toHaveValue(0)
    })

    it('keeps a configured profile and offers a different supported suggestion', async () => {
        setup('inverter', {
            profiles: [profile, { ...profile, name: 'sungrow', description: 'Sungrow inverter' }],
            setupSuggestions: {
                patch: {},
                candidates: {},
                missing_required: [],
                brands: [],
                suggested_profile: 'sungrow',
            },
        })
        expect(await screen.findByText('Suggested profile: sungrow.')).toBeInTheDocument()
        expect(screen.getByText('generic — Generic inverter')).toBeInTheDocument()
    })

    it('saves typed standalone credentials and refreshes suggestions after discovery recovers', async () => {
        const entity = {
            entity_id: 'sensor.house_power',
            friendly_name: 'House power',
            domain: 'sensor',
            state: '1250',
            unit_of_measurement: 'W',
        }
        const setupSuggestions = {
            patch: { input_sensors: { load_power: 'sensor.house_power' } },
            candidates: {
                'input_sensors.load_power': [
                    { entity_id: 'sensor.house_power', confidence: 'high', reasons: ['Matches house load'] },
                ],
            },
            missing_required: [],
            brands: [],
            suggested_profile: 'generic',
        }
        setup('connect', {
            failDiscoveryInitially: true,
            failSuggestionsInitially: true,
            discoveryEntities: [entity],
            setupSuggestions,
            profileSuggestionResult: { patch: {}, candidates: {}, current: {}, missing_required: [] },
        })

        expect(await screen.findByText(/No saved Home Assistant connection/)).toBeInTheDocument()
        fireEvent.change(screen.getByLabelText(/Home Assistant URL/), { target: { value: 'http://ha.local/' } })
        fireEvent.change(screen.getByLabelText(/Long-lived access token/), { target: { value: 'test-token' } })
        fireEvent.click(screen.getByRole('button', { name: 'Test connection and save' }))

        await waitFor(() =>
            expect(api.haSaveConnection).toHaveBeenCalledWith({ url: 'http://ha.local/', token: 'test-token' }),
        )
        await waitFor(() => expect(api.suggestions).toHaveBeenCalledTimes(2))
        await waitFor(() => expect(api.profileSuggestions).toHaveBeenCalledTimes(2))
        await waitFor(() => expect(screen.getByRole('button', { name: 'Next' })).toBeEnabled())
        fireEvent.click(screen.getByRole('button', { name: 'Next' }))
        expect(await screen.findByRole('heading', { name: 'My system' })).toBeInTheDocument()
        fireEvent.click(screen.getByRole('button', { name: 'Next' }))
        expect(await screen.findByRole('heading', { name: 'Location & pricing' })).toBeInTheDocument()
        fireEvent.click(screen.getByRole('button', { name: 'Next' }))
        expect(await screen.findByRole('heading', { name: 'Inverter' })).toBeInTheDocument()
        fireEvent.click(screen.getByRole('button', { name: 'Next' }))

        expect(await screen.findByRole('heading', { name: 'Core sensors' })).toBeInTheDocument()
        expect(screen.getByText('House power')).toBeInTheDocument()
        expect(screen.getByText('Auto-detected')).toBeInTheDocument()
    })

    it('auto-checks the add-on connection without showing credential fields', async () => {
        window.history.pushState({}, '', '/hassio_ingress/abc/')
        setup()

        expect(await screen.findByText('Home Assistant add-on connection verified.')).toBeInTheDocument()
        expect(screen.queryByLabelText(/Home Assistant URL/)).not.toBeInTheDocument()
        expect(screen.queryByLabelText(/Long-lived access token/)).not.toBeInTheDocument()
        expect(api.haSaveConnection).not.toHaveBeenCalled()
    })

    it('saves a selected synthetic daily load estimate with the core sensor step', async () => {
        const defaults = baseConfig()
        setup('sensors', {
            config: {
                ...defaults,
                input_sensors: { load_power: 'sensor.house', grid_power: 'sensor.grid' },
            },
        })
        expect(await screen.findByRole('heading', { name: 'Core sensors' })).toBeInTheDocument()

        fireEvent.click(screen.getByText('Estimate daily use'))
        expect(screen.getByLabelText(/Estimated daily use/)).toHaveValue(20)
        fireEvent.click(screen.getByRole('button', { name: 'Next' }))

        await waitFor(() =>
            expect(api.configSave).toHaveBeenCalledWith(
                expect.objectContaining({
                    input_sensors: expect.objectContaining({ synthetic_daily_load_kwh: 20 }),
                }),
            ),
        )
    })

    it('shows cumulative energy units for total sensors and power units for instantaneous sensors', async () => {
        const defaults = baseConfig()
        setup('sensors', {
            config: {
                ...defaults,
                system: { ...defaults.system, has_battery: true },
            },
        })

        expect(await screen.findByRole('heading', { name: 'Core sensors' })).toBeInTheDocument()
        expect(screen.getAllByText('Cumulative energy sensors should report Wh, kWh, or MWh.').length).toBeGreaterThan(
            0,
        )
        expect(screen.getAllByText('Power sensors should report W or kW.').length).toBeGreaterThan(0)
        expect(screen.getByText('State of charge should be between 0 and 100%.')).toBeInTheDocument()
    })

    it('routes a failed readiness check to the owning step', async () => {
        setup('review', {
            readiness: {
                ready: false,
                checks: [
                    {
                        id: 'battery_soc',
                        group: 'sensors',
                        status: 'fail',
                        message: 'Battery state of charge is missing',
                        fix_hint: 'Choose a battery SoC sensor.',
                        settings_path: 'input_sensors.battery_soc',
                    },
                ],
            },
        })
        expect(await screen.findByText('Battery state of charge is missing')).toBeInTheDocument()

        fireEvent.click(screen.getByRole('button', { name: 'Fix' }))

        expect(await screen.findByRole('heading', { name: 'Core sensors' })).toBeInTheDocument()
        await waitFor(() =>
            expect(api.saveOnboarding).toHaveBeenLastCalledWith(expect.objectContaining({ current_step: 'sensors' })),
        )
    })

    it('shows one readiness loading state, then displays returned status totals', async () => {
        setup('review', { deferReadiness: true })
        expect(await screen.findByText(/Checking readiness… Results will appear together/)).toBeInTheDocument()

        await act(async () => {
            resolveReadiness({
                ready: true,
                checks: [
                    { id: 'one', group: 'core', status: 'pass', message: 'First check', settings_path: 'system.grid' },
                    { id: 'two', group: 'core', status: 'warn', message: 'Second check', settings_path: 'system.grid' },
                    {
                        id: 'three',
                        group: 'core',
                        status: 'skipped',
                        message: 'Third check',
                        settings_path: 'system.grid',
                    },
                ],
            })
        })

        expect(await screen.findByText('1/3 checks passed · 1 warnings · 0 failures · 1 skipped')).toBeInTheDocument()
    })

    it('keeps readiness failure guidance mode-neutral on a live rerun', async () => {
        const defaults = baseConfig()
        setup('review', {
            config: { ...defaults, executor: { shadow_mode: false } },
            failReadiness: true,
        })

        expect(
            await screen.findByText(
                /Readiness checks could not be completed\. Refresh to try again; you can still finish setup\./,
            ),
        ).toBeInTheDocument()
        expect(screen.getByRole('button', { name: 'Finish and keep live mode' })).toBeInTheDocument()
    })

    it('confirms Go live and saves live mode after readiness passes', async () => {
        setup('review', {
            readiness: {
                ready: true,
                checks: [{ id: 'core', group: 'core', status: 'pass', message: 'Ready', settings_path: 'system.grid' }],
            },
        })
        expect(await screen.findByText('Ready')).toBeInTheDocument()

        fireEvent.click(screen.getByRole('button', { name: 'Go live now' }))

        await waitFor(() => expect(api.configSave).toHaveBeenCalledWith({ executor: { shadow_mode: false } }))
        expect(confirmSpy).toHaveBeenCalledWith(
            'Go live now? Darkstar may control your inverter and connected equipment.',
        )
        expect(
            await screen.findByText('Darkstar is live and can control your configured hardware.'),
        ).toBeInTheDocument()
        expect(api.executorRun).not.toHaveBeenCalled()
    })

    it('keeps an existing live mode on rerun and labels Finish accurately', async () => {
        const defaults = baseConfig()
        setup('review', {
            config: { ...defaults, executor: { shadow_mode: false } },
            readiness: {
                ready: true,
                checks: [{ id: 'core', group: 'core', status: 'pass', message: 'Ready', settings_path: 'system.grid' }],
            },
        })
        expect(await screen.findByRole('button', { name: 'Finish and keep live mode' })).toBeInTheDocument()
        expect(
            screen.getAllByRole('status').some((status) => status.textContent?.includes('Current executor mode: Live')),
        ).toBe(true)
        fireEvent.click(screen.getByRole('button', { name: 'Finish and keep live mode' }))

        await waitFor(() => expect(api.configSave).toHaveBeenCalledWith({ executor: { shadow_mode: false } }))
        expect(
            await screen.findByText('Darkstar is live and can control your configured hardware.'),
        ).toBeInTheDocument()
    })

    it('blocks live mode on failed readiness and finishes in shadow without executing controls', async () => {
        setup('review', {
            readiness: {
                ready: false,
                checks: [
                    {
                        id: 'profile',
                        group: 'profile',
                        status: 'fail',
                        message: 'Profile needs attention',
                        fix_hint: 'Choose a profile',
                        settings_path: 'system.inverter_profile',
                    },
                    {
                        id: 'battery_soc',
                        group: 'sensors',
                        status: 'pass',
                        message: 'battery_soc: 50 %.',
                        fix_hint: 'Wrong power-unit guidance must stay hidden.',
                        settings_path: 'input_sensors.battery_soc',
                    },
                ],
            },
        })
        expect(await screen.findByText('Profile needs attention')).toBeInTheDocument()
        expect(screen.getByText('1/2 checks passed · 0 warnings · 1 failures · 0 skipped')).toBeInTheDocument()
        expect(screen.queryByText('Wrong power-unit guidance must stay hidden.')).not.toBeInTheDocument()
        expect(screen.getByRole('button', { name: 'Go live now' })).toBeDisabled()

        fireEvent.click(screen.getByRole('button', { name: 'Finish in shadow mode' }))

        await waitFor(() => expect(api.configSave).toHaveBeenCalledWith({ executor: { shadow_mode: true } }))
        await waitFor(() =>
            expect(api.saveOnboarding).toHaveBeenLastCalledWith(expect.objectContaining({ status: 'completed' })),
        )
        expect(api.executorRun).not.toHaveBeenCalled()
        expect(await screen.findByText(/planning in shadow mode/i)).toBeInTheDocument()
    })
})
