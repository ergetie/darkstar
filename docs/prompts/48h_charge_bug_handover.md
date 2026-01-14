# Bug Handover: 48h View Missing Historical Charge Data

## Problem Summary
User reports that historical charge actions (00:00-07:30 today) are visible in 24h view but NOT in 48h view. Discharge is visible in BOTH views. Current time: 19:00.

## Verified Facts

### 1. API Data is Correct
```bash
docker exec darkstar curl -s http://localhost:5000/api/schedule/today_with_history | jq '.slots[:5]'
```
Returns slots with `battery_charge_kw: 6.34`, `5.95`, etc. for 00:00-07:30 slots.

### 2. Environment
- Server timezone: `Europe/Stockholm` (+01:00)
- Browser timezone: Matches server (offset = -60)
- No console errors when switching views
- Backend running in Docker on port 5000

### 3. Code State
- Both 24h and 48h views use `Api.scheduleTodayWithHistory()` (line 816-821 in ChartCard.tsx)
- Both views build charge data identically (lines 1028-1031 for 24h, 1174 for 48h)
- Filtering logic: 24h uses `filterSlotsByDay(slots, day)`, 48h uses `slots.filter(slot => isToday(slot.start_time) || isTomorrow(slot.start_time))`

### 4. Recent Changes
- REV H4: Added `planned_water_heating_kwh` to schema, fixed `soc_target_percent` mapping
- Fixed API to include tomorrow's slots (changed line 164 in schedule.py)

## Suspected Issue
The 48h view's `buildLiveData` function (lines 1088-1228) is filtering or indexing slots differently than 24h view, causing historical charge to be excluded. Both receive the same API data but process it differently.

## Next Steps to Debug
1. Add console.log to line 932 in ChartCard.tsx to see filtered slot count for 48h
2. Add console.log to line 1138-1141 to verify slotByTime map population
3. Add console.log inside the bucket loop (line 1158-1197) to check if slots are being found during lookup
4. Compare bucketStart timestamps to slot timestamps to verify alignment

## Files to Check
- `/home/s/sync/documents/projects/darkstar/frontend/src/components/ChartCard.tsx` (lines 922-1228)
- `/home/s/sync/documents/projects/darkstar/frontend/src/lib/time.ts` (isToday/isTomorrow functions)
- `/home/s/sync/documents/projects/darkstar/backend/api/routers/schedule.py` (API endpoint)

## Known Working
- API returns correct data with charge values
- 24h view displays correctly
- Discharge works in both views
- Timezone handling is correct
