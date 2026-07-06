export type FieldType =
    | 'number'
    | 'text'
    | 'boolean'
    | 'entity'
    | 'service'
    | 'select'
    | 'array'
    | 'azimuth'
    | 'tilt'
    | 'solar_arrays'
    | 'penalty_levels'
    | 'entity_array'
    | 'balanced_loads'
    | 'charger_priority'
    | 'info'

export interface HaEntity {
    entity_id: string
    friendly_name: string
    domain: string
    unit_of_measurement?: string
    device_class?: string
}

export interface BaseField {
    key: string
    label: string
    helper?: string
    path: string[]
    type: FieldType
    options?: { label: string; value: string }[]
    companionKey?: string
    disabled?: boolean
    notImplemented?: boolean
    required?: boolean
    /** Conditional visibility based on a single config key */
    showIf?: {
        configKey: string // e.g., 'system.has_water_heater'
        value?: string | boolean | number | (string | boolean | number)[] // expected value(s)
        disabledText?: string // overlay text when disabled
    }
    /** All config keys must be truthy for field to be enabled */
    showIfAll?: string[]
    /** Any config key must be truthy for field to be enabled */
    showIfAny?: string[]
    /** Flags this field as hidden unless Advanced Mode is enabled */
    isAdvanced?: boolean
    /** Subsection grouping within a card */
    subsection?: string
    /** Custom CSS classes for the field wrapper (e.g., col-span-2) */
    className?: string
    /** For entity_array type: specifies which entity type to manage */
    entityType?: 'water_heater' | 'ev_charger'
}

export interface InverterProfile {
    name: string
    description: string
    supported_brands: string[]
    version: string
    schema_version: number
    entities: Record<
        string,
        {
            default_entity: string | null
            domain: string
            category: 'system' | 'battery'
            description: string
            required: boolean
        }
    >
    modes: Record<
        string,
        {
            description: string
            action_count: number
        }
    >
    behavior: {
        control_unit: 'A' | 'W' | null
        min_charge_a?: number
        min_charge_w?: number
        round_step_a?: number
        round_step_w?: number
        write_threshold_w?: number
        mode_settling_ms?: number
    }
}

export interface SettingsSection<T extends BaseField = BaseField> {
    title: string
    description: string
    isHA?: boolean
    fields: T[]
    /** Section-level conditional visibility */
    showIf?: {
        configKey: string
        value?: string | boolean | number | (string | boolean | number)[]
    }
}

