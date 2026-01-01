import Card from './Card'
import { useEffect, useRef, useState } from 'react'
import { Chart as ChartJS, ChartConfiguration } from 'chart.js/auto'
import type { Chart } from 'chart.js/auto'
import { sampleChart } from '../lib/sample'
import { Api } from '../lib/api'
import type { ScheduleSlot } from '../lib/types'
import { filterSlotsByDay, formatHour, DaySel, isToday, isTomorrow } from '../lib/time'
// Note: chartjs-plugin-annotation is not used for the
// NOW marker; we use a CSS overlay instead to avoid
// config recursion issues with the Chart.js proxies.

const chartOptions: ChartConfiguration['options'] = {
    maintainAspectRatio: false,
    spanGaps: false,
    animation: false,
    plugins: {
        legend: {
            display: false,
            labels: {
                color: '#e6e9ef',
                boxWidth: 10,
                font: { size: 12 },
                filter: () => false,
            },
        },
        tooltip: {
            enabled: true,
            mode: 'index',
            intersect: false,
            backgroundColor: 'rgba(30, 30, 46, 0.95)',
            titleColor: '#e6e9ef',
            bodyColor: '#a6b0bf',
            borderColor: 'rgba(255, 255, 255, 0.1)',
            borderWidth: 1,
            padding: 12,
            displayColors: true,
            // Nudge the tooltip away from the exact cursor/data point
            caretPadding: 8,
            yAlign: 'bottom',
            callbacks: {
                title: function (context) {
                    return context[0].label
                },
                label: function (context) {
                    const datasetLabel = context.dataset.label || ''
                    const value = context.parsed.y
                    if (value === null || value === undefined) return null

                    let formattedValue = value.toFixed(2)
                    let unit = ''

                    if (datasetLabel.includes('SEK/kWh')) {
                        formattedValue = value.toFixed(2)
                        unit = ' SEK/kWh'
                    } else if (datasetLabel.includes('kW')) {
                        formattedValue = value.toFixed(1)
                        unit = ' kW'
                    } else if (datasetLabel.includes('kWh')) {
                        formattedValue = value.toFixed(2)
                        unit = ' kWh'
                    } else if (datasetLabel.includes('%')) {
                        formattedValue = value.toFixed(1)
                        unit = '%'
                    }

                    return `${datasetLabel}: ${formattedValue}${unit}`
                },
            },
        },
    },
    scales: {
        x: {
            grid: { color: 'rgba(255,255,255,0.06)' },
            ticks: {
                color: '#a6b0bf',
                maxRotation: 0,
                autoSkip: false,
                callback: function (value, index, ticks) {
                    // Show only full hours as HH on the axis; keep labels as HH:mm
                    const label = (this as any)?.getLabelForValue
                        ? (this as any).getLabelForValue(value)
                        : (ticks[index] as any)?.label
                    if (typeof label !== 'string') return ''
                    const parts = label.split(':')
                    if (parts.length < 2) return ''
                    const [hh, mm] = parts
                    return mm === '00' ? hh : ''
                },
            },
        },
        y: {
            position: 'right',
            min: 0,
            max: 8,
            title: {
                display: false,
                text: 'SEK/kWh',
                color: '#a6b0bf',
            },
            grid: { color: 'rgba(255,255,255,0.06)' },
            ticks: { color: '#a6b0bf', display: false },
        },
        y1: {
            position: 'left',
            min: 0,
            max: 9,
            title: {
                display: false,
                text: 'kW',
                color: '#a6b0bf',
            },
            grid: { display: false },
            ticks: { color: '#a6b0bf', display: false },
        },
        y2: {
            position: 'left',
            min: 0,
            max: 9,
            title: {
                display: false,
                text: 'kWh',
                color: '#a6b0bf',
            },
            grid: { display: false },
            ticks: { color: '#a6b0bf', display: false },
            display: false,
        },
        y3: {
            position: 'right',
            min: 0,
            max: 100,
            title: {
                display: true,
                text: '%',
                color: '#a6b0bf',
            },
            grid: { display: false },
            ticks: { color: '#a6b0bf' },
            display: false,
        },
        // Dedicated axis for PV/history so we can zoom it
        y4: {
            position: 'left',
            min: 0,
            max: 1.5,
            title: {
                display: false,
                text: 'kW (PV)',
                color: '#a6b0bf',
            },
            grid: { display: false },
            ticks: { color: '#a6b0bf', display: false },
        },
    },
}

