/* eslint-disable react-refresh/only-export-components -- this module owns the onboarding step registry and its components. */
import { useState } from 'react'
import type { ComponentType } from 'react'
import type {
    EntityCandidate,
    HaCoreConfigResponse,
    HaDiscoveryEntity,
    ProfileSuggestionsResponse,
    ReadinessResponse,
    SetupSuggestionsResponse,
} from '../../lib/api'
import type { InverterProfile } from '../../pages/settings/types'
import Select from '../ui/Select'
import Switch from '../ui/Switch'
import { EntityField } from './EntityField'
import {
    configDiff,
    getPath,
    hasFiniteNumber,
    isConfigured,
    isFeatureEnabled,
    settingLabel,
    type WizardConfig,
} from './helpers'

export type StepId =
    'connect' | 'system' | 'pricing' | 'inverter' | 'sensors' | 'solar' | 'battery' | 'water' | 'ev' | 'review'

export type StepProps = {
    config: WizardConfig
    initialConfig: WizardConfig
    update: (path: string, value: unknown) => void
    profiles: InverterProfile[]
    entities: HaDiscoveryEntity[]
    suggestions: SetupSuggestionsResponse | null
    profileSuggestions: ProfileSuggestionsResponse | null
    isAddon: boolean
    connectReady: boolean
    connectionMessage: string | null
    testConnection: (credentials?: { url: string; token: string }) => Promise<boolean>
    readiness: ReadinessResponse | null
    readinessStatus: 'idle' | 'checking' | 'ready' | 'error'
    haCurrencySuggestion?: string | null
    haCoreConfig?: HaCoreConfigResponse | null
    refreshReadiness: () => void
    onFix: (step: StepId) => void
}

export type StepDefinition = {
    id: StepId
    title: string
    appliesWhen: (config: WizardConfig) => boolean
    component: ComponentType<StepProps>
    buildPatch: (config: WizardConfig) => Record<string, unknown>
    isComplete: (config: WizardConfig, profiles: InverterProfile[]) => boolean
}

function patchFor(config: WizardConfig, paths: string[]): Record<string, unknown> {
    const patch: WizardConfig = {} as WizardConfig
    for (const path of paths) {
        const value = getPath(config, path)
        if (value === undefined) continue
        const parts = path.split('.')
        let node: Record<string, unknown> | unknown[] = patch
        for (let index = 0; index < parts.length - 1; index += 1) {
            const part = parts[index]
            const nextIsIndex = /^\d+$/.test(parts[index + 1])
            const current = Array.isArray(node) ? node[Number(part)] : node[part]
            const next = current && typeof current === 'object' ? current : nextIsIndex ? [] : {}
            if (Array.isArray(node)) node[Number(part)] = next
            else node[part] = next
            node = next as Record<string, unknown> | unknown[]
        }
        const last = parts[parts.length - 1]
        if (Array.isArray(node)) node[Number(last)] = value
        else node[last] = value
    }
    return patch
}

function TextField({
    config,
    update,
    path,
    label,
    unit,
    type = 'text',
    min,
    max,
    step,
    required = false,
    autoDetected = false,
}: {
    config: WizardConfig
    update: StepProps['update']
    path: string
    label: string
    unit?: string
    type?: 'text' | 'number'
    min?: number
    max?: number
    step?: number
    required?: boolean
    autoDetected?: boolean
}) {
    const value = getPath(config, path)
    return (
        <label className="block space-y-1.5">
            <span className="block text-sm font-semibold text-text">
                {label} {required && <span className="text-bad">*</span>}
            </span>
            <span className="flex items-center gap-2">
                <input
                    className="input w-full"
                    type={type}
                    value={value === null || value === undefined ? '' : String(value)}
                    min={min}
                    max={max}
                    step={step}
                    required={required}
                    onChange={(event) =>
                        update(
                            path,
                            type === 'number'
                                ? event.target.value === ''
                                    ? ''
                                    : Number(event.target.value)
                                : event.target.value,
                        )
                    }
                />
                {unit && <span className="text-sm text-muted">{unit}</span>}
            </span>
            {autoDetected && <span className="text-xs text-good">Auto-detected from Home Assistant</span>}
        </label>
    )
}

function SelectField({
    config,
    update,
    path,
    label,
    options,
    placeholder,
    required = false,
}: {
    config: WizardConfig
    update: StepProps['update']
    path: string
    label: string
    options: { label: string; value: string }[]
    placeholder?: string
    required?: boolean
}) {
    const value = getPath(config, path)
    return (
        <label className="block space-y-1.5">
            <span className="block text-sm font-semibold text-text">
                {label} {required && <span className="text-bad">*</span>}
            </span>
            <Select
                value={typeof value === 'string' ? value : ''}
                onChange={(next) => update(path, next)}
                options={options}
                placeholder={placeholder ?? 'Choose…'}
                className="w-full"
            />
        </label>
    )
}

function ToggleField({
    config,
    update,
    path,
    label,
}: {
    config: WizardConfig
    update: StepProps['update']
    path: string
    label: string
}) {
    return (
        <label className="flex items-center gap-3 rounded-ds-md border border-line bg-surface p-3 text-sm text-text">
            <span className="flex-1">{label}</span>
            <Switch checked={getPath(config, path) === true} onCheckedChange={(checked) => update(path, checked)} />
        </label>
    )
}

function entityCandidate(props: StepProps, path: string): EntityCandidate | undefined {
    return props.profileSuggestions?.candidates[path]?.[0] ?? props.suggestions?.candidates[path]?.[0]
}

