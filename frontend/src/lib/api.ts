async function getJSON<T>(path: string): Promise<T> {
  const r = await fetch(path, { headers: { Accept: "application/json" } })
  if (!r.ok) throw new Error(`${path} -> ${r.status}`)
  return r.json() as Promise<T>
}

export const Api = {
  schedule: () => getJSON<{ slots: import("./types").ScheduleSlot[] }>("/api/schedule"),
  status:   () => getJSON<{ soc: import("./types").Status }>("/api/status"),
  horizon:  () => getJSON<{ pv_days?: number; weather_days?: number; [k: string]: number }>("/api/forecast/horizon"),
}