export const systemSections: SettingsSection[] = [
    {
        title: 'System Profile',
        description: 'Core hardware toggles.',
        fields: [
            {
                key: 'system.inverter_profile',
                label: 'Inverter Profile',
                path: ['system', 'inverter_profile'],
                type: 'select',
                options: [
                    { label: 'Generic (Standard)', value: 'generic' },
                    { label: 'Deye / SunSynk', value: 'deye' },
                    { label: 'Fronius', value: 'fronius' },
                    { label: 'Victron', value: 'victron' },
                ],
                helper: 'Select your inverter brand. Note: Only Deye/SunSynk is fully supported. Others are experimental.',
            },
            {
                key: 'system.has_solar',
                label: 'Solar panels installed',
                path: ['system', 'has_solar'],
                type: 'boolean',
                subsection: 'Hardware Features',
            },
            {
                key: 'system.has_battery',
                label: 'Home battery installed',
                path: ['system', 'has_battery'],
                type: 'boolean',
                subsection: 'Hardware Features',
            },
            {
                key: 'system.has_water_heater',
                label: 'Smart water heater',
                path: ['system', 'has_water_heater'],
                type: 'boolean',
                subsection: 'Hardware Features',
            },
            {
                key: 'system.has_ev_charger',
                label: 'EV charger installed',
                path: ['system', 'has_ev_charger'],
                type: 'boolean',
                subsection: 'Hardware Features',
            },
            {
                key: 'executor.inverter.control_unit',
                label: 'Control Unit',
                path: ['executor', 'inverter', 'control_unit'],
                type: 'select',
                options: [
                    { label: 'Amperes (A)', value: 'A' },
                    { label: 'Watts (W)', value: 'W' },
                ],
                helper: 'Unit used for inverter control commands.',
                required: true,
            },

            {
                key: 'system.grid_meter_type',
                label: 'Grid Meter Type',
                path: ['system', 'grid_meter_type'],
                type: 'select',
                options: [
                    { label: 'Net Meter (Single Sensor)', value: 'net' },
                    { label: 'Dual Meter (Separate Import/Export)', value: 'dual' },
                ],
                helper: 'Select "Net" if you have one sensor (+/-). Select "Dual" if you have separate import/export sensors.',
            },
            {
                key: 'system.grid.max_power_kw',
                label: 'Grid Max Power (kW)',
                helper: 'HARD limit from your grid fuse. The planner will never exceed this.',
                path: ['system', 'grid', 'max_power_kw'],
                type: 'number',
            },
            {
                key: 'system.inverter.max_ac_power_kw',
                label: 'Inverter Max AC Power (kW)',
                helper: 'Maximum AC power your inverter can produce.',
                path: ['system', 'inverter', 'max_ac_power_kw'],
                type: 'number',
            },
            {
                key: 'system.inverter.max_dc_input_kw',
                label: 'Inverter Max DC Input (kW)',
                helper: 'Maximum DC power from PV strings.',
                path: ['system', 'inverter', 'max_dc_input_kw'],
                type: 'number',
            },
            {
                key: 'export.enable_export',
                label: 'Enable grid export',
                path: ['export', 'enable_export'],
                type: 'boolean',
                helper: 'If disabled, the planner will enforce zero export to the grid.',
            },
        ],
    },
    {
        title: 'Pricing & Timezone',
        description: 'Nordpool zone and local timezone for planner calculations.',
        fields: [
            {
                key: 'nordpool.price_area',
                label: 'Nordpool Price Area',
                helper: 'e.g. SE4, NO1, DK2',
                path: ['nordpool', 'price_area'],
                type: 'text',
            },
            { key: 'pricing.vat_percent', label: 'VAT (%)', path: ['pricing', 'vat_percent'], type: 'number' },
            {
                key: 'pricing.grid_transfer_fee_sek',
                label: 'Grid transfer fee (SEK/kWh)',
                helper: 'Fee paid to your grid operator for power delivery.',
                path: ['pricing', 'grid_transfer_fee_sek'],
                type: 'number',
            },
            {
                key: 'pricing.energy_tax_sek',
                label: 'Energy tax (SEK/kWh)',
                path: ['pricing', 'energy_tax_sek'],
                type: 'number',
            },
            {
                key: 'pricing.subscription_fee_sek_per_month',
                label: 'Monthly subscription fee (SEK)',
                helper: 'Fixed monthly grid connection fee.',
                path: ['pricing', 'subscription_fee_sek_per_month'],
                type: 'number',
            },
            { key: 'timezone', label: 'Timezone', path: ['timezone'], type: 'text' },
        ],
    },
    {
        title: '── Home Assistant Connection ──',
        isHA: true,
        description: 'Connection parameters for your Home Assistant instance.',
        fields: [
            {
                key: 'home_assistant.url',
                label: 'HA URL',
                helper: 'e.g. http://homeassistant.local:8123',
                path: ['home_assistant', 'url'],
                type: 'text',
            },
            {
                key: 'home_assistant.token',
                label: 'Long-Lived Access Token',
                path: ['home_assistant', 'token'],
                type: 'text',
            },
        ],
    },
    {
        title: 'Required HA Input Sensors',
        isHA: true,
        description: 'Core sensors Darkstar reads from Home Assistant.',
        fields: [
            {
                key: 'input_sensors.load_power',
                label: 'Load Power (W/kW)',
                path: ['input_sensors', 'load_power'],
                type: 'entity',
                helper: 'Used by executor for system state and Aurora training.',
            },
            {
                key: 'input_sensors.grid_power',
                label: 'Grid Power (W/kW)',
                path: ['input_sensors', 'grid_power'],
                type: 'entity',
                helper: 'Net grid power (+=import, -=export). Required for net metering.',
                showIf: {
                    configKey: 'system.grid_meter_type',
                    value: 'net',
                },
            },
            {
                key: 'input_sensors.grid_import_power',
                label: 'Grid Import Power (W/kW)',
                path: ['input_sensors', 'grid_import_power'],
                type: 'entity',
                helper: 'Grid import power sensor. Required for dual metering.',
                showIf: {
                    configKey: 'system.grid_meter_type',
                    value: 'dual',
                },
            },
            {
                key: 'input_sensors.grid_export_power',
                label: 'Grid Export Power (W/kW)',
                path: ['input_sensors', 'grid_export_power'],
                type: 'entity',
                helper: 'Grid export power sensor. Required for dual metering.',
                showIf: {
                    configKey: 'system.grid_meter_type',
                    value: 'dual',
                },
            },
        ],
    },
    {
        title: '── Lifetime Energy Totals ──',
        isHA: true,
        description: 'Cumulative lifetime energy sensors for forecasting accuracy.',
        fields: [
            {
                key: 'input_sensors.total_load_consumption',
                label: 'Total Load Consumption (kWh)',
                path: ['input_sensors', 'total_load_consumption'],
                type: 'entity',
                helper: 'Lifetime total load consumption. Required for forecasting accuracy.',
                required: true,
            },
            {
                key: 'input_sensors.total_grid_import',
                label: 'Total Grid Import (kWh)',
                path: ['input_sensors', 'total_grid_import'],
                type: 'entity',
                helper: 'Lifetime total grid import. Required for energy accounting.',
                required: true,
            },
            {
                key: 'input_sensors.total_grid_export',
                label: 'Total Grid Export (kWh)',
                path: ['input_sensors', 'total_grid_export'],
                type: 'entity',
                helper: 'Lifetime total grid export. Required for energy accounting.',
                required: true,
                showIf: {
                    configKey: 'export.enable_export',
                    disabledText: 'Enable "Grid Export" in System Profile to configure',
                },
            },
        ],
    },
    {
        title: 'Required HA Control Entities',
        isHA: true,
        description: 'Entities Darkstar writes to for control.',
        fields: [
            {
                key: 'executor.inverter.max_charge_current',
                label: 'Max Charge Current',
                path: ['executor', 'inverter', 'max_charge_current'],
                type: 'entity',
                helper: 'Darkstar sets charge rate in Amps.',
                showIf: {
                    configKey: 'executor.inverter.control_unit',
                    value: 'A',
                },
            },
            {
                key: 'executor.inverter.max_charge_power',
                label: 'Max Charge Power',
                path: ['executor', 'inverter', 'max_charge_power'],
                type: 'entity',
                helper: 'Darkstar sets charge rate in Watts.',
                showIf: {
                    configKey: 'executor.inverter.control_unit',
                    value: 'W',
                },
            },
            {
                key: 'executor.inverter.max_discharge_current',
                label: 'Max Discharge Current',
                path: ['executor', 'inverter', 'max_discharge_current'],
                type: 'entity',
                helper: 'Darkstar sets discharge rate in Amps.',
                showIf: {
                    configKey: 'executor.inverter.control_unit',
                    value: 'A',
                },
            },
            {
                key: 'executor.inverter.max_discharge_power',
                label: 'Max Discharge Power',
                path: ['executor', 'inverter', 'max_discharge_power'],
                type: 'entity',
                helper: 'Darkstar sets discharge rate in Watts.',
                showIf: {
                    configKey: 'executor.inverter.control_unit',
                    value: 'W',
                },
            },
            {
                key: 'executor.inverter.grid_max_export_power',
                label: 'Max Grid Export (W)',
                helper: 'HA Number entity to control grid export limit in Watts.',
                path: ['executor', 'inverter', 'grid_max_export_power'],
                type: 'entity',
                showIf: {
                    configKey: 'export.enable_export',
                    disabledText: 'Enable "Grid Export" in System Profile to configure',
                },
            },
            {
                key: 'executor.inverter.grid_max_export_power_switch',
                label: 'Max Grid Export Switch',
                helper: 'HA Switch entity to enable/disable grid export limit.',
                path: ['executor', 'inverter', 'grid_max_export_power_switch'],
                type: 'entity',
                showIf: {
                    configKey: 'export.enable_export',
                    disabledText: 'Enable "Grid Export" in System Profile to configure',
                },
            },
            {
                key: 'executor.inverter.work_mode',
                label: 'Work Mode Selector',
                path: ['executor', 'inverter', 'work_mode'],
                type: 'entity',
                helper: 'Darkstar sets inverter operating mode (Export/Zero-Export/etc.).',
            },
            {
                key: 'executor.inverter.soc_target',
                label: 'SoC Target',
                path: ['executor', 'inverter', 'soc_target'],
                type: 'entity',
                helper: 'Darkstar sets battery state of charge target percentage.',
            },
            {
                key: 'executor.inverter.grid_charging_enable',
                label: 'Grid Charging Switch',
                path: ['executor', 'inverter', 'grid_charging_enable'],
                type: 'entity',
                helper: 'Darkstar enables/disables grid charging.',
                showIf: {
                    configKey: 'system.inverter_profile',
                    value: ['generic', 'deye'],
                },
            },
            {
                key: 'executor.inverter.minimum_reserve',
                label: 'Minimum Reserve',
                path: ['executor', 'inverter', 'minimum_reserve'],
                type: 'entity',
                helper: 'Darkstar sets minimum battery reserve (Fronius-specific).',
                showIf: {
                    configKey: 'system.inverter_profile',
                    value: 'fronius',
                },
            },
            {
                key: 'executor.inverter.grid_charge_power',
                label: 'Grid Charge Power',
                path: ['executor', 'inverter', 'grid_charge_power'],
                type: 'entity',
                helper: 'Darkstar sets grid charging power in Watts (Fronius-specific).',
                showIf: {
                    configKey: 'system.inverter_profile',
                    value: 'fronius',
                },
            },
        ],
    },
    {
        title: 'Optional HA Input Sensors',
        isHA: true,
        description: 'Optional sensors for monitoring, Smart Home integration, and statistics.',
        fields: [
            // Power Flow & Dashboard
            {
                key: 'input_sensors.grid_power',
                label: 'Net Grid Power (W/kW)',
                helper: 'Positive = import, negative = export. Required for Net Meter mode.',
                path: ['input_sensors', 'grid_power'],
                type: 'entity',
                companionKey: 'input_sensors.grid_power_inverted',
                subsection: 'Power Flow & Dashboard',
                showIf: {
                    configKey: 'system.grid_meter_type',
                    value: 'net',
                    disabledText: 'Enable "Net Meter" in System Profile to configure',
                },
            },
            {
                key: 'input_sensors.grid_import_power',
                label: 'Grid Import Power (W/kW)',
                helper: 'Required for Dual Meter mode.',
                path: ['input_sensors', 'grid_import_power'],
                type: 'entity',
                subsection: 'Power Flow & Dashboard',
                showIf: {
                    configKey: 'system.grid_meter_type',
                    value: 'dual',
                    disabledText: 'Enable "Dual Meter" in System Profile to configure',
                },
            },
            {
                key: 'input_sensors.grid_export_power',
                label: 'Grid Export Power (W/kW)',
                helper: 'Required for Dual Meter mode.',
                path: ['input_sensors', 'grid_export_power'],
                type: 'entity',
                subsection: 'Power Flow & Dashboard',
                showIf: {
                    configKey: 'export.enable_export',
                    disabledText: 'Enable "Grid Export" in System Profile to configure',
                },
            },

            // Smart Home Integration
            {
                key: 'input_sensors.vacation_mode',
                label: 'Vacation Mode Toggle',
                path: ['input_sensors', 'vacation_mode'],
                type: 'entity',
                helper: 'Reduces water heating quota when active.',
                subsection: 'Smart Home Integration',
            },
            {
                key: 'input_sensors.alarm_state',
                label: 'Alarm Control Panel',
                path: ['input_sensors', 'alarm_state'],
                type: 'entity',
                helper: 'Enables emergency reserve boost when armed.',
                subsection: 'Smart Home Integration',
            },

            // User Override Toggles (READS)
            {
                key: 'executor.automation_toggle_entity',
                label: 'Automation Toggle',
                path: ['executor', 'automation_toggle_entity'],
                type: 'entity',
                helper: 'When OFF, executor skips all inverter actions.',
                subsection: 'User Override Toggles',
            },
            {
                key: 'executor.manual_override_entity',
                label: 'Manual Override Toggle',
                path: ['executor', 'manual_override_entity'],
                type: 'entity',
                helper: 'Triggers manual override mode in executor.',
                subsection: 'User Override Toggles',
            },
        ],
    },
]

