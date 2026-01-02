import Card from './Card'
import { useEffect, useRef, useState } from 'react'
import { Chart as ChartJS, ChartConfiguration, Plugin } from 'chart.js/auto'
import type { Chart, Scale, Tick, ChartData } from 'chart.js/auto'
import zoomPlugin from 'chartjs-plugin-zoom'
ChartJS.register(zoomPlugin)
import { sampleChart } from '../lib/sample'
import { Api } from '../lib/api'
import type { ScheduleSlot } from '../lib/types'
import { filterSlotsByDay, formatHour, DaySel, isToday, isTomorrow } from '../lib/time'
// Note: We use a custom plugin for the NOW marker to support zooming.
// CSS overlays don't work well with pan/zoom.

const chartOptions: ChartConfiguration['options'] = {
    maintainAspectRatio: false,
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
                    if (value === null || value === undefined) return ''

                    let formattedValue = value.toFixed(2)
                    let unit = ''

                    if (datasetLabel.includes('SEK/kWh')) {
                        formattedValue = value.toFixed(2)
                        unit = ' SEK/kWh'

                        const data = context.chart.data as ExtendedChartData
                        const pricing = data.pricingConfig

                        // If we have pricing config, show breakdown
                        if (pricing) {
                            // Total = (Spot + Fees) * (1 + VAT/100)
                            // Spot = (Total / (1 + VAT/100)) - Fees
                            const vatMul = 1 + pricing.vat / 100
                            // Avoid division by zero
                            const basePrice = vatMul > 0 ? value / vatMul : value
                            const spot = Math.max(0, basePrice - pricing.fees)
                            // Fees + Tax part of the total
                            const feesAndVat = value - spot

                            return [
                                `${datasetLabel}: ${formattedValue}${unit}`,
                                `(Spot: ${spot.toFixed(2)} + Tax/Fees: ${feesAndVat.toFixed(2)})`,
                            ] as any // Chart.js allows string arrays for multiline
                        }
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
        zoom: {
            pan: {
                enabled: true,
                mode: 'x',
            },
            zoom: {
                wheel: {
                    enabled: true,
                },
                pinch: {
                    enabled: true,
                },
                mode: 'x',
            },
        },
    },
    scales: {
        x: {
            grid: {
                display: false, // Disabled - using dot grid plugin instead
            },
            ticks: {
                color: '#6c7086',
                font: {
                    family: 'monospace',
                    size: 10,
                },
                maxRotation: 0,
                autoSkip: false,
                callback: function (this: Scale, value: string | number, _index: number, _ticks: Tick[]) {
                    const label = this.getLabelForValue(value as number)
                    if (typeof label !== 'string') return ''
                    const parts = label.split(':')
                    if (parts.length < 2) return ''
                    const [hh, mm] = parts
                    return mm === '00' ? hh : ''
                },
            },
            border: { display: false },
        },
        y: {
            position: 'right',
            min: 0,
            max: 8,
            title: {
                display: false,
                text: 'SEK/kWh',
            },
            grid: {
                display: false, // Disabled - using dot grid plugin instead
            },
            border: { display: false },
            ticks: {
                display: false,
                color: '#6c7086',
                font: { family: 'monospace', size: 10 },
                callback: (val) => `${val} SEK`,
            },
        },
        y1: {
            position: 'left',
            min: 0,
            max: 9,
            title: { display: false, text: 'kW' },
            grid: { display: false },
            ticks: { display: false },
            border: { display: false },
        },
        y2: {
            position: 'left',
            min: 0,
            max: 9,
            title: { display: false, text: 'kWh' },
            grid: { display: false },
            ticks: { display: false },
            border: { display: false },
            display: false,
        },
        y3: {
            position: 'right',
            min: 0,
            max: 100,
            title: { display: true, text: '%', color: '#a6b0bf' },
            grid: { display: false },
            ticks: { color: '#a6b0bf', font: { family: 'monospace', size: 10 } },
            border: { display: false },
            display: false,
        },
        y4: {
            position: 'left',
            min: 0,
            max: 1.5,
            title: { display: false, text: 'kW (PV)' },
            grid: { display: false },
            ticks: { display: false },
            border: { display: false },
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
    nowPct?: number | null
}

interface ExtendedChartData extends ChartData {
    nowIndex?: number | null
    nowPct?: number | null
    hasNoData?: boolean
    plugins?: unknown
    pricingConfig?: { vat: number; fees: number }
}

const createChartData = (
    values: ChartValues,
    _themeColors: Record<string, string> = {}, // Deprecated - using Design System tokens directly
    pricing?: { vat: number; fees: number },
): ExtendedChartData => {
    // Design System Colors (from index.css)
    // Semantic mapping - APPROVED V2:
    // - accent (gold): PV/Solar - it's the SUN
    // - grid (grey): Import Price - neutral
    // - house (cyan): Load - house consumption
    // - good (green): Export - positive (selling)
    // - bad (orange): Charge/Discharge - costs money
    // - water (blue): Water heating
    // - night (cyan): SoC lines
    const DS = {
        accent: '#FFCE59', // --color-accent: PV/Solar (SUN)
        grid: '#64748B', // --color-grid: Import Price (neutral)
        house: '#00B7B5', // --color-house: Load (cyan)
        good: '#1FB256', // --color-good: Export
        bad: '#F15132', // --color-bad: Charge (costs money)
        peak: '#EC4899', // --color-peak: Discharge (pink)
        water: '#4EA8DE', // --color-water: Water heating
        night: '#06B6D4', // --color-night: SoC lines
    }

    const baseData: ExtendedChartData = {
        labels: values.labels,
        datasets: [
            {
                type: 'line',
                label: 'Import Price (SEK/kWh)',
                data: values.price,
                borderColor: DS.grid, // Grey - neutral grid price
                backgroundColor: (context: any) => {
                    const ctx = context.chart.ctx
                    const isDark = document.documentElement.classList.contains('dark')
                    const opacity = isDark ? 0.35 : 0.5 // Higher in light mode
                    const gradient = ctx.createLinearGradient(0, 0, 0, context.chart.height)
                    gradient.addColorStop(0, `rgba(100, 116, 139, ${opacity})`) // DS.grid
                    gradient.addColorStop(1, 'rgba(100, 116, 139, 0)')
                    return gradient
                },
                fill: true,
                yAxisID: 'y',
                tension: 0.4,
                pointRadius: 0,
                borderWidth: 3,
                order: 1,
            } as any,
            {
                type: 'line',
                label: 'PV Forecast (kW)',
                data: values.pv,
                borderColor: DS.accent, // Gold - it's the SUN
                backgroundColor: (context: any) => {
                    const ctx = context.chart.ctx
                    const isDark = document.documentElement.classList.contains('dark')
                    const opacity = isDark ? 0.5 : 0.65 // Higher in light mode
                    const gradient = ctx.createLinearGradient(0, 0, 0, context.chart.height)
                    gradient.addColorStop(0, `rgba(255, 206, 89, ${opacity})`) // DS.accent
                    gradient.addColorStop(1, 'rgba(255, 206, 89, 0)')
                    return gradient
                },
                fill: true,
                yAxisID: 'y4',
                tension: 0.4,
                pointRadius: 0,
                borderWidth: 3,
                order: 2,
            } as any,
            {
                type: 'bar',
                label: 'Load (kW)',
                data: values.load,
                backgroundColor: 'rgba(0, 183, 181, 0.3)', // DS.house cyan at 30%
                borderWidth: 0,
                borderRadius: 2,
                yAxisID: 'y1',
                barPercentage: 0.85,
                categoryPercentage: 0.9,
                grouped: false,
                order: 0, // Render in front of gradient lines
            },
            {
                type: 'bar',
                label: 'Charge (kW)',
                data: values.charge ?? values.labels.map(() => null),
                backgroundColor: 'rgba(241, 81, 50, 0.3)', // DS.bad - grid charge costs money
                borderWidth: 0,
                borderRadius: 2,
                hidden: true,
                yAxisID: 'y1',
                barPercentage: 0.85,
                categoryPercentage: 0.9,
                grouped: false,
                order: 0,
            },
            {
                type: 'bar',
                label: 'Discharge (kW)',
                data: values.discharge ?? values.labels.map(() => null),
                backgroundColor: 'rgba(236, 72, 153, 0.3)', // DS.peak (pink) at 30%
                borderWidth: 0,
                borderRadius: 2,
                hidden: true,
                yAxisID: 'y1',
                barPercentage: 0.85,
                categoryPercentage: 0.9,
                grouped: false,
                order: 0,
            },
            {
                type: 'bar',
                label: 'Export (kWh)',
                data: values.export ?? values.labels.map(() => null),
                backgroundColor: 'rgba(31, 178, 86, 0.3)', // DS.good - selling is positive!
                borderWidth: 0,
                borderRadius: 2,
                hidden: true,
                yAxisID: 'y2',
                barPercentage: 0.85,
                categoryPercentage: 0.9,
                grouped: false,
                order: 0,
            },
            {
                type: 'bar',
                label: 'Water Heating (kW)',
                data: values.water ?? values.labels.map(() => null),
                backgroundColor: 'rgba(78, 168, 222, 0.3)', // DS.water at 30%
                borderWidth: 0,
                borderRadius: 2,
                hidden: true,
                yAxisID: 'y1',
                barPercentage: 0.85,
                categoryPercentage: 0.9,
                grouped: false,
                order: 0,
            },
            {
                type: 'line',
                label: 'SoC Target (%)',
                data: values.socTarget ?? values.labels.map(() => null),
                borderColor: DS.night, // Cyan
                borderDash: [0, 6], // Round dots (0 dash + round cap = dots)
                borderCapStyle: 'round',
                backgroundColor: (context: any) => {
                    const ctx = context.chart.ctx
                    const isDark = document.documentElement.classList.contains('dark')
                    const opacity = isDark ? 0.05 : 0.1 // Very subtle fill
                    const gradient = ctx.createLinearGradient(0, 0, 0, context.chart.height)
                    gradient.addColorStop(0, `rgba(6, 182, 212, ${opacity})`) // DS.night
                    gradient.addColorStop(1, 'rgba(6, 182, 212, 0)')
                    return gradient
                },
                fill: true,
                // Dim historical segments (before nowIndex) to 50% opacity
                segment: {
                    borderColor: (ctx: any) => {
                        const nowIdx = values.nowIndex ?? -1
                        if (nowIdx >= 0 && ctx.p1DataIndex < nowIdx) {
                            return 'rgba(6, 182, 212, 0.5)' // DS.night at 50%
                        }
                        return DS.night
                    },
                },
                yAxisID: 'y3',
                pointRadius: 0,
                borderWidth: 3,
                tension: 0,
                stepped: 'after',
                hidden: true,
                order: 10, // Render behind other datasets (higher = further back)
            } as any,
            {
                type: 'line',
                label: 'SoC Projected (%)',
                data: values.socProjected ?? values.labels.map(() => null),
                borderColor: DS.night, // Cyan - solid line
                // Dim historical segments (before nowIndex) to 50% opacity
                segment: {
                    borderColor: (ctx: any) => {
                        const nowIdx = values.nowIndex ?? -1
                        // If segment end point is before nowIndex, it's historical
                        if (nowIdx >= 0 && ctx.p1DataIndex < nowIdx) {
                            return 'rgba(6, 182, 212, 0.5)' // DS.night at 50%
                        }
                        return DS.night
                    },
                },
                yAxisID: 'y3',
                pointRadius: 0,
                borderWidth: 3,
                tension: 0.3,
                hidden: true,
            } as any,
            {
                type: 'line',
                label: 'SoC Actual (%)',
                data: values.socActual ?? values.labels.map(() => null),
                borderColor: DS.night, // Cyan - dotted to differentiate
                borderDash: [0, 6], // Round dots (same as SoC Target)
                borderCapStyle: 'round',
                yAxisID: 'y3',
                pointRadius: 0,
                borderWidth: 3,
                tension: 0.3,
                hidden: true,
            },
        ],
    }

    // Add no-data message if needed
    if (values.hasNoData) {
        // cast to ExtendedChartData here to avoid ChartData strictness while manipulating plugins
        ;(baseData as ExtendedChartData).plugins = {
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
        nowPct: values.nowPct ?? null,
        hasNoData: !!values.hasNoData,
        pricingConfig: pricing,
    }
}

const nowLinePlugin: Plugin = {
    id: 'nowLine',
    afterDatasetsDraw(chart) {
        const {
            ctx,
            chartArea: { top, bottom },
            scales: { x },
        } = chart
        const data = chart.data as ExtendedChartData
        const nowPct = data.nowPct

        if (typeof nowPct !== 'number' || nowPct < 0 || nowPct > 1) return

        const totalLabels = data.labels?.length || 0
        if (totalLabels < 2) return

        // Calculate fractional index position
        // nowPct is linear 0..1 fraction of the total domain duration
        // For a time axis where labels represent intervals (e.g. 00:00 start),
        // the full 24h duration corresponds to 'totalLabels' slots conceptually.
        // (totalLabels - 1) ends at the *start* of the last slot.
        // We want 1.0 to mapped to the end of the last slot.
        const fractionalIndex = nowPct * totalLabels
        const idx1 = Math.floor(fractionalIndex)
        const idx2 = Math.ceil(fractionalIndex)
        const ratio = fractionalIndex - idx1

        const x1 = x.getPixelForValue(idx1)
        const x2 = x.getPixelForValue(idx2)
        const xPos = x1 + (x2 - x1) * ratio

        // Check if visible (within current zoom)
        if (xPos < x.left || xPos > x.right) return

        ctx.save()
        ctx.beginPath()
        ctx.strokeStyle = '#e879f9'
        ctx.lineWidth = 1.5
        ctx.shadowColor = '#e879f9'
        ctx.shadowBlur = 10
        ctx.setLineDash([4, 4])
        ctx.moveTo(xPos, top)
        ctx.lineTo(xPos, bottom)
        ctx.stroke()
        ctx.setLineDash([])

        // Draw "NOW" Label with Glow
        ctx.fillStyle = '#e879f9'
        ctx.textAlign = 'center'
        ctx.font = 'bold 10px monospace'
        ctx.fillText('NOW', xPos, top - 8)

        ctx.restore()
    },
}

// Production-grade dot grid plugin - aligns with data slots, zoom-adaptive
const dotGridPlugin: Plugin = {
    id: 'dotGrid',
    beforeDraw(chart) {
        const { ctx, chartArea, scales } = chart
        if (!chartArea || !scales.x) return

        const { left, right, top, bottom } = chartArea
        const xScale = scales.x
        const dotRadius = 1
        const yDotSpacing = 30 // Visual spacing in pixels for Y axis

        ctx.save()
        ctx.fillStyle = 'rgba(100, 116, 139, 0.25)' // --color-grid at 25% opacity

        const totalLabels = chart.data.labels?.length || 0
        if (totalLabels < 2) {
            ctx.restore()
            return
        }

        // Calculate pixels per slot to determine zoom level
        const firstX = xScale.getPixelForValue(0)
        const secondX = xScale.getPixelForValue(1)
        const pixelsPerSlot = Math.abs(secondX - firstX)

        // Adaptive step: if zoomed out (small pixels/slot), show hourly (every 4 slots for 15-min data)
        // If zoomed in (large pixels/slot), show every slot
        let step = 1
        if (pixelsPerSlot < 8) {
            step = 4 // Hourly when very zoomed out
        } else if (pixelsPerSlot < 15) {
            step = 2 // Every 30 min when moderately zoomed out
        }

        // Draw dots at each visible data slot position (X) and at regular Y intervals
        for (let i = 0; i < totalLabels; i += step) {
            const x = xScale.getPixelForValue(i)

            // Skip if outside visible area
            if (x < left - 5 || x > right + 5) continue

            // Draw dots vertically at regular intervals
            for (let y = top; y <= bottom; y += yDotSpacing) {
                ctx.beginPath()
                ctx.arc(x, y, dotRadius, 0, Math.PI * 2)
                ctx.fill()
            }
        }

        ctx.restore()
    },
}

// Custom plugin for OLED-like glow effects
const glowPlugin: Plugin = {
    id: 'glowEffects',
    beforeDatasetsDraw(chart) {
        const { ctx } = chart
        ctx.save()
        // Default shadow settings
        ctx.shadowBlur = 0
        ctx.shadowColor = 'transparent'
    },
    afterDatasetDraw(chart, args) {
        const { ctx } = chart
        const dataset = chart.data.datasets[args.index] as any

        // Only restore if we saved in beforeDatasetDraw
        if (dataset.glow) {
            ctx.restore()
        }
    },
    beforeDatasetDraw(chart, args) {
        const { ctx } = chart
        const dataset = chart.data.datasets[args.index] as any

        if (dataset.glow) {
            ctx.save()
            ctx.shadowColor = dataset.borderColor as string
            ctx.shadowBlur = 8 // Subtle glow (reduced from 15)
            ctx.shadowOffsetX = 0
            ctx.shadowOffsetY = 0
        }
    },
}

// Chart configuration helpers removed and consolidated into applyData

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
    range = '48h',
    refreshToken = 0,
    slotsOverride,
    useHistoryForToday = false,
    showDayToggle = false,
}: ChartCardProps) {
    const [hasNoDataMessage, setHasNoDataMessage] = useState(false)
    const currentDay = day || 'today'
    const [rangeState, setRangeState] = useState<ChartRange>(range)
    const ref = useRef<HTMLCanvasElement | null>(null)
    const chartRef = useRef<Chart | null>(null)
    const [themeColors, setThemeColors] = useState<Record<string, string>>({})
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
    const [pricingConfig, setPricingConfig] = useState<{ vat: number; fees: number } | undefined>()

    // Load overlay defaults from config
    useEffect(() => {
        Api.config()
            .then((config) => {
                // Parse pricing for tooltips
                if ((config as any)?.pricing) {
                    const p = (config as any).pricing
                    const vat = p.vat_percent ?? 25
                    const fees = (p.grid_transfer_fee_sek ?? 0) + (p.energy_tax_sek ?? 0)
                    setPricingConfig({ vat, fees })
                }

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
    }, [overlays.socActual])
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
                pricingConfig,
            ),
            options: chartOptions,
            plugins: [dotGridPlugin, nowLinePlugin, glowPlugin],
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
        const anyChart = chartInstance as unknown as { _destroyed?: boolean; _plugins?: unknown; $plugins?: unknown }
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
            const liveData = buildLiveData(slots, currentDay, rangeState, themeColors, pricingConfig)
            if (!liveData) return

            setHasNoDataMessage(!!liveData.hasNoData)

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

            try {
                if (!isChartUsable(chartRef.current)) return
                if (chartRef.current) {
                    chartRef.current.data = liveData
                    chartRef.current.update()
                }
            } catch (err) {
                console.error('Chart update error:', err)
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
            })
    }, [currentDay, overlays, themeColors, rangeState, refreshToken, slotsOverride, useHistoryForToday, pricingConfig])

    // Memoize theme colors to prevent unnecessary re-computations
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
    pricing?: { vat: number; fees: number },
): ExtendedChartData | null {
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
                const isExec = slot.is_executed === true

                price.push(slot.import_price_sek_kwh ?? null)
                pv.push(isExec && slot.actual_pv_kwh != null ? slot.actual_pv_kwh : (slot.pv_forecast_kwh ?? null))
                load.push(
                    isExec && slot.actual_load_kwh != null ? slot.actual_load_kwh : (slot.load_forecast_kwh ?? null),
                )
                // For charge/export, prefer actual_* when executed; discharge/water remain planned.
                charge.push(
                    isExec && slot.actual_charge_kw != null
                        ? slot.actual_charge_kw
                        : (slot.battery_charge_kw ?? slot.charge_kw ?? null),
                )
                discharge.push(slot.battery_discharge_kw ?? slot.discharge_kw ?? null)
                exp.push(isExec && slot.actual_export_kw != null ? slot.actual_export_kw : (slot.export_kwh ?? null))
                water.push(slot.water_heating_kw ?? null)
                socTarget.push(slot.soc_target_percent ?? null)
                socProjected.push(slot.projected_soc_percent ?? null)
                socActual.push(slot.soc_actual_percent != null ? slot.soc_actual_percent : null)
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

        // Calculate precise time percentage for "Now Line"
        let nowPct: number | null = null
        if (day === 'today') {
            const totalMs = steps * stepMs
            const elapsed = now.getTime() - anchor.getTime()
            if (elapsed >= 0 && elapsed <= totalMs) {
                nowPct = elapsed / totalMs
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
                nowPct,
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
            return createChartData(
                {
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
                const isExec = slot.is_executed === true

                price.push(slot.import_price_sek_kwh ?? null)
                pv.push(isExec && slot.actual_pv_kwh != null ? slot.actual_pv_kwh : (slot.pv_forecast_kwh ?? null))
                load.push(
                    isExec && slot.actual_load_kwh != null ? slot.actual_load_kwh : (slot.load_forecast_kwh ?? null),
                )
                charge.push(
                    isExec && slot.actual_charge_kw != null
                        ? slot.actual_charge_kw
                        : (slot.battery_charge_kw ?? slot.charge_kw ?? null),
                )
                discharge.push(slot.battery_discharge_kw ?? slot.discharge_kw ?? null)
                exp.push(isExec && slot.actual_export_kw != null ? slot.actual_export_kw : (slot.export_kwh ?? null))
                water.push(slot.water_heating_kw ?? null)
                socTarget.push(slot.soc_target_percent ?? null)
                socProjected.push(slot.projected_soc_percent ?? null)
                socActual.push(slot.soc_actual_percent != null ? slot.soc_actual_percent : null)
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

        // Calculate precise time percentage for "Now Line"
        let nowPct: number | null = null
        const totalMs = steps * stepMs
        const elapsed = now.getTime() - anchor.getTime()
        // For 48h view, we show "now" if it's within the window (which starts at 00:00 today)
        if (elapsed >= 0 && elapsed <= totalMs) {
            nowPct = elapsed / totalMs
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
                nowPct,
            },
            themeColors,
            pricing,
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
    const socActual = ordered.map((slot) => slot.soc_actual_percent ?? null)

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
