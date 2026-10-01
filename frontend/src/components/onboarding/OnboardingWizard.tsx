import { useCallback, useEffect, useMemo, useRef, useState } from 'react'
import { X } from 'lucide-react'
import {
    Api,
    ApiError,
    type ConfigSaveWarning,
    type HaCoreConfigResponse,
    type HaDiscoveryEntity,
    type OnboardingProgress,
    type ProfileSuggestionsResponse,
    type ReadinessResponse,
    type SetupSuggestionsResponse,
} from '../../lib/api'
import type { InverterProfile } from '../../pages/settings/types'
import { applicableSteps, type StepId, type StepProps } from './steps'
import { getPath, hasFiniteNumber, isConfigured, prefillHighConfidence, setPath, type WizardConfig } from './helpers'

type Props = { onClose: () => void }

const emptyProgress: OnboardingProgress = { status: 'not_started', current_step: null, completed_steps: [] }

function describeError(error: unknown): string {
    if (error instanceof ApiError) {
        const detail = error.detail as { errors?: { message?: string; guidance?: string }[] } | undefined
        const details = detail?.errors
            ?.map((item) => [item.message, item.guidance].filter(Boolean).join(': '))
            .filter(Boolean)
        if (details?.length) return details.join(' ')
        return error.message
    }
    return error instanceof Error ? error.message : 'Something went wrong. Please try again.'
}

function suggestionRoleNames(): string[] {
    return [
        'load_power',
        'battery_soc',
        'battery_power',
        'pv_power',
        'grid_power',
        'grid_import_power',
        'grid_export_power',
        'total_pv_production',
        'total_load_consumption',
        'total_grid_import',
        'total_grid_export',
        'total_battery_charge',
        'total_battery_discharge',
        'water_heater_control',
        'water_heater_power',
        'ev_switch',
        'ev_current',
        'ev_soc',
        'ev_plug',
        'ev_power',
    ]
}