export const parameterSections: SettingsSection[] = [
    {
        title: 'Forecasting & Strategy',

        description: 'Tuning the AI forecasting engine and safety margins.',
        fields: [
            {
                key: 'forecasting.pv_confidence_percent',
                label: 'PV Confidence (%)',
                helper: '100 = trust forecast fully. Lower values make the planner more conservative with solar.',
                path: ['forecasting', 'pv_confidence_percent'],
                type: 'number',
                isAdvanced: true,
            },
            {
                key: 'forecasting.load_safety_margin_percent',
                label: 'Load Safety Margin (%)',
                helper: '100 = neutral. >100 = expect more load than predicted (safer).',
                path: ['forecasting', 'load_safety_margin_percent'],
                type: 'number',
                isAdvanced: true,
            },
        ],
    },
    {
        title: 'Arbitrage & Economics',
        description: 'Export thresholds, peak-only export, and degradation costs.',
        fields: [
            {
                key: 'kepler.curtailment_penalty_sek',
                label: 'Curtailment Penalty (SEK)',
                helper: 'Penalty for wasting available solar power when battery is not full (higher = more aggressive charging).',
                path: ['kepler', 'curtailment_penalty_sek'],
                type: 'number',
                subsection: 'Advanced Tuning',
                isAdvanced: true,
            },
            {
                key: 'kepler.ramping_cost_sek_per_kw',
                label: 'Ramping Cost (SEK/kW)',
                helper: 'Penalty for rapid battery power changes (higher = smoother power flow, reduces "sawtooth" behavior).',
                path: ['kepler', 'ramping_cost_sek_per_kw'],
                type: 'number',
                subsection: 'Advanced Tuning',
                isAdvanced: true,
            },
        ],
    },
    {
        title: 'Learning Parameter Limits',
        description: 'Limits that keep learning adjustments conservative.',
        fields: [
            {
                key: 'learning.min_sample_threshold',
                label: 'Min sample threshold',
                path: ['learning', 'min_sample_threshold'],
                type: 'number',
                isAdvanced: true,
            },
            {
                key: 'learning.min_improvement_threshold',
                label: 'Min improvement (%)',
                path: ['learning', 'min_improvement_threshold'],
                type: 'number',
                isAdvanced: true,
            },
            {
                key: 'learning.max_daily_param_change.battery_use_margin_sek',
                label: 'Battery margin change (SEK)',
                path: ['learning', 'max_daily_param_change', 'battery_use_margin_sek'],
                type: 'number',
                isAdvanced: true,
            },
            {
                key: 'learning.max_daily_param_change.export_profit_margin_sek',
                label: 'Export margin change (SEK)',
                path: ['learning', 'max_daily_param_change', 'export_profit_margin_sek'],
                type: 'number',
                isAdvanced: true,
            },
            {
                key: 'learning.max_daily_param_change.future_price_guard_buffer_sek',
                label: 'Future guard buffer change (SEK)',
                path: ['learning', 'max_daily_param_change', 'future_price_guard_buffer_sek'],
                type: 'number',
                isAdvanced: true,
            },
            {
                key: 'learning.max_daily_param_change.load_safety_margin_percent',
                label: 'Load safety change (%)',
                path: ['learning', 'max_daily_param_change', 'load_safety_margin_percent'],
                type: 'number',
                isAdvanced: true,
            },
            {
                key: 'learning.max_daily_param_change.pv_confidence_percent',
                label: 'PV confidence change (%)',
                path: ['learning', 'max_daily_param_change', 'pv_confidence_percent'],
                type: 'number',
                isAdvanced: true,
            },
            {
                key: 'learning.max_daily_param_change.s_index_base_factor',
                label: 'S-index base change',
                path: ['learning', 'max_daily_param_change', 's_index_base_factor'],
                type: 'number',
                isAdvanced: true,
            },
            {
                key: 'learning.max_daily_param_change.s_index_pv_deficit_weight',
                label: 'S-index PV weight change',
                path: ['learning', 'max_daily_param_change', 's_index_pv_deficit_weight'],
                type: 'number',
                isAdvanced: true,
            },
            {
                key: 'learning.max_daily_param_change.s_index_temp_weight',
                label: 'S-index temp weight change',
                path: ['learning', 'max_daily_param_change', 's_index_temp_weight'],
                type: 'number',
                isAdvanced: true,
            },
        ],
    },
    {
        title: 'S-Index Safety',
        description: 'Seasonal index parameters for reserve calculations.',
        fields: [
            {
                key: 's_index.temp_cold_c',
                label: 'Cold temp (°C)',
                path: ['s_index', 'temp_cold_c'],
                type: 'number',
                isAdvanced: true,
            },
            {
                key: 's_index.s_index_horizon_days',
                label: 'S-Index Horizon (days)',
                path: ['s_index', 's_index_horizon_days'],
                type: 'select',
                isAdvanced: true,
                options: [
                    { label: '1 Day', value: '1' },
                    { label: '2 Days', value: '2' },
                    { label: '3 Days', value: '3' },
                    { label: '4 Days', value: '4' },
                    { label: '5 Days', value: '5' },
                    { label: '6 Days', value: '6' },
                    { label: '7 Days', value: '7' },
                ],
            },
        ],
    },
]