function EntityInput({
    props,
    path,
    label,
    plausibility,
    required,
}: {
    props: StepProps
    path: string
    label: string
    plausibility?: string
    required?: boolean
}) {
    const value = getPath(props.config, path)
    return (
        <EntityField
            label={label}
            value={typeof value === 'string' ? value : ''}
            onChange={(next) => props.update(path, next)}
            entities={props.entities}
            candidate={entityCandidate(props, path)}
            plausibility={plausibility}
            required={required}
        />
    )
}

function ConnectStep(props: StepProps) {
    const [url, setUrl] = useState(String(getPath(props.config, 'home_assistant.url') ?? ''))
    const [token, setToken] = useState('')
    const [busy, setBusy] = useState(false)
    const [message, setMessage] = useState<string | null>(null)
    const runCheck = async () => {
        setBusy(true)
        setMessage(null)
        try {
            const connected = await props.testConnection(props.isAddon ? undefined : { url, token })
            setMessage(connected ? 'Home Assistant connection is ready.' : 'Home Assistant could not be reached.')
        } catch (error) {
            setMessage(error instanceof Error ? error.message : 'Could not test the Home Assistant connection.')
        } finally {
            setBusy(false)
        }
    }
    return (
        <div className="space-y-4">
            <p className="text-sm text-muted">
                Connect Darkstar to Home Assistant so it can discover sensors and read live values.
            </p>
            {props.isAddon ? (
                <div className={props.connectReady ? 'banner banner-success' : 'banner banner-info'} aria-live="polite">
                    {props.connectReady
                        ? 'Home Assistant add-on connection verified.'
                        : (props.connectionMessage ?? 'Checking the Supervisor connection…')}
                </div>
            ) : (
                <div className="space-y-3 rounded-ds-md border border-line bg-surface p-4">
                    <TextField
                        config={{ ...props.config, home_assistant: { url } }}
                        update={(_, value) => setUrl(String(value))}
                        path="home_assistant.url"
                        label="Home Assistant URL"
                        required
                    />
                    <label className="block space-y-1.5">
                        <span className="block text-sm font-semibold text-text">
                            Long-lived access token <span className="text-bad">*</span>
                        </span>
                        <input
                            className="input w-full"
                            type="password"
                            autoComplete="new-password"
                            value={token}
                            onChange={(event) => setToken(event.target.value)}
                        />
                    </label>
                    <button
                        className="btn btn-secondary"
                        type="button"
                        disabled={busy || !url.trim() || !token.trim()}
                        onClick={() => void runCheck()}
                    >
                        {busy ? 'Testing…' : 'Test connection and save'}
                    </button>
                    {(message || props.connectionMessage) && (
                        <p className="text-sm text-muted" role="status">
                            {message ?? props.connectionMessage}
                        </p>
                    )}
                    {props.connectReady && <p className="text-sm text-good">Credentials tested and saved.</p>}
                </div>
            )}
        </div>
    )
}

function SystemStep(props: StepProps) {
    const [phases, setPhases] = useState(3)
    const gridPower = Number(getPath(props.config, 'system.grid.max_power_kw') ?? 0)
    const fuseAmps = Number(getPath(props.config, 'system.grid.main_fuse_a') ?? '')
    const voltage = Number(getPath(props.config, 'system.grid.nominal_voltage_v') ?? 230)
    const suggestedPower =
        Number.isFinite(fuseAmps) && fuseAmps > 0 ? Number(((fuseAmps * phases * voltage) / 1000).toFixed(1)) : 0
    return (
        <div className="space-y-5">
            <div className="grid gap-3 sm:grid-cols-2">
                <ToggleField
                    config={props.config}
                    update={props.update}
                    path="system.has_solar"
                    label="I have solar panels"
                />
                <ToggleField
                    config={props.config}
                    update={props.update}
                    path="system.has_battery"
                    label="I have a home battery"
                />
                <ToggleField
                    config={props.config}
                    update={props.update}
                    path="system.has_water_heater"
                    label="I have a controllable water heater"
                />
                <ToggleField
                    config={props.config}
                    update={props.update}
                    path="system.has_ev_charger"
                    label="I have an EV charger"
                />
            </div>
            <SelectField
                config={props.config}
                update={props.update}
                path="system.grid_meter_type"
                label="Grid meter type"
                required
                options={[
                    { value: 'net', label: 'Net meter (one import/export sensor)' },
                    { value: 'dual', label: 'Dual meter (separate import and export sensors)' },
                ]}
            />
            <TextField
                config={props.config}
                update={props.update}
                path="system.grid.max_power_kw"
                label="Maximum grid import"
                type="number"
                min={0.1}
                step={0.1}
                unit="kW"
                required
            />
            <div className="grid gap-3 sm:grid-cols-[1fr_1fr_auto] sm:items-end">
                <TextField
                    config={props.config}
                    update={props.update}
                    path="system.grid.main_fuse_a"
                    label="Main fuse"
                    type="number"
                    min={1}
                    step={1}
                    unit="A"
                />
                <label className="block space-y-1.5">
                    <span className="block text-sm font-semibold text-text">Number of phases</span>
                    <Select
                        value={String(phases)}
                        onChange={(next) => setPhases(Number(next))}
                        options={[
                            { value: '1', label: '1 phase' },
                            { value: '2', label: '2 phases' },
                            { value: '3', label: '3 phases' },
                        ]}
                        className="w-full"
                    />
                </label>
                <button
                    className="btn btn-secondary"
                    type="button"
                    disabled={suggestedPower <= 0}
                    onClick={() => props.update('system.grid.max_power_kw', suggestedPower)}
                >
                    Use {suggestedPower || '—'} kW
                </button>
            </div>
            <p className="text-xs text-muted">
                Fuse estimate: {suggestedPower || '—'} kW from {Number.isFinite(fuseAmps) ? fuseAmps || '—' : '—'} A ×{' '}
                {phases} × {voltage} V.
            </p>
            <p className="text-xs text-muted">Current grid limit: {gridPower || 'not set'} kW.</p>
        </div>
    )
}

