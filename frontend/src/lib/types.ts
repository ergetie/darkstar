export type ScheduleSlot = {
    start_time: string
    end_time?: string
    import_price_sek_kwh?: number
    pv_forecast_kwh?: number
    load_forecast_kwh?: number
    battery_charge_kw?: number
    battery_discharge_kw?: number
    charge_kw?: number
    discharge_kw?: number // legacy
    water_heating_kw?: number
    export_kwh?: number
    projected_soc_percent?: number
    soc_target_percent?: number
    is_historical?: boolean
    slot_number?: number
    // Execution history overlays (for today_with_history)
    is_executed?: boolean
    soc_actual_percent?: number
    actual_soc?: number // Backend key for SOC actual
    actual_charge_kw?: number
    actual_export_kw?: number
    actual_load_kwh?: number
    actual_pv_kwh?: number
}

export type Status = { value: number; timestamp: string; planned_at?: string; planner_version?: string }

export type AuroraGraduation = {
    label: 'infant' | 'statistician' | 'graduate' | string
    runs: number
}

export type AuroraRiskProfile = {
    persona: string
    base_factor: number
    risk_appetite?: number
    current_factor?: number | null
    raw_factor?: number | null
    mode?: string
    max_factor?: number | null
    static_factor?: number | null
    raw?: Record<string, unknown>
}

export type AuroraPerformanceData = {
    soc_series: { time: string; planned: number; actual: number }[]
    cost_series: { date: string; planned: number; realized: number }[]
}

export type AuroraWeatherVolatility = {
    cloud_volatility: number
    temp_volatility: number
    overall: number
}

export type AuroraHorizonSlot = {
    slot_start: string
    base: { pv_kwh: number; load_kwh: number }
    correction: { pv_kwh: number; load_kwh: number }
    final: { pv_kwh: number; load_kwh: number }
    probabilistic?: {
        pv_p10: number | null
        pv_p90: number | null
        load_p10: number | null
        load_p90: number | null
    }
}

export type AuroraHorizon = {
    start: string
    end: string
    forecast_version?: string
    slots: AuroraHorizonSlot[]
    history_series?: {
        pv: {
            slot_start: string
            actual: number | null
            p10?: number | null
            p90?: number | null
            forecast?: number | null
        }[]
        load: {
            slot_start: string
            actual: number | null
            p10?: number | null
            p90?: number | null
            forecast?: number | null
        }[]
    }
}

export type AuroraHistoryDay = {
    date: string
    total_correction_kwh: number
    pv_correction_kwh?: number
    load_correction_kwh?: number
}

export type StrategyEvent = {
    timestamp: string
    type: string
    message: string
    details?: Record<string, unknown>
}

export type AuroraDashboardResponse = {
    identity: { graduation: AuroraGraduation }
    state: {
        risk_profile: AuroraRiskProfile
        weather_volatility: AuroraWeatherVolatility
        auto_tune_enabled: boolean
        reflex_enabled?: boolean
    }
    horizon: AuroraHorizon
    history: {
        correction_volume_days: AuroraHistoryDay[]
        strategy_events?: StrategyEvent[]
    }
    metrics?: {
        mae_pv_aurora?: number | null
        mae_pv_baseline?: number | null
        mae_load_aurora?: number | null
        mae_load_baseline?: number | null
        max_price_spread?: number | null
        forecast_bias?: number | null
    }
    generated_at: string
}

export type ToastVariant = 'success' | 'error' | 'warning' | 'info'

export interface Toast {
    id: string
    message: string
    description?: string
    variant: ToastVariant
}