export const uiSections: SettingsSection[] = [
    {
        title: 'Notifications',
        description: 'Configure automated notifications via Home Assistant.',
        fields: [
            {
                key: 'executor.notifications.service',
                label: 'HA Notify Service',
                helper: 'e.g. notify.mobile_app_iphone',
                path: ['executor', 'notifications', 'service'],
                type: 'service',
            },
            {
                key: 'executor.notifications.on_charge_start',
                label: 'On charge start',
                path: ['executor', 'notifications', 'on_charge_start'],
                type: 'boolean',
            },
            {
                key: 'executor.notifications.on_charge_stop',
                label: 'On charge stop',
                path: ['executor', 'notifications', 'on_charge_stop'],
                type: 'boolean',
            },
            {
                key: 'executor.notifications.on_export_start',
                label: 'On export start',
                path: ['executor', 'notifications', 'on_export_start'],
                type: 'boolean',
            },
            {
                key: 'executor.notifications.on_export_stop',
                label: 'On export stop',
                path: ['executor', 'notifications', 'on_export_stop'],
                type: 'boolean',
            },
            {
                key: 'executor.notifications.on_water_heat_start',
                label: 'On water heating start',
                path: ['executor', 'notifications', 'on_water_heat_start'],
                type: 'boolean',
            },
            {
                key: 'executor.notifications.on_water_heat_stop',
                label: 'On water heating stop',
                path: ['executor', 'notifications', 'on_water_heat_stop'],
                type: 'boolean',
            },
            {
                key: 'executor.notifications.on_soc_target_change',
                label: 'On SoC target change',
                path: ['executor', 'notifications', 'on_soc_target_change'],
                type: 'boolean',
            },
            {
                key: 'executor.notifications.on_override_activated',
                label: 'On override activated',
                path: ['executor', 'notifications', 'on_override_activated'],
                type: 'boolean',
            },
            {
                key: 'executor.notifications.on_error',
                label: 'On error',
                path: ['executor', 'notifications', 'on_error'],
                type: 'boolean',
            },
        ],
    },
    {
        title: 'Dashboard Defaults',
        description: 'Overlay defaults and refresh cadence for the planner dashboard.',
        fields: [
            {
                key: 'dashboard.auto_refresh_enabled',
                label: 'Auto refresh',
                helper: 'Enable automatic refresh of the dashboard schedule.',
                path: ['dashboard', 'auto_refresh_enabled'],
                type: 'boolean',
            },
        ],
    },
    {
        title: 'AI Advisor',
        description: 'Control the Smart Advisor LLM settings.',
        fields: [
            {
                key: 'advisor.enable_llm',
                label: 'Enable LLM advice',
                path: ['advisor', 'enable_llm'],
                type: 'boolean',
            },
            {
                key: 'advisor.auto_fetch',
                label: 'Auto-fetch advice on dashboard load',
                path: ['advisor', 'auto_fetch'],
                type: 'boolean',
            },
            {
                key: 'advisor.personality',
                label: 'Advisor personality',
                path: ['advisor', 'personality'],
                type: 'select',
                options: [
                    { label: 'Concise (Money focus)', value: 'concise' },
                    { label: 'Friendly (Emoji style)', value: 'friendly' },
                    { label: 'Technical (Data heavy)', value: 'technical' },
                ],
            },
        ],
    },
]