type ChartValues = {
    labels: string[]
    price: (number | null)[]
    pv: (number | null)[]
    load: (number | null)[]
    charge?: (number | null)[]
    discharge?: (number | null)[]
    export?: (number | null)[]
    water?: (number | null)[]
    socTarget?: (number | null)[]
    socProjected?: (number | null)[]
    socActual?: (number | null)[]
    hasNoData?: boolean
    day?: DaySel
    nowIndex?: number | null
}

const createChartData = (values: ChartValues, themeColors: Record<string, string> = {}) => {
    // Use theme colors with fallbacks to Material Design colors
    const getColor = (paletteIndex: number, fallback: string) => {
        const themeKey = `palette = ${paletteIndex}`
        return themeColors[themeKey] || fallback
    }

    const baseData = {
        labels: values.labels,
        datasets: [
            {
                type: 'line',
                label: 'Import Price (SEK/kWh)',
                data: values.price,
                borderColor: getColor(4, '#2196F3'), // palette 4 (blue) or Material Blue
                backgroundColor: themeColors['palette = 4'] ? `${getColor(4, '#2196F3')}20` : 'rgba(33,150,243,0.1)',
                yAxisID: 'y',
                tension: 0,
                stepped: 'after',
                pointRadius: 0,
            },
            {
                type: 'line',
                label: 'PV Forecast (kW)',
                data: values.pv,
                borderColor: getColor(2, '#4CAF50'), // palette 2 (green) or Material Green
                backgroundColor: themeColors['palette = 2'] ? `${getColor(2, '#4CAF50')}30` : 'rgba(76,175,80,0.15)',
                fill: true,
                yAxisID: 'y4',
                tension: 0.35,
                pointRadius: 0,
            },
            {
                type: 'bar',
                label: 'Load (kW)',
                data: values.load,
                backgroundColor: `${getColor(3, '#FF9800')}80`, // more transparent
                borderRadius: 0,
                yAxisID: 'y1',
                barPercentage: 1,
                categoryPercentage: 1,
                grouped: false,
            },
            {
                type: 'bar',
                label: 'Charge (kW)',
                data: values.charge ?? values.labels.map(() => null),
                backgroundColor: `${getColor(4, '#2196F3')}80`, // more transparent
                hidden: true,
                yAxisID: 'y1',
                barPercentage: 1,
                categoryPercentage: 1,
                grouped: false,
            },
            {
                type: 'bar',
                label: 'Discharge (kW)',
                data: values.discharge ?? values.labels.map(() => null),
                backgroundColor: `${getColor(1, '#F44336')}80`, // more transparent
                hidden: true,
                yAxisID: 'y1',
                barPercentage: 1,
                categoryPercentage: 1,
                grouped: false,
            },
            {
                type: 'bar',
                label: 'Export (kWh)',
                data: values.export ?? values.labels.map(() => null),
                backgroundColor: `${getColor(2, '#4CAF50')}80`, // more transparent
                hidden: true,
                yAxisID: 'y2', // Use kWh axis
                barPercentage: 1,
                categoryPercentage: 1,
                grouped: false,
            },
            {
                type: 'bar',
                label: 'Water Heating (kW)',
                data: values.water ?? values.labels.map(() => null),
                backgroundColor: `${getColor(5, '#FF5722')}80`, // more transparent
                hidden: true,
                yAxisID: 'y1',
                barPercentage: 1,
                categoryPercentage: 1,
                grouped: false,
            },
            {
                type: 'line',
                label: 'SoC Target (%)',
                data: values.socTarget ?? values.labels.map(() => null),
                borderColor: getColor(13, '#9C27B0'), // palette 13 (pink) or Material Purple
                yAxisID: 'y3', // Use percentage axis
                pointRadius: 0,
                tension: 0,
                stepped: 'after',
                hidden: true,
            },
            {
                type: 'line',
                label: 'SoC Projected (%)',
                data: values.socProjected ?? values.labels.map(() => null),
                borderColor: getColor(14, '#FFEB3B'), // palette 14 or fallback yellow
                yAxisID: 'y3', // Use percentage axis
                pointRadius: 0,
                hidden: true,
            },
            {
                type: 'line',
                label: 'SoC Actual (%)',
                data: values.socActual ?? values.labels.map(() => null),
                borderColor: getColor(15, '#80CBC4'), // palette 15 or fallback teal
                yAxisID: 'y3',
                pointRadius: 0,
                hidden: true,
            },
        ],
    }

    // Add no-data message if needed
    if (values.hasNoData) {
        baseData.plugins = {
            ...baseData.plugins,
            tooltip: {
                enabled: true,
                external: true,
                callbacks: {
                    title: () => (values.day === 'tomorrow' ? 'No Price Data' : 'No Data'),
                    label: () =>
                        values.day === 'tomorrow'
                            ? 'Schedule data not available yet. Check back later for prices.'
                            : 'No schedule data available.',
                },
            },
        }
    }

    // Preserve nowIndex on the returned object so runtime
    // logic can position the "NOW" marker.
    return {
        ...baseData,
        nowIndex: values.nowIndex ?? null,
    } as any
}

