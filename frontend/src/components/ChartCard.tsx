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
    plugins: {
        legend: {
            labels: {
                color: '#e6e9ef',
                boxWidth: 10,
                font: { size: 12 },
                filter: (item) =>
                    typeof item.datasetIndex === 'number' && item.datasetIndex < 4,
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
            callbacks: {
                title: function(context) {
                    return context[0].label
                },
                label: function(context) {
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
            }
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
                display: true,
                text: 'SEK/kWh',
                color: '#a6b0bf'
            },
            grid: { color: 'rgba(255,255,255,0.06)' },
            ticks: { color: '#a6b0bf' },
        },
        y1: {
            position: 'left',
            min: 0,
            max: 9,
            title: {
                display: true,
                text: 'kW',
                color: '#a6b0bf'
            },
            grid: { display: false },
            ticks: { color: '#a6b0bf' },
        },
        y2: {
            position: 'left',
            min: 0,
            max: 9,
            title: {
                display: true,
                text: 'kWh',
                color: '#a6b0bf'
            },
            grid: { display: false },
            ticks: { color: '#a6b0bf' },
            display: false,
        },
        y3: {
            position: 'right',
            min: 0,
            max: 100,
            title: {
                display: true,
                text: '%',
                color: '#a6b0bf'
            },
            grid: { display: false },
            ticks: { color: '#a6b0bf' },
            display: false,
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
            tension: 0.2,
            pointRadius: 0,
        },
        {
            type: 'line',
            label: 'PV Forecast (kW)',
            data: values.pv,
            borderColor: getColor(2, '#4CAF50'), // palette 2 (green) or Material Green
            backgroundColor: themeColors['palette = 2'] ? `${getColor(2, '#4CAF50')}30` : 'rgba(76,175,80,0.15)',
            fill: true,
            yAxisID: 'y1',
            tension: .35,
            pointRadius: 0,
        },
        {
            type: 'bar',
            label: 'Load (kW)',
            data: values.load,
            backgroundColor: getColor(3, '#FF9800'), // palette 3 (yellow) or Material Orange
            borderRadius: 6,
            yAxisID: 'y1',
            barPercentage: 1,
            categoryPercentage: .9,
        },
        {
            type: 'bar',
            label: 'Charge (kW)',
            data: values.charge ?? values.labels.map(() => null),
            backgroundColor: getColor(4, '#2196F3'), // palette 4 (blue) or Material Blue
            hidden: true,
            yAxisID: 'y1',
        },
        {
            type: 'bar',
            label: 'Discharge (kW)',
            data: values.discharge ?? values.labels.map(() => null),
            backgroundColor: getColor(1, '#F44336'), // palette 1 (red) or Material Red
            hidden: true,
            yAxisID: 'y1',
        },
        {
            type: 'bar',
            label: 'Export (kWh)',
            data: values.export ?? values.labels.map(() => null),
            backgroundColor: getColor(2, '#4CAF50'), // palette 2 (green) or Material Green
            hidden: true,
            yAxisID: 'y2', // Use kWh axis
        },
        {
            type: 'bar',
            label: 'Water Heating (kW)',
            data: values.water ?? values.labels.map(() => null),
            backgroundColor: getColor(5, '#FF5722'), // palette 5 (pink) or Material Deep Orange
            hidden: true,
            yAxisID: 'y1',
        },
        {
            type: 'line',
            label: 'SoC Target (%)',
            data: values.socTarget ?? values.labels.map(() => null),
            borderColor: getColor(13, '#9C27B0'), // palette 13 (pink) or Material Purple
            yAxisID: 'y3', // Use percentage axis
            pointRadius: 0,
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
                    title: () => values.day === 'tomorrow' ? 'No Price Data' : 'No Data',
                    label: () => values.day === 'tomorrow' 
                        ? 'Schedule data not available yet. Check back later for prices.' 
                        : 'No schedule data available.'
                }
            }
        }
    }
    
    // Preserve nowIndex on the returned object so runtime
    // logic can position the "NOW" marker.
    return {
        ...baseData,
        nowIndex: values.nowIndex ?? null,
    } as any
}

const fallbackData = createChartData({
    labels: sampleChart.labels,
    price: sampleChart.price,
    pv: sampleChart.pv,
    load: sampleChart.load,
}, {}) // Use empty theme colors initially, will be updated

type ChartRange = 'day' | '48h'

type ChartCardProps = {
    day?: DaySel
    range?: ChartRange
    refreshToken?: number
    showDayToggle?: boolean
}