function LocationStep(props: StepProps) {
    const currencyPath = 'nordpool.currency'
    const currentCurrency = getPath(props.config, currencyPath)
    const suggestedCurrency = props.haCurrencySuggestion ?? undefined
    const auto = (path: string, value: unknown) =>
        value !== undefined && value !== null && String(getPath(props.config, path)) === String(value)
    const useHaLocation = () => {
        if (props.haCoreConfig?.latitude !== undefined)
            props.update('system.location.latitude', props.haCoreConfig.latitude)
        if (props.haCoreConfig?.longitude !== undefined)
            props.update('system.location.longitude', props.haCoreConfig.longitude)
    }
    const differingLocation =
        (props.haCoreConfig?.latitude !== undefined &&
            String(getPath(props.config, 'system.location.latitude')) !== String(props.haCoreConfig.latitude)) ||
        (props.haCoreConfig?.longitude !== undefined &&
            String(getPath(props.config, 'system.location.longitude')) !== String(props.haCoreConfig.longitude))
    const differingTimezone = Boolean(
        props.haCoreConfig?.time_zone && getPath(props.config, 'timezone') !== props.haCoreConfig.time_zone,
    )
    return (
        <div className="space-y-5">
            <div className="grid gap-3 sm:grid-cols-2">
                <TextField
                    config={props.config}
                    update={props.update}
                    path="system.location.latitude"
                    label="Latitude"
                    type="number"
                    min={-90}
                    max={90}
                    step={0.0001}
                    required
                    autoDetected={auto('system.location.latitude', props.haCoreConfig?.latitude)}
                />
                <TextField
                    config={props.config}
                    update={props.update}
                    path="system.location.longitude"
                    label="Longitude"
                    type="number"
                    min={-180}
                    max={180}
                    step={0.0001}
                    required
                    autoDetected={auto('system.location.longitude', props.haCoreConfig?.longitude)}
                />
            </div>
            {differingLocation && (
                <p className="text-xs text-muted">
                    Home Assistant reports {props.haCoreConfig?.latitude}, {props.haCoreConfig?.longitude}.{' '}
                    <button className="btn btn-ghost px-2 py-1" type="button" onClick={useHaLocation}>
                        Use suggested
                    </button>
                </p>
            )}
            <TextField
                config={props.config}
                update={props.update}
                path="timezone"
                label="Time zone"
                required
                autoDetected={auto('timezone', props.haCoreConfig?.time_zone)}
            />
            {differingTimezone && (
                <p className="text-xs text-muted">
                    Home Assistant reports {props.haCoreConfig?.time_zone}.{' '}
                    <button
                        className="btn btn-ghost px-2 py-1"
                        type="button"
                        onClick={() => props.update('timezone', props.haCoreConfig?.time_zone)}
                    >
                        Use suggested
                    </button>
                </p>
            )}
            <SelectField
                config={props.config}
                update={props.update}
                path="nordpool.price_area"
                label="Nord Pool price area"
                required
                placeholder="Choose your area from your electricity bill"
                options={[
                    { value: 'SE1', label: 'SE1 — Northern Sweden (Luleå area)' },
                    { value: 'SE2', label: 'SE2 — Northern and central Sweden (Sundsvall area)' },
                    { value: 'SE3', label: 'SE3 — Central Sweden (Stockholm and Gothenburg area)' },
                    { value: 'SE4', label: 'SE4 — Southern Sweden (Malmö area)' },
                ]}
            />
            <p className="text-xs text-muted">
                Price area boundaries follow municipalities; check the area printed on your electricity bill.
            </p>
            <TextField
                config={props.config}
                update={props.update}
                path={currencyPath}
                label="Currency"
                required
                autoDetected={auto(currencyPath, props.haCoreConfig?.currency)}
            />
            {suggestedCurrency && typeof currentCurrency === 'string' && currentCurrency !== suggestedCurrency && (
                <div className="text-xs text-muted">
                    Home Assistant reports {suggestedCurrency}.{' '}
                    <button
                        className="btn btn-ghost px-2 py-1"
                        type="button"
                        onClick={() => props.update(currencyPath, suggestedCurrency)}
                    >
                        Use suggested
                    </button>
                </div>
            )}
            <div className="grid gap-3 sm:grid-cols-3">
                <TextField
                    config={props.config}
                    update={props.update}
                    path="pricing.vat_percent"
                    label="VAT"
                    type="number"
                    min={0}
                    step={0.1}
                    unit="%"
                    required
                />
                <TextField
                    config={props.config}
                    update={props.update}
                    path="pricing.energy_tax_sek"
                    label="Energy tax"
                    type="number"
                    min={0}
                    step={0.001}
                    unit="SEK/kWh"
                    required
                />
                <TextField
                    config={props.config}
                    update={props.update}
                    path="pricing.grid_transfer_fee_sek"
                    label="Grid transfer fee"
                    type="number"
                    min={0}
                    step={0.001}
                    unit="SEK/kWh"
                    required
                />
            </div>
        </div>
    )
}