const fallbackData = createChartData(
    {
        labels: sampleChart.labels,
        price: sampleChart.price,
        pv: sampleChart.pv,
        load: sampleChart.load,
    },
    {},
) // Use empty theme colors initially, will be updated

type ChartRange = 'day' | '48h'

type ChartCardProps = {
    day?: DaySel
    range?: ChartRange
    refreshToken?: number
    showDayToggle?: boolean
    useHistoryForToday?: boolean
    slotsOverride?: ScheduleSlot[]
}

export default function ChartCard({
    day = 'today',
    range = 'day',
    refreshToken = 0,
    showDayToggle = true,
    useHistoryForToday = false,
    slotsOverride,
}: ChartCardProps) {
    const [currentDay, setCurrentDay] = useState<DaySel>(day)
    const [rangeState, setRangeState] = useState<ChartRange>(range)
    const ref = useRef<HTMLCanvasElement | null>(null)
    const chartRef = useRef<Chart | null>(null)
    const [themeColors, setThemeColors] = useState<Record<string, string>>({})
    const [currentTheme, setCurrentTheme] = useState<string>('')
    const [overlays, setOverlays] = useState({
        price: true,
        pv: true,
        load: true,
        charge: false,
        discharge: false,
        export: false,
        water: false,
        socTarget: false,
        socProjected: false,
        socActual: true,
    })
    const [showOverlayMenu, setShowOverlayMenu] = useState(false)

    // Load overlay defaults from config
    useEffect(() => {
        Api.config()
            .then((config) => {
                const overlayDefaults = config?.dashboard?.overlay_defaults
                if (overlayDefaults && typeof overlayDefaults === 'string') {
                    const defaultOverlays = overlayDefaults.split(',').map((s) => s.trim().toLowerCase())
                    const hasSocActualToken =
                        defaultOverlays.includes('socactual') || defaultOverlays.includes('soc_actual')
                    const parsedOverlays = {
                        price: !defaultOverlays.includes('price_off'),
                        pv: !defaultOverlays.includes('pv_off'),
                        load: !defaultOverlays.includes('load_off'),
                        charge: defaultOverlays.includes('charge'),
                        discharge: defaultOverlays.includes('discharge'),
                        export: defaultOverlays.includes('export'),
                        water: defaultOverlays.includes('water'),
                        socTarget: defaultOverlays.includes('soctarget') || defaultOverlays.includes('soc_target'),
                        socProjected:
                            defaultOverlays.includes('socprojected') || defaultOverlays.includes('soc_projected'),
                        // Only override SoC Actual if config explicitly mentions it;
                        // otherwise keep the initial default (true).
                        socActual: hasSocActualToken ? true : overlays.socActual,
                    }
                    setOverlays(parsedOverlays)
                }
            })
            .catch((err) => console.error('Failed to load overlay defaults:', err))
    }, [])
    const [nowPosition, setNowPosition] = useState<number | null>(null)

    useEffect(() => {
        // Fetch theme colors on mount
        Api.theme()
            .then((themeData) => {
                const currentThemeInfo = themeData.themes.find((t) => t.name === themeData.current)
                if (currentThemeInfo) {
                    // Convert palette array to key-value format
                    const colorMap: Record<string, string> = {}
                    currentThemeInfo.palette.forEach((color, index) => {
                        colorMap[`palette = ${index}`] = color
                    })
                    colorMap['background'] = currentThemeInfo.background
                    colorMap['foreground'] = currentThemeInfo.foreground
                    setThemeColors(colorMap)
                    setCurrentTheme(themeData.current)
                }
            })
            .catch((err) => console.error('Failed to load theme colors:', err))
    }, [])

    useEffect(() => {
        if (!ref.current || Object.keys(themeColors).length === 0) return
        const cfg: ChartConfiguration = {
            type: 'bar',
            data: createChartData(
                {
                    labels: sampleChart.labels,
                    price: sampleChart.price,
                    pv: sampleChart.pv,
                    load: sampleChart.load,
                },
                themeColors,
            ),
            options: chartOptions,
        }
        chartRef.current = new ChartJS(ref.current, cfg)

        return () => {
            if (chartRef.current) {
                chartRef.current.destroy()
                chartRef.current = null
            }
        }
    }, [themeColors]) // Re-create chart when theme colors are loaded

    const isChartUsable = (chartInstance: Chart | null) => {
        if (!chartInstance) return false
        const anyChart = chartInstance as any
        if (anyChart._destroyed) return false
        if (anyChart._plugins === undefined && anyChart.$plugins === undefined) return false
        return true
    }

    useEffect(() => {
        setRangeState(range)
    }, [range])

    useEffect(() => {
        const chartInstance = chartRef.current
        if (!isChartUsable(chartInstance) || Object.keys(themeColors).length === 0) return
        const applyData = (slots: ScheduleSlot[]) => {
            if (!isChartUsable(chartRef.current)) return
            const liveData = buildLiveData(slots, currentDay, rangeState, themeColors)
            if (!liveData) return
            setHasNoDataMessage(liveData.hasNoData ?? false)
            const ds = liveData.datasets
            if (ds[0]) ds[0].hidden = !overlays.price
            if (ds[1]) ds[1].hidden = !overlays.pv
            if (ds[2]) ds[2].hidden = !overlays.load
            if (ds[3]) ds[3].hidden = !overlays.charge
            if (ds[4]) ds[4].hidden = !overlays.discharge
            if (ds[5]) ds[5].hidden = !overlays.export
            if (ds[6]) ds[6].hidden = !overlays.water
            if (ds[7]) ds[7].hidden = !overlays.socTarget
            if (ds[8]) ds[8].hidden = !overlays.socProjected
            if (ds[9]) ds[9].hidden = !overlays.socActual

            // Compute CSS overlay position for "NOW" (0–1 across labels)
            const anyData = liveData as any
            if (
                currentDay === 'today' &&
                typeof anyData.nowIndex === 'number' &&
                anyData.nowIndex >= 0 &&
                liveData.labels.length > 1
            ) {
                const idx = anyData.nowIndex as number
                const denom = liveData.labels.length - 1
                setNowPosition(idx / denom)
            } else {
                setNowPosition(null)
            }
            try {
                if (!isChartUsable(chartRef.current)) return
                if (chartRef.current) {
                    ;(chartRef.current as any).data = liveData
                    chartRef.current.update()
                }
            } catch (err) {
                console.error('Chart update failed, skipping frame:', err)
            }
        }

        if (slotsOverride && slotsOverride.length) {
            applyData(slotsOverride)
            return
        }

        const loader =
            useHistoryForToday && rangeState === 'day' && currentDay === 'today'
                ? Api.scheduleTodayWithHistory().then((res) => ({ schedule: res.slots }))
                : Api.schedule()

        loader
            .then((data) => {
                applyData(data.schedule ?? [])
            })
            .catch((err) => {
                console.error('Failed to load schedule:', err)
                // Show an explicit "no data" overlay instead of leaving stale/mock data visible
                setHasNoDataMessage(true)
                setNowPosition(null)
            })
    }, [currentDay, overlays, themeColors, rangeState, refreshToken, slotsOverride, useHistoryForToday])

    const [hasNoDataMessage, setHasNoDataMessage] = useState(false)

    return (
        <Card className="p-4 md:p-6 h-[380px]">
            <div className="flex items-baseline justify-between pb-2">
                <div className="text-sm text-muted">Schedule Overview</div>
                {showDayToggle && (
                    <div className="flex items-center gap-2">
                        <div className="flex gap-1">
                            <button
                                className={`rounded-pill px-3 py-1 text-[11px] font-semibold uppercase tracking-wide transition ${
                                    rangeState === 'day'
                                        ? 'bg-accent text-canvas'
                                        : 'bg-surface border border-line/60 text-muted'
                                }`}
                                onClick={() => setRangeState('day')}
                            >
                                24h
                            </button>
                            <button
                                className={`rounded-pill px-3 py-1 text-[11px] font-semibold uppercase tracking-wide transition ${
                                    rangeState === '48h'
                                        ? 'bg-accent text-canvas'
                                        : 'bg-surface border border-line/60 text-muted'
                                }`}
                                onClick={() => setRangeState('48h')}
                            >
                                48h
                            </button>
                        </div>
                        <button
                            className="rounded-pill px-3 py-1 text-[11px] font-semibold uppercase tracking-wide border border-line/60 text-muted hover:border-accent hover:text-accent transition"
                            onClick={() => setShowOverlayMenu((v) => !v)}
                        >
                            Overlays
                        </button>
                    </div>
                )}
            </div>
            {showOverlayMenu && (
                <div className="mt-2 flex flex-wrap gap-2 text-[11px]">
                    {(
                        [
                            ['Price', 'price'],
                            ['PV', 'pv'],
                            ['Load', 'load'],
                            ['Charge', 'charge'],
                            ['Discharge', 'discharge'],
                            ['Export', 'export'],
                            ['Water', 'water'],
                            ['SoC Target', 'socTarget'],
                            ['SoC Projected', 'socProjected'],
                            ['SoC Actual', 'socActual'],
                        ] as const
                    ).map(([label, key]) => (
                        <button
                            key={key}
                            onClick={(e) => {
                                e.preventDefault()
                                setOverlays((o) => ({ ...o, [key]: !o[key as keyof typeof o] }))
                            }}
                            className={`rounded-pill px-3 py-1 border ${
                                overlays[key as keyof typeof overlays]
                                    ? 'bg-accent text-canvas border-accent'
                                    : 'border-line/60 text-muted hover:border-accent'
                            }`}
                        >
                            {label}
                        </button>
                    ))}
                </div>
            )}
            <div className="h-[310px] relative mt-1">
                {hasNoDataMessage && (
                    <div className="absolute inset-0 flex items-center justify-center bg-surface/90 rounded-lg">
                        <div className="text-center">
                            <div className="text-lg font-semibold text-accent mb-2">No Price Data</div>
                            <div className="text-sm text-muted">
                                Schedule data not available yet. Check back later for prices.
                            </div>
                        </div>
                    </div>
                )}
                {!hasNoDataMessage && currentDay === 'today' && nowPosition !== null && (
                    <div className="pointer-events-none absolute inset-0 z-10">
                        <div
                            className="absolute top-2 bottom-6 border-l-2 border-accent/80"
                            style={{ left: `${nowPosition * 100}%` }}
                        />
                    </div>
                )}
                <canvas ref={ref} style={{ display: hasNoDataMessage ? 'none' : 'block' }} />
            </div>
        </Card>
    )
}

