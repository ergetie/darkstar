export type PlannerSIndex = {
    effective_load_margin?: number
    risk_factor?: number
    factor?: number
    adjusted_factor?: number
    avg_deficit?: number
    temp_adjustment?: number
    mean_temperature_c?: number
    base_factor?: number
    safety_floor?: {
        method?: string
        deficit_ratio?: number
        calculated_floor_kwh?: number
        min_soc_kwh?: number
        base_reserve_kwh?: number
        weather_buffer_kwh?: number
        risk_multiplier?: number
        effective_reserve_kwh?: number
        final_floor_kwh?: number
        price_reserve_active?: boolean
        price_reserve_reason?: string
        price_reserve_kwh?: number
        price_reserve_applied_kwh?: number
        price_reserve_capped_by?: string
        known_cost_sek_kwh?: number | null
        own_day_cost_sek_kwh?: number | null
        unseen_window_start?: string | null
        [key: string]: unknown
    }
    [key: string]: unknown
}

/** Live per-charger reading (websocket live_metrics / GET /api/status). */
export type LiveEvCharger = {
    id?: string
    name: string
    kw: number
    soc: number | null
    plugged_in: boolean
    unreachable?: boolean
}

export type StatusResponse = {
    // New flat structure from Rev ARC1
    soc_percent?: number
    pv_power_kw?: number
    load_power_kw?: number
    battery_power_kw?: number
    grid_power_kw?: number
    ev_kw?: number
    ev_plugged_in?: boolean
    ev_chargers?: LiveEvCharger[]
    status?: string
    mode?: string
    rev?: string
    // Legacy structure (fallback)
    current_soc?: { value: number; timestamp: string; source?: string }
    local?: { planned_at?: string; planner_version?: string; s_index?: PlannerSIndex }
}

export type HorizonResponse = {
    total_days_in_schedule?: number
    days_list?: string[]
    pv_days_schedule?: number
    load_days_schedule?: number
    pv_forecast_days?: number
    weather_forecast_days?: number
    s_index_considered_days?: number
}

export type ScheduleResponse = {
    schedule: import('./types').ScheduleSlot[]
    meta?: {
        last_error?: string
        last_error_at?: string
        overlay_defaults?: string[]
        [key: string]: unknown
    }
}
export type ScheduleTodayWithHistoryResponse = {
    slots: import('./types').ScheduleSlot[]
    timezone?: string
}
export type ConfigResponse = {
    /** IANA timezone for all schedule/price calculations (backend default Europe/Stockholm). */
    timezone?: string
    installation_stats?: {
        enabled?: boolean
        endpoint?: string
    }
    system?: {
        inverter_profile?: string
        battery?: { capacity_kwh?: number }
        solar_array?: { kwp?: number }
        solar_arrays?: { kwp?: number; name?: string }[]
        grid?: { max_power_kw?: number; main_fuse_a?: number; nominal_voltage_v?: number }
        inverter?: { max_power_kw?: number }
        has_solar?: boolean
        has_battery?: boolean
        has_water_heater?: boolean
        has_ev_charger?: boolean
    }
    // Battery is also at root level in actual API response
    battery?: { capacity_kwh?: number; min_soc_percent?: number; max_soc_percent?: number }
    automation?: {
        enable_scheduler?: boolean
        external_executor_mode?: boolean
        schedule?: { every_minutes?: number }
    }
    water_heating?: {
        comfort_level?: number
        vacation_mode?: { enabled?: boolean; end_date?: string | null }
    }
    pricing?: {
        vat_percent?: number
        grid_transfer_fee_sek?: number
        transfer_fee_mode?: 'flat' | 'time_of_use'
        holidays_as_weekend?: boolean
        transfer_fee_rules?: {
            months?: number[]
            weekdays?: number[]
            hours?: { start: number; end: number }
            fee_sek: number
        }[]
        energy_tax_sek?: number
    }
    input_sensors?: {
        vacation_mode?: string
    }
    dashboard?: {
        overlay_defaults?: string
    }
    advisor?: {
        enable_llm?: boolean
        auto_fetch?: boolean
    }
    forecasting?: {
        active_forecast_version?: 'aurora' | 'baseline_7_day_avg' | string
        aurora_load_enabled?: boolean
        aurora_pv_enabled?: boolean
        pv_residual_bound_fraction?: number
        pv_ceiling_efficiency?: number
        pv_personalization_ramp_days?: number
    }
    ui?: {
        theme_accent_index?: number
        theme_mode?: 'light' | 'dark' | 'system'
    }
    // ARC15: Entity-Centric Configuration
    water_heaters?: {
        id: string
        name: string
        enabled: boolean
        power_kw: number
        min_kwh_per_day: number
        max_hours_between_heating: number
        water_min_spacing_hours: number
        sensor: string
        target_entity?: string
        control_type: 'temperature' | 'switch'
        type: 'binary' | 'modulating'
    }[]
    ev_chargers?: {
        id: string
        name: string
        enabled: boolean
        rated_power_kw?: number
        battery_capacity_kwh: number
        min_soc_percent: number
        target_soc_percent: number
        sensor: string
        type: 'binary' | 'current'
        min_current_a?: number
        max_current_a?: number
        phases?: number[]
    }[]
    executor?: {
        excess_pv?: {
            priority?: { type: string; charger_id?: string }[]
            custom_entity?: { power_kw?: number; [key: string]: unknown }
            [key: string]: unknown
        }
        [key: string]: unknown
    }
    [key: string]: unknown
}
export type ConfigSaveError = { field?: string; message: string }
// REV LCL01: Backend now returns warnings on config save
export type ConfigSaveWarning = { severity: string; message: string; guidance: string }
export type ConfigSaveResponse = {
    status?: string
    errors?: ConfigSaveError[]
    warnings?: ConfigSaveWarning[]
}
export type HaCoreConfigResponse = {
    latitude?: number | null
    longitude?: number | null
    time_zone?: string | null
    currency?: string | null
    country?: string | null
    unit_system?: Record<string, unknown>
}
export type HaDiscoveryEntity = {
    entity_id: string
    friendly_name: string
    domain: string
    state?: string
    unit_of_measurement?: string
    device_class?: string
    state_class?: string
    platform?: string
    manufacturer?: string
    model?: string
}
export type HaDiscoveryResponse = { entities: HaDiscoveryEntity[]; registry_available: boolean }
export type EntityCandidate = {
    entity_id: string
    score: number
    confidence: 'high' | 'medium' | 'low'
    reasons: string[]
}
export type SetupSuggestionsResponse = {
    patch: Record<string, unknown>
    candidates: Record<string, EntityCandidate[]>
    current: Record<string, unknown>
    missing_required: string[]
    brands: { name: string; score: number; confidence: 'high' | 'medium' | 'low'; reasons: string[] }[]
    suggested_profile: string | null
    fallback_profile: string
    registry_available: boolean
}
export type ProfileSuggestionsResponse = {
    profile_name: string
    patch: Record<string, unknown>
    candidates: Record<string, EntityCandidate[]>
    current: Record<string, unknown>
    missing_required: string[]
}
export type ReadinessCheck = {
    id: string
    group: string
    status: 'pass' | 'warn' | 'fail' | 'skipped'
    message: string
    fix_hint: string
    settings_path: string
}
export type ReadinessResponse = { ready: boolean; checks: ReadinessCheck[] }
export type OnboardingProgress = {
    status: 'not_started' | 'in_progress' | 'dismissed' | 'completed'
    current_step: string | null
    completed_steps: string[]
    version?: number
    updated_at?: string | null
}