export default function ChartCard({
    day = 'today',
    range = 'day',
    refreshToken = 0,
    showDayToggle = true,
}: ChartCardProps){
    const [currentDay, setCurrentDay] = useState<DaySel>(day)
    const ref = useRef<HTMLCanvasElement | null>(null)
    const chartRef = useRef<Chart | null>(null)
    const [themeColors, setThemeColors] = useState<Record<string, string>>({})
    const [currentTheme, setCurrentTheme] = useState<string>('')
    const [overlays, setOverlays] = useState({
        charge: false,
        discharge: false,
        export: false,
        water: false,
        socTarget: false,
        socProjected: false,
    })
    const [nowPosition, setNowPosition] = useState<number | null>(null)

    useEffect(() => {
        // Fetch theme colors on mount
        Api.theme()
            .then(themeData => {
                const currentThemeInfo = themeData.themes.find(t => t.name === themeData.current)
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
            .catch(err => console.error('Failed to load theme colors:', err))
    }, [])

    useEffect(() => {
        if (!ref.current || Object.keys(themeColors).length === 0) return
        const cfg: ChartConfiguration = {
            type: 'bar',
            data: createChartData({
                labels: sampleChart.labels,
                price: sampleChart.price,
                pv: sampleChart.pv,
                load: sampleChart.load,
            }, themeColors),
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
        const chartInstance = chartRef.current
        if (!isChartUsable(chartInstance) || Object.keys(themeColors).length === 0) return
        Api.schedule()
            .then(data => {
                if (!isChartUsable(chartRef.current)) return
                const liveData = buildLiveData(data.schedule ?? [], currentDay, range, themeColors)
                if (!liveData) return
                setHasNoDataMessage(liveData.hasNoData ?? false)
                const ds = liveData.datasets
                if (ds[3]) ds[3].hidden = !overlays.charge
                if (ds[4]) ds[4].hidden = !overlays.discharge
                if (ds[5]) ds[5].hidden = !overlays.export
                if (ds[6]) ds[6].hidden = !overlays.water
                if (ds[7]) ds[7].hidden = !overlays.socTarget
                if (ds[8]) ds[8].hidden = !overlays.socProjected

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
            })
            .catch(err => console.error('Failed to load schedule:', err))
    }, [currentDay, overlays, themeColors, range, refreshToken])

    const [hasNoDataMessage, setHasNoDataMessage] = useState(false)
    
    return (
        <Card className="p-4 md:p-6 h-[380px]">
        <div className="flex items-baseline justify-between pb-3">
        <div className="text-sm text-muted">Schedule Overview</div>
        {showDayToggle && (
            <div className="flex gap-1">
                <button 
                    className={`rounded-pill px-3 py-1 text-[11px] font-semibold uppercase tracking-wide transition ${
                        currentDay === 'today' ? 'bg-accent text-canvas' : 'bg-surface border border-line/60 text-muted'
                    }`}
                    onClick={() => setCurrentDay('today')}
                >
                    Today
                </button>
                <button 
                    className={`rounded-pill px-3 py-1 text-[11px] font-semibold uppercase tracking-wide transition ${
                        currentDay === 'tomorrow' ? 'bg-accent text-canvas' : 'bg-surface border border-line/60 text-muted'
                    }`}
                    onClick={() => setCurrentDay('tomorrow')}
                >
                    Tomorrow
                </button>
            </div>
        )}
        </div>
        <div className="h-[310px] relative">
        {hasNoDataMessage && (
            <div className="absolute inset-0 flex items-center justify-center bg-surface/90 rounded-lg">
                <div className="text-center">
                    <div className="text-lg font-semibold text-accent mb-2">No Price Data</div>
                    <div className="text-sm text-muted">Schedule data not available yet. Check back later for prices.</div>
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
        <canvas ref={ref} style={{ display: hasNoDataMessage ? 'none' : 'block' }}/>
        </div>
        <div className="mt-3 flex flex-wrap gap-2 text-[11px]">
        {([
            ['Charge', 'charge'],
            ['Discharge', 'discharge'],
            ['Export', 'export'],
            ['Water', 'water'],
            ['SoC Target', 'socTarget'],
            ['SoC Projected', 'socProjected'],
        ] as const).map(([label, key]) => (
            <button
                key={key}
                onClick={(e) => { e.preventDefault(); setOverlays(o => ({...o, [key]: !o[key as keyof typeof o]})) }}
                className={`rounded-pill px-3 py-1 border ${overlays[key as keyof typeof overlays] ? 'bg-accent text-canvas border-accent' : 'border-line/60 text-muted hover:border-accent'}`}
            >
                {label}
            </button>
        ))}
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
    if(!filtered.length) {
        // For tomorrow without schedule data, create minimal structure with message
        console.log(`[buildLiveData] No ${day} slots found, creating fallback`)
        return {
            labels: Array.from({length: 24}, (_, i) => `${String(i).padStart(2, '0')}:00`),
            price: Array(24).fill(null),
            pv: Array(24).fill(null),
            load: Array(24).fill(null),
            charge: Array(24).fill(null),
            discharge: Array(24).fill(null),
            export: Array(24).fill(null),
            water: Array(24).fill(null),
            socTarget: Array(24).fill(null),
            socProjected: Array(24).fill(null),
            hasNoData: true,
            day
        }
    }
    const ordered = [...filtered].sort((a, b) => {
        const aTime = new Date(a.start_time).getTime()
        const bTime = new Date(b.start_time).getTime()
        return aTime - bTime
    })

    const price = ordered.map(slot => slot.import_price_sek_kwh ?? null)
    const pv = ordered.map(slot => slot.pv_forecast_kwh ?? null)
    const load = ordered.map(slot => slot.load_forecast_kwh ?? null)
    const charge = ordered.map(slot => slot.battery_charge_kw ?? slot.charge_kw ?? null)
    const discharge = ordered.map(slot => slot.battery_discharge_kw ?? slot.discharge_kw ?? null)
    const exp = ordered.map(slot => slot.export_kwh ?? null)
    const water = ordered.map(slot => slot.water_heating_kw ?? null)
    const socTarget = ordered.map(slot => slot.soc_target_percent ?? null)
    const socProjected = ordered.map(slot => slot.projected_soc_percent ?? null)

    const labels = ordered.map(slot => formatHour(slot.start_time))

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

    return createChartData({
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
        nowIndex,
    }, themeColors)
}