function InverterStep(props: StepProps) {
    const profileName = String(getPath(props.config, 'system.inverter_profile') ?? '')
    const profile = props.profiles.find((item) => item.name === profileName)
    const suggestedProfile = props.suggestions?.suggested_profile
    const entities = Object.entries(profile?.entities ?? {})
    return (
        <div className="space-y-4">
            <SelectField
                config={props.config}
                update={props.update}
                path="system.inverter_profile"
                label="Inverter profile"
                required
                placeholder="Choose your inverter"
                options={props.profiles.map((item) => ({
                    value: item.name,
                    label: `${item.name} — ${item.description}`,
                }))}
            />
            {suggestedProfile && suggestedProfile !== profileName && (
                <p className="text-xs text-muted">
                    Suggested profile: {suggestedProfile}.{' '}
                    <button
                        className="btn btn-ghost px-2 py-1"
                        type="button"
                        onClick={() => props.update('system.inverter_profile', suggestedProfile)}
                    >
                        Use suggested
                    </button>
                </p>
            )}
            {profile && (
                <p className="text-xs text-muted">{profile.supported_brands.join(', ') || profile.description}</p>
            )}
            {entities.length > 0 && (
                <div className="space-y-4 rounded-ds-md border border-line bg-surface p-4">
                    <h3 className="text-sm font-bold text-text">Required inverter entities</h3>
                    {entities.map(([key, definition]) => {
                        const path =
                            Object.keys(props.profileSuggestions?.candidates ?? {}).find((candidatePath) => {
                                const pathParts = candidatePath.split('.')
                                return pathParts[pathParts.length - 1] === key
                            }) ?? `executor.inverter.${key}`
                        return (
                            <EntityInput
                                key={key}
                                props={props}
                                path={path}
                                label={definition.description || key.replace(/_/g, ' ')}
                                required={definition.required}
                            />
                        )
                    })}
                </div>
            )}
        </div>
    )
}

const ROLE_LABELS: Record<string, string> = {
    load_power: 'House load power',
    grid_power: 'Grid power',
    grid_import_power: 'Grid import power',
    grid_export_power: 'Grid export power',
    battery_soc: 'Battery state of charge',
    battery_power: 'Battery power',
    pv_power: 'Solar power',
}

function CoreSensorsStep(props: StepProps) {
    const meter =
        getPath(props.config, 'system.grid_meter_type') === 'dual'
            ? ['grid_import_power', 'grid_export_power']
            : ['grid_power']
    const roles = ['load_power', ...meter]
    if (isFeatureEnabled(props.config, 'has_battery')) roles.push('battery_soc', 'battery_power')
    if (isFeatureEnabled(props.config, 'has_solar')) roles.push('pv_power')
    return (
        <div className="space-y-4">
            <p className="text-xs text-muted">
                High-confidence matches are preselected; other matches need your approval. Instantaneous power sensors
                report W or kW and state of charge reports %.
            </p>
            {roles.map((role) => {
                const path = `input_sensors.${role}`
                return (
                    <EntityInput
                        key={role}
                        props={props}
                        path={path}
                        label={ROLE_LABELS[role] ?? role}
                        required={['load_power', ...meter].includes(role) || role === 'battery_soc'}
                        plausibility={
                            role === 'battery_soc'
                                ? 'State of charge should be between 0 and 100%.'
                                : 'Power sensors should report W or kW.'
                        }
                    />
                )
            })}
            <div className="space-y-3 rounded-ds-md border border-line bg-surface p-4">
                <h3 className="text-sm font-bold text-text">Load baseline (optional)</h3>
                <TextField
                    config={props.config}
                    update={props.update}
                    path="input_sensors.synthetic_daily_load_kwh"
                    label="Estimated daily use"
                    type="number"
                    min={1}
                    step={1}
                    unit="kWh/day"
                />
                <p className="text-xs text-muted">
                    Used for the load forecast only when the house load power sensor has no usable history yet.
                </p>
            </div>
        </div>
    )
}

