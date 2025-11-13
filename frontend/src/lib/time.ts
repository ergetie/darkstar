export function clampTo48hISO(isoList: string[], nowIso?: string) {
  const now = nowIso ? new Date(nowIso).getTime() : Date.now()
  const end = now + 48 * 3600 * 1000
  return isoList
    .map((t, idx) => ({ idx, time: new Date(t).getTime() }))
    .map(({ idx, time }) => (time >= now && time < end ? idx : -1))
    .filter((idx) => idx >= 0)
}

const TZ = 'Europe/Stockholm'

export function isoToLocal(dateIso: string): Date {
  const d = new Date(dateIso)
  return d
}

export function ymdLocal(date: Date, tz: string = TZ): string {
  // Format YYYY-MM-DD in the provided timezone using Intl
  const fmt = new Intl.DateTimeFormat('sv-SE', {
    year: 'numeric', month: '2-digit', day: '2-digit', timeZone: tz,
  })
  // sv-SE yields YYYY-MM-DD already
  return fmt.format(date)
}

export function isToday(dateIso: string, now = new Date()): boolean {
  return ymdLocal(isoToLocal(dateIso)) === ymdLocal(now)
}

export function isTomorrow(dateIso: string, now = new Date()): boolean {
  const t = new Date(now)
  t.setDate(t.getDate() + 1)
  return ymdLocal(isoToLocal(dateIso)) === ymdLocal(t)
}

export function formatHour(dateIso: string): string {
  const d = isoToLocal(dateIso)
  return new Intl.DateTimeFormat('sv-SE', { hour: '2-digit', minute: '2-digit', timeZone: TZ }).format(d)
}

export type DaySel = 'today' | 'tomorrow'

export function filterSlotsByDay<T extends { start_time: string }>(
  slots: T[],
  sel: DaySel,
  now = new Date(),
): T[] {
  const filtered = slots.filter((s) =>
    sel === 'today' ? isToday(s.start_time, now) : isTomorrow(s.start_time, now),
  )
  return filtered
}