// UI20: Device-centric tab sections
export const solarSections: SettingsSection[] = [
    {
        title: 'Location',
        description: 'Geographic coordinates for the forecasting engine.',
        fields: [
            {
                key: 'system.location.latitude',
                label: 'Latitude',
                helper: 'Decimal degrees, positive north. Example: 55.4932',
                path: ['system', 'location', 'latitude'],
                type: 'number',
            },
            {
                key: 'system.location.longitude',
                label: 'Longitude',
                helper: 'Decimal degrees, positive east. Example: 13.1112',
                path: ['system', 'location', 'longitude'],
                type: 'number',
            },
        ],
    },
    {
        title: 'Solar Arrays',
        description: 'Configure up to 6 solar arrays with different orientations.',
        fields: [
            {
                key: 'system.solar_arrays',
                label: 'Solar Arrays',
                path: ['system', 'solar_arrays'],
                type: 'solar_arrays',
                helper: 'Configure up to 6 solar arrays with different orientations.',
            },
        ],
    },
    {
        title: 'HA Input Sensors',
        description: 'Solar-related Home Assistant sensors.',
        isHA: true,
        fields: [
            {
                key: 'input_sensors.pv_power',
                label: 'PV Power (W/kW)',
                path: ['input_sensors', 'pv_power'],
                type: 'entity',
                helper: 'Used by executor for PV dump detection and recorder for history.',
            },
        ],
    },
    {
        title: '── Lifetime Energy Totals ──',
        isHA: true,
        description: 'Cumulative lifetime solar production for forecasting accuracy.',
        fields: [
            {
                key: 'input_sensors.total_pv_production',
                label: 'Total PV Production (kWh)',
                path: ['input_sensors', 'total_pv_production'],
                type: 'entity',
                helper: 'Lifetime total solar production. Required for forecasting accuracy.',
                required: true,
            },
        ],
    },
]

export const batterySections: SettingsSection[] = [
    {
        title: 'Specifications',
        description: 'Capacity, max power, and SoC limits define safe operating bands.',
        fields: [
            {
                key: 'battery.capacity_kwh',
                label: 'Battery capacity (kWh)',
                helper: 'Total usable capacity of your battery bank.',
                path: ['battery', 'capacity_kwh'],
                type: 'number',
            },
            {
                key: 'battery.max_charge_a',
                label: 'Max charge current (A)',
                helper: 'Maximum charging current allowed from grid.',
                path: ['battery', 'max_charge_a'],
                type: 'number',
                showIf: {
                    configKey: 'executor.inverter.control_unit',
                    value: 'A',
                },
            },
            {
                key: 'battery.max_charge_w',
                label: 'Max charge power (W)',
                helper: 'Maximum charging power allowed from grid.',
                path: ['battery', 'max_charge_w'],
                type: 'number',
                showIf: {
                    configKey: 'executor.inverter.control_unit',
                    value: 'W',
                },
            },
            {
                key: 'battery.max_discharge_a',
                label: 'Max discharge current (A)',
                helper: 'Maximum discharge current for load following.',
                path: ['battery', 'max_discharge_a'],
                type: 'number',
                showIf: {
                    configKey: 'executor.inverter.control_unit',
                    value: 'A',
                },
            },
            {
                key: 'battery.max_discharge_w',
                label: 'Max discharge power (W)',
                helper: 'Maximum discharge power for load following.',
                path: ['battery', 'max_discharge_w'],
                type: 'number',
                showIf: {
                    configKey: 'executor.inverter.control_unit',
                    value: 'W',
                },
            },
            {
                key: 'battery.nominal_voltage_v',
                label: 'Nominal Voltage (V)',
                helper: 'Used for Ampere-to-kW calculations in the Planner.',
                path: ['battery', 'nominal_voltage_v'],
                type: 'number',
                showIf: {
                    configKey: 'executor.inverter.control_unit',
                    value: 'A',
                },
            },
            {
                key: 'battery.min_voltage_v',
                label: 'Worst-case Voltage (V)',
                helper: 'Min safe voltage used by Executor for amperage safety.',
                path: ['battery', 'min_voltage_v'],
                type: 'number',
                showIf: {
                    configKey: 'executor.inverter.control_unit',
                    value: 'A',
                },
            },
            {
                key: 'battery.min_soc_percent',
                label: 'Min SoC (%)',
                path: ['battery', 'min_soc_percent'],
                type: 'number',
            },
            {
                key: 'battery.max_soc_percent',
                label: 'Max SoC (%)',
                path: ['battery', 'max_soc_percent'],
                type: 'number',
            },
            {
                key: 'executor.override.low_soc_export_floor',
                label: 'Export Prevention Floor (%)',
                helper: 'Minimum SoC to allow battery export. Prevents discharging to grid when battery is low.',
                path: ['executor', 'override', 'low_soc_export_floor'],
                type: 'number',
            },
            {
                key: 'battery_economics.battery_cycle_cost_kwh',
                label: 'Battery cycle cost (SEK/kWh)',
                helper: 'Estimated degradation cost for every kWh cycled. Affects arbitrage profitability.',
                path: ['battery_economics', 'battery_cycle_cost_kwh'],
                type: 'number',
            },
        ],
    },
    {
        title: 'HA Sensors',
        description: 'Home Assistant sensors for battery monitoring.',
        fields: [
            {
                key: 'input_sensors.battery_soc',
                label: 'Battery SoC (%)',
                path: ['input_sensors', 'battery_soc'],
                type: 'entity',
                helper: 'Core sensor. Required for planner SoC targeting.',
                required: true,
            },
            {
                key: 'input_sensors.battery_power',
                label: 'Battery Power (W/kW)',
                helper: 'Positive = charging, negative = discharging',
                path: ['input_sensors', 'battery_power'],
                type: 'entity',
                companionKey: 'input_sensors.battery_power_inverted',
            },
        ],
    },
    {
        title: '── Lifetime Energy Totals ──',
        isHA: true,
        description: 'Cumulative lifetime battery energy for forecasting accuracy.',
        fields: [
            {
                key: 'input_sensors.total_battery_charge',
                label: 'Total Battery Charge (kWh)',
                path: ['input_sensors', 'total_battery_charge'],
                type: 'entity',
                helper: 'Lifetime total battery charge. Required for forecasting accuracy.',
                required: true,
            },
            {
                key: 'input_sensors.total_battery_discharge',
                label: 'Total Battery Discharge (kWh)',
                path: ['input_sensors', 'total_battery_discharge'],
                type: 'entity',
                helper: 'Lifetime total battery discharge. Required for forecasting accuracy.',
                required: true,
            },
        ],
    },
    {
        title: 'HA Control Entities',
        description: 'Home Assistant entities for battery control.',
        isHA: true,
        fields: [],
    },
]

export const evSections: SettingsSection[] = [
    {
        title: 'EV Chargers',
        description: 'Configure multiple EV chargers for optimization and load disaggregation.',
        fields: [
            {
                key: 'ev_chargers',
                label: 'EV Chargers',
                path: ['ev_chargers'],
                type: 'entity_array',
                entityType: 'ev_charger',
                className: 'col-span-2',
                helper: 'Add and configure EV chargers for optimization. Each charger needs a unique ID, name, power rating, and sensor.',
            },
        ],
    },
]

