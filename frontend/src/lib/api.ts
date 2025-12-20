export type StatusResponse = {
  current_soc?: { value: number; timestamp: string; source?: string }
  local?: { planned_at?: string; planner_version?: string; s_index?: any }
  db?: { planned_at?: string; planner_version?: string; s_index?: any } | { error?: string }
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
    [key: string]: any
  }
}
export type ScheduleTodayWithHistoryResponse = {
  slots: import('./types').ScheduleSlot[]
  timezone?: string
}

export type ConfigResponse = {
  system?: { battery?: { capacity_kwh?: number } }
  [key: string]: any
}
export type ConfigSaveError = { field?: string; message: string }
export type ConfigSaveResponse = { status?: string; errors?: ConfigSaveError[] }

export type HaAverageResponse = {
  average_load_kw?: number
  daily_kwh?: number
  [key: string]: any
}

export type WaterTodayResponse = {
  source?: 'home_assistant' | 'sqlite'
  water_kwh_today?: number
  [key: string]: any
}

export type LearningStatusResponse = {
  enabled?: boolean
  last_updated?: string
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
  [key: string]: any
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
    [key: string]: any
  }
  [key: string]: any
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
  [key: string]: any
}

export type LearningLoopsResponse = {
  forecast_calibrator?: { status?: string; result?: any }
  threshold_tuner?: { status?: string; result?: any }
  s_index_tuner?: { status?: string; result?: any }
  export_guard_tuner?: { status?: string; result?: any }
  [key: string]: any
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
  [key: string]: any
}

export type ThemeInfo = {
  name: string
  background: string
  foreground: string
  palette: string[]
}

export type ThemeResponse = {
  current: string
  accent_index?: number
  themes: ThemeInfo[]
}

export type AdviceResponse = {
  advice: string
  report: any
}

export type AnalystReport = {
  analyzed_at?: string
  recommendations?: Record<string, any>
  [key: string]: any
}

export type SimulateResponse = {
  schedule: import('./types').ScheduleSlot[]
  meta?: any
}

export type ThemeSetResponse = {
  status?: string
  current?: string
  accent_index?: number
  theme?: ThemeInfo
}

export type AuroraDashboardResponse = import('./types').AuroraDashboardResponse
export type AuroraBriefingResponse = { briefing: string }

async function getJSON<T>(path: string, method: 'GET' | 'POST' | 'DELETE' = 'GET', body?: any): Promise<T> {
  const options: RequestInit = {
    method,
    headers: { Accept: 'application/json', 'Content-Type': 'application/json' }
  }
  if (body && (method === 'POST' || method === 'DELETE')) {
    options.body = JSON.stringify(body)
  }
  const r = await fetch(path, options)
  if (!r.ok) throw new Error(`${path} -> ${r.status}`)
  return r.json() as Promise<T>
}

export const Api = {
  schedule: () => getJSON<ScheduleResponse>('/api/schedule'),
  scheduleTodayWithHistory: () => getJSON<ScheduleTodayWithHistoryResponse>('/api/schedule/today_with_history'),
  status: () => getJSON<StatusResponse>('/api/status'),
  horizon: () => getJSON<HorizonResponse>('/api/forecast/horizon'),
  config: () => getJSON<ConfigResponse>('/api/config'),
  configSave: (payload: Record<string, any>) =>
    getJSON<ConfigSaveResponse>('/api/config/save', 'POST', payload),
  configReset: () => getJSON<{ status: string }>('/api/config/reset', 'POST'),
  setTheme: (payload: { theme: string; accent_index?: number | null }) =>
    getJSON<ThemeSetResponse>('/api/theme', 'POST', payload),
  haAverage: () => getJSON<HaAverageResponse>('/api/ha/average'),
  haWaterToday: () => getJSON<WaterTodayResponse>('/api/ha/water_today'),
  learningStatus: () => getJSON<LearningStatusResponse>('/api/learning/status'),
  learningHistory: () => getJSON<LearningHistoryResponse>('/api/learning/history'),
  learningDailyMetrics: () => getJSON<LearningDailyMetricsResponse>('/api/learning/daily_metrics'),
  learningRun: () => getJSON<LearningRunResponse>('/api/learning/run', 'POST'),
  learningLoops: () => getJSON<LearningLoopsResponse>('/api/learning/loops'),
  theme: () => getJSON<ThemeResponse>('/api/themes'),
  runPlanner: () => getJSON<{ status: string; message?: string }>('/api/run_planner', 'POST'),
  loadServerPlan: () => getJSON<ScheduleResponse>('/api/db/current_schedule'),
  pushToDb: () => getJSON<{ status: string; rows?: number }>('/api/db/push_current', 'POST'),
  resetToOptimal: () => getJSON<{ status: string }>('/api/schedule/save', 'POST'),
  simulate: async (payload: any): Promise<ScheduleResponse> => {
    const response = await fetch('/api/simulate', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify(payload),
    })
    if (!response.ok) throw new Error('Simulation failed')
    return response.json() as Promise<ScheduleResponse>
  },
  getAdvice: async (): Promise<AdviceResponse> => {
    const response = await fetch('/api/analyst/advice')
    if (!response.ok) throw new Error('Failed to fetch advice')
    return response.json() as Promise<AdviceResponse>
  },
  analystRun: () => getJSON<AnalystReport>('/api/analyst/run'),
  debug: () => getJSON<DebugResponse>('/api/debug'),
  debugLogs: () => getJSON<DebugLogsResponse>('/api/debug/logs'),
  historySoc: (date: string | 'today' = 'today') =>
    getJSON<HistorySocResponse>(`/api/history/soc?date=${date}`),
  forecastEval: () => getJSON<any>('/api/forecast/eval'),
  forecastDay: (date?: string) =>
    getJSON<any>(date ? `/api/forecast/day?date=${date}` : '/api/forecast/day'),
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
  performanceData: (days = 7) => getJSON<any>(`/api/performance/data?days=${days}`),
  // Executor controls
  executor: {
    status: () => getJSON<any>('/api/executor/status'),
    run: () => getJSON<any>('/api/executor/run', 'POST'),
    pause: () => getJSON<{ success: boolean; paused_at?: string; message?: string; error?: string }>('/api/executor/pause', 'POST'),
    resume: () => getJSON<{ success: boolean; resumed_at?: string; paused_duration_minutes?: number; message?: string; error?: string }>('/api/executor/resume', 'POST'),
  },
  // Water boost
  waterBoost: {
    status: () => getJSON<{ water_boost: { expires_at: string; remaining_minutes: number; temp_target: number } | null }>('/api/water/boost'),
    start: (durationMinutes: number) => getJSON<{ success: boolean; expires_at?: string; duration_minutes?: number; temp_target?: number }>('/api/water/boost', 'POST', { duration_minutes: durationMinutes }),
    cancel: () => getJSON<{ success: boolean; was_active?: boolean }>('/api/water/boost', 'DELETE'),
  },
}

export const Sel = {
  socValue: (s: StatusResponse) => s.current_soc?.value,
  pvDays: (h: HorizonResponse) => h.pv_forecast_days ?? h.pv_days_schedule ?? null,
  wxDays: (h: HorizonResponse) => h.weather_forecast_days ?? null,
}