export class ApiError extends Error {
    constructor(
        message: string,
        readonly status: number,
        readonly detail?: unknown,
    ) {
        super(message)
        this.name = 'ApiError'
    }
}

export type HaAverageResponse = {
    average_load_kw?: number
    daily_kwh?: number
    [key: string]: unknown
}

export type LearningStatusResponse = {
    enabled?: boolean
    last_updated?: string
    pv_personalization?: {
        source?: string
        paired_days?: number
        ramp_days?: number
        weight?: number
        mode?: 'baseline' | 'personalized'
    }
    metrics?: {
        completed_learning_runs?: number
        days_with_data?: number
        db_size_bytes?: number
        failed_learning_runs?: number
        last_learning_run?: string
        last_observation?: string
        price_coverage_ratio?: number
        quality_gap_events?: number
        quality_reset_events?: number
        total_export_kwh?: number
        total_import_kwh?: number
        total_learning_runs?: number
        total_load_kwh?: number
        total_pv_kwh?: number
        total_slots?: number
    }
    sqlite_path?: string
    sync_interval_minutes?: number
    [key: string]: unknown
}

export type LearningHistoryEntry = {
    id: number
    started_at: string
    status: string
    loops_run?: number
    changes_proposed?: number
    changes_applied?: number
}

export type SIndexHistoryEntry = {
    date: string
    metric: string
    value: number | null
}

export type LearningParamChange = {
    run_id?: number | null
    started_at?: string | null
    param_path: string
    old_value?: string | null
    new_value?: string | null
    loop?: string | null
    reason?: string | null
}

export type LearningHistoryResponse = {
    runs: LearningHistoryEntry[]
    s_index_history?: SIndexHistoryEntry[]
    recent_changes?: LearningParamChange[]
}

export type LearningDailyMetricsResponse = {
    date?: string
    pv_error_mean_abs_kwh?: number | null
    load_error_mean_abs_kwh?: number | null
    s_index_base_factor?: number | null
    message?: string
}

export type DebugResponse = {
    s_index?: {
        mode?: string
        base_factor?: number
        factor?: number
        max_factor?: number
        [key: string]: unknown
    }
    [key: string]: unknown
}

export type DebugLogEntry = {
    timestamp: string
    level: string
    logger: string
    message: string
}

export type DebugLogsResponse = {
    logs: DebugLogEntry[]
}

export type LoadItem = {
    id: string
    name: string
    power_kw: number
    healthy: boolean
    type: string
    sensor: string
}

export type LoadQualityMetrics = {
    metrics: {
        negative_base_load_count: number
        total_calculations: number
        sensor_failures: number
    }
    drift_rate: number
    sensor_health: Record<string, boolean>
}

export type LoadsDebugResponse = {
    controllable_total_kw: number
    loads: LoadItem[]
    quality_metrics: LoadQualityMetrics
}

export type HistorySocSlot = {
    timestamp: string
    soc_percent: number
    quality_flags?: string
}

export type HistorySocResponse = {
    date: string
    slots: HistorySocSlot[]
    count: number
    message?: string
}
export type LearningRunResponse = {
    status?: string
    message?: string
    loops_run?: number
    changes_proposed?: number
    changes_applied?: number
    [key: string]: unknown
}

export type LearningLoopsResponse = {
    forecast_calibrator?: { status?: string; result?: unknown }
    threshold_tuner?: { status?: string; result?: unknown }
    s_index_tuner?: { status?: string; result?: unknown }
    export_guard_tuner?: { status?: string; result?: unknown }
    [key: string]: unknown
}

export type SchedulerStatusResponse = {
    enabled?: boolean
    every_minutes?: number
    jitter_minutes?: number
    last_run_at?: string
    next_run_at?: string
    last_run_status?: string
    last_error?: string
    ml_training_last_run_at?: string
    [key: string]: unknown
}

export type ThemeInfo = {
    name: string
    background: string
    foreground: string
    palette: string[]
}

export type ExecutorStatusResponse = {
    shadow_mode?: boolean
    paused?: {
        paused_at?: string
        paused_minutes?: number
    } | null
    quick_action?: {
        type: string
        expires_at: string
        remaining_minutes: number
        reason: string
        params?: Record<string, unknown>
    } | null
    [key: string]: unknown
}

export type LoadBalancerEvStatus = {
    charger_id: string
    charger_name: string
    setpoint_a: number | null
    planned_target_a: number | null
    /** ev-measured-draw: amps per phase the car actually draws (null = no measurement) */
    measured_a?: number | null
    state: string
    reason: string
    /** excess-pv-priority-dispatch 4.1: additive surplus-mode fields */
    surplus_mode?: boolean
    surplus_state?: string | null
    surplus_reason?: string | null
    phase_mode?: number | null
    paused?: boolean
    /** load-balancer-graceful-degradation 6.4: held (or switching) to 1-phase to relieve an overloaded phase */
    relief_1p?: boolean
    /** e.g. "1-phase on L1 — relieving L3" */
    relief_reason?: string | null
    /** Grid phase the charger uses in 1-phase mode */
    phase_1_line?: number | null
}

export type LoadBalancerShedStatus = {
    load_id: string
    device_type: string
    shed: boolean
    reason: string
}

export type LoadBalancerStatusResponse = {
    enabled: boolean
    state: 'disabled' | 'idle' | 'throttling' | 'shedding' | 'paused' | 'stale_fallback' | string
    reason: string
    main_fuse_a: number | null
    phase_current_a: Record<string, number>
    phase_headroom_a: Record<string, number>
    /** Balancer ramps up only while each phase stays at or below this share of the fuse */
    target_margin_percent?: number
    /** Executor tick interval (s) — the balancer reacts and reports once per tick. */
    tick_interval_s?: number
    /** excess-pv-priority-dispatch 4.1: whole-house measured surplus (export - import), kW */
    measured_surplus_kw?: number | null
    ev: LoadBalancerEvStatus[]
    shed: LoadBalancerShedStatus[]
}

/** One entry in load_balancing.give_way_order (top gives way first). */
export type GiveWayOrderEntry = {
    kind: 'charger' | 'shed'
    id: string
}

export type ExecutorHealthResponse = {
    status: 'healthy' | 'error' | 'warning'
    is_running: boolean
    is_enabled: boolean
    is_paused: boolean
    should_be_running: boolean
    last_run_at: string | null
    last_run_status: string
    has_error: boolean
    error: string | null
    recent_errors: {
        timestamp: string
        type: string
        message: string
    }[]
    warnings: string[]
    is_healthy: boolean
}