export const waterSections: SettingsSection[] = [
    {
        title: 'Water Heaters',
        description: 'Configure multiple water heaters for optimization and load disaggregation.',
        fields: [
            {
                key: 'water_heaters',
                label: 'Water Heaters',
                path: ['water_heaters'],
                type: 'entity_array',
                entityType: 'water_heater',
                className: 'col-span-2',
                helper: 'Add and configure water heaters for optimization. Each heater needs a unique ID, name, power rating, and sensor.',
            },
        ],
    },
    {
        title: 'Scheduling',
        description: 'Quota, deferral, and sizing controls for the water heater scheduler.',
        fields: [
            {
                key: 'water_heating.defer_up_to_hours',
                label: 'Max defer hours',
                path: ['water_heating', 'defer_up_to_hours'],
                type: 'number',
                isAdvanced: true,
            },
            {
                key: 'water_heating.enable_top_ups',
                label: 'Enable spaced top-ups',
                path: ['water_heating', 'enable_top_ups'],
                type: 'boolean',
                helper: 'Enable small top-up heating blocks to maintain temperature. Disable for bulk heating only.',
            },
        ],
    },
    {
        title: 'Temperatures',
        description: 'Temperature setpoints for different operating modes.',
        fields: [
            {
                key: 'executor.water_heater.temp_off',
                label: 'Temp: Off/Idle (°C)',
                helper: 'Target temperature when not heating (legionella safety min).',
                path: ['executor', 'water_heater', 'temp_off'],
                type: 'number',
            },
            {
                key: 'executor.water_heater.temp_normal',
                label: 'Temp: Normal (°C)',
                helper: 'Target temperature for regular scheduled heating.',
                path: ['executor', 'water_heater', 'temp_normal'],
                type: 'number',
            },
            {
                key: 'executor.water_heater.temp_boost',
                label: 'Temp: Boost (°C)',
                helper: 'Target temperature for manual boost / spa mode.',
                path: ['executor', 'water_heater', 'temp_boost'],
                type: 'number',
            },
            {
                key: 'executor.water_heater.temp_max',
                label: 'Temp: Max/PV Dump (°C)',
                helper: 'Max safe temperature for dumping excess solar PV.',
                path: ['executor', 'water_heater', 'temp_max'],
                type: 'number',
            },
        ],
    },
    {
        title: 'Vacation Mode',
        description: 'Anti-legionella safety cycle when vacation mode is active.',
        fields: [
            {
                key: 'water_heating.vacation_mode.enabled',
                label: 'Enable Vacation Mode',
                path: ['water_heating', 'vacation_mode', 'enabled'],
                type: 'boolean',
            },
            {
                key: 'water_heating.vacation_mode.anti_legionella_temp_c',
                label: 'Safety Cycle Temp (°C)',
                path: ['water_heating', 'vacation_mode', 'anti_legionella_temp_c'],
                type: 'number',
            },
            {
                key: 'water_heating.vacation_mode.anti_legionella_interval_days',
                label: 'Safety Cycle Interval (days)',
                path: ['water_heating', 'vacation_mode', 'anti_legionella_interval_days'],
                type: 'number',
            },
            {
                key: 'water_heating.vacation_mode.anti_legionella_duration_hours',
                label: 'Safety Cycle Duration (hours)',
                path: ['water_heating', 'vacation_mode', 'anti_legionella_duration_hours'],
                type: 'number',
            },
        ],
    },
]

export const loadBalancingSections: SettingsSection[] = [
    {
        title: 'Real-Time Load Balancing',
        description:
            'Protects your main fuse in real time by throttling EV charging — and, as a last resort, shedding other loads — based on live per-phase grid current. Stays completely inactive until the fuse rating, all three phase sensors, and at least one balanced load are configured below. This is a best-effort software control loop, not a certified protection device — if your charger has its own load-management/fallback setting, keep that configured too.',
        fields: [
            {
                key: 'load_balancing.enabled',
                label: 'Enable load balancing',
                path: ['load_balancing', 'enabled'],
                type: 'boolean',
                helper: 'Master switch. No-op until the fuse rating, phase sensors, and at least one balanced load are set.',
            },
            {
                key: 'system.grid.main_fuse_a',
                label: 'Main fuse rating (A)',
                path: ['system', 'grid', 'main_fuse_a'],
                type: 'number',
                helper: 'Per-phase physical fuse rating in amps (e.g. 20). Independent of the total grid import limit — a balanced total can still overload a single phase.',
            },
            {
                key: 'input_sensors.grid_current_l1',
                label: 'Grid Current/Power sensor — L1',
                path: ['input_sensors', 'grid_current_l1'],
                type: 'entity',
                helper: 'Home Assistant sensor reporting phase L1 current (A) or power (W/kW) at the grid connection point — the kind is auto-detected from the entity’s unit.',
            },
            {
                key: 'input_sensors.grid_current_l2',
                label: 'Grid Current/Power sensor — L2',
                path: ['input_sensors', 'grid_current_l2'],
                type: 'entity',
                helper: 'Home Assistant sensor reporting phase L2 current (A) or power (W/kW) at the grid connection point — the kind is auto-detected from the entity’s unit.',
            },
            {
                key: 'input_sensors.grid_current_l3',
                label: 'Grid Current/Power sensor — L3',
                path: ['input_sensors', 'grid_current_l3'],
                type: 'entity',
                helper: 'Home Assistant sensor reporting phase L3 current (A) or power (W/kW) at the grid connection point — the kind is auto-detected from the entity’s unit.',
            },
            {
                key: 'input_sensors.grid_voltage_l1',
                label: 'Grid voltage sensor — L1',
                path: ['input_sensors', 'grid_voltage_l1'],
                type: 'entity',
                showIf: { configKey: '_computed.any_phase_power_mode', value: true },
                helper: 'Optional. Used to convert L1 to current when it’s a power sensor. Falls back to the nominal voltage below if left blank.',
            },
            {
                key: 'input_sensors.grid_voltage_l2',
                label: 'Grid voltage sensor — L2',
                path: ['input_sensors', 'grid_voltage_l2'],
                type: 'entity',
                showIf: { configKey: '_computed.any_phase_power_mode', value: true },
                helper: 'Optional. Used to convert L2 to current when it’s a power sensor. Falls back to the nominal voltage below if left blank.',
            },
            {
                key: 'input_sensors.grid_voltage_l3',
                label: 'Grid voltage sensor — L3',
                path: ['input_sensors', 'grid_voltage_l3'],
                type: 'entity',
                showIf: { configKey: '_computed.any_phase_power_mode', value: true },
                helper: 'Optional. Used to convert L3 to current when it’s a power sensor. Falls back to the nominal voltage below if left blank.',
            },
            {
                key: 'load_balancing.nominal_voltage_v',
                label: 'Nominal voltage (V)',
                path: ['load_balancing', 'nominal_voltage_v'],
                type: 'number',
                showIf: { configKey: '_computed.any_phase_power_mode', value: true },
                helper: 'Fallback voltage for converting a power sensor to current when that phase has no voltage sensor set above. Deliberately biased below 230V so a fixed value never under-reports current during a sag.',
            },
        ],
    },
    {
        title: 'Dynamically Throttled Chargers',
        description:
            'Every EV charger configured with a variable-current setpoint (type: current, set in the EV tab) is always in this group and throttled continuously in real time — it never needs to be added manually. When several such chargers share an overloaded phase, priority decides the order: the charger with the lowest number is reduced toward its floor first, fully, before the next one is touched at all.',
        fields: [
            {
                key: 'load_balancing.charger_priority',
                label: 'Charger priority',
                path: ['load_balancing', 'charger_priority'],
                type: 'charger_priority',
                className: 'col-span-2',
            },
        ],
    },
    {
        title: 'Shed as Last Resort',
        description:
            "Loads the balancer can shed as a last resort, once every dynamically throttled charger above is already at its floor or paused. Phase assignment must match your home's actual wiring — the balancer can only protect a phase it knows a load sits on.",
        fields: [
            {
                key: 'load_balancing.loads',
                label: 'Balanced loads',
                path: ['load_balancing', 'loads'],
                type: 'balanced_loads',
                className: 'col-span-2',
            },
        ],
    },
    {
        title: 'Anti-Flap Tuning',
        description:
            'Advanced timing parameters controlling how cautiously the balancer resumes or ramps back up after throttling.',
        fields: [
            {
                key: 'load_balancing.resume_delay_s',
                label: 'Resume delay (seconds)',
                path: ['load_balancing', 'resume_delay_s'],
                type: 'number',
                isAdvanced: true,
                helper: 'How long headroom must stay healthy before resuming a throttled/shed load.',
            },
            {
                key: 'load_balancing.resume_margin_percent',
                label: 'Resume margin (%)',
                path: ['load_balancing', 'resume_margin_percent'],
                type: 'number',
                isAdvanced: true,
                helper: 'Only resume/increase current when phase current is below this % of the fuse rating.',
            },
            {
                key: 'load_balancing.increase_step_a',
                label: 'Ramp-up step (A per tick)',
                path: ['load_balancing', 'increase_step_a'],
                type: 'number',
                isAdvanced: true,
            },
            {
                key: 'load_balancing.sensor_stale_after_s',
                label: 'Sensor stale after (seconds)',
                path: ['load_balancing', 'sensor_stale_after_s'],
                type: 'number',
                isAdvanced: true,
                helper: 'Phase sensors older than this are treated as stale: EV is forced to its minimum current, then paused if it stays stale.',
            },
        ],
    },
]

