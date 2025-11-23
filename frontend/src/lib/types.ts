export type ScheduleSlot = {
  start_time: string; end_time?: string;
  import_price_sek_kwh?: number;
  pv_forecast_kwh?: number; load_forecast_kwh?: number;
  battery_charge_kw?: number; battery_discharge_kw?: number;
  charge_kw?: number; discharge_kw?: number; // legacy
  water_heating_kw?: number; export_kwh?: number;
  projected_soc_percent?: number; soc_target_percent?: number;
  is_historical?: boolean; slot_number?: number;
  // Execution history overlays (for today_with_history)
  is_executed?: boolean;
  soc_actual_percent?: number;
  actual_charge_kw?: number;
  actual_export_kw?: number;
  actual_load_kwh?: number;
  actual_pv_kwh?: number;
};

export type Status = { value: number; timestamp: string; planned_at?: string; planner_version?: string; };

export type AuroraGraduation = {
  label: 'infant' | 'statistician' | 'graduate' | string;
  runs: number;
};

export type AuroraRiskProfile = {
  persona: string;
  base_factor: number;
  mode?: string;
  max_factor?: number | null;
  static_factor?: number | null;
  raw?: Record<string, any>;
};

export type AuroraWeatherVolatility = {
  cloud_volatility: number;
  temp_volatility: number;
  overall: number;
};

export type AuroraHorizonSlot = {
  slot_start: string;
  base: { pv_kwh: number; load_kwh: number };
  correction: { pv_kwh: number; load_kwh: number };
  final: { pv_kwh: number; load_kwh: number };
};

export type AuroraHorizon = {
  start: string;
  end: string;
  forecast_version?: string;
  slots: AuroraHorizonSlot[];
};

export type AuroraHistoryDay = {
  date: string;
  total_correction_kwh: number;
  pv_correction_kwh?: number;
  load_correction_kwh?: number;
};

export type AuroraDashboardResponse = {
  identity: { graduation: AuroraGraduation };
  state: {
    risk_profile: AuroraRiskProfile;
    weather_volatility: AuroraWeatherVolatility;
  };
  horizon: AuroraHorizon;
  history: { correction_volume_days: AuroraHistoryDay[] };
  generated_at: string;
};
