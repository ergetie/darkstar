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

export function ymd(date: Date): string {
  return date.toISOString().slice(0, 10)
}

export function isToday(dateIso: string, now = new Date()): boolean {
  return ymd(isoToLocal(dateIso)) === ymd(now)
}

export function isTomorrow(dateIso: string, now = new Date()): boolean {
  const t = new Date(now)
  t.setDate(t.getDate() + 1)
  return ymd(isoToLocal(dateIso)) === ymd(t)
}

export function formatHM(dateIso: string): string {
  const d = isoToLocal(dateIso)
  return new Intl.DateTimeFormat('sv-SE', {
    hour: '2-digit',
    minute: '2-digit',
    timeZone: TZ,
  }).format(d)
}

export type DaySel = 'today' | 'tomorrow'

export function filterSlotsByDay<T extends { start_time: string }>(
  slots: T[],
  sel: DaySel,
  now = new Date(),
): T[] {
  return slots.filter((s) =>
    sel === 'today' ? isToday(s.start_time, now) : isTomorrow(s.start_time, now),
  )
}