function buildLiveData(
    slots: ScheduleSlot[],
    day: DaySel,
    range: ChartRange,
    themeColors: Record<string, string> = {},
) {
    const filtered =
        range === 'day'
            ? filterSlotsByDay(slots, day)
            : slots.filter((slot) => isToday(slot.start_time) || isTomorrow(slot.start_time))

    // Special handling for full-day views: always show 00:00–24:00,
    // padding with nulls where the schedule has no data.
    if (range === 'day') {
        if (!filtered.length) {
            // No slots at all for this day → show explicit "no data" state
            const labels = Array.from({ length: 24 }, (_, i) => `${String(i).padStart(2, '0')}:00`)
            const nulls = Array(24).fill(null)
            return createChartData(
                {
                    labels,
                    price: nulls.slice(),
                    pv: nulls.slice(),
                    load: nulls.slice(),
                    charge: nulls.slice(),
                    discharge: nulls.slice(),
                    export: nulls.slice(),
                    water: nulls.slice(),
                    socTarget: nulls.slice(),
                    socProjected: nulls.slice(),
                    socActual: nulls.slice(),
                    hasNoData: true,
                    day,
                },
                themeColors,
            )
        }

        const ordered = [...filtered].sort((a, b) => {
            const aTime = new Date(a.start_time).getTime()
            const bTime = new Date(b.start_time).getTime()
            return aTime - bTime
        })

        // Infer resolution from consecutive slots; default to 15 minutes.
        let resolutionMinutes = 15
        if (ordered.length >= 2) {
            const dt0 = new Date(ordered[0].start_time).getTime()
            const dt1 = new Date(ordered[1].start_time).getTime()
            const deltaMinutes = Math.max(1, Math.round((dt1 - dt0) / 60000))
            if (deltaMinutes === 15 || deltaMinutes === 30 || deltaMinutes === 60) {
                resolutionMinutes = deltaMinutes
            }
        }

        // Build a full-day time grid from 00:00–24:00 local time
        const anchor = new Date()
        if (day === 'today') {
            anchor.setHours(0, 0, 0, 0)
        } else {
            anchor.setDate(anchor.getDate() + 1)
            anchor.setHours(0, 0, 0, 0)
        }

        const stepMs = resolutionMinutes * 60 * 1000
        const steps = Math.round((24 * 60) / resolutionMinutes)

        // Index slots by exact start timestamp for quick lookup
        const slotByTime = new Map<number, ScheduleSlot>()
        for (const s of ordered) {
            const t = new Date(s.start_time).getTime()
            slotByTime.set(t, s)
        }

        const labels: string[] = []
        const price: (number | null)[] = []
        const pv: (number | null)[] = []
        const load: (number | null)[] = []
        const charge: (number | null)[] = []
        const discharge: (number | null)[] = []
        const exp: (number | null)[] = []
        const water: (number | null)[] = []
        const socTarget: (number | null)[] = []
        const socProjected: (number | null)[] = []
        const socActual: (number | null)[] = []

        let nowIndex: number | null = null
        const now = new Date()

        for (let i = 0; i < steps; i++) {
            const bucketStart = new Date(anchor.getTime() + i * stepMs)
            const bucketEnd = new Date(bucketStart.getTime() + stepMs)
            const slot = slotByTime.get(bucketStart.getTime())

            labels.push(formatHour(bucketStart.toISOString()))

            if (slot) {
                const isExec = (slot as any).is_executed === true
                const anySlot = slot as any

                price.push(slot.import_price_sek_kwh ?? null)
                pv.push(
                    isExec && anySlot.actual_pv_kwh != null ? anySlot.actual_pv_kwh : (slot.pv_forecast_kwh ?? null),
                )
                load.push(
                    isExec && anySlot.actual_load_kwh != null
                        ? anySlot.actual_load_kwh
                        : (slot.load_forecast_kwh ?? null),
                )
                // For charge/export, prefer actual_* when executed; discharge/water remain planned.
                charge.push(
                    isExec && anySlot.actual_charge_kw != null
                        ? anySlot.actual_charge_kw
                        : (slot.battery_charge_kw ?? slot.charge_kw ?? null),
                )
                discharge.push(slot.battery_discharge_kw ?? slot.discharge_kw ?? null)
                exp.push(
                    isExec && anySlot.actual_export_kw != null ? anySlot.actual_export_kw : (slot.export_kwh ?? null),
                )
                water.push(slot.water_heating_kw ?? null)
                socTarget.push(slot.soc_target_percent ?? null)
                socProjected.push(slot.projected_soc_percent ?? null)
                socActual.push(anySlot.soc_actual_percent != null ? anySlot.soc_actual_percent : null)
            } else {
                price.push(null)
                pv.push(null)
                load.push(null)
                charge.push(null)
                discharge.push(null)
                exp.push(null)
                water.push(null)
                socTarget.push(null)
                socProjected.push(null)
                socActual.push(null)
            }

            if (day === 'today' && now >= bucketStart && now < bucketEnd) {
                nowIndex = i
            }
        }

        return createChartData(
            {
                labels,
                price,
                pv,
                load,
                charge,
                discharge,
                export: exp,
                water,
                socTarget,
                socProjected,
                socActual,
                nowIndex,
            },
            themeColors,
        )
    }

    // 48h / multi-day range: build a fixed 48-hour window (today+tomorrow)
    if (range === '48h') {
        if (!filtered.length) {
            console.log('[buildLiveData] No slots found for 48h range, creating fallback')
            const labels = Array.from({ length: 48 }, (_, i) => {
                const hour = i % 24
                return `${String(hour).padStart(2, '0')}:00`
            })
            return {
                labels,
                price: Array(labels.length).fill(null),
                pv: Array(labels.length).fill(null),
                load: Array(labels.length).fill(null),
                charge: Array(labels.length).fill(null),
                discharge: Array(labels.length).fill(null),
                export: Array(labels.length).fill(null),
                water: Array(labels.length).fill(null),
                socTarget: Array(labels.length).fill(null),
                socProjected: Array(labels.length).fill(null),
                hasNoData: true,
                day,
            }
        }

        const ordered = [...filtered].sort((a, b) => {
            const aTime = new Date(a.start_time).getTime()
            const bTime = new Date(b.start_time).getTime()
            return aTime - bTime
        })

        // Infer resolution from consecutive slots; default to 15 minutes.
        let resolutionMinutes = 15
        if (ordered.length >= 2) {
            const dt0 = new Date(ordered[0].start_time).getTime()
            const dt1 = new Date(ordered[1].start_time).getTime()
            const deltaMinutes = Math.max(1, Math.round((dt1 - dt0) / 60000))
            if (deltaMinutes === 15 || deltaMinutes === 30 || deltaMinutes === 60) {
                resolutionMinutes = deltaMinutes
            }
        }

        const anchor = new Date()
        anchor.setHours(0, 0, 0, 0)

        const stepMs = resolutionMinutes * 60 * 1000
        const steps = Math.round((48 * 60) / resolutionMinutes)

        const slotByTime = new Map<number, ScheduleSlot>()
        for (const s of ordered) {
            const t = new Date(s.start_time).getTime()
            slotByTime.set(t, s)
        }

        const labels: string[] = []
        const price: (number | null)[] = []
        const pv: (number | null)[] = []
        const load: (number | null)[] = []
        const charge: (number | null)[] = []
        const discharge: (number | null)[] = []
        const exp: (number | null)[] = []
        const water: (number | null)[] = []
        const socTarget: (number | null)[] = []
        const socProjected: (number | null)[] = []
        const socActual: (number | null)[] = []

        let nowIndex: number | null = null
        const now = new Date()

        for (let i = 0; i < steps; i++) {
            const bucketStart = new Date(anchor.getTime() + i * stepMs)
            const bucketEnd = new Date(bucketStart.getTime() + stepMs)
            const slot = slotByTime.get(bucketStart.getTime())

            labels.push(formatHour(bucketStart.toISOString()))

            if (slot) {
                const isExec = (slot as any).is_executed === true
                const anySlot = slot as any

                price.push(slot.import_price_sek_kwh ?? null)
                pv.push(
                    isExec && anySlot.actual_pv_kwh != null ? anySlot.actual_pv_kwh : (slot.pv_forecast_kwh ?? null),
                )
                load.push(
                    isExec && anySlot.actual_load_kwh != null
                        ? anySlot.actual_load_kwh
                        : (slot.load_forecast_kwh ?? null),
                )
                charge.push(
                    isExec && anySlot.actual_charge_kw != null
                        ? anySlot.actual_charge_kw
                        : (slot.battery_charge_kw ?? slot.charge_kw ?? null),
                )
                discharge.push(slot.battery_discharge_kw ?? slot.discharge_kw ?? null)
                exp.push(
                    isExec && anySlot.actual_export_kw != null ? anySlot.actual_export_kw : (slot.export_kwh ?? null),
                )
                water.push(slot.water_heating_kw ?? null)
                socTarget.push(slot.soc_target_percent ?? null)
                socProjected.push(slot.projected_soc_percent ?? null)
                socActual.push(anySlot.soc_actual_percent != null ? anySlot.soc_actual_percent : null)
            } else {
                price.push(null)
                pv.push(null)
                load.push(null)
                charge.push(null)
                discharge.push(null)
                exp.push(null)
                water.push(null)
                socTarget.push(null)
                socProjected.push(null)
                socActual.push(null)
            }

            if (now >= bucketStart && now < bucketEnd) {
                nowIndex = i
            }
        }

        return createChartData(
            {
                labels,
                price,
                pv,
                load,
                charge,
                discharge,
                export: exp,
                water,
                socTarget,
                socProjected,
                socActual,
                nowIndex,
            },
            themeColors,
        )
    }

    // Fallback for any other future range types (none today)
    const ordered = [...filtered].sort((a, b) => {
        const aTime = new Date(a.start_time).getTime()
        const bTime = new Date(b.start_time).getTime()
        return aTime - bTime
    })

    const price = ordered.map((slot) => slot.import_price_sek_kwh ?? null)
    const pv = ordered.map((slot) => slot.pv_forecast_kwh ?? null)
    const load = ordered.map((slot) => slot.load_forecast_kwh ?? null)
    const charge = ordered.map((slot) => slot.battery_charge_kw ?? slot.charge_kw ?? null)
    const discharge = ordered.map((slot) => slot.battery_discharge_kw ?? slot.discharge_kw ?? null)
    const exp = ordered.map((slot) => slot.export_kwh ?? null)
    const water = ordered.map((slot) => slot.water_heating_kw ?? null)
    const socTarget = ordered.map((slot) => slot.soc_target_percent ?? null)
    const socProjected = ordered.map((slot) => slot.projected_soc_percent ?? null)
    const socActual = ordered.map((slot) => (slot as any).soc_actual_percent ?? null)

    const labels = ordered.map((slot) => formatHour(slot.start_time))

    let nowIndex: number | null = null
    if (day === 'today') {
        const now = new Date()
        for (let i = 0; i < ordered.length; i++) {
            const start = new Date(ordered[i].start_time || '')
            const end = new Date(start.getTime() + 30 * 60 * 1000)
            if (now >= start && now < end) {
                nowIndex = i
                break
            }
        }
    }

    return createChartData(
        {
            labels,
            price,
            pv,
            load,
            charge,
            discharge,
            export: exp,
            water,
            socTarget,
            socProjected,
            socActual,
            nowIndex,
        },
        themeColors,
    )
}