function SolarStep(props: StepProps) {
    const arrays = (getPath(props.config, 'system.solar_arrays') as Record<string, unknown>[] | undefined) ?? []
    const list = arrays.length ? arrays : [{ name: 'Main array', kwp: '', tilt: 30, azimuth: 180 }]
    const updateArray = (index: number, key: string, value: unknown) =>
        props.update(`system.solar_arrays.${index}.${key}`, value)
    return (
        <div className="space-y-4">
            {list.map((array, index) => (
                <div key={index} className="grid gap-3 rounded-ds-md border border-line bg-surface p-4 sm:grid-cols-2">
                    <label className="block space-y-1.5">
                        <span className="text-sm font-semibold">Array name</span>
                        <input
                            className="input w-full"
                            value={String(array.name ?? '')}
                            onChange={(event) => updateArray(index, 'name', event.target.value)}
                        />
                    </label>
                    <label className="block space-y-1.5">
                        <span className="text-sm font-semibold">Peak power</span>
                        <input
                            className="input w-full"
                            type="number"
                            min="0.1"
                            step="0.1"
                            value={String(array.kwp ?? '')}
                            onChange={(event) => updateArray(index, 'kwp', Number(event.target.value) || '')}
                        />{' '}
                        <span className="text-xs text-muted">kWp</span>
                    </label>
                    <label className="block space-y-1.5">
                        <span className="text-sm font-semibold">Tilt</span>
                        <input
                            className="input w-full"
                            type="number"
                            min="0"
                            max="90"
                            value={String(array.tilt ?? '')}
                            onChange={(event) => updateArray(index, 'tilt', Number(event.target.value))}
                        />{' '}
                        <span className="text-xs text-muted">degrees from horizontal</span>
                    </label>
                    <label className="block space-y-1.5">
                        <span className="text-sm font-semibold">Azimuth</span>
                        <Select
                            value={String(array.azimuth ?? 180)}
                            onChange={(next) => updateArray(index, 'azimuth', Number(next))}
                            options={[
                                { value: 0, label: 'North' },
                                { value: 45, label: 'North east' },
                                { value: 90, label: 'East' },
                                { value: 135, label: 'South east' },
                                { value: 180, label: 'South' },
                                { value: 225, label: 'South west' },
                                { value: 270, label: 'West' },
                                { value: 315, label: 'North west' },
                            ].map((option) => ({ value: String(option.value), label: option.label }))}
                            className="w-full"
                        />
                    </label>
                    {list.length > 1 && (
                        <button
                            className="btn btn-ghost sm:col-span-2"
                            type="button"
                            onClick={() =>
                                props.update(
                                    'system.solar_arrays',
                                    list.filter((_, itemIndex) => itemIndex !== index),
                                )
                            }
                        >
                            Remove array
                        </button>
                    )}
                </div>
            ))}
            <button
                className="btn btn-secondary"
                type="button"
                onClick={() =>
                    props.update('system.solar_arrays', [
                        ...list,
                        { name: `Array ${list.length + 1}`, kwp: '', tilt: 30, azimuth: 180 },
                    ])
                }
            >
                Add solar array
            </button>
        </div>
    )
}

function BatteryStep(props: StepProps) {
    const profile = props.profiles.find((item) => item.name === getPath(props.config, 'system.inverter_profile'))
    const requiresVoltage = profile?.behavior.control_unit === 'A'
    return (
        <div className="grid gap-4 sm:grid-cols-2">
            <TextField
                config={props.config}
                update={props.update}
                path="battery.capacity_kwh"
                label="Battery capacity"
                type="number"
                min={0.1}
                step={0.1}
                unit="kWh"
                required
            />
            <TextField
                config={props.config}
                update={props.update}
                path="battery.min_soc_percent"
                label="Minimum state of charge"
                type="number"
                min={0}
                max={100}
                unit="%"
                required
            />
            <TextField
                config={props.config}
                update={props.update}
                path="battery.max_soc_percent"
                label="Maximum state of charge"
                type="number"
                min={1}
                max={100}
                unit="%"
                required
            />
            <TextField
                config={props.config}
                update={props.update}
                path="battery.max_charge_w"
                label="Maximum charge power"
                type="number"
                min={1}
                step={100}
                unit="W"
                required
            />
            <TextField
                config={props.config}
                update={props.update}
                path="battery.max_discharge_w"
                label="Maximum discharge power"
                type="number"
                min={1}
                step={100}
                unit="W"
                required
            />
            {requiresVoltage && (
                <TextField
                    config={props.config}
                    update={props.update}
                    path="battery.nominal_voltage_v"
                    label="Nominal battery voltage"
                    type="number"
                    min={1}
                    unit="V"
                    required
                />
            )}
            <p className="text-xs text-muted sm:col-span-2">
                Charge and discharge power are required in watts. Check the inverter or battery specifications.
            </p>
        </div>
    )
}

function WaterStep(props: StepProps) {
    const itemPath = 'water_heaters.0'
    const type = getPath(props.config, `${itemPath}.type`) === 'modulating' ? 'modulating' : 'binary'
    return (
        <div className="space-y-4">
            <div className="grid gap-3 sm:grid-cols-2">
                <TextField
                    config={props.config}
                    update={props.update}
                    path={`${itemPath}.name`}
                    label="Heater name"
                    required
                />
                <TextField
                    config={props.config}
                    update={props.update}
                    path={`${itemPath}.power_kw`}
                    label="Rated power"
                    type="number"
                    min={0.1}
                    step={0.1}
                    unit="kW"
                    required
                />
            </div>
            <SelectField
                config={props.config}
                update={props.update}
                path={`${itemPath}.type`}
                label="Control type"
                required
                options={[
                    { value: 'binary', label: 'On/off' },
                    { value: 'modulating', label: 'Modulating' },
                ]}
            />
            <EntityInput props={props} path={`${itemPath}.target_entity`} label="Control entity" required />
            <EntityInput props={props} path={`${itemPath}.sensor`} label="Power sensor" />
            <ToggleField
                config={props.config}
                update={props.update}
                path={`${itemPath}.enabled`}
                label="Enable this heater"
            />
            <p className="text-xs text-muted">
                {type === 'binary' ? 'Darkstar switches the heater on and off.' : 'Darkstar adjusts the heater output.'}
            </p>
        </div>
    )
}