export const advancedSections: SettingsSection[] = [
    {
        title: 'Experimental Features',
        description: 'Toggle advanced and experimental modes.',
        fields: [
            {
                key: 'executor.interval_seconds',
                label: 'Executor Interval',
                helper: 'How often the executor runs to update inverter settings. Lower = faster response, higher = less resource usage.',
                path: ['executor', 'interval_seconds'],
                type: 'select',
                options: [
                    { label: '5 seconds', value: '5' },
                    { label: '10 seconds', value: '10' },
                    { label: '15 seconds', value: '15' },
                    { label: '20 seconds', value: '20' },
                    { label: '30 seconds', value: '30' },
                    { label: '1 minute', value: '60' },
                    { label: '2.5 minutes', value: '150' },
                    { label: '5 minutes', value: '300' },
                    { label: '10 minutes', value: '600' },
                ],
            },
            {
                key: 'automation.schedule.every_minutes',
                label: 'Planner Interval',
                helper: 'How often to regenerate the optimal schedule. Lower = faster SoC adaptation, higher = less CPU usage.',
                path: ['automation', 'schedule', 'every_minutes'],
                type: 'select',
                options: [
                    { label: '15 minutes', value: '15' },
                    { label: '30 minutes', value: '30' },
                    { label: '60 minutes', value: '60' },
                    { label: '90 minutes', value: '90' },
                ],
            },
            {
                key: 'automation.enable_scheduler',
                label: 'Enable Background Scheduler',
                helper: 'Master toggle for automatic schedule regeneration.',
                path: ['automation', 'enable_scheduler'],
                type: 'boolean',
            },

            {
                key: 'learning.reflex_enabled',
                label: 'Enable Reflex Loop',
                helper: 'Real-time parameter adjustment loop.',
                path: ['learning', 'reflex_enabled'],
                type: 'boolean',
            },
            {
                key: 's_index.mode',
                label: 'S-Index Mode',
                helper: 'Switch between probabilistic risk and dynamic balancing.',
                path: ['s_index', 'mode'],
                type: 'select',
                options: [
                    { label: 'Probabilistic (P10/P90)', value: 'probabilistic' },
                    { label: 'Dynamic (Adaptive)', value: 'dynamic' },
                ],
                showIf: {
                    configKey: 'system.has_battery',
                    value: true,
                    disabledText: "Enable 'Home battery installed' in System Profile to configure",
                },
            },
            {
                key: 'price_forecast.enabled',
                label: 'Enable Price Forecasting',
                helper: 'Use ML-based spot price forecasts for D+1 through D+7. Requires sufficient training data.',
                path: ['price_forecast', 'enabled'],
                type: 'boolean',
            },
        ],
    },
    {
        title: 'Inverter Logic',
        description: 'Custom command strings for your inverter work modes.',
        showIf: {
            configKey: 'system.inverter_profile',
            value: 'generic',
        },
        fields: [
            {
                key: 'executor.inverter.work_mode_export',
                label: 'Export Mode String',
                helper: 'The exact value your inverter select entity expects for Export mode.',
                path: ['executor', 'inverter', 'work_mode_export'],
                type: 'text',
                showIf: {
                    configKey: 'system.inverter_profile',
                    value: 'generic',
                },
            },
            {
                key: 'executor.inverter.work_mode_zero_export',
                label: 'Zero-Export Mode String',
                helper: 'The exact value your inverter select entity expects for Zero-Export mode.',
                path: ['executor', 'inverter', 'work_mode_zero_export'],
                type: 'text',
                showIf: {
                    configKey: 'system.inverter_profile',
                    value: 'generic',
                },
            },
        ],
    },
    {
        title: 'Excess PV Dispatch',
        description:
            'Configure how forecast excess PV energy is utilized. The planner schedules excess PV into the chosen sink.',
        showIf: { configKey: 'system.has_solar', value: true },
        fields: [
            {
                key: 'executor.excess_pv.sink',
                label: 'Excess PV Sink',
                path: ['executor', 'excess_pv', 'sink'],
                type: 'select',
                options: [
                    { label: 'Disabled', value: 'disabled' },
                    { label: 'Water Heater Boost', value: 'water_heater_boost' },
                    { label: 'Custom Entity', value: 'custom_entity' },
                ],
                helper: 'Choose where excess PV energy goes. Water Heater Boost heats water to max temp. Custom Entity toggles any HA entity.',
                showIf: { configKey: 'system.has_water_heater', value: true },
                className: 'col-span-2',
            },
            {
                key: 'executor.excess_pv.sink',
                label: 'Excess PV Sink',
                path: ['executor', 'excess_pv', 'sink'],
                type: 'select',
                options: [
                    { label: 'Disabled', value: 'disabled' },
                    { label: 'Custom Entity', value: 'custom_entity' },
                ],
                helper: 'Choose where excess PV energy goes. Custom Entity toggles any HA entity.',
                showIf: { configKey: 'system.has_water_heater', value: false },
                className: 'col-span-2',
            },
            {
                key: 'executor.excess_pv.custom_entity.entity',
                label: 'Custom Entity',
                path: ['executor', 'excess_pv', 'custom_entity', 'entity'],
                type: 'entity',
                helper: 'Home Assistant entity to toggle (e.g., switch.pool_pump).',
                showIf: {
                    configKey: 'executor.excess_pv.sink',
                    value: 'custom_entity',
                },
            },
            {
                key: 'executor.excess_pv.custom_entity.on_value',
                label: 'On Value',
                path: ['executor', 'excess_pv', 'custom_entity', 'on_value'],
                type: 'text',
                helper: 'Value to set when excess PV is available.',
                showIf: {
                    configKey: 'executor.excess_pv.sink',
                    value: 'custom_entity',
                },
            },
            {
                key: 'executor.excess_pv.custom_entity.off_value',
                label: 'Off Value',
                path: ['executor', 'excess_pv', 'custom_entity', 'off_value'],
                type: 'text',
                helper: 'Value to set when excess PV is not available.',
                showIf: {
                    configKey: 'executor.excess_pv.sink',
                    value: 'custom_entity',
                },
            },
            {
                key: 'executor.excess_pv.custom_entity.power_kw',
                label: 'Power (kW)',
                path: ['executor', 'excess_pv', 'custom_entity', 'power_kw'],
                type: 'number',
                helper: 'Estimated power consumption in kW. Used by the solver to size the reward correctly.',
                showIf: {
                    configKey: 'executor.excess_pv.sink',
                    value: 'custom_entity',
                },
            },
            {
                key: 'executor.excess_pv.boost_reward_sek_per_kwh',
                label: 'Sink Reward (SEK/kWh)',
                path: ['executor', 'excess_pv', 'boost_reward_sek_per_kwh'],
                type: 'number',
                helper: 'Reward for using excess PV at the sink instead of exporting.',
                showIf: {
                    configKey: 'executor.excess_pv.sink',
                    value: ['water_heater_boost', 'custom_entity'],
                },
            },
            {
                key: 'executor.excess_pv.soc_threshold_percent',
                label: 'SoC Threshold (%)',
                path: ['executor', 'excess_pv', 'soc_threshold_percent'],
                type: 'number',
                helper: 'Battery must reach this SoC% before sink activates.',
                showIf: {
                    configKey: 'executor.excess_pv.sink',
                    value: ['water_heater_boost', 'custom_entity'],
                },
            },
        ],
    },
    {
        title: 'Danger Zone',
        description: 'Sensitive actions. Proceed with caution.',
        fields: [], // Handled specially in render
    },
]