export type EnergyTodayResponse = {
    // Unified keys (new standard)
    pv_production_kwh: number | null
    load_consumption_kwh: number | null
    grid_import_kwh: number | null
    grid_export_kwh: number | null
    battery_charge_kwh: number | null
    battery_discharge_kwh: number | null
    ev_charging_kwh: number | null
    ev_grid_kwh?: number | null
    ev_solar_kwh?: number | null
    ev_cost_sek?: number | null
    ev_solar_share?: number | null
    water_heating_kwh: number | null
    net_cost_sek: number | null
    battery_cycles: number | null
    base_load_avg_daily_kwh: number | null
    // Legacy aliases (for backwards compatibility)
    solar?: number | null
    consumption?: number | null
    grid_import?: number | null
    grid_export?: number | null
    net_cost_kr?: number | null
}

export type CostSeriesPoint = {
    start: string
    import_cost_sek: number
    export_revenue_sek: number
    net_cost_sek: number
    cumulative_net_cost_sek: number
}

export type CostSeriesCoverage = {
    covered_slots: number
    total_slots: number
    excluded_slots: number
}

export type CostSeriesTimeAxis = {
    timezone: string
    start: string
    end: string
}

export type GridOnlyBucketPoint = {
    start: string
    end: string
    import_cost_sek: number
    export_revenue_sek: number
    ds_electricity_cost_sek: number
    ds_wear_cost_sek: number
    grid_only_wear_cost_sek: number
    ds_cost_sek: number
    grid_only_cost_sek: number
    cumulative_ds_cost_sek: number
    cumulative_grid_only_cost_sek: number
}

export type GridOnlySegmentPoint = {
    at: string
    cumulative_ds_cost_sek: number
    cumulative_grid_only_cost_sek: number
}

export type GridOnlySegment = {
    start: string
    end: string
    points: GridOnlySegmentPoint[]
}

type GridOnlyComparisonBase = {
    reason: string
    method_version: 'grid-only-bill-v1'
    coverage: CostSeriesCoverage
    time_axis: CostSeriesTimeAxis
}

export type GridOnlyComparison = GridOnlyComparisonBase &
    (
        | {
              status: 'available' | 'partial'
              reason: 'complete_coverage' | 'partial_coverage'
              through: string
              grid_only_cost_sek: number
              grid_only_wear_cost_sek: number
              ds_electricity_cost_sek: number
              ds_wear_cost_sek: number
              ds_cost_sek: number
              saving_sek: number
              points: GridOnlyBucketPoint[]
              segments: GridOnlySegment[]
          }
        | {
              status: 'no_data' | 'unavailable'
              reason: 'no_completed_observations' | 'no_usable_observations'
              through?: never
              grid_only_cost_sek?: never
              grid_only_wear_cost_sek?: never
              ds_electricity_cost_sek?: never
              ds_wear_cost_sek?: never
              ds_cost_sek?: never
              saving_sek?: never
              points?: never
              segments?: never
          }
    )

export type CostSeriesResponse = {
    period: string
    start_date?: string
    end_date?: string
    bucket: 'hour' | 'day'
    points: CostSeriesPoint[]
    grid_only_comparison?: GridOnlyComparison
    error?: string
}

function isRecord(value: unknown): value is Record<string, unknown> {
    return typeof value === 'object' && value !== null && !Array.isArray(value)
}

function finite(value: unknown): value is number {
    return typeof value === 'number' && Number.isFinite(value)
}

function integer(value: unknown): value is number {
    return Number.isInteger(value)
}

function zonedTimestamp(value: unknown): number | null {
    if (
        typeof value !== 'string' ||
        !/^\d{4}-\d\d-\d\dT\d\d:\d\d(?::\d\d(?:\.\d+)?)?(?:Z|[+-]\d\d:\d\d)$/.test(value)
    ) {
        return null
    }
    const timestamp = Date.parse(value)
    return Number.isFinite(timestamp) ? timestamp : null
}

function invalidCostSeries(): never {
    throw new Error('Invalid cost-series response')
}

// Cost-series money values are rounded to 0.001 SEK independently by the
// backend. The tolerance counts each rounded value in the relationship; its
// small scale term covers only IEEE-754 arithmetic used for the comparison.
function withinMoneyRoundingBound(residual: number, roundedValues: number, arithmeticScale: number): boolean {
    if (!Number.isFinite(residual) || !Number.isFinite(arithmeticScale)) return false
    const roundingBound = roundedValues * 0.0005
    const floatingPointBound = Number.EPSILON * Math.max(1, arithmeticScale) * (roundedValues + 2)
    return Math.abs(residual) <= roundingBound + floatingPointBound
}