export function OnboardingWizard({ onClose }: Props) {
    const [config, setConfig] = useState<WizardConfig | null>(null)
    const [initialConfig, setInitialConfig] = useState<WizardConfig | null>(null)
    const [progress, setProgress] = useState<OnboardingProgress>(emptyProgress)
    const [profiles, setProfiles] = useState<InverterProfile[]>([])
    const [haCoreConfig, setHaCoreConfig] = useState<HaCoreConfigResponse | null>(null)
    const [entities, setEntities] = useState<HaDiscoveryEntity[]>([])
    const [suggestions, setSuggestions] = useState<SetupSuggestionsResponse | null>(null)
    const [profileSuggestionEntry, setProfileSuggestionEntry] = useState<{
        profileName: string
        suggestions: ProfileSuggestionsResponse
    } | null>(null)
    const [readiness, setReadiness] = useState<ReadinessResponse | null>(null)
    const [readinessStatus, setReadinessStatus] = useState<'idle' | 'checking' | 'ready' | 'error'>('idle')
    const [currentStepId, setCurrentStepId] = useState<StepId>('connect')
    const [isAddon, setIsAddon] = useState(false)
    const [connectReady, setConnectReady] = useState(false)
    const [connectionMessage, setConnectionMessage] = useState<string | null>(null)
    const [loading, setLoading] = useState(true)
    const [busy, setBusy] = useState(false)
    const [errorMessage, setErrorMessage] = useState<string | null>(null)
    const [warnings, setWarnings] = useState<ConfigSaveWarning[]>([])
    const [completed, setCompleted] = useState(false)
    const [finishedShadow, setFinishedShadow] = useState(true)
    const [freshInstall, setFreshInstall] = useState(false)
    const autoDefaultsLoaded = useRef(false)

    const activeSteps = useMemo(() => (config ? applicableSteps(config) : []), [config])
    const configIsLoaded = config !== null
    const selectedProfileName = String(getPath(config, 'system.inverter_profile') ?? '')
    const foundStepIndex = activeSteps.findIndex((step) => step.id === currentStepId)
    const stepIndex = Math.max(0, foundStepIndex)
    const activeStep = foundStepIndex >= 0 ? activeSteps[foundStepIndex] : activeSteps[0]
    const StepComponent = activeStep?.component
    const profileSuggestions =
        profileSuggestionEntry?.profileName === selectedProfileName ? profileSuggestionEntry.suggestions : null

    useEffect(() => {
        let mounted = true
        const initialize = async () => {
            try {
                const [loadedConfig, loadedProgress, loadedProfiles] = await Promise.all([
                    Api.config(),
                    Api.setup.onboarding(),
                    Api.listProfiles(),
                ])
                if (!mounted) return
                let draft = structuredClone(loadedConfig) as WizardConfig
                const fresh = loadedConfig.system?.inverter_profile == null && loadedProgress.status === 'not_started'
                if (fresh && getPath(draft, 'nordpool.price_area') === 'SE4')
                    draft = setPath(draft, 'nordpool.price_area', '')
                setFreshInstall(fresh)
                setConfig(draft)
                setInitialConfig(structuredClone(draft))
                setProgress(loadedProgress)
                setProfiles(loadedProfiles)
                const addon = window.location.pathname.includes('hassio_ingress')
                setIsAddon(addon)
                const available = applicableSteps(draft)
                const persisted = loadedProgress.current_step as StepId | null
                const resume =
                    persisted && available.some((step) => step.id === persisted)
                        ? persisted
                        : (available.find((step) => !loadedProgress.completed_steps.includes(step.id))?.id ??
                          available[0]?.id ??
                          'connect')
                setCurrentStepId(resume)
                await Api.setup.saveOnboarding({
                    ...loadedProgress,
                    status: 'in_progress',
                    current_step: resume,
                })
                setProgress((current) => ({ ...current, status: 'in_progress', current_step: resume }))
            } catch (error) {
                if (mounted) setErrorMessage(describeError(error))
            } finally {
                if (mounted) setLoading(false)
            }
        }
        void initialize()
        return () => {
            mounted = false
        }
    }, [])

    const update = useCallback((path: string, value: unknown) => {
        setConfig((current) => (current ? setPath(current, path, value) : current))
    }, [])

    const applyCoreDefaults = useCallback(async () => {
        if (autoDefaultsLoaded.current) return
        autoDefaultsLoaded.current = true
        try {
            const core = await Api.haCoreConfig()
            setHaCoreConfig(core)
            setConfig((current) => {
                if (!current) return current
                let next = current
                const latitude = getPath(current, 'system.location.latitude')
                const longitude = getPath(current, 'system.location.longitude')
                const placeholderLocation = Number(latitude) === 55.123 && Number(longitude) === 13.123
                if (Number.isFinite(core.latitude) && Number.isFinite(core.longitude)) {
                    if (placeholderLocation || !hasFiniteNumber(latitude))
                        next = setPath(next, 'system.location.latitude', core.latitude)
                    if (placeholderLocation || !hasFiniteNumber(longitude))
                        next = setPath(next, 'system.location.longitude', core.longitude)
                }
                if (!isConfigured(getPath(next, 'timezone')) && core.time_zone)
                    next = setPath(next, 'timezone', core.time_zone)
                if (!isConfigured(getPath(next, 'nordpool.currency')) && core.currency)
                    next = setPath(next, 'nordpool.currency', core.currency)
                return next
            })
        } catch {
            setConnectionMessage(
                (value) =>
                    value ?? 'Connected to Home Assistant. Location and currency were not available for auto-fill.',
            )
        }
    }, [])

    const refreshSuggestions = useCallback(async () => {
        const profileName = selectedProfileName
        const setupPromise = Api.setup
            .suggestions(suggestionRoleNames())
            .then((result) => {
                setSuggestions(result)
                setConfig((current) => {
                    if (!current) return current
                    let next = prefillHighConfidence(current, result.patch, result.candidates)
                    const suggestedProfile = result.suggested_profile
                    if (
                        !isConfigured(getPath(next, 'system.inverter_profile')) &&
                        suggestedProfile &&
                        profiles.some((profile) => profile.name === suggestedProfile)
                    ) {
                        next = setPath(next, 'system.inverter_profile', suggestedProfile)
                    }
                    return next
                })
                setConnectionMessage((message) =>
                    message?.startsWith('Entity suggestions are unavailable:') ? null : message,
                )
            })
            .catch((error: unknown) => {
                setConnectionMessage(`Entity suggestions are unavailable: ${describeError(error)}`)
            })
        const profilePromise = profileName
            ? Api.profileSuggestions(profileName)
                  .then((result) => {
                      setProfileSuggestionEntry({ profileName, suggestions: result })
                      setConfig((current) =>
                          current && getPath(current, 'system.inverter_profile') === profileName
                              ? prefillHighConfidence(current, result.patch, result.candidates)
                              : current,
                      )
                      setConnectionMessage((message) =>
                          message?.startsWith('Inverter suggestions are unavailable:') ? null : message,
                      )
                  })
                  .catch((error: unknown) => {
                      setConnectionMessage(`Inverter suggestions are unavailable: ${describeError(error)}`)
                  })
            : Promise.resolve()
        await Promise.all([setupPromise, profilePromise])
    }, [profiles, selectedProfileName])

    useEffect(() => {
        if (!configIsLoaded || !profiles.length) return
        void refreshSuggestions()
    }, [configIsLoaded, profiles, refreshSuggestions])

    useEffect(() => {
        if (!configIsLoaded || loading) return
        let active = true
        Api.haDiscovery()
            .then((result) => {
                if (!active) return
                setEntities(result.entities)
                setConnectReady(true)
                setConnectionMessage(
                    isAddon
                        ? 'Home Assistant add-on connection verified.'
                        : 'Saved Home Assistant connection verified.',
                )
                void applyCoreDefaults()
            })
            .catch((error) => {
                if (!active) return
                setConnectionMessage(
                    isAddon
                        ? `Supervisor discovery failed: ${describeError(error)}`
                        : 'No saved Home Assistant connection is available. Enter credentials to test and save it.',
                )
            })
        return () => {
            active = false
        }
    }, [configIsLoaded, loading, isAddon, applyCoreDefaults])

    useEffect(() => {
        if (currentStepId !== 'review') return
        let active = true
        void Api.setup
            .readiness()
            .then((result) => {
                if (!active) return
                setReadiness(result)
                setReadinessStatus('ready')
            })
            .catch((error) => {
                if (!active) return
                setReadinessStatus('error')
                setErrorMessage(`Readiness check failed: ${describeError(error)}`)
            })
        return () => {
            active = false
        }
    }, [currentStepId])

    const refreshReadiness = () => {
        setReadinessStatus('checking')
        setReadiness(null)
        void Api.setup
            .readiness()
            .then((result) => {
                setReadiness(result)
                setReadinessStatus('ready')
            })
            .catch((error) => {
                setReadinessStatus('error')
                setErrorMessage(`Readiness check failed: ${describeError(error)}`)
            })
    }

    const persistProgress = async (next: OnboardingProgress) => {
        const saved = await Api.setup.saveOnboarding(next)
        setProgress(saved)
        return saved
    }

    const testConnection = async (credentials?: { url: string; token: string }) => {
        setBusy(true)
        setConnectionMessage(null)
        try {
            if (credentials) {
                const saved = await Api.haSaveConnection(credentials)
                update('home_assistant.url', credentials.url.trim().replace(/\/$/, ''))
                setConnectionMessage(saved.message)
            }
            const discovery = await Api.haDiscovery()
            setEntities(discovery.entities)
            setConnectReady(true)
            await applyCoreDefaults()
            void refreshSuggestions()
            return true
        } catch (error) {
            setConnectReady(false)
            setConnectionMessage(describeError(error))
            return false
        } finally {
            setBusy(false)
        }
    }

    const currentIsComplete = Boolean(activeStep?.isComplete(config ?? ({} as WizardConfig), profiles))
    const connectCanContinue = activeStep?.id !== 'connect' || connectReady
    const canContinue = currentIsComplete && connectCanContinue

    const handleNext = async () => {
        if (!activeStep || !config || !canContinue || busy) return
        setBusy(true)
        setErrorMessage(null)
        setWarnings([])
        try {
            const patch = activeStep.buildPatch(config)
            if (Object.keys(patch).length) {
                const result = await Api.configSave(patch)
                setWarnings(result.warnings ?? [])
                window.dispatchEvent(new Event('config-changed'))
            }
            const completedSteps = [...new Set([...progress.completed_steps, activeStep.id])]
            const nextStep = activeSteps[stepIndex + 1]
            const nextId = nextStep?.id ?? 'review'
            await persistProgress({
                status: 'in_progress',
                current_step: nextId,
                completed_steps: completedSteps,
            })
            setCurrentStepId(nextId)
        } catch (error) {
            setErrorMessage(describeError(error))
        } finally {
            setBusy(false)
        }
    }

    const handleBack = async () => {
        if (!activeStep || stepIndex <= 0 || busy) return
        const previous = activeSteps[stepIndex - 1]
        if (activeStep.id === 'review') {
            setReadiness(null)
            setReadinessStatus('idle')
        }
        setCurrentStepId(previous.id)
        setErrorMessage(null)
        try {
            await persistProgress({ ...progress, status: 'in_progress', current_step: previous.id })
        } catch (error) {
            setErrorMessage(describeError(error))
        }
    }

    const dismissSetup = async (confirmation: string) => {
        if (!window.confirm(confirmation)) return
        setBusy(true)
        try {
            await persistProgress({ ...progress, status: 'dismissed', current_step: currentStepId })
            onClose()
        } catch (error) {
            setErrorMessage(describeError(error))
        } finally {
            setBusy(false)
        }
    }

    const skipSetup = () => dismissSetup('Skip setup for now? You can reopen it from Settings.')
    const closeSetup = () => dismissSetup('Close setup and save your progress?')

    const finish = async (goLive: boolean) => {
        if (!config || busy) return
        if (goLive && readiness?.checks.some((check) => check.status === 'fail')) return
        if (goLive && !window.confirm('Go live now? Darkstar may control your inverter and connected equipment.'))
            return
        setBusy(true)
        setErrorMessage(null)
        try {
            const currentlyShadow = getPath(config, 'executor.shadow_mode')
            const shadowMode = goLive ? false : currentlyShadow === false ? false : true
            const response = await Api.configSave({ executor: { shadow_mode: shadowMode } })
            setWarnings(response.warnings ?? [])
            await persistProgress({
                ...progress,
                status: 'completed',
                current_step: null,
                completed_steps: activeSteps.map((step) => step.id),
            })
            setFinishedShadow(shadowMode)
            setCompleted(true)
            window.dispatchEvent(new Event('config-changed'))
        } catch (error) {
            setErrorMessage(describeError(error))
        } finally {
            setBusy(false)
        }
    }

    const handleFix = (step: StepId) => {
        const target = activeSteps.find((item) => item.id === step)
        if (!target) return
        setReadiness(null)
        setReadinessStatus('idle')
        setCurrentStepId(step)
        setErrorMessage(null)
        void persistProgress({ ...progress, status: 'in_progress', current_step: step }).catch((error) =>
            setErrorMessage(describeError(error)),
        )
    }

    if (loading) {
        return (
            <main className="fixed inset-0 z-50 flex items-center justify-center bg-canvas/90 p-4">
                <div className="spinner" aria-label="Loading setup" />
            </main>
        )
    }
    if (!config || !initialConfig) {
        return (
            <main className="fixed inset-0 z-50 flex items-center justify-center bg-canvas/90 p-4">
                <div className="w-full max-w-xl rounded-ds-lg border border-line bg-surface p-6">
                    <div className="banner banner-error">
                        Could not load setup: {errorMessage ?? 'Configuration is unavailable.'}
                    </div>
                    <button className="btn btn-secondary mt-4" onClick={onClose}>
                        Close
                    </button>
                </div>
            </main>
        )
    }
    if (completed) {
        return (
            <main className="fixed inset-0 z-50 overflow-y-auto bg-canvas/95 p-4 sm:p-8">
                <div className="mx-auto max-w-3xl rounded-ds-lg border border-line bg-surface p-6 shadow-float sm:p-8">
                    <div className="flex justify-end">
                        <button className="btn btn-ghost" onClick={onClose} aria-label="Close setup summary">
                            <X size={18} />
                        </button>
                    </div>
                    <div className={finishedShadow ? 'banner banner-purple' : 'banner banner-success'}>
                        <h1 className="text-2xl font-bold">Setup complete</h1>
                        <p className="mt-2">
                            {finishedShadow
                                ? 'Darkstar is planning in shadow mode. It will not control your hardware until you turn shadow mode off in Settings → Executor.'
                                : 'Darkstar is live and can control your configured hardware.'}
                        </p>
                    </div>
                    {warnings.map((warning) => (
                        <div className="banner banner-warning mt-3" key={warning.message}>
                            {warning.message} {warning.guidance}
                        </div>
                    ))}
                    <button className="btn btn-primary mt-6" onClick={onClose}>
                        Done
                    </button>
                </div>
            </main>
        )
    }
    if (!activeStep || !StepComponent) return null

    const stepProps: StepProps = {
        config,
        initialConfig,
        update,
        profiles,
        entities,
        suggestions,
        profileSuggestions,
        isAddon,
        connectReady,
        connectionMessage,
        testConnection,
        readiness,
        readinessStatus,
        haCurrencySuggestion: haCoreConfig?.currency,
        haCoreConfig,
        refreshReadiness,
        onFix: handleFix,
    }

    return (
        <main className="fixed inset-0 z-50 overflow-y-auto bg-canvas/95 p-3 sm:p-6">
            <div className="mx-auto max-w-4xl overflow-hidden rounded-ds-lg border border-line bg-surface shadow-float">
                <header className="border-b border-line p-4 sm:p-6">
                    <div className="flex items-start justify-between gap-4">
                        <div>
                            <p className="text-xs font-bold uppercase tracking-widest text-accent">Darkstar setup</p>
                            <h1 className="mt-1 text-2xl font-bold text-text">{activeStep.title}</h1>
                            <p className="mt-1 text-sm text-muted">
                                Step {stepIndex + 1} of {activeSteps.length}
                            </p>
                        </div>
                        <button
                            className="btn btn-ghost"
                            type="button"
                            aria-label="Close setup"
                            onClick={() => void closeSetup()}
                            disabled={busy}
                        >
                            <X size={18} />
                        </button>
                    </div>
                    <div className="progress-bar mt-4">
                        <div
                            className="progress-bar-fill"
                            style={{ width: `${((stepIndex + 1) / Math.max(activeSteps.length, 1)) * 100}%` }}
                        />
                    </div>
                </header>
                <section className="space-y-4 p-4 sm:p-6">
                    {errorMessage && (
                        <div className="banner banner-error" role="alert">
                            {errorMessage}
                        </div>
                    )}
                    {warnings.map((warning) => (
                        <div className="banner banner-warning" key={warning.message}>
                            {warning.message} {warning.guidance}
                        </div>
                    ))}
                    {freshInstall && currentStepId === 'pricing' && (
                        <div className="banner banner-info">
                            Choose the SE1–SE4 area shown on your electricity bill. Darkstar has not selected one for
                            you.
                        </div>
                    )}
                    <StepComponent {...stepProps} />
                </section>
                <footer className="flex flex-wrap items-center justify-between gap-3 border-t border-line bg-surface2 p-4 sm:p-6">
                    <div className="flex gap-2">
                        <button
                            className="btn btn-ghost"
                            type="button"
                            onClick={() => void skipSetup()}
                            disabled={busy}
                        >
                            Skip setup
                        </button>
                        {stepIndex > 0 && (
                            <button
                                className="btn btn-secondary"
                                type="button"
                                onClick={() => void handleBack()}
                                disabled={busy}
                            >
                                Back
                            </button>
                        )}
                    </div>
                    {currentStepId === 'review' ? (
                        <div className="flex flex-wrap gap-2">
                            <button
                                className="btn btn-primary"
                                type="button"
                                onClick={() => void finish(false)}
                                disabled={busy}
                            >
                                {busy
                                    ? 'Saving…'
                                    : getPath(config, 'executor.shadow_mode') === false
                                      ? 'Finish and keep live mode'
                                      : 'Finish in shadow mode'}
                            </button>
                            <button
                                className="btn btn-danger"
                                type="button"
                                onClick={() => void finish(true)}
                                disabled={
                                    busy || !readiness || readiness.checks.some((check) => check.status === 'fail')
                                }
                            >
                                {busy ? 'Saving…' : 'Go live now'}
                            </button>
                        </div>
                    ) : (
                        <button
                            className="btn btn-primary"
                            type="button"
                            onClick={() => void handleNext()}
                            disabled={busy || !canContinue}
                        >
                            {busy ? 'Saving…' : 'Next'}
                        </button>
                    )}
                </footer>
            </div>
        </main>
    )
}