export const systemFieldList = systemSections.flatMap((section) => section.fields)

// Include system toggles that control Parameters tab section visibility
const systemToggleFields = systemFieldList.filter(
    (f) => f.key === 'system.has_ev_charger' || f.key === 'system.has_water_heater',
)

export const parameterFieldList = [...systemToggleFields, ...parameterSections.flatMap((section) => section.fields)]
export const solarFieldList = solarSections.flatMap((section) => section.fields)
export const batteryFieldList = batterySections.flatMap((section) => section.fields)
export const evFieldList = evSections.flatMap((section) => section.fields)
export const waterFieldList = waterSections.flatMap((section) => section.fields)
export const uiFieldList = uiSections.flatMap((section) => section.fields)
export const advancedFieldList = advancedSections.flatMap((section) => section.fields)
export const loadBalancingFieldList = loadBalancingSections.flatMap((section) => section.fields)

export const allFields = [
    ...systemFieldList,
    ...parameterFieldList,
    ...solarFieldList,
    ...batteryFieldList,
    ...evFieldList,
    ...waterFieldList,
    ...uiFieldList,
    ...advancedFieldList,
    ...loadBalancingFieldList,
    {
        key: 'dashboard.overlay_defaults',
        label: 'Overlay Defaults',
        path: ['dashboard', 'overlay_defaults'],
        type: 'text' as FieldType,
    },
]

// Standard keys that live directly in the inverter config (not in custom_entities)
export const standardInverterKeys = new Set([
    'work_mode',
    'soc_target',
    'grid_charging_enable',
    'grid_charge_power',
    'minimum_reserve',
    'grid_max_export_power',
    'grid_max_export_power_switch',
    'max_charge_current',
    'max_discharge_current',
    'max_charge_power',
    'max_discharge_power',
])

export function generateProfileEntityFields(profile: InverterProfile, category?: string): BaseField[] {
    const fields: BaseField[] = []

    for (const [key, entity] of Object.entries(profile.entities)) {
        if (category !== undefined && entity.category !== category) continue
        const isStandard = standardInverterKeys.has(key)
        const configPath = isStandard ? `executor.inverter.${key}` : `executor.inverter.custom_entities.${key}`
        const arrayPath = isStandard ? ['executor', 'inverter', key] : ['executor', 'inverter', 'custom_entities', key]
        fields.push({
            key: configPath,
            label: entity.description,
            path: arrayPath,
            type: 'entity' as FieldType,
            helper: entity.required ? `Required for ${profile.name} profile` : `Optional for ${profile.name} profile`,
            required: entity.required,
        })
    }

    return fields
}

export const fieldMap = allFields.reduce(
    (acc, field) => {
        acc[field.key] = field
        return acc
    },
    {} as Record<string, BaseField>,
)