/** Validate the changed financial contract at the JSON boundary. */
export function parseCostSeriesResponse(value: unknown): CostSeriesResponse {
    if (!isRecord(value) || typeof value.period !== 'string' || !['hour', 'day'].includes(String(value.bucket))) {
        return invalidCostSeries()
    }
    if ('baseline' in value || 'battery_comparison' in value) return invalidCostSeries()
    if (!Array.isArray(value.points)) return invalidCostSeries()
    const actualPoints: CostSeriesPoint[] = value.points.map((raw) => {
        if (!isRecord(raw) || zonedTimestamp(raw.start) === null) return invalidCostSeries()
        if (Object.keys(raw).some((key) => key.startsWith('baseline_'))) return invalidCostSeries()
        if (
            !finite(raw.import_cost_sek) ||
            !finite(raw.export_revenue_sek) ||
            !finite(raw.net_cost_sek) ||
            !finite(raw.cumulative_net_cost_sek)
        ) {
            return invalidCostSeries()
        }
        return raw as unknown as CostSeriesPoint
    })
    const comparisonValue = value.grid_only_comparison
    if (comparisonValue === undefined) {
        if (typeof value.error === 'string') return { ...value, points: actualPoints } as unknown as CostSeriesResponse
        return invalidCostSeries()
    }
    if (!isRecord(comparisonValue)) return invalidCostSeries()

    const comparison = comparisonValue
    const coverage = comparison.coverage
    const axis = comparison.time_axis
    if (!isRecord(coverage) || !isRecord(axis)) return invalidCostSeries()
    const axisStart = zonedTimestamp(axis.start)
    const axisEnd = zonedTimestamp(axis.end)
    if (
        !integer(coverage.covered_slots) ||
        !integer(coverage.total_slots) ||
        !integer(coverage.excluded_slots) ||
        coverage.covered_slots < 0 ||
        coverage.total_slots < 0 ||
        coverage.excluded_slots < 0 ||
        coverage.covered_slots + coverage.excluded_slots !== coverage.total_slots ||
        typeof axis.timezone !== 'string' ||
        axisStart === null ||
        axisEnd === null ||
        axisEnd <= axisStart ||
        comparison.method_version !== 'grid-only-bill-v1'
    ) {
        return invalidCostSeries()
    }
    try {
        new Intl.DateTimeFormat('en', { timeZone: axis.timezone })
    } catch {
        return invalidCostSeries()
    }

    const coveredSlots = coverage.covered_slots
    const excludedSlots = coverage.excluded_slots
    if (comparison.status === 'no_data' || comparison.status === 'unavailable') {
        if (
            (comparison.status === 'no_data' && comparison.reason !== 'no_completed_observations') ||
            (comparison.status === 'unavailable' && comparison.reason !== 'no_usable_observations') ||
            coveredSlots !== 0 ||
            'through' in comparison ||
            'grid_only_cost_sek' in comparison ||
            'grid_only_wear_cost_sek' in comparison ||
            'ds_electricity_cost_sek' in comparison ||
            'ds_wear_cost_sek' in comparison ||
            'ds_cost_sek' in comparison ||
            'saving_sek' in comparison ||
            'points' in comparison ||
            'segments' in comparison
        ) {
            return invalidCostSeries()
        }
        return { ...value, points: actualPoints } as unknown as CostSeriesResponse
    }

    if (
        (comparison.status !== 'available' && comparison.status !== 'partial') ||
        (comparison.status === 'available' && (comparison.reason !== 'complete_coverage' || excludedSlots !== 0)) ||
        (comparison.status === 'partial' && (comparison.reason !== 'partial_coverage' || excludedSlots === 0)) ||
        coveredSlots <= 0 ||
        !finite(comparison.grid_only_cost_sek) ||
        !finite(comparison.grid_only_wear_cost_sek) ||
        comparison.grid_only_wear_cost_sek !== 0 ||
        !finite(comparison.ds_electricity_cost_sek) ||
        !finite(comparison.ds_wear_cost_sek) ||
        !finite(comparison.ds_cost_sek) ||
        !finite(comparison.saving_sek)
    ) {
        return invalidCostSeries()
    }
    const through = zonedTimestamp(comparison.through)
    if (through === null || through < axisStart || through > axisEnd) return invalidCostSeries()
    if (!Array.isArray(comparison.points) || comparison.points.length === 0) return invalidCostSeries()

    let previousBucketEnd = -Infinity
    let previousCumulativeDs = 0
    let previousCumulativeGrid = 0
    let bucketDsElectricity = 0
    let bucketDsWear = 0
    let bucketGridCost = 0
    let bucketDsElectricityMagnitude = 0
    let bucketDsWearMagnitude = 0
    let bucketGridCostMagnitude = 0
    for (const raw of comparison.points) {
        if (!isRecord(raw)) return invalidCostSeries()
        const start = zonedTimestamp(raw.start)
        const end = zonedTimestamp(raw.end)
        if (
            start === null ||
            end === null ||
            start < axisStart ||
            end > axisEnd ||
            end <= start ||
            start < previousBucketEnd ||
            !finite(raw.import_cost_sek) ||
            !finite(raw.export_revenue_sek) ||
            !finite(raw.ds_electricity_cost_sek) ||
            !finite(raw.ds_wear_cost_sek) ||
            raw.grid_only_wear_cost_sek !== 0 ||
            !finite(raw.ds_cost_sek) ||
            !finite(raw.grid_only_cost_sek) ||
            !finite(raw.cumulative_ds_cost_sek) ||
            !finite(raw.cumulative_grid_only_cost_sek) ||
            !withinMoneyRoundingBound(
                raw.import_cost_sek - raw.export_revenue_sek - raw.ds_electricity_cost_sek,
                3,
                Math.abs(raw.import_cost_sek) +
                    Math.abs(raw.export_revenue_sek) +
                    Math.abs(raw.ds_electricity_cost_sek),
            ) ||
            !withinMoneyRoundingBound(
                raw.ds_electricity_cost_sek + raw.ds_wear_cost_sek - raw.ds_cost_sek,
                3,
                Math.abs(raw.ds_electricity_cost_sek) + Math.abs(raw.ds_wear_cost_sek) + Math.abs(raw.ds_cost_sek),
            )
        ) {
            return invalidCostSeries()
        }
        previousBucketEnd = end
        bucketDsElectricity += raw.ds_electricity_cost_sek
        bucketDsWear += raw.ds_wear_cost_sek
        bucketGridCost += raw.grid_only_cost_sek
        bucketDsElectricityMagnitude += Math.abs(raw.ds_electricity_cost_sek)
        bucketDsWearMagnitude += Math.abs(raw.ds_wear_cost_sek)
        bucketGridCostMagnitude += Math.abs(raw.grid_only_cost_sek)
        const dsDelta = raw.cumulative_ds_cost_sek - previousCumulativeDs
        const gridDelta = raw.cumulative_grid_only_cost_sek - previousCumulativeGrid
        if (
            !Number.isFinite(bucketDsElectricity) ||
            !Number.isFinite(bucketDsWear) ||
            !Number.isFinite(bucketGridCost) ||
            !withinMoneyRoundingBound(
                dsDelta - raw.ds_cost_sek,
                previousCumulativeDs === 0 ? 2 : 3,
                Math.abs(previousCumulativeDs) + Math.abs(raw.cumulative_ds_cost_sek) + Math.abs(raw.ds_cost_sek),
            ) ||
            !withinMoneyRoundingBound(
                gridDelta - raw.grid_only_cost_sek,
                previousCumulativeGrid === 0 ? 2 : 3,
                Math.abs(previousCumulativeGrid) +
                    Math.abs(raw.cumulative_grid_only_cost_sek) +
                    Math.abs(raw.grid_only_cost_sek),
            )
        ) {
            return invalidCostSeries()
        }
        previousCumulativeDs = raw.cumulative_ds_cost_sek
        previousCumulativeGrid = raw.cumulative_grid_only_cost_sek
    }

    if (!Array.isArray(comparison.segments) || comparison.segments.length === 0) return invalidCostSeries()
    let previousSegmentEnd = -Infinity
    let previousSegmentDs = 0
    let previousSegmentGrid = 0
    let segmentSlots = 0
    let segmentBucketIndex = 0
    const bucketSegmentEndpoints = new Map<number, { ds: number; grid: number }>()
    for (const raw of comparison.segments) {
        if (!isRecord(raw) || !Array.isArray(raw.points) || raw.points.length < 2) return invalidCostSeries()
        const start = zonedTimestamp(raw.start)
        const end = zonedTimestamp(raw.end)
        if (
            start === null ||
            end === null ||
            start < axisStart ||
            end > through ||
            end <= start ||
            start <= previousSegmentEnd
        ) {
            return invalidCostSeries()
        }
        let previousPoint = -Infinity
        for (const [index, point] of raw.points.entries()) {
            if (!isRecord(point)) return invalidCostSeries()
            const at = zonedTimestamp(point.at)
            if (
                at === null ||
                at < start ||
                at > end ||
                at <= previousPoint ||
                (at - axisStart) % 900_000 !== 0 ||
                (index > 0 && at - previousPoint !== 900_000) ||
                !finite(point.cumulative_ds_cost_sek) ||
                !finite(point.cumulative_grid_only_cost_sek) ||
                (index === 0 &&
                    (at !== start ||
                        Math.abs(point.cumulative_ds_cost_sek - previousSegmentDs) > 0.002 ||
                        Math.abs(point.cumulative_grid_only_cost_sek - previousSegmentGrid) > 0.002)) ||
                (index === raw.points.length - 1 && at !== end)
            ) {
                return invalidCostSeries()
            }
            if (index > 0) {
                while (
                    segmentBucketIndex < comparison.points.length &&
                    previousPoint >= Date.parse(comparison.points[segmentBucketIndex].end)
                ) {
                    segmentBucketIndex += 1
                }
                const bucket = comparison.points[segmentBucketIndex]
                if (!bucket || previousPoint < Date.parse(bucket.start) || at > Date.parse(bucket.end)) {
                    return invalidCostSeries()
                }
                bucketSegmentEndpoints.set(segmentBucketIndex, {
                    ds: point.cumulative_ds_cost_sek,
                    grid: point.cumulative_grid_only_cost_sek,
                })
            }
            previousPoint = at
        }
        if ((end - start) % 900_000 !== 0 || raw.points.length - 1 !== (end - start) / 900_000) {
            return invalidCostSeries()
        }
        const segmentFinal = raw.points[raw.points.length - 1] as Record<string, unknown>
        previousSegmentDs = segmentFinal.cumulative_ds_cost_sek as number
        previousSegmentGrid = segmentFinal.cumulative_grid_only_cost_sek as number
        segmentSlots += (end - start) / 900_000
        previousSegmentEnd = end
    }
    for (const [index, bucket] of comparison.points.entries()) {
        const endpoint = bucketSegmentEndpoints.get(index)
        if (
            !endpoint ||
            !withinMoneyRoundingBound(
                endpoint.ds - bucket.cumulative_ds_cost_sek,
                2,
                Math.abs(endpoint.ds) + Math.abs(bucket.cumulative_ds_cost_sek),
            ) ||
            !withinMoneyRoundingBound(
                endpoint.grid - bucket.cumulative_grid_only_cost_sek,
                2,
                Math.abs(endpoint.grid) + Math.abs(bucket.cumulative_grid_only_cost_sek),
            )
        ) {
            return invalidCostSeries()
        }
    }

    const finalBucket = comparison.points[comparison.points.length - 1] as Record<string, unknown>
    const lastSegment = comparison.segments[comparison.segments.length - 1] as Record<string, unknown>
    const segmentPoints = lastSegment.points as Record<string, unknown>[]
    const finalSegmentPoint = segmentPoints[segmentPoints.length - 1]
    if (
        segmentSlots !== coveredSlots ||
        zonedTimestamp(lastSegment.end) !== through ||
        !finalSegmentPoint ||
        !withinMoneyRoundingBound(
            bucketDsElectricity - Number(comparison.ds_electricity_cost_sek),
            comparison.points.length + 1,
            bucketDsElectricityMagnitude + Math.abs(Number(comparison.ds_electricity_cost_sek)),
        ) ||
        !withinMoneyRoundingBound(
            bucketDsWear - Number(comparison.ds_wear_cost_sek),
            comparison.points.length + 1,
            bucketDsWearMagnitude + Math.abs(Number(comparison.ds_wear_cost_sek)),
        ) ||
        !withinMoneyRoundingBound(
            bucketGridCost - Number(comparison.grid_only_cost_sek),
            comparison.points.length + 1,
            bucketGridCostMagnitude + Math.abs(Number(comparison.grid_only_cost_sek)),
        ) ||
        !withinMoneyRoundingBound(
            Number(finalBucket.cumulative_ds_cost_sek) - Number(comparison.ds_cost_sek),
            2,
            Math.abs(Number(finalBucket.cumulative_ds_cost_sek)) + Math.abs(Number(comparison.ds_cost_sek)),
        ) ||
        !withinMoneyRoundingBound(
            Number(finalBucket.cumulative_grid_only_cost_sek) - Number(comparison.grid_only_cost_sek),
            2,
            Math.abs(Number(finalBucket.cumulative_grid_only_cost_sek)) +
                Math.abs(Number(comparison.grid_only_cost_sek)),
        ) ||
        !withinMoneyRoundingBound(
            Number(finalSegmentPoint.cumulative_ds_cost_sek) - Number(comparison.ds_cost_sek),
            2,
            Math.abs(Number(finalSegmentPoint.cumulative_ds_cost_sek)) + Math.abs(Number(comparison.ds_cost_sek)),
        ) ||
        !withinMoneyRoundingBound(
            Number(finalSegmentPoint.cumulative_grid_only_cost_sek) - Number(comparison.grid_only_cost_sek),
            2,
            Math.abs(Number(finalSegmentPoint.cumulative_grid_only_cost_sek)) +
                Math.abs(Number(comparison.grid_only_cost_sek)),
        ) ||
        !withinMoneyRoundingBound(
            Number(comparison.ds_electricity_cost_sek) +
                Number(comparison.ds_wear_cost_sek) -
                Number(comparison.ds_cost_sek),
            3,
            Math.abs(Number(comparison.ds_electricity_cost_sek)) +
                Math.abs(Number(comparison.ds_wear_cost_sek)) +
                Math.abs(Number(comparison.ds_cost_sek)),
        ) ||
        !withinMoneyRoundingBound(
            Number(comparison.grid_only_cost_sek) - Number(comparison.ds_cost_sek) - Number(comparison.saving_sek),
            3,
            Math.abs(Number(comparison.grid_only_cost_sek)) +
                Math.abs(Number(comparison.ds_cost_sek)) +
                Math.abs(Number(comparison.saving_sek)),
        )
    ) {
        return invalidCostSeries()
    }
    return { ...value, points: actualPoints } as unknown as CostSeriesResponse
}