function EvStep(props: StepProps) {
    const itemPath = 'ev_chargers.0'
    const type = getPath(props.config, `${itemPath}.type`) === 'current' ? 'current' : 'binary'
    return (
        <div className="space-y-4">
            <div className="grid gap-3 sm:grid-cols-2">
                <TextField
                    config={props.config}
                    update={props.update}
                    path={`${itemPath}.name`}
                    label="Charger name"
                    required
                />
                <SelectField
                    config={props.config}
                    update={props.update}
                    path={`${itemPath}.type`}
                    label="Control type"
                    required
                    options={[
                        { value: 'binary', label: 'On/off' },
                        { value: 'current', label: 'Adjustable current' },
                    ]}
                />
                <TextField
                    config={props.config}
                    update={props.update}
                    path={`${itemPath}.battery_capacity_kwh`}
                    label="Vehicle battery capacity"
                    type="number"
                    min={1}
                    step={1}
                    unit="kWh"
                    required
                />
                {type === 'binary' ? (
                    <TextField
                        config={props.config}
                        update={props.update}
                        path={`${itemPath}.rated_power_kw`}
                        label="Charger rated power"
                        type="number"
                        min={0.1}
                        step={0.1}
                        unit="kW"
                        required
                    />
                ) : (
                    <>
                        <TextField
                            config={props.config}
                            update={props.update}
                            path={`${itemPath}.min_current_a`}
                            label="Minimum current"
                            type="number"
                            min={1}
                            step={1}
                            unit="A"
                            required
                        />
                        <TextField
                            config={props.config}
                            update={props.update}
                            path={`${itemPath}.max_current_a`}
                            label="Maximum current"
                            type="number"
                            min={1}
                            step={1}
                            unit="A"
                            required
                        />
                        <label className="block space-y-1.5">
                            <span className="block text-sm font-semibold">Phases</span>
                            <Select
                                value={String(
                                    Array.isArray(getPath(props.config, `${itemPath}.phases`))
                                        ? (getPath(props.config, `${itemPath}.phases`) as number[]).length
                                        : 3,
                                )}
                                onChange={(next) =>
                                    props.update(
                                        `${itemPath}.phases`,
                                        Array.from({ length: Number(next) }, (_, index) => index + 1),
                                    )
                                }
                                options={[
                                    { value: '1', label: '1 phase' },
                                    { value: '2', label: '2 phases' },
                                    { value: '3', label: '3 phases' },
                                ]}
                                className="w-full"
                            />
                        </label>
                    </>
                )}
            </div>
            <ToggleField
                config={props.config}
                update={props.update}
                path={`${itemPath}.enabled`}
                label="Enable this charger"
            />
            <EntityInput props={props} path={`${itemPath}.switch_entity`} label="Enable/disable control" required />
            {type === 'current' && (
                <EntityInput
                    props={props}
                    path={`${itemPath}.current_entity`}
                    label="Current setpoint control"
                    required
                />
            )}
            <EntityInput props={props} path={`${itemPath}.sensor`} label="Charger power sensor" />
            <EntityInput
                props={props}
                path={`${itemPath}.soc_sensor`}
                label="Vehicle state of charge"
                required
                plausibility="State of charge should be between 0 and 100%."
            />
            <EntityInput props={props} path={`${itemPath}.plug_sensor`} label="Plug status sensor" required />
        </div>
    )
}

