import React, { useState, useEffect } from 'react'
import { Api } from '../../lib/api'
import { ProfileSetupHelper } from '../../pages/settings/components/ProfileSetupHelper'
import Card from '../Card'
import EntitySelect from '../EntitySelect'
import type { HaEntity } from '../../pages/settings/types'

interface StartupWizardProps {
    onComplete: () => void
}

export const StartupWizard: React.FC<StartupWizardProps> = ({ onComplete }) => {
    // Step 0 is HA Connection check. Step 1-3 are normal.
    const [step, setStep] = useState(0)
    const [loading, setLoading] = useState(false)
    const [errorMsg, setErrorMsg] = useState<string | null>(null)
    const [haEntities, setHaEntities] = useState<HaEntity[]>([])
    const [haLoading, setHaLoading] = useState(false)
    const [haTestStatus, setHaTestStatus] = useState<string | null>(null)

    // HA manual auth state (if not add-on)
    const [haUrl, setHaUrl] = useState('')
    const [haToken, setHaToken] = useState('')
    const [isAddon, setIsAddon] = useState(false)

    // Form State
    const [profile, setProfile] = useState<string | null>(null)
    const [batteryCapacity, setBatteryCapacity] = useState<string>('')
    const [solarArrayKwp, setSolarArrayKwp] = useState<string>('')
    const [baselineType, setBaselineType] = useState<'sensor' | 'synthetic'>('synthetic')
    const [baselineSensor, setBaselineSensor] = useState<string>('')
    const [baselineEstimated, setBaselineEstimated] = useState<string>('20')
    const [profileSuggestions, setProfileSuggestions] = useState<Record<string, unknown>>({})

    // Fetch initial config & check HA status
    useEffect(() => {
        let isMounted = true

        const initialize = async () => {
            try {
                // Determine if running as a HA Add-on based on URL path or a specific API check
                const isIngress = window.location.pathname.includes('hassio_ingress')
                if (isMounted) setIsAddon(isIngress)

                setHaLoading(true)
                const [cfg, entitiesResponse] = await Promise.all([Api.config(), Api.haEntities()])

                if (isMounted) {
                    setHaEntities(entitiesResponse.entities || [])
                    setHaLoading(false)

                    // Pre-fill states from config
                    if (cfg.system?.inverter_profile) {
                        setProfile(cfg.system.inverter_profile)
                    }
                    if (cfg.battery?.capacity_kwh !== undefined) {
                        setBatteryCapacity(String(cfg.battery.capacity_kwh))
                    }
                    const sysAny = cfg.system as Record<string, unknown> | undefined
                    if (sysAny?.solar_arrays && Array.isArray(sysAny.solar_arrays)) {
                        const totalKwp = sysAny.solar_arrays.reduce(
                            (sum, arr: Record<string, unknown>) => sum + (Number(arr?.kwp) || 0),
                            0,
                        )
                        if (totalKwp > 0) setSolarArrayKwp(String(totalKwp))
                    }

                    const sensorsAny = cfg.input_sensors as Record<string, unknown> | undefined
                    const consumption = sensorsAny?.total_load_consumption
                    if (consumption) {
                        const parsed = Number(consumption)
                        if (!isNaN(parsed) && parsed > 0 && !String(consumption).startsWith('sensor.')) {
                            setBaselineType('synthetic')
                            setBaselineEstimated(String(parsed))
                        } else {
                            setBaselineType('sensor')
                            setBaselineSensor(String(consumption))
                        }
                    }

                    // For step 0 decision:
                    if (isIngress) {
                        setStep(1) // Skip HA connection check if Add-on
                    } else {
                        // Test connection if URL/token exist in config
                        const haCfg = (cfg as Record<string, unknown>).home_assistant as
                            Record<string, string> | undefined

                        if (haCfg?.url) setHaUrl(haCfg.url)
                        if (haCfg?.token) setHaToken(haCfg.token)

                        if (haCfg?.url && haCfg?.token) {
                            const test = await Api.haTest({
                                url: haCfg.url,
                                token: haCfg.token,
                            })
                            if (test.success || test.status === 'success') {
                                setStep(1) // Skip if connection works
                            }
                        }
                    }
                }
            } catch (err) {
                console.error('Failed to initialize Wizard', err)
                if (isMounted) setHaLoading(false)
            }
        }

        initialize()
        return () => {
            isMounted = false
        }
    }, [])

    const handleTestConnection = async () => {
        setHaTestStatus('Testing...')
        try {
            const data = await Api.haTest({ url: haUrl, token: haToken })
            if (data.success || data.status === 'success') {
                setHaTestStatus('Success: Connected!')
                // Fetch entities now that we are connected
                const ents = await Api.haEntities()
                setHaEntities(ents.entities || [])

                // Save the credentials to backend so it remembers
                const cfg = await Api.config()
                await Api.configSave({
                    ...cfg,
                    home_assistant: { url: haUrl, token: haToken },
                })

                setTimeout(() => setStep(1), 1000)
            } else {
                setHaTestStatus(`Error: ${data.message}`)
            }
        } catch (e) {
            setHaTestStatus(`Error: ${e instanceof Error ? e.message : 'Unknown error'}`)
        }
    }

    const handleProfileApply = (suggestions: Record<string, unknown>) => {
        setProfileSuggestions(suggestions)
    }

    const handleNext = () => setStep((s) => s + 1)
    const handlePrev = () => setStep((s) => s - 1)

    const handleSave = async () => {
        setLoading(true)
        setErrorMsg(null)
        try {
            // First fetch current config to merge against
            const config = await Api.config()

            // Safely fall back to empty objects/arrays for TS
            const currentSystem = config.system || {}
            const currentBattery = config.battery || {}
            const currentInputSensors = config.input_sensors || {}

            // Build the update payload
            const updatePayload = {
                system: {
                    ...currentSystem,
                    inverter_profile: profile,
                    solar_arrays:
                        Array.isArray((currentSystem as Record<string, unknown>).solar_arrays) &&
                        ((currentSystem as Record<string, unknown>).solar_arrays as Array<Record<string, unknown>>)
                            .length > 0
                            ? (
                                  (currentSystem as Record<string, unknown>).solar_arrays as Array<
                                      Record<string, unknown>
                                  >
                              ).map((arr: Record<string, unknown>, i: number, all: Record<string, unknown>[]) => {
                                  // Distribute the new max kwp proportionally across existing arrays
                                  const oldTotal = all.reduce((sum, a) => sum + (Number(a?.kwp) || 0), 0)
                                  const newTotal = parseFloat(solarArrayKwp) || 0
                                  const ratio = oldTotal > 0 ? (Number(arr.kwp) || 0) / oldTotal : 1 / all.length
                                  return {
                                      ...arr,
                                      kwp: parseFloat((newTotal * ratio).toFixed(2)),
                                  }
                              })
                            : [
                                  {
                                      azimuth: 180,
                                      tilt: 30,
                                      kwp: parseFloat(solarArrayKwp) || 0,
                                  },
                              ],
                },
                battery: {
                    ...currentBattery,
                    capacity_kwh: parseFloat(batteryCapacity) || 0,
                },
                input_sensors: {
                    ...currentInputSensors,
                    total_load_consumption:
                        baselineType === 'sensor'
                            ? baselineSensor
                            : (currentInputSensors as Record<string, unknown>).total_load_consumption,
                },
                // Merge in any profile-specific suggestions that were applied
                ...profileSuggestions,
            }

            // Note: synthetic baseline logic implementation implies passing the estimated daily kWh
            // to a backend endpoint or setting it as a config attribute. For now we just save the standard config.
            await Api.configSave(updatePayload)

            // Trigger an executor module reload in the backend
            await Api.executor.run()

            onComplete()
        } catch (err) {
            setErrorMsg(err instanceof Error ? err.message : 'Unknown error during save')
            setLoading(false)
        }
    }

    const handleSkip = () => {
        if (
            window.confirm(
                'Are you sure you want to skip? Darkstar cannot optimize your energy without a hardware profile, and you may experience errors.',
            )
        ) {
            onComplete()
        }
    }

    return (
        <div className="fixed inset-0 z-50 flex items-center justify-center bg-canvas/90 backdrop-blur-sm p-4">
            <Card className="w-full max-w-2xl bg-surface border-accent/20 shadow-2xl overflow-hidden p-0 relative">
                <div className="bg-surface2/50 p-6 border-b border-line/10">
                    <h2 className="text-xl font-bold text-text">Welcome to Darkstar</h2>
                    <p className="text-sm text-muted mt-1">Let's set up your system to get the solver running.</p>
                </div>

                <div className="p-6 h-[400px] overflow-y-auto overflow-x-hidden">
                    {step === 0 && (
                        <div className="space-y-4 animate-in fade-in slide-in-from-bottom-4">
                            <h3 className="text-lg font-bold">Step 0: Home Assistant Connection</h3>
                            <p className="text-sm text-muted">
                                {' '}
                                Darkstar integrates tightly with Home Assistant to read sensors and control your
                                hardware.{' '}
                            </p>

                            {isAddon ? (
                                <div className="p-4 bg-accent/10 border border-accent/20 rounded-xl text-sm">
                                    <span className="font-bold">Add-on Detected!</span> Connection is handled
                                    automatically via Supervisor.
                                </div>
                            ) : (
                                <div className="space-y-4">
                                    <div>
                                        <label className="block text-sm font-semibold text-text mb-1">
                                            HA Server URL
                                        </label>
                                        <input
                                            type="text"
                                            className="input"
                                            value={haUrl}
                                            onChange={(e) => setHaUrl(e.target.value)}
                                            placeholder="http://homeassistant.local:8123"
                                        />
                                    </div>
                                    <div>
                                        <label className="block text-sm font-semibold text-text mb-1">
                                            Long-Lived Access Token
                                        </label>
                                        <input
                                            type="password"
                                            className="input"
                                            value={haToken}
                                            onChange={(e) => setHaToken(e.target.value)}
                                            placeholder="eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9..."
                                        />
                                    </div>

                                    <div className="flex items-center gap-3 mt-4">
                                        <button
                                            type="button"
                                            onClick={handleTestConnection}
                                            disabled={!haUrl || !haToken}
                                            className="px-4 py-2 rounded-lg bg-surface2 text-text font-semibold hover:bg-surface transition disabled:opacity-50"
                                        >
                                            {haTestStatus && haTestStatus.startsWith('Testing')
                                                ? 'Testing...'
                                                : 'Test Connection'}
                                        </button>
                                        {haTestStatus && (
                                            <span
                                                className={`text-xs ${haTestStatus.startsWith('Success') ? 'text-good' : 'text-bad'}`}
                                            >
                                                {haTestStatus}
                                            </span>
                                        )}
                                    </div>
                                </div>
                            )}
                        </div>
                    )}

                    {step === 1 && (
                        <div className="space-y-4 animate-in fade-in slide-in-from-bottom-4">
                            <h3 className="text-lg font-bold">Step 1: Hardware Profile</h3>
                            <p className="text-sm text-muted">Select the make of your hybrid inverter.</p>

                            <div className="grid grid-cols-2 gap-4">
                                {['deye', 'fronius', 'victron', 'generic'].map((p) => (
                                    <button
                                        key={p}
                                        onClick={() => setProfile(p)}
                                        className={`p-4 rounded-xl border-2 text-left transition ${
                                            profile === p
                                                ? 'border-accent bg-accent/10'
                                                : 'border-line/20 hover:border-line/40'
                                        }`}
                                    >
                                        <div className="font-bold capitalize">{p}</div>
                                    </button>
                                ))}
                            </div>

                            {profile && (
                                <ProfileSetupHelper
                                    profileName={profile}
                                    currentForm={{}}
                                    onApply={handleProfileApply}
                                />
                            )}
                        </div>
                    )}

                    {step === 2 && (
                        <div className="space-y-4 animate-in fade-in slide-in-from-bottom-4">
                            <h3 className="text-lg font-bold">Step 2: Equipment Specs</h3>
                            <p className="text-sm text-muted">Provide the capabilities of your installation.</p>

                            <div className="space-y-4">
                                <div>
                                    <label className="block text-sm font-semibold text-text mb-1">
                                        Battery Capacity (kWh)
                                    </label>
                                    <input
                                        type="number"
                                        className="input"
                                        value={batteryCapacity}
                                        onChange={(e) => setBatteryCapacity(e.target.value)}
                                        placeholder="e.g. 10.24"
                                    />
                                </div>
                                <div>
                                    <label className="block text-sm font-semibold text-text mb-1">
                                        Total Solar Array Peak (kWp)
                                    </label>
                                    <input
                                        type="number"
                                        className="input"
                                        value={solarArrayKwp}
                                        onChange={(e) => setSolarArrayKwp(e.target.value)}
                                        placeholder="e.g. 5.5"
                                    />
                                </div>
                            </div>
                        </div>
                    )}

                    {step === 3 && (
                        <div className="space-y-4 animate-in fade-in slide-in-from-bottom-4">
                            <h3 className="text-lg font-bold">Step 3: Baseline Consumption</h3>
                            <p className="text-sm text-muted">
                                The solver needs to know your house's base load to plan charging accurately.
                            </p>

                            <div className="flex gap-4 p-1 bg-surface2/50 rounded-lg w-fit">
                                <button
                                    onClick={() => setBaselineType('synthetic')}
                                    className={`px-4 py-2 rounded-md text-sm font-semibold transition ${
                                        baselineType === 'synthetic'
                                            ? 'bg-surface text-text shadow'
                                            : 'text-muted hover:text-text'
                                    }`}
                                >
                                    Synthetic Profile
                                </button>
                                <button
                                    onClick={() => setBaselineType('sensor')}
                                    className={`px-4 py-2 rounded-md text-sm font-semibold transition ${
                                        baselineType === 'sensor'
                                            ? 'bg-surface text-text shadow'
                                            : 'text-muted hover:text-text'
                                    }`}
                                >
                                    Home Assistant Sensor
                                </button>
                            </div>

                            {baselineType === 'synthetic' ? (
                                <div>
                                    <label className="block text-sm font-semibold text-text mb-1">
                                        Estimated Daily Usage - Excl. EV/Water (kWh)
                                    </label>
                                    <input
                                        type="number"
                                        className="input"
                                        value={baselineEstimated}
                                        onChange={(e) => setBaselineEstimated(e.target.value)}
                                        placeholder="e.g. 20"
                                    />
                                    <p className="text-xs text-muted mt-2">
                                        We will generate a realistic dynamic load profile scaled to your daily estimate.
                                    </p>
                                </div>
                            ) : (
                                <div>
                                    <label className="block text-sm font-semibold text-text mb-1">
                                        Total Load Consumption Sensor Entity ID
                                    </label>
                                    <EntitySelect
                                        entities={haEntities}
                                        value={baselineSensor}
                                        onChange={(val: string) => setBaselineSensor(val)}
                                        loading={haLoading}
                                        placeholder="Select entity..."
                                    />
                                    <p className="text-xs text-muted mt-2">
                                        Must be an accumulating energy sensor (kWh). We will fetch the last 7 days of
                                        history to build the baseline.
                                    </p>
                                </div>
                            )}

                            {errorMsg && (
                                <div className="text-sm text-bad bg-bad/10 border border-bad/20 p-3 rounded-lg mt-4">
                                    {errorMsg}
                                </div>
                            )}
                        </div>
                    )}
                </div>

                <div className="bg-surface2/50 p-6 border-t border-line/10 flex justify-between items-center">
                    <div className="flex gap-2 items-center">
                        {step > 1 && (
                            <button
                                className="px-4 py-2 rounded-lg bg-surface2 text-text font-semibold hover:bg-surface transition disabled:opacity-50"
                                onClick={handlePrev}
                                disabled={loading}
                            >
                                Back
                            </button>
                        )}
                        <button
                            className="text-xs text-muted hover:text-text hover:underline transition ml-2"
                            onClick={handleSkip}
                            disabled={loading}
                        >
                            Skip for now
                        </button>
                    </div>

                    <div className="flex gap-2 items-center">
                        <div className="flex gap-1 mr-4">
                            {[1, 2, 3].map((i) => (
                                <div
                                    key={i}
                                    className={`w-2 h-2 rounded-full ${step >= i ? 'bg-accent' : 'bg-line/20'}`}
                                />
                            ))}
                        </div>

                        {step < 3 ? (
                            <button
                                className="px-4 py-2 rounded-lg bg-accent text-[#100f0e] font-bold hover:brightness-110 transition disabled:opacity-50"
                                onClick={handleNext}
                                disabled={
                                    (step === 0 && !isAddon && !haTestStatus?.startsWith('Success')) ||
                                    (step === 1 && !profile) ||
                                    (step === 2 && (!batteryCapacity || !solarArrayKwp))
                                }
                            >
                                Next Step
                            </button>
                        ) : (
                            <button
                                className="px-4 py-2 rounded-lg bg-accent text-[#100f0e] font-bold hover:brightness-110 shadow-lg shadow-accent/20 transition disabled:opacity-50"
                                onClick={handleSave}
                                disabled={
                                    loading ||
                                    (baselineType === 'sensor' && !baselineSensor) ||
                                    (baselineType === 'synthetic' && !baselineEstimated)
                                }
                            >
                                {loading ? 'Saving...' : 'Finish Setup'}
                            </button>
                        )}
                    </div>
                </div>
            </Card>
        </div>
    )
}