export type EnergyRangeResponse = {
    period: 'today' | 'yesterday' | 'week' | 'month' | 'custom'
    start_date: string
    end_date: string
    grid_import_kwh: number
    grid_export_kwh: number
    battery_charge_kwh: number
    battery_discharge_kwh: number
    water_heating_kwh: number
    pv_production_kwh: number
    load_consumption_kwh: number
    ev_charging_kwh: number
    // EV attribution, grid first. ev_cost_sek is the EV grid import cost only (part of import_cost_sek); ev_solar_share is informational.
    ev_grid_kwh: number
    ev_solar_kwh: number
    ev_cost_sek: number
    ev_solar_share: number | null
    import_cost_sek: number
    export_revenue_sek: number
    grid_charge_cost_sek: number
    self_consumption_savings_sek: number
    net_cost_sek: number
    battery_wear_cost_sek: number
    net_cost_incl_wear_sek: number
    slot_count: number
    error?: string
}

export type ThemeResponse = {
    current: string
    accent_index?: number
    themes: ThemeInfo[]
}

export type AdviceResponse = {
    advice: AdviceItem[]
    count?: number
    source?: string
    report?: unknown
}

export type AnalystReport = {
    analyzed_at?: string
    recommendations?: Record<string, unknown>
    [key: string]: unknown
}

export type SimulateResponse = {
    schedule: import('./types').ScheduleSlot[]
    meta?: unknown
}