function ReviewStep(props: StepProps) {
    const diffs = configDiff(props.initialConfig, props.config)
    const existingLiveMode = getPath(props.config, 'executor.shadow_mode') === false
    const refresh = () => {
        props.refreshReadiness()
    }
    const fixStep = (path: string): StepId => {
        if (path.startsWith('home_assistant')) return 'connect'
        if (
            path.includes('price') ||
            path.includes('location') ||
            path.startsWith('pricing') ||
            path.startsWith('nordpool')
        )
            return 'pricing'
        if (path.startsWith('input_sensors')) return 'sensors'
        if (path.startsWith('battery')) return 'battery'
        if (path.startsWith('water_heaters')) return 'water'
        if (path.startsWith('ev_chargers')) return 'ev'
        if (path.includes('solar')) return 'solar'
        if (path.startsWith('system.inverter_profile') || path.startsWith('executor.inverter')) return 'inverter'
        return 'system'
    }
    return (
        <div className="space-y-5">
            <section className="space-y-2">
                <div className="flex items-center justify-between">
                    <h3 className="text-sm font-bold text-text">Changes in this setup</h3>
                    <span className="text-xs text-muted">{diffs.length} changed</span>
                </div>
                {diffs.length === 0 ? (
                    <p className="text-sm text-muted">No values changed in this session.</p>
                ) : (
                    <div className="max-h-52 overflow-y-auto rounded-ds-md border border-line">
                        {diffs.map((item) => (
                            <div
                                className="grid grid-cols-[minmax(0,1fr)_minmax(0,2fr)] gap-3 border-b border-line p-2 text-xs last:border-b-0"
                                key={item.path}
                            >
                                <span className="truncate text-muted" title={item.path}>
                                    {settingLabel(item.path)}
                                </span>
                                <span className="flex min-w-0 items-start gap-2">
                                    <span className="break-all text-muted">{String(item.before ?? 'not set')}</span>
                                    <span aria-hidden="true">→</span>
                                    <span className="break-all text-text">{String(item.after ?? 'not set')}</span>
                                </span>
                            </div>
                        ))}
                    </div>
                )}
            </section>
            <div className="rounded-ds-md border border-line bg-surface p-3 text-sm" role="status">
                Current executor mode: <strong>{existingLiveMode ? 'Live' : 'Shadow'}</strong>
                {existingLiveMode
                    ? ' — finishing setup will keep control enabled.'
                    : ' — Darkstar will plan without controlling hardware.'}
            </div>
            <section className="space-y-2">
                <div className="flex items-center justify-between">
                    <h3 className="text-sm font-bold text-text">Readiness checks</h3>
                    <button
                        type="button"
                        className="btn btn-ghost px-2 py-1"
                        onClick={refresh}
                        disabled={props.readinessStatus === 'checking'}
                    >
                        {props.readinessStatus === 'checking' ? 'Checking…' : 'Refresh'}
                    </button>
                </div>
                {props.readinessStatus === 'checking' || (props.readinessStatus === 'idle' && !props.readiness) ? (
                    <div
                        className="flex items-center gap-3 rounded-ds-md border border-line bg-surface p-4"
                        role="status"
                    >
                        <div className="spinner" aria-label="Checking readiness" />
                        <span className="text-sm text-muted">Checking readiness… Results will appear together.</span>
                    </div>
                ) : props.readinessStatus === 'error' ? (
                    <div className="banner banner-warning" role="status">
                        Readiness checks could not be completed. Refresh to try again; you can still finish setup.
                    </div>
                ) : props.readiness ? (
                    <div className="space-y-2">
                        <>
                            <p className="text-xs text-muted" role="status">
                                {props.readiness.checks.filter((check) => check.status === 'pass').length}/
                                {props.readiness.checks.length} checks passed ·{' '}
                                {props.readiness.checks.filter((check) => check.status === 'warn').length} warnings ·{' '}
                                {props.readiness.checks.filter((check) => check.status === 'fail').length} failures ·{' '}
                                {props.readiness.checks.filter((check) => check.status === 'skipped').length} skipped
                            </p>
                            {props.readiness.checks.map((check) => (
                                <div
                                    key={check.id}
                                    className="flex flex-wrap items-center justify-between gap-2 rounded-ds-md border border-line bg-surface p-3"
                                >
                                    <div className="min-w-[60%]">
                                        <div className="flex items-center gap-2">
                                            <span
                                                className={`badge ${check.status === 'pass' ? 'badge-good' : check.status === 'warn' ? 'badge-warn' : check.status === 'fail' ? 'badge-bad' : 'badge-muted'}`}
                                            >
                                                {check.status}
                                            </span>
                                            <span className="text-sm font-medium text-text">{check.message}</span>
                                        </div>
                                        {(check.status === 'fail' || check.status === 'warn') && check.fix_hint && (
                                            <p className="mt-1 text-xs text-muted">{check.fix_hint}</p>
                                        )}
                                    </div>
                                    {check.status === 'fail' && (
                                        <button
                                            className="btn btn-ghost px-2 py-1"
                                            type="button"
                                            onClick={() => props.onFix(fixStep(check.settings_path))}
                                        >
                                            Fix
                                        </button>
                                    )}
                                </div>
                            ))}
                        </>
                    </div>
                ) : (
                    <div className="banner banner-info">No readiness checks were returned. Refresh to try again.</div>
                )}
                {props.readiness?.checks.some((check) => check.status === 'fail') && (
                    <div className="banner banner-warning">
                        Some checks failed. You can finish setup, but Darkstar will not work until those issues are
                        resolved.
                    </div>
                )}
            </section>
        </div>
    )
}

