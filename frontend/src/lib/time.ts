export function clampTo48hISO(isoList: string[], nowIso?: string) {
  const now = nowIso ? new Date(nowIso).getTime() : Date.now()
  const end = now + 48 * 3600 * 1000
  return isoList
    .map((t, idx) => ({ idx, time: new Date(t).getTime() }))
    .map(({ idx, time }) => (time >= now && time < end ? idx : -1))
    .filter((idx) => idx >= 0)
}