export type ThemeSetResponse = {
    status?: string
    current?: string
    accent_index?: number
    theme?: ThemeInfo
}

export type HealthIssue = {
    category: string
    severity: 'critical' | 'warning' | 'info'
    message: string
    guidance: string
    entity_id?: string | null
    code?: string | null
    details?: Record<string, unknown> | null
    retry_in_s?: number | null
}

export type HealthResponse = {
    healthy: boolean
    issues: HealthIssue[]
    checked_at: string
    critical_count: number
    warning_count: number
}

export type AuroraDashboardResponse = import('./types').AuroraDashboardResponse
export type AuroraPerformanceData = import('./types').AuroraPerformanceData
export type DashboardBundleResponse = {
    status: StatusResponse | null
    config: ConfigResponse | null
    schedule: ScheduleResponse | null
    executor_status: ExecutorStatusResponse | null
    scheduler_status: SchedulerStatusResponse | null
    water_boost: {
        boost: boolean
        active?: boolean
        expires_at?: string
        source?: string
        heaters?: Record<string, { expires_at: string; remaining_seconds: number }>
    } | null
}
export type AuroraBriefingResponse = { briefing: string }
export type LogInfoResponse = {
    filename: string
    size_bytes: number
    last_modified: string
}

// Price Outlook Types (Tasks 3.1)
export type PriceLevel = 'cheap' | 'normal' | 'expensive' | 'unknown'
export type ConfidenceLevel = 'high' | 'medium' | 'low'

export type PriceOutlookDay = {
    date: string
    day_label: string
    days_ahead: number
    avg_spot_p50: number
    avg_spot_p10: number | null
    avg_spot_p90: number | null
    min_hour_p50: number
    max_hour_p50: number
    level: PriceLevel
    confidence: ConfidenceLevel
}

export type PriceOutlookResponse = {
    enabled: boolean
    days: PriceOutlookDay[]
    reference_avg: number | null
    status: string
}

export type PriceAccuracyResponse = {
    enabled: boolean
    d1_mae: number | null
    d1_bias: number | null
    sample_days: number
    status: string
}

export type PriceForecastSlot = {
    slot_start: string
    days_ahead: number
    spot_p10: number | null
    spot_p50: number | null
    spot_p90: number | null
    import_p50: number | null
    export_p50: number | null
    actual_spot?: number | null
}

export type PriceForecastStatusResponse = {
    enabled: boolean
    config: {
        min_training_samples: number
        model_name: string
    }
    model_available: boolean
    model_info: {
        name: string
        size_bytes: number
        last_modified: string
    } | null
    training_samples_count: number
}

export type AdviceItem = {
    category: string
    message: string
    priority: 'info' | 'warning' | 'error'
}

export type SystemHealthResponse = {
    learning: {
        total_runs: number
        status: string
        last_run: string | null
    }
    database: {
        size_mb: number
        slot_plans_count: number
        slot_observations_count: number
        health: string
    }
    planner: {
        last_run: string | null
        status: string
        next_scheduled: string | null
    }
    forecast: {
        pv_status: string
        load_status: string
        load_reason: string
    }
    system: {
        errors_24h: number
        uptime_hours: number
        version: string
    }
}

export type MonitorStatus = {
    running: boolean
    healthy: boolean
    last_cycle_at: string | null
    last_error: string | null
    invariants: Record<
        string,
        {
            name: string
            status: 'pass' | 'violation' | 'skipped'
            detail: string
            evaluated_at: string
        }
    >
    active_violations: { invariant: string; first_detected_at: string; detail: string }[]
}

export type TrainingStatusResponse = {
    is_training: boolean
    lock_age_seconds: number | null
    lock_status?: {
        locked: boolean
        stale: boolean
        lock_age_seconds: number | null
    }
    graduation_level?: {
        level: number
        label: string
        days_of_data: number
    }
    models: Record<
        string,
        {
            last_modified: string
            age_seconds: number
            size_bytes: number
        }
    >
}

export type TrainingHistoryResponse = {
    runs: {
        id: number
        run_date: string
        status: string
        training_type: string
        models_trained: string[]
        training_duration_seconds: number
        partial_failure: boolean
    }[]
    count: number
}

export type EVPlannedDay = {
    /** Local calendar date (YYYY-MM-DD) */
    date: string
    kwh: number
    /** known: every slot that day has a published price; estimated: rests on forecasts */
    basis: 'known' | 'estimated'
}

export type EVChargerState = {
    id: string
    name: string
    plugged_in: boolean
    /** Plug sensor or switch reads unavailable/unknown; plugged_in is the last known state */
    unreachable?: boolean
    soc_percent: number | null
    /** Resolved SoC status (null when no SoC sensor is configured) */
    soc_status?: 'live' | 'carried' | 'stale' | null
    /** Age in minutes of the last valid SoC reading (null when none since startup) */
    soc_age_minutes?: number | null
    power_kw: number | null
    target_soc_percent: number | null
    ready_by: string | null
    repeat: string | null
    ready_by_date: string | null
    deadline: string | null
    required_kwh: number | null
    delivered_kwh: number | null
    remaining_kwh: number | null
    /** Planned per-day estimate from today through the deadline day */
    planned_by_day?: EVPlannedDay[]
    /** Least-reliable price source used to price post-horizon deferral */
    deferral_price_source?: 'forecast' | 'trailing_average' | 'horizon_max' | null
    keep_on_after_target: boolean
    ha_ready_by_entity: string | null
    ha_target_soc_entity: string | null
    type: 'current' | 'binary'
    /** Manual-charge current range (current-type only, else null) */
    min_current_a?: number | null
    max_current_a?: number | null
    n_days: number | null
    status: 'on_track' | 'at_risk' | 'behind' | 'complete' | 'idle' | 'soc_unavailable'
    /** kWh the current plan will not deliver by the deadline (at_risk only) */
    shortfall_kwh?: number | null
    shortfall_reason?: 'grid_limit' | 'deadline_too_close' | 'cost_tradeoff' | null
    /** Grid import cap used for the grid_limit explanation */
    max_import_kw?: number | null
    source: 'api' | 'ha' | null
    externally_controlled: boolean
    last_updated: string | null
    last_planned_at: string | null
    /** every_n_days cycle anchor (YYYY-MM-DD), null for other repeat modes */
    anchor_date?: string | null
    /** Goal edited after the last plan, or a goal-triggered replan is queued/running */
    plan_pending?: boolean
    /** Plan schedules goal charging while the car is unplugged (awaiting plug-in) */
    assumed_plugged?: boolean
    /** Start (ISO) of the first upcoming slot with planned charging, null when none */
    planned_start?: string | null
    /** Active manual "charge now" override, null when none */
    manual_charge?: EVManualCharge | null
    /** Why the charger is disabled for planning (e.g. missing phases), null when enabled */
    disabled_reason?: string | null
}

export type EVManualCharge = {
    target_soc: number
    /** Requested amps (current-type only); null = charger's max_current_a */
    current_a: number | null
    started_at: string
}

