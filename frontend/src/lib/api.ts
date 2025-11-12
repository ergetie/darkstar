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

async function getJSON<T>(path: string): Promise<T> {
  const r = await fetch(path, { headers: { Accept: 'application/json' } })
  if (!r.ok) throw new Error(`${path} -> ${r.status}`)
  return r.json() as Promise<T>
}

export const Api = {
  schedule: () => getJSON<ScheduleResponse>('/api/schedule'),
  status: () => getJSON<StatusResponse>('/api/status'),
  horizon: () => getJSON<HorizonResponse>('/api/forecast/horizon'),
}

export const Sel = {
  socValue: (s: StatusResponse) => s.current_soc?.value,
  pvDays: (h: HorizonResponse) => h.pv_forecast_days ?? h.pv_days_schedule ?? null,
  wxDays: (h: HorizonResponse) => h.weather_forecast_days ?? null,
}