const systemPaths = [
    'system.has_solar',
    'system.has_battery',
    'system.has_water_heater',
    'system.has_ev_charger',
    'system.grid_meter_type',
    'system.grid.max_power_kw',
    'system.grid.main_fuse_a',
]
const pricingPaths = [
    'system.location.latitude',
    'system.location.longitude',
    'timezone',
    'nordpool.price_area',
    'nordpool.currency',
    'pricing.vat_percent',
    'pricing.energy_tax_sek',
    'pricing.grid_transfer_fee_sek',
]
const commonSensorPaths = [
    'input_sensors.load_power',
    'input_sensors.grid_power',
    'input_sensors.grid_import_power',
    'input_sensors.grid_export_power',
    'input_sensors.battery_soc',
    'input_sensors.battery_power',
    'input_sensors.pv_power',
    'input_sensors.synthetic_daily_load_kwh',
]
export const steps: StepDefinition[] = [
    {
        id: 'connect',
        title: 'Connect',
        appliesWhen: () => true,
        component: ConnectStep,
        buildPatch: () => ({}),
        isComplete: () => true,
    },
    {
        id: 'system',
        title: 'My system',
        appliesWhen: () => true,
        component: SystemStep,
        buildPatch: (config) => patchFor(config, systemPaths),
        isComplete: (config) =>
            ['net', 'dual'].includes(String(getPath(config, 'system.grid_meter_type'))) &&
            Number(getPath(config, 'system.grid.max_power_kw')) > 0,
    },
    {
        id: 'pricing',
        title: 'Location & pricing',
        appliesWhen: () => true,
        component: LocationStep,
        buildPatch: (config) => patchFor(config, pricingPaths),
        isComplete: (config) =>
            ['SE1', 'SE2', 'SE3', 'SE4'].includes(String(getPath(config, 'nordpool.price_area'))) &&
            hasFiniteNumber(getPath(config, 'system.location.latitude')) &&
            hasFiniteNumber(getPath(config, 'system.location.longitude')) &&
            Boolean(getPath(config, 'timezone')) &&
            Boolean(getPath(config, 'nordpool.currency')),
    },
    {
        id: 'inverter',
        title: 'Inverter',
        appliesWhen: () => true,
        component: InverterStep,
        buildPatch: (config) => ({
            system: { inverter_profile: getPath(config, 'system.inverter_profile') },
            executor: getPath(config, 'executor'),
        }),
        isComplete: (config, profiles) =>
            Boolean(getPath(config, 'system.inverter_profile')) &&
            profiles.some((profile) => profile.name === getPath(config, 'system.inverter_profile')),
    },
    {
        id: 'sensors',
        title: 'Core sensors',
        appliesWhen: () => true,
        component: CoreSensorsStep,
        buildPatch: (config) => patchFor(config, commonSensorPaths),
        isComplete: (config) =>
            isConfigured(getPath(config, 'input_sensors.load_power')) &&
            isConfigured(
                getPath(
                    config,
                    getPath(config, 'system.grid_meter_type') === 'dual'
                        ? 'input_sensors.grid_import_power'
                        : 'input_sensors.grid_power',
                ),
            ) &&
            (!isFeatureEnabled(config, 'has_battery') || isConfigured(getPath(config, 'input_sensors.battery_soc'))),
    },
    {
        id: 'solar',
        title: 'Solar',
        appliesWhen: (config) => isFeatureEnabled(config, 'has_solar'),
        component: SolarStep,
        buildPatch: (config) => ({ system: { solar_arrays: getPath(config, 'system.solar_arrays') } }),
        isComplete: (config) =>
            Array.isArray(getPath(config, 'system.solar_arrays')) &&
            (getPath(config, 'system.solar_arrays') as Record<string, unknown>[]).length > 0 &&
            (getPath(config, 'system.solar_arrays') as Record<string, unknown>[]).every(
                (item) =>
                    Number(item.kwp) > 0 && Boolean(item.name) && Number(item.tilt) >= 0 && Number(item.azimuth) >= 0,
            ),
    },
    {
        id: 'battery',
        title: 'Battery',
        appliesWhen: (config) => isFeatureEnabled(config, 'has_battery'),
        component: BatteryStep,
        buildPatch: (config) =>
            patchFor(config, [
                'battery.capacity_kwh',
                'battery.min_soc_percent',
                'battery.max_soc_percent',
                'battery.max_charge_w',
                'battery.max_discharge_w',
                'battery.nominal_voltage_v',
            ]),
        isComplete: (config, profiles) =>
            hasFiniteNumber(getPath(config, 'battery.capacity_kwh')) &&
            Number(getPath(config, 'battery.capacity_kwh')) > 0 &&
            hasFiniteNumber(getPath(config, 'battery.min_soc_percent')) &&
            Number(getPath(config, 'battery.min_soc_percent')) >= 0 &&
            Number(getPath(config, 'battery.min_soc_percent')) <= 100 &&
            hasFiniteNumber(getPath(config, 'battery.max_soc_percent')) &&
            Number(getPath(config, 'battery.max_soc_percent')) > 0 &&
            Number(getPath(config, 'battery.max_soc_percent')) <= 100 &&
            Number(getPath(config, 'battery.max_charge_w')) > 0 &&
            Number(getPath(config, 'battery.max_discharge_w')) > 0 &&
            (profiles.find((profile) => profile.name === getPath(config, 'system.inverter_profile'))?.behavior
                .control_unit !== 'A' ||
                Number(getPath(config, 'battery.nominal_voltage_v')) > 0),
    },
    {
        id: 'water',
        title: 'Water heater',
        appliesWhen: (config) => isFeatureEnabled(config, 'has_water_heater'),
        component: WaterStep,
        buildPatch: (config) => {
            const waterHeaters = getPath(config, 'water_heaters')
            return waterHeaters === undefined ? {} : { water_heaters: waterHeaters }
        },
        isComplete: (config) =>
            getPath(config, 'water_heaters.0.enabled') === true &&
            Boolean(getPath(config, 'water_heaters.0.name')) &&
            Number(getPath(config, 'water_heaters.0.power_kw')) > 0 &&
            Boolean(getPath(config, 'water_heaters.0.target_entity')),
    },
    {
        id: 'ev',
        title: 'EV',
        appliesWhen: (config) => isFeatureEnabled(config, 'has_ev_charger'),
        component: EvStep,
        buildPatch: (config) => {
            const chargers = getPath(config, 'ev_chargers')
            return chargers === undefined ? {} : { ev_chargers: chargers }
        },
        isComplete: (config) =>
            getPath(config, 'ev_chargers.0.enabled') === true &&
            Boolean(getPath(config, 'ev_chargers.0.name')) &&
            Boolean(getPath(config, 'ev_chargers.0.switch_entity')) &&
            Boolean(getPath(config, 'ev_chargers.0.soc_sensor')) &&
            Boolean(getPath(config, 'ev_chargers.0.plug_sensor')) &&
            (getPath(config, 'ev_chargers.0.type') === 'current'
                ? Boolean(getPath(config, 'ev_chargers.0.current_entity')) &&
                  Number(getPath(config, 'ev_chargers.0.max_current_a')) > 0 &&
                  Number(
                      Array.isArray(getPath(config, 'ev_chargers.0.phases'))
                          ? (getPath(config, 'ev_chargers.0.phases') as number[]).length
                          : 0,
                  ) > 0
                : Number(getPath(config, 'ev_chargers.0.rated_power_kw')) > 0),
    },
    {
        id: 'review',
        title: 'Review & readiness',
        appliesWhen: () => true,
        component: ReviewStep,
        buildPatch: () => ({}),
        isComplete: () => true,
    },
]

export function applicableSteps(config: WizardConfig): StepDefinition[] {
    return steps.filter((step) => step.appliesWhen(config))
}

export function getStep(stepId: StepId): StepDefinition | undefined {
    return steps.find((step) => step.id === stepId)
}