/** Payload of the `ev_manual_charge_updated` websocket event. */
export type EVManualChargeUpdatedEvent = {
    chargers: Record<string, EVManualCharge & { expires_at: string }>
}

export type EVChargersResponse = EVChargerState[]

async function getJSON<T>(path: string, method: 'GET' | 'POST' | 'PUT' | 'DELETE' = 'GET', body?: unknown): Promise<T> {
    // Strip leading slash to make paths relative - works with base href for HA Ingress
    const relativePath = path.startsWith('/') ? path.slice(1) : path

    const options: RequestInit = {
        method,
        headers: { Accept: 'application/json', 'Content-Type': 'application/json' },
    }
    if (body !== undefined && (method === 'POST' || method === 'PUT' || method === 'DELETE')) {
        options.body = JSON.stringify(body)
    }
    const r = await fetch(relativePath, options)
    if (!r.ok) {
        const data = await r.json().catch(() => null)
        const rawDetail = data?.detail
        const detailMessage =
            typeof rawDetail === 'string'
                ? rawDetail
                : typeof rawDetail?.message === 'string'
                  ? rawDetail.message
                  : null
        throw new ApiError(detailMessage ?? `${path} -> ${r.status}`, r.status, rawDetail)
    }
    return r.json() as Promise<T>
}

