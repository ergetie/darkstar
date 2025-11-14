export type StatusResponse = {
  current_soc?: { value: number; timestamp: string; source?: string }
  local?: { planned_at?: string; planner_version?: string }
  db?: { planned_at?: string; planner_version?: string } | { error?: string }
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

export type ScheduleResponse = { schedule: import('./types').ScheduleSlot[] }

export type ConfigResponse = {
  system?: { battery?: { capacity_kwh?: number } }
  [key: string]: any
}
export type ConfigSaveResponse = { status?: string }

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

export type LearningHistoryResponse = {
  runs: LearningHistoryEntry[]
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

async function getJSON<T>(path: string, method: 'GET' | 'POST' = 'GET', body?: any): Promise<T> {
  const options: RequestInit = { 
    method,
    headers: { Accept: 'application/json', 'Content-Type': 'application/json' }
  }
  if (body && method === 'POST') {
    options.body = JSON.stringify(body)
  }
  const r = await fetch(path, options)
  if (!r.ok) throw new Error(`${path} -> ${r.status}`)
  return r.json() as Promise<T>
}

export const Api = {
  schedule: () => getJSON<ScheduleResponse>('/api/schedule'),
  status: () => getJSON<StatusResponse>('/api/status'),
  horizon: () => getJSON<HorizonResponse>('/api/forecast/horizon'),
  config: () => getJSON<ConfigResponse>('/api/config'),
  configSave: (payload: Record<string, any>) =>
    getJSON<ConfigSaveResponse>('/api/config/save', 'POST', payload),
  configReset: () => getJSON<{status: string}>('/api/config/reset', 'POST'),
  setTheme: (payload: { theme: string; accent_index?: number | null }) =>
    getJSON<ThemeSetResponse>('/api/theme', 'POST', payload),
  haAverage: () => getJSON<HaAverageResponse>('/api/ha/average'),
  haWaterToday: () => getJSON<WaterTodayResponse>('/api/ha/water_today'),
  learningStatus: () => getJSON<LearningStatusResponse>('/api/learning/status'),
  learningHistory: () => getJSON<LearningHistoryResponse>('/api/learning/history'),
  learningRun: () => getJSON<LearningRunResponse>('/api/learning/run', 'POST'),
  learningLoops: () => getJSON<LearningLoopsResponse>('/api/learning/loops'),
  theme: () => getJSON<ThemeResponse>('/api/themes'),
  runPlanner: () => getJSON<{ status: string; message?: string }>('/api/run_planner', 'POST'),
  loadServerPlan: () => getJSON<ScheduleResponse>('/api/db/current_schedule'),
  pushToDb: () => getJSON<{ status: string; rows?: number }>('/api/db/push_current', 'POST'),
  resetToOptimal: () => getJSON<{ status: string }>('/api/schedule/save', 'POST'),
  simulate: (payload: any) => getJSON<SimulateResponse>('/api/simulate', 'POST', payload),
  debug: () => getJSON<DebugResponse>('/api/debug'),
  debugLogs: () => getJSON<DebugLogsResponse>('/api/debug/logs'),
  historySoc: (date: string | 'today' = 'today') =>
    getJSON<HistorySocResponse>(`/api/history/soc?date=${date}`),
}

export const Sel = {
  socValue: (s: StatusResponse) => s.current_soc?.value,
  pvDays: (h: HorizonResponse) => h.pv_forecast_days ?? h.pv_days_schedule ?? null,
  wxDays: (h: HorizonResponse) => h.weather_forecast_days ?? null,
}