export const Api = {
    dashboardBundle: () => getJSON<DashboardBundleResponse>('/api/dashboard/bundle'),
    schedule: () => getJSON<ScheduleResponse>('/api/schedule'),
    scheduleTodayWithHistory: () => getJSON<ScheduleTodayWithHistoryResponse>('/api/schedule/today_with_history'),
    status: () => getJSON<StatusResponse>('/api/status'),
    health: () => getJSON<HealthResponse>('/api/health'),
    version: () => getJSON<{ version: string }>('/api/version'),
    horizon: () => getJSON<HorizonResponse>('/api/forecast/horizon'),
    config: () => getJSON<ConfigResponse>('/api/config'),
    // REV UI23: Validate config without saving
    configValidate: () => getJSON<ConfigSaveResponse>('/api/config/validate'),
    // REV LCL01: Custom configSave that handles 400 validation errors
    configSave: async (payload: Record<string, unknown>): Promise<ConfigSaveResponse> => {
        const r = await fetch('api/config/save', {
            method: 'POST',
            headers: { Accept: 'application/json', 'Content-Type': 'application/json' },
            body: JSON.stringify(payload),
        })
        const data = await r.json()
        if (!r.ok) {
            const detail = data?.detail
            if (r.status === 400 && typeof detail === 'object' && detail) {
                const errors = Array.isArray(detail.errors) ? detail.errors : []
                const firstError = errors[0] as { message?: string; guidance?: string } | undefined
                const message = firstError
                    ? [firstError.message, firstError.guidance].filter(Boolean).join(': ')
                    : typeof detail.message === 'string'
                      ? detail.message
                      : 'Configuration error'
                throw new ApiError(message, r.status, detail)
            }
            throw new ApiError(`/api/config/save -> ${r.status}`, r.status, detail)
        }
        return data as ConfigSaveResponse
    },
    configReset: () => getJSON<{ status: string }>('/api/config/reset', 'POST'),
    setTheme: (payload: { theme: string; accent_index?: number | null }) =>
        getJSON<ThemeSetResponse>('/api/theme', 'POST', payload),
    haAverage: () => getJSON<HaAverageResponse>('/api/ha/average'),
    haTest: (payload: { url: string; token: string }) =>
        getJSON<{ status?: string; success?: boolean; message: string }>('/api/ha/test', 'POST', payload),
    haSaveConnection: (payload: { url: string; token: string }) =>
        getJSON<{ status: string; message: string }>('/api/ha/config', 'PUT', payload),
    haDiscovery: () => getJSON<HaDiscoveryResponse>('/api/ha/discovery'),
    haCoreConfig: () => getJSON<HaCoreConfigResponse>('/api/ha/core-config'),
    haEntities: () =>
        getJSON<{
            entities: {
                entity_id: string
                friendly_name: string
                domain: string
                unit_of_measurement?: string
                device_class?: string
                options?: string[]
            }[]
        }>('/api/ha/entities'),
    haServices: () => getJSON<{ services: string[] }>('/api/ha/services'),
    haEntityState: (entityId: string) =>
        getJSON<{ entity_id: string; state: string; attributes: Record<string, unknown> }>(
            `/api/ha/entity/${entityId}`,
        ),
    learningStatus: () => getJSON<LearningStatusResponse>('/api/learning/status'),
    learningHistory: () => getJSON<LearningHistoryResponse>('/api/learning/history'),
    learningTrainingStatus: () => getJSON<TrainingStatusResponse>('/api/learning/training-status'),
    learningTrainingHistory: (limit = 5) =>
        getJSON<TrainingHistoryResponse>(`/api/learning/training-history?limit=${limit}`),
    learningDailyMetrics: () => getJSON<LearningDailyMetricsResponse>('/api/learning/daily_metrics'),
    learningRun: () => getJSON<LearningRunResponse>('/api/learning/run', 'POST'),
    learningLoops: () => getJSON<LearningLoopsResponse>('/api/learning/loops'),
    learningTrain: () => getJSON<{ status: string; message: string }>('/api/learning/train', 'POST'),
    theme: () => getJSON<ThemeResponse>('/api/themes'),
    runPlanner: () => getJSON<{ status: string; message?: string }>('/api/run_planner', 'POST'),
    resetToOptimal: () => getJSON<{ status: string }>('/api/schedule/save', 'POST'),
    getAdvice: async (): Promise<AdviceResponse> => {
        const response = await fetch('api/analyst/advice')
        if (!response.ok) throw new Error('Failed to fetch advice')
        return response.json() as Promise<AdviceResponse>
    },
    analystRun: () => getJSON<AnalystReport>('/api/analyst/run'),
    debug: () => getJSON<DebugResponse>('/api/debug'),
    debugLogs: () => getJSON<DebugLogsResponse>('/api/debug/logs'),
    historySoc: (date: string | 'today' = 'today') => getJSON<HistorySocResponse>(`/api/history/soc?date=${date}`),
    forecastEval: () => getJSON<unknown>('/api/forecast/eval'),
    forecastDay: (date?: string) => getJSON<unknown>(date ? `/api/forecast/day?date=${date}` : '/api/forecast/day'),
    forecastRunEval: (daysBack = 7) =>
        getJSON<{ status: string }>('/api/forecast/run_eval', 'POST', { days_back: daysBack }),
    forecastRunForward: (horizonHours = 48) =>
        getJSON<{ status: string }>('/api/forecast/run_forward', 'POST', { horizon_hours: horizonHours }),
    schedulerStatus: () => getJSON<SchedulerStatusResponse>('/api/scheduler/status'),
    aurora: {
        dashboard: () => getJSON<AuroraDashboardResponse>('/api/aurora/dashboard'),
        briefing: (payload: AuroraDashboardResponse) =>
            getJSON<AuroraBriefingResponse>('/api/aurora/briefing', 'POST', payload),
        toggleReflex: (enabled: boolean) =>
            getJSON<{ status: string; enabled: boolean }>('/api/aurora/config/toggle_reflex', 'POST', { enabled }),
    },
    performanceData: (days = 7) => getJSON<AuroraPerformanceData>(`/api/performance/data?days=${days}`),
    // Executor controls
    executor: {
        status: () => getJSON<ExecutorStatusResponse>('/api/executor/status'),
        run: () => getJSON<unknown>('/api/executor/run', 'POST'),
        pause: (durationMinutes = 60) =>
            getJSON<{ success: boolean; paused_at?: string; message?: string; error?: string }>(
                '/api/executor/pause',
                'POST',
                { duration_minutes: durationMinutes },
            ),
        resume: () =>
            getJSON<{
                success: boolean
                resumed_at?: string
                paused_duration_minutes?: number
                message?: string
                error?: string
            }>('/api/executor/resume', 'POST'),
        quickAction: {
            get: () => getJSON<{ quick_action: unknown | null }>('/api/executor/quick-action'),
            set: (action: string, duration_minutes: number, params?: Record<string, unknown>) =>
                getJSON<{ status: string }>('/api/executor/quick-action', 'POST', {
                    action,
                    duration_minutes,
                    params,
                }),
            clear: () => getJSON<unknown>('/api/executor/quick-action', 'DELETE'),
        },
        health: () => getJSON<ExecutorHealthResponse>('/api/executor/health'),
        loadBalancerStatus: () => getJSON<LoadBalancerStatusResponse>('/api/executor/load-balancer/status'),
        testNotification: () =>
            getJSON<{ status: string; message: string }>('/api/executor/notifications/test', 'POST'),
    },
    waterBoost: {
        status: () =>
            getJSON<{
                boost: boolean
                active?: boolean
                expires_at?: string
                heaters?: Record<string, { expires_at: string; remaining_seconds: number }>
            }>('/api/water/boost'),
        start: (durationMinutes: number) =>
            getJSON<{ success: boolean; expires_at?: string; duration_minutes?: number; heater_ids?: string[] }>(
                '/api/water/boost',
                'POST',
                { duration_minutes: durationMinutes },
            ),
        startFor: (durationMinutes: number, heaterIds: string[]) =>
            getJSON<{ success: boolean; expires_at?: string; duration_minutes?: number; heater_ids?: string[] }>(
                '/api/water/boost',
                'POST',
                { duration_minutes: durationMinutes, heater_ids: heaterIds },
            ),
        cancel: (heaterIds?: string[]) =>
            getJSON<{ success: boolean; was_active?: boolean; heater_ids?: string[] }>(
                '/api/water/boost',
                'DELETE',
                heaterIds ? { heater_ids: heaterIds } : undefined,
            ),
    },
    // Energy stats from HA sensors
    energyToday: () => getJSON<EnergyTodayResponse>('/api/energy/today'),
    energyRange: (
        period: 'today' | 'yesterday' | 'week' | 'month' | 'custom',
        start_date?: string,
        end_date?: string,
    ) => {
        let url = `/api/energy/range?period=${period}`
        if (period === 'custom' && start_date && end_date) {
            url += `&start_date=${start_date}&end_date=${end_date}`
        }
        return getJSON<EnergyRangeResponse>(url)
    },
    energyCostSeries: (
        period: 'today' | 'yesterday' | 'week' | 'month' | 'custom',
        start_date?: string,
        end_date?: string,
    ) => {
        let url = `/api/energy/cost-series?period=${period}`
        if (period === 'custom' && start_date && end_date) {
            url += `&start_date=${start_date}&end_date=${end_date}`
        }
        return getJSON<unknown>(url).then(parseCostSeriesResponse)
    },
    // Log management
    logInfo: () => getJSON<LogInfoResponse>('/api/system/log-info'),
    systemHealth: () => getJSON<SystemHealthResponse>('/api/system/health'),
    monitors: () => getJSON<MonitorStatus>('/api/system/monitors'),
    clearLogs: () => getJSON<{ status: string }>('/api/system/logs', 'DELETE'),
    // Load Disaggregation Debug (Rev ARC12)
    loadsDebug: () => getJSON<LoadsDebugResponse>('/api/loads/debug'),
    // Profile Management (Rev IP4)
    listProfiles: () => getJSON<import('../pages/settings/types').InverterProfile[]>('/api/profiles'),
    profileSuggestions: (profile: string) =>
        getJSON<ProfileSuggestionsResponse>(`/api/profiles/${encodeURIComponent(profile)}/suggestions`),
    setup: {
        suggestions: (roles?: string[]) => {
            const query = roles?.length ? `?roles=${encodeURIComponent(roles.join(','))}` : ''
            return getJSON<SetupSuggestionsResponse>(`/api/setup/suggestions${query}`)
        },
        readiness: () => getJSON<ReadinessResponse>('/api/setup/readiness'),
        onboarding: () => getJSON<OnboardingProgress>('/api/setup/onboarding'),
        saveOnboarding: (progress: OnboardingProgress) =>
            getJSON<OnboardingProgress>('/api/setup/onboarding', 'PUT', {
                status: progress.status,
                current_step: progress.current_step,
                completed_steps: progress.completed_steps,
            }),
    },
    // Price Forecast (Tasks 3.2)
    priceForecast: {
        outlook: () => getJSON<PriceOutlookResponse>('/api/price-forecast/outlook'),
        accuracy: () => getJSON<PriceAccuracyResponse>('/api/price-forecast/accuracy'),
        forecasts: (includeActuals?: boolean) =>
            getJSON<{ status: string; message: string; forecasts: PriceForecastSlot[] }>(
                '/api/price-forecast' + (includeActuals ? '?include_actuals=true' : ''),
            ),
        priceForecastStatus: () => getJSON<PriceForecastStatusResponse>('/api/price-forecast/status'),
    },
    // EV Chargers (Module 5)
    ev: {
        chargers: () => getJSON<EVChargersResponse>('/api/ev/chargers'),
        setSchedule: (
            id: string,
            body: {
                target_soc_percent: number | null
                ready_by?: string | null
                repeat?: string | null
                ready_by_date?: string | null
                n_days?: number | null
                keep_on_after_target?: boolean | null
            },
        ) => getJSON<EVChargerState>(`/api/ev/chargers/${id}/schedule`, 'POST', body),
        manualCharge: {
            start: (id: string, body: { target_soc: number; current_a?: number | null }) =>
                getJSON<{ success: boolean } & EVManualCharge>(`/api/ev/chargers/${id}/manual-charge`, 'POST', body),
            stop: (id: string) =>
                getJSON<{ success: boolean; was_active: boolean }>(`/api/ev/chargers/${id}/manual-charge`, 'DELETE'),
        },
    },
}

export const Sel = {
    socValue: (s: StatusResponse) => s.current_soc?.value,
    pvDays: (h: HorizonResponse) => h.pv_forecast_days ?? h.pv_days_schedule ?? null,
    wxDays: (h: HorizonResponse) => h.weather_forecast_days ?? null,
}
