import Card from './Card'
import { useEffect, useMemo, useRef, useState } from 'react'
import {
    Chart as ChartJS,
    ChartConfiguration,
    ChartDataset,
    Plugin,
    ScriptableContext,
    ScriptableLineSegmentContext,
} from 'chart.js/auto'
import type { Chart, Scale, Tick, ChartData } from 'chart.js/auto'
import zoomPlugin from 'chartjs-plugin-zoom'
ChartJS.register(zoomPlugin)
import { sampleChart } from '../lib/sample'
import { Api } from '../lib/api'
import type { ScheduleSlot } from '../lib/types'
import { formatHour, DaySel, isToday, isTomorrow } from '../lib/time'
// Note: We use a custom plugin for the NOW marker to support zooming.
// CSS overlays don't work well with pan/zoom.

// Fixed bar height for the "EV standby" band — keep-on slots carry no planned
// energy, so this is a presence indicator, not a real kW value.
const EV_STANDBY_BAND_KW = 0.3

// Hook: returns true when viewport is below Tailwind's `md` breakpoint (768px)
function useIsMobile(): boolean {
    const [isMobile, setIsMobile] = useState(() => {
        if (typeof window === 'undefined') return false
        return window.matchMedia('(max-width: 767px)').matches
    })
    useEffect(() => {
        const mq = window.matchMedia('(max-width: 767px)')
        const handler = (e: MediaQueryListEvent) => setIsMobile(e.matches)
        mq.addEventListener('change', handler)
        return () => mq.removeEventListener('change', handler)
    }, [])
    return isMobile
}

/** Splits a total SEK/kWh price into spot and fees+VAT parts.
 * Total = (Spot + Fees) * (1 + VAT/100); Spot = (Total / (1 + VAT/100)) - Fees. */
// eslint-disable-next-line react-refresh/only-export-components -- pure helper, tested directly
export function splitPriceBreakdown(
    value: number,
    pricing?: { vat: number; fees: number },
): { spot: number; feesAndVat: number } | null {
    if (!pricing) return null
    const vatMul = 1 + pricing.vat / 100
    // Avoid division by zero
    const basePrice = vatMul > 0 ? value / vatMul : value
    const spot = Math.max(0, basePrice - pricing.fees)
    const feesAndVat = value - spot
    return { spot, feesAndVat }
}

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
            backgroundColor: 'rgba(30, 30, 46, 0.75)',
            titleColor: '#e6e9ef',
            bodyColor: '#a6b0bf',
            borderColor: 'rgba(255, 255, 255, 0.1)',
            borderWidth: 1,
            padding: 12,
            displayColors: true,
            usePointStyle: true,
            // Align tooltip to the left to avoid covering the graph
            xAlign: 'right',
            yAlign: 'bottom',
            caretPadding: 8,
            callbacks: {
                labelPointStyle: function (context) {
                    // eslint-disable-next-line @typescript-eslint/no-explicit-any
                    const dataset = context.dataset as any
                    // Dashed lines get filled circle markers
                    if (dataset.borderDash && dataset.borderDash.length > 0) {
                        return { pointStyle: 'circle', rotation: 0 }
                    }
                    // Solid lines get filled rect markers
                    return { pointStyle: 'rectRounded', rotation: 0 }
                },
                labelColor: function (context) {
                    // Return the dataset color for both border and background to make markers solid/filled
                    const color = context.dataset.borderColor as string
                    return {
                        borderColor: color,
                        backgroundColor: color,
                        borderWidth: 0,
                    }
                },
                title: function (context) {
                    return context[0].label
                },
                label: function (context) {
                    const datasetLabel = context.dataset.label || ''
                    if (datasetLabel === 'EV Standby') {
                        return 'EV Standby: Charger switch held on after target — car draws only what it needs'
                    }
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
                        const breakdown = splitPriceBreakdown(value, pricing)
                        if (breakdown) {
                            return [
                                `${datasetLabel}: ${formattedValue}${unit}`,
                                `(Spot: ${breakdown.spot.toFixed(2)} + Tax/Fees: ${breakdown.feesAndVat.toFixed(2)})`,
                            ] as unknown as string[] // Chart.js allows string arrays for multiline
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
            title: { display: false, text: 'kW' },
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
            max: 9,
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
    waterBoost?: (boolean | null)[]
    customEntityActive?: (number | null)[]
    evCharging?: (number | null)[]
    evSurplus?: (number | null)[]
    evKeepOn?: (number | null)[]
    socTarget?: (number | null)[]
    socProjected?: (number | null)[]
    socActual?: (number | null)[]
    hasNoData?: boolean
    day?: DaySel
    nowIndex?: number | null
    nowPct?: number | null
    actualPv?: (number | null)[]
    actualLoad?: (number | null)[]
    actualCharge?: (number | null)[]
    actualDischarge?: (number | null)[]
    actualExport?: (number | null)[]
    actualWater?: (number | null)[]
    actualEvCharging?: (number | null)[]
}

interface ExtendedChartData extends ChartData {
    nowIndex?: number | null
    nowPct?: number | null
    hasNoData?: boolean
    plugins?: unknown
    pricingConfig?: { vat: number; fees: number }
}

const hexToRgba = (hex: string, alpha: number) => {
    if (!hex || !hex.startsWith('#')) return hex
    const r = parseInt(hex.slice(1, 3), 16)
    const g = parseInt(hex.slice(3, 5), 16)
    const b = parseInt(hex.slice(5, 7), 16)
    return `rgba(${r}, ${g}, ${b}, ${alpha})`
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
        ai: '#8B5CF6', // --color-ai: Violet
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
                backgroundColor: (context: ScriptableContext<'line'>) => {
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
                stepped: 'middle',
                pointRadius: 0,
                borderWidth: 3,
                order: 1,
            } as ChartDataset,
            {
                type: 'line',
                label: 'PV Forecast (kW)',
                data: values.pv,
                borderColor: DS.accent, // Gold - it's the SUN
                backgroundColor: (context: ScriptableContext<'line'>) => {
                    const ctx = context.chart.ctx
                    const isDark = document.documentElement.classList.contains('dark')
                    const opacity = isDark ? 0.2 : 0.65 // Higher in light mode
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
                order: 20,
            } as ChartDataset,
            {
                type: 'bar',
                label: 'Load (kW)',
                data: values.load,
                backgroundColor: 'rgba(0, 183, 181, 0.25)', // DS.house cyan at 25%
                borderColor: DS.house,
                glow: false,
                borderWidth: 0,
                borderRadius: 2,
                yAxisID: 'y1',
                barPercentage: 0.85,
                categoryPercentage: 0.9,
                grouped: false,
                order: 0, // Render in front of gradient lines
                // eslint-disable-next-line @typescript-eslint/no-explicit-any
            } as any,
            {
                type: 'bar',
                label: 'Charge (kW)',
                data: values.charge ?? values.labels.map(() => null),
                backgroundColor: 'rgba(241, 81, 50, 0.25)', // DS.bad - grid charge costs money
                borderColor: DS.bad,
                glow: false,
                borderWidth: 0,
                borderRadius: 2,
                hidden: true,
                yAxisID: 'y1',
                barPercentage: 0.85,
                categoryPercentage: 0.9,
                grouped: false,
                order: 0,
                // eslint-disable-next-line @typescript-eslint/no-explicit-any
            } as any,
            {
                type: 'bar',
                label: 'Discharge (kW)',
                data: values.discharge ?? values.labels.map(() => null),
                backgroundColor: 'rgba(236, 72, 153, 0.25)', // DS.peak (pink) at 25%
                borderColor: DS.peak,
                glow: false,
                borderWidth: 0,
                borderRadius: 2,
                hidden: true,
                yAxisID: 'y1',
                barPercentage: 0.85,
                categoryPercentage: 0.9,
                grouped: false,
                order: 0,
                // eslint-disable-next-line @typescript-eslint/no-explicit-any
            } as any,
            {
                type: 'bar',
                label: 'Export (kW)',
                data: values.export ?? values.labels.map(() => null),
                backgroundColor: 'rgba(31, 178, 86, 0.3)', // DS.good - selling is positive!
                borderColor: DS.good,
                glow: false,
                borderWidth: 0,
                borderRadius: 2,
                hidden: true,
                yAxisID: 'y2',
                barPercentage: 0.85,
                categoryPercentage: 0.9,
                grouped: false,
                order: 0,
                // eslint-disable-next-line @typescript-eslint/no-explicit-any
            } as any,
            {
                type: 'bar',
                label: 'Water Heating (kW)',
                data: values.water ?? values.labels.map(() => null),
                backgroundColor: 'rgba(78, 168, 222, 0.25)',
                borderColor: DS.water,
                glow: false,
                borderWidth: 0,
                borderRadius: 2,
                hidden: true,
                yAxisID: 'y1',
                barPercentage: 0.85,
                categoryPercentage: 0.9,
                grouped: false,
                order: 0,
                // eslint-disable-next-line @typescript-eslint/no-explicit-any
            } as any,
            {
                type: 'bar',
                label: 'Water Heating Boost (kW)',
                data:
                    values.waterBoost?.map((b, i) =>
                        b && values.water && i < values.water.length ? values.water[i] : null,
                    ) ?? values.labels.map(() => null),
                backgroundColor: 'rgba(0, 255, 200, 0.90)',
                borderColor: '#00ffc8ff',
                glow: true,
                glowBlur: 20,
                glowOpacity: 1.0,
                borderWidth: 0,
                borderRadius: 2,
                hidden: true,
                yAxisID: 'y1',
                barPercentage: 0.85,
                categoryPercentage: 0.9,
                grouped: false,
                order: 0,
                // eslint-disable-next-line @typescript-eslint/no-explicit-any
            } as any,
            {
                type: 'bar',
                label: 'EV Charging (kW)',
                data: values.evCharging ?? values.labels.map(() => null),
                backgroundColor: 'rgba(139, 92, 246, 0.25)', // DS.ai (violet) at 25%
                borderColor: DS.ai,
                glow: false,
                borderWidth: 0,
                borderRadius: 2,
                yAxisID: 'y1',
                barPercentage: 0.85,
                categoryPercentage: 0.9,
                grouped: false,
                order: 0,
                // eslint-disable-next-line @typescript-eslint/no-explicit-any
            } as any,
            {
                type: 'bar',
                label: 'EV Surplus Charging (kW)',
                data: values.evSurplus ?? values.labels.map(() => null),
                backgroundColor: 'rgba(139, 92, 246, 0.90)', // DS.ai (violet) at 90%
                borderColor: '#c084fc',
                glow: true,
                glowBlur: 20,
                glowOpacity: 1.0,
                borderWidth: 0,
                borderRadius: 2,
                yAxisID: 'y1',
                barPercentage: 0.85,
                categoryPercentage: 0.9,
                grouped: false,
                order: 0,
                // eslint-disable-next-line @typescript-eslint/no-explicit-any
            } as any,
            {
                type: 'bar',
                label: 'Excess PV Sink (kW)',
                data: values.customEntityActive ?? values.labels.map(() => null),
                backgroundColor: 'rgba(255, 182, 64, 0.90)',
                borderColor: '#FF9F40',
                glow: true,
                glowBlur: 20,
                glowOpacity: 1.0,
                borderWidth: 0,
                borderRadius: 2,
                hidden: true,
                yAxisID: 'y1',
                barPercentage: 0.85,
                categoryPercentage: 0.9,
                grouped: false,
                order: 0,
                // eslint-disable-next-line @typescript-eslint/no-explicit-any
            } as any,
            {
                type: 'line',
                label: 'SoC Target (%)',
                data: values.socTarget ?? values.labels.map(() => null),
                borderColor: DS.night, // Cyan
                borderDash: [0, 6], // Round dots (0 dash + round cap = dots)
                borderCapStyle: 'round',
                backgroundColor: (context: ScriptableContext<'line'>) => {
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
                    borderColor: (ctx: ScriptableLineSegmentContext) => {
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
                stepped: 'middle',
                hidden: true,
                order: 10, // Render behind other datasets (higher = further back)
            } as ChartDataset,
            {
                type: 'line',
                label: 'SoC Projected (%)',
                data: values.socProjected ?? values.labels.map(() => null),
                borderColor: DS.night, // Cyan - solid line
                // Dim historical segments (before nowIndex) to 50% opacity
                segment: {
                    borderColor: (ctx: ScriptableLineSegmentContext) => {
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
            } as ChartDataset,
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
            } as ChartDataset,
            {
                type: 'line',
                label: 'Actual PV (kW)',
                data: values.actualPv ?? values.labels.map(() => null),
                borderColor: DS.accent,
                borderDash: [2, 4],
                pointRadius: 0,
                borderWidth: 2,
                yAxisID: 'y4',
                tension: 0.4,
                hidden: true,
                order: 1,
            } as ChartDataset,
            {
                type: 'line',
                label: 'Actual Load (kW)',
                data: values.actualLoad ?? values.labels.map(() => null),
                borderColor: DS.house,
                borderDash: [2, 4],
                pointRadius: 0,
                borderWidth: 2,
                yAxisID: 'y1',
                stepped: 'middle',
                hidden: true,
                order: 1,
            } as ChartDataset,
            {
                type: 'line',
                label: 'Actual Charge (kW)',
                data: values.actualCharge ?? values.labels.map(() => null),
                borderColor: DS.bad,
                borderDash: [2, 4],
                pointRadius: 0,
                borderWidth: 2,
                yAxisID: 'y1',
                stepped: 'middle',
                hidden: true,
                order: 1,
            } as ChartDataset,
            {
                type: 'line',
                label: 'Actual Discharge (kW)',
                data: values.actualDischarge ?? values.labels.map(() => null),
                borderColor: DS.peak,
                borderDash: [2, 4],
                pointRadius: 0,
                borderWidth: 2,
                yAxisID: 'y1',
                stepped: 'middle',
                hidden: true,
                order: 1,
            } as ChartDataset,
            {
                type: 'line',
                label: 'Actual EV (kW)',
                data: values.actualEvCharging ?? values.labels.map(() => null),
                borderColor: DS.ai,
                borderDash: [2, 4],
                pointRadius: 0,
                borderWidth: 2,
                yAxisID: 'y1',
                stepped: 'middle',
                hidden: true,
                order: 1,
            } as ChartDataset,
            {
                type: 'line',
                label: 'Actual Export (kW)',
                data: values.actualExport ?? values.labels.map(() => null),
                borderColor: DS.good,
                borderDash: [2, 4],
                pointRadius: 0,
                borderWidth: 2,
                yAxisID: 'y2',
                stepped: 'middle',
                hidden: true,
                order: 1,
            } as ChartDataset,
            {
                type: 'line',
                label: 'Actual Water (kW)',
                data: values.actualWater ?? values.labels.map(() => null),
                borderColor: DS.water,
                borderDash: [2, 4],
                pointRadius: 0,
                borderWidth: 2,
                yAxisID: 'y1',
                stepped: 'middle',
                hidden: true,
                order: 1,
            } as ChartDataset,
            {
                type: 'bar',
                label: 'EV Standby',
                data: values.evKeepOn ?? values.labels.map(() => null),
                backgroundColor: 'rgba(139, 92, 246, 0.35)', // DS.ai (violet), muted vs. EV Charging
                borderColor: '#8b5cf6',
                borderDash: [3, 2],
                glow: false,
                borderWidth: 1,
                borderRadius: 2,
                yAxisID: 'y1',
                barPercentage: 0.85,
                categoryPercentage: 0.9,
                grouped: false,
                order: 0,
                // eslint-disable-next-line @typescript-eslint/no-explicit-any
            } as any,
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

// Mobile tap-to-select: vertical band drawn at selected slot's x-position.
// Per-instance plugin options are used (chart.options.plugins.selectionBand)
// so there is no module-level mutable state and multiple ChartCard instances
// never bleed into each other.
const selectionBandPlugin: Plugin = {
    id: 'selectionBand',
    beforeDatasetsDraw(chart) {
        // Read per-instance options set by the component
        // eslint-disable-next-line @typescript-eslint/no-explicit-any
        const opts = (chart.options.plugins as any)?.selectionBand as
            | { mobile?: boolean; index?: number | null }
            | undefined
        if (!opts?.mobile) return
        const idx = opts.index
        if (idx === null || idx === undefined) return

        const {
            ctx,
            chartArea: { top, bottom },
            scales: { x },
        } = chart

        if (!x) return

        const xPos = x.getPixelForValue(idx)
        if (xPos < x.left || xPos > x.right) return

        // Width of one slot in pixels for the band
        const slotWidth =
            chart.data.labels && chart.data.labels.length > 1
                ? Math.abs(x.getPixelForValue(1) - x.getPixelForValue(0))
                : 8

        ctx.save()
        ctx.fillStyle = 'rgba(255, 255, 255, 0.08)'
        ctx.fillRect(xPos - slotWidth / 2, top, slotWidth, bottom - top)

        // Vertical accent line at centre of selected slot
        ctx.beginPath()
        ctx.strokeStyle = 'rgba(255, 206, 89, 0.7)' // --color-accent at 70%
        ctx.lineWidth = 1.5
        ctx.shadowColor = 'rgba(255, 206, 89, 0.5)'
        ctx.shadowBlur = 6
        ctx.moveTo(xPos, top)
        ctx.lineTo(xPos, bottom)
        ctx.stroke()
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
        ctx.fillStyle = 'rgba(100, 116, 139, 0.4)' // --color-grid at 40% opacity (increased for visibility)

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
        const dataset = chart.data.datasets[args.index] as unknown as {
            glow?: boolean
            borderColor?: string
        }

        // Only restore if we saved in beforeDatasetDraw
        if (dataset.glow) {
            ctx.restore()
        }
    },
    beforeDatasetDraw(chart, args) {
        const { ctx } = chart
        const dataset = chart.data.datasets[args.index] as unknown as {
            glow?: boolean
            borderColor?: string
            glowBlur?: number
            glowOpacity?: number
        }

        if (dataset.glow) {
            ctx.save()
            const isDark = document.documentElement.classList.contains('dark')
            const opacity = dataset.glowOpacity ?? (isDark ? 0.4 : 0.25)
            ctx.shadowColor = hexToRgba(dataset.borderColor as string, opacity)
            ctx.shadowBlur = dataset.glowBlur ?? (isDark ? 30 : 20)
            ctx.shadowOffsetX = 0
            ctx.shadowOffsetY = 0
        }
    },
}

// Chart configuration helpers removed and consolidated into applyData

type ChartCardProps = {
    day?: DaySel
    refreshToken?: number
    useHistoryForToday?: boolean
    slotsOverride?: ScheduleSlot[]
}

export default function ChartCard({
    day = 'today',
    refreshToken = 0,
    slotsOverride,
    useHistoryForToday = false,
}: ChartCardProps) {
    const isMobile = useIsMobile()
    const [hasNoDataMessage, setHasNoDataMessage] = useState(false)
    const [hasRealData, setHasRealData] = useState(false) // Track when real data has been loaded
    const currentDay = day || 'today'
    const ref = useRef<HTMLCanvasElement | null>(null)
    const chartRef = useRef<Chart | null>(null)
    const cardRef = useRef<HTMLDivElement | null>(null)
    const userHasZoomedRef = useRef(false) // Track if user has manually zoomed/panned
    const lastHadTomorrowPricesRef = useRef<boolean | null>(null) // Track tomorrow prices availability
    const [isZoomed, setIsZoomed] = useState(false) // UI state for reset button visibility
    const [themeColors, setThemeColors] = useState<Record<string, string>>({})
    // Mobile tap-to-select state
    const [selectedIndex, setSelectedIndex] = useState<number | null>(null)
    // Snapshot of the latest chart data pushed to the chart instance — used by the
    // selection panel memo so it reads stable React state rather than a mutating ref (S2b)
    const [liveChartData, setLiveChartData] = useState<ExtendedChartData | null>(null)
    // Per-instance ref for current mobile state — kept in sync so the baked-in onClick
    // handler always reads the live value even after viewport crosses 768px (N1)
    const isMobileRef = useRef(isMobile)
    useEffect(() => {
        isMobileRef.current = isMobile
    }, [isMobile])

    // Click-away handler: tapping outside the card clears selection (mobile only)
    useEffect(() => {
        if (!isMobile) return
        const handler = (e: MouseEvent) => {
            if (cardRef.current && !cardRef.current.contains(e.target as Node)) {
                setSelectedIndex(null)
            }
        }
        document.addEventListener('click', handler, true)
        return () => document.removeEventListener('click', handler, true)
    }, [isMobile])

    // Build formatted slot data for the selection panel from stable React state (S2b).
    // Keyed on liveChartData (updated whenever chart data is swapped) + selectedIndex + isMobile,
    // so the panel never reads a mutating ref mid-render.
    const selectedSlotPanel = useMemo(() => {
        if (!isMobile || selectedIndex === null || !liveChartData) return null
        const data = liveChartData
        if (!data.labels || selectedIndex >= data.labels.length) return null

        const label = data.labels[selectedIndex] as string
        const pricing = data.pricingConfig

        const rows: { label: string; value: string; color: string }[] = []

        for (const ds of data.datasets) {
            if (ds.hidden) continue
            const raw = ds.data[selectedIndex]
            if (raw === null || raw === undefined) continue
            const value = typeof raw === 'number' ? raw : null
            if (value === null) continue

            const dsLabel = ds.label || ''
            let formattedValue = value.toFixed(2)
            let unit = ''
            let extra: string | null = null

            if (dsLabel.includes('SEK/kWh')) {
                formattedValue = value.toFixed(2)
                unit = ' SEK/kWh'
                const breakdown = splitPriceBreakdown(value, pricing)
                if (breakdown) {
                    extra = `Spot: ${breakdown.spot.toFixed(2)} + Tax/Fees: ${breakdown.feesAndVat.toFixed(2)}`
                }
            } else if (dsLabel.includes('kW')) {
                formattedValue = value.toFixed(1)
                unit = ' kW'
            } else if (dsLabel.includes('kWh')) {
                formattedValue = value.toFixed(2)
                unit = ' kWh'
            } else if (dsLabel.includes('%')) {
                formattedValue = value.toFixed(1)
                unit = '%'
            }

            const color = typeof ds.borderColor === 'string' ? ds.borderColor : '#e6e9ef'
            rows.push({ label: dsLabel, value: `${formattedValue}${unit}`, color })
            if (extra) {
                rows.push({ label: '', value: extra, color: 'transparent' })
            }
        }

        return { label, rows }
    }, [isMobile, selectedIndex, liveChartData])
    const [overlays, setOverlays] = useState(() => {
        // Load from localStorage if available, otherwise use defaults
        const STORAGE_KEY = 'darkstar-chart-overlays'
        const STORAGE_VERSION = 5 // Increment to force migration

        try {
            const saved = localStorage.getItem(STORAGE_KEY)
            if (saved) {
                const parsed = JSON.parse(saved)

                // Check version - if missing or old, use new defaults
                if (parsed._version !== STORAGE_VERSION) {
                    console.log(`Migrating overlay preferences from v${parsed._version || 1} to v${STORAGE_VERSION}`)
                    // Use new defaults, but preserve user's explicit customizations if they match new defaults
                    const newDefaults = {
                        _version: STORAGE_VERSION,
                        price: true,
                        pv: true,
                        load: true,
                        charge: true,
                        discharge: true,
                        export: true,
                        water: false,
                        ev: false,
                        evKeepOn: false,
                        excessPvSink: false,
                        socTarget: false,
                        socProjected: false,
                        socActual: true,
                        showActual: false,
                    }
                    // Save migrated version immediately
                    localStorage.setItem(STORAGE_KEY, JSON.stringify(newDefaults))
                    return newDefaults
                }

                return {
                    _version: STORAGE_VERSION,
                    price: parsed.price ?? true,
                    pv: parsed.pv ?? true,
                    load: parsed.load ?? true,
                    charge: parsed.charge ?? true,
                    discharge: parsed.discharge ?? true,
                    export: parsed.export ?? true,
                    water: parsed.water ?? false,
                    ev: parsed.ev ?? false,
                    evKeepOn: parsed.evKeepOn ?? false,
                    excessPvSink: parsed.excessPvSink ?? false,
                    socTarget: parsed.socTarget ?? false,
                    socProjected: parsed.socProjected ?? false,
                    socActual: parsed.socActual ?? true,
                    showActual: parsed.showActual ?? false,
                }
            }
        } catch (e) {
            console.warn('Failed to load overlay preferences:', e)
        }
        return {
            _version: STORAGE_VERSION,
            price: true,
            pv: true,
            load: true,
            charge: true,
            discharge: true,
            export: true,
            water: false,
            ev: false,
            evKeepOn: false,
            excessPvSink: false,
            socTarget: false,
            socProjected: false,
            socActual: true,
            showActual: false,
        }
    })
    const [showOverlayMenu, setShowOverlayMenu] = useState(false)
    const [pricingConfig, setPricingConfig] = useState<{ vat: number; fees: number } | undefined>()
    const [excessPvPowerKw, setExcessPvPowerKw] = useState(1.0)
    const [scaling, setScaling] = useState({
        solarKwp: 10,
        gridMaxKw: 8,
        inverterMaxKw: 8,
    })

    // Persist overlay preferences to localStorage
    useEffect(() => {
        try {
            localStorage.setItem('darkstar-chart-overlays', JSON.stringify(overlays))
        } catch (e) {
            console.warn('Failed to save overlay preferences:', e)
        }
    }, [overlays])

    // Load scaling values from config and set default overlays for new users
    // All overlays are enabled by default - users can toggle them off via the chart controls
    useEffect(() => {
        const STORAGE_KEY = 'darkstar-chart-overlays'
        const hasStoredPreferences = localStorage.getItem(STORAGE_KEY) !== null

        Api.config()
            .then((config) => {
                // Scaling values - always apply
                const legacySolarKwp = config?.system?.solar_array?.kwp
                const solarArrays = config?.system?.solar_arrays
                let solarKwp = 10

                if (legacySolarKwp != null) {
                    solarKwp = Number(legacySolarKwp)
                } else if (Array.isArray(solarArrays) && solarArrays.length > 0) {
                    solarKwp = solarArrays.reduce((sum, arr) => sum + Number(arr.kwp || 0), 0)
                }

                const gridMaxKw = config?.system?.grid?.max_power_kw ?? 8
                const inverterMaxKw = config?.system?.inverter?.max_power_kw ?? 8
                setScaling({
                    solarKwp: Number(solarKwp),
                    gridMaxKw: Number(gridMaxKw),
                    inverterMaxKw: Number(inverterMaxKw),
                })

                // Parse pricing for tooltips - always apply
                if (config.pricing) {
                    const p = config.pricing
                    const vat = p.vat_percent ?? 25
                    const fees = (p.grid_transfer_fee_sek ?? 0) + (p.energy_tax_sek ?? 0)
                    setPricingConfig({ vat, fees })
                }

                // Load custom entity power_kw for chart bar scaling
                const powerKw = config?.executor?.excess_pv?.custom_entity?.power_kw
                if (powerKw != null) {
                    setExcessPvPowerKw(Number(powerKw))
                }

                // For NEW users (no localStorage), enable all overlays by default
                if (!hasStoredPreferences) {
                    setOverlays({
                        _version: 5,
                        price: true,
                        pv: true,
                        load: true,
                        charge: true,
                        discharge: true,
                        export: true,
                        water: true,
                        ev: true,
                        evKeepOn: true,
                        excessPvSink: false,
                        socTarget: true,
                        socProjected: true,
                        socActual: true,
                        showActual: false,
                    })
                }
            })
            .catch((err) => console.error('Failed to load config:', err))
    }, []) // No dependencies - only run once on mount

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

    // Chart initialization: only runs ONCE when canvas ref is available
    useEffect(() => {
        if (!ref.current || Object.keys(themeColors).length === 0) return
        // Skip re-initialization if real data has already been loaded
        if (hasRealData && chartRef.current) return

        const cfg: ChartConfiguration = {
            type: 'bar',
            data: createChartData(
                {
                    labels: sampleChart.labels,
                    price: sampleChart.price,
                    pv: sampleChart.pv,
                    load: sampleChart.load,
                    charge: sampleChart.charge,
                    discharge: sampleChart.discharge,
                },
                themeColors,
                pricingConfig,
            ),
            options: {
                ...chartOptions,
                // On mobile: disable built-in floating tooltip (replaced by tap-panel below)
                plugins: {
                    ...chartOptions?.plugins,
                    tooltip: {
                        ...chartOptions?.plugins?.tooltip,
                        enabled: !isMobile,
                    },
                    zoom: {
                        ...chartOptions?.plugins?.zoom,
                        zoom: {
                            ...chartOptions?.plugins?.zoom?.zoom,
                            onZoomComplete: () => {
                                userHasZoomedRef.current = true
                                setIsZoomed(true)
                            },
                        },
                        pan: {
                            ...chartOptions?.plugins?.zoom?.pan,
                            onPanComplete: () => {
                                userHasZoomedRef.current = true
                                setIsZoomed(true)
                            },
                        },
                    },
                    // Per-instance plugin options for the selection band (B1/S1)
                    selectionBand: { mobile: isMobile, index: null as number | null },
                    // eslint-disable-next-line @typescript-eslint/no-explicit-any
                } as any,
                // Always register onClick but guard on isMobileRef so crossing 768px mid-session
                // works without recreating the chart (N1).
                onClick: (_event, elements) => {
                    if (!isMobileRef.current) return
                    if (elements && elements.length > 0) {
                        const idx = elements[0].index
                        setSelectedIndex((prev) => (prev === idx ? null : idx))
                    } else {
                        setSelectedIndex(null)
                    }
                },
                scales: {
                    ...chartOptions?.scales,
                    y1: {
                        ...chartOptions?.scales?.y1,
                        max: Math.max(scaling.gridMaxKw, scaling.inverterMaxKw, scaling.solarKwp),
                    },
                    y2: {
                        ...chartOptions?.scales?.y2,
                        max: Math.max(scaling.gridMaxKw, scaling.inverterMaxKw, scaling.solarKwp),
                    },
                    y4: {
                        ...chartOptions?.scales?.y4,
                        max: Math.max(scaling.gridMaxKw, scaling.inverterMaxKw, scaling.solarKwp),
                    },
                },
            },
            plugins: [dotGridPlugin, nowLinePlugin, selectionBandPlugin, glowPlugin],
        }
        chartRef.current = new ChartJS(ref.current, cfg)

        return () => {
            if (chartRef.current) {
                chartRef.current.destroy()
                chartRef.current = null
            }
        }
        // eslint-disable-next-line react-hooks/exhaustive-deps
    }, [themeColors, pricingConfig, hasRealData, scaling.gridMaxKw, scaling.inverterMaxKw, scaling.solarKwp]) // Re-create chart only for initial creation or theme/pricing changes (but not after real data loads)

    // Mobile: push current selection into per-instance plugin options and redraw (B1/S1/S3).
    // Dependency array is [selectedIndex] so it only runs when selection actually changes.
    useEffect(() => {
        if (!chartRef.current) return
        // eslint-disable-next-line @typescript-eslint/no-explicit-any
        const pluginsOpts = chartRef.current.options.plugins as any
        if (pluginsOpts) {
            pluginsOpts.selectionBand = {
                mobile: isMobileRef.current,
                index: selectedIndex,
            }
        }
        chartRef.current.draw()
    }, [selectedIndex])

    // Mobile: update chart tooltip enabled state when viewport changes.
    // Also updates the per-instance selectionBand plugin option so the band is
    // disabled the moment the viewport crosses to desktop (N1/S1).
    useEffect(() => {
        if (!chartRef.current) return
        if (chartRef.current.options?.plugins?.tooltip) {
            chartRef.current.options.plugins.tooltip.enabled = !isMobile
        }
        // eslint-disable-next-line @typescript-eslint/no-explicit-any
        const pluginsOpts = chartRef.current.options.plugins as any
        if (pluginsOpts) {
            pluginsOpts.selectionBand = {
                mobile: isMobile,
                index: selectedIndex,
            }
        }
        chartRef.current.update('none')
        if (!isMobile) {
            // Clearing selection when switching to desktop
            setSelectedIndex(null)
        }
    }, [isMobile]) // eslint-disable-line react-hooks/exhaustive-deps

    // Dynamically update chart scales when scaling configuration changes
    // This prevents chart re-initialization and preserves loaded data
    useEffect(() => {
        if (!chartRef.current || !hasRealData) return

        const chart = chartRef.current
        if (chart.options?.scales) {
            const sharedPowerMax = Math.max(scaling.gridMaxKw, scaling.inverterMaxKw, scaling.solarKwp)

            if (chart.options.scales.y1) {
                chart.options.scales.y1.max = sharedPowerMax
            }
            if (chart.options.scales.y2) {
                chart.options.scales.y2.max = sharedPowerMax
            }
            if (chart.options.scales.y4) {
                chart.options.scales.y4.max = sharedPowerMax
            }

            chart.update('none') // Update without animation for instant response
        }
    }, [scaling.gridMaxKw, scaling.inverterMaxKw, scaling.solarKwp, hasRealData])

    const isChartUsable = (chartInstance: Chart | null) => {
        if (!chartInstance) return false
        const anyChart = chartInstance as unknown as { _destroyed?: boolean; _plugins?: unknown; $plugins?: unknown }
        if (anyChart._destroyed) return false
        if (anyChart._plugins === undefined && anyChart.$plugins === undefined) return false
        return true
    }

    useEffect(() => {
        const chartInstance = chartRef.current
        if (!isChartUsable(chartInstance) || Object.keys(themeColors).length === 0) return
        const applyData = (slots: ScheduleSlot[]) => {
            if (!isChartUsable(chartRef.current)) return
            const liveData = buildLiveData(slots, currentDay, themeColors, pricingConfig, excessPvPowerKw)
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
            if (ds[7]) ds[7].hidden = !overlays.water
            if (ds[8]) ds[8].hidden = !overlays.ev
            if (ds[9]) ds[9].hidden = !overlays.ev // EV Surplus
            if (ds[10]) ds[10].hidden = !overlays.excessPvSink
            if (ds[11]) ds[11].hidden = !overlays.socTarget
            if (ds[12]) ds[12].hidden = !overlays.socProjected
            if (ds[13]) ds[13].hidden = !overlays.socActual

            // Actual Overlays
            if (ds[14]) ds[14].hidden = !overlays.showActual || !overlays.pv
            if (ds[15]) ds[15].hidden = !overlays.showActual || !overlays.load
            if (ds[16]) ds[16].hidden = !overlays.showActual || !overlays.charge
            if (ds[17]) ds[17].hidden = !overlays.showActual || !overlays.discharge
            if (ds[18]) ds[18].hidden = !overlays.showActual || !overlays.ev
            if (ds[19]) ds[19].hidden = !overlays.showActual || !overlays.export
            if (ds[20]) ds[20].hidden = !overlays.showActual || !overlays.water
            if (ds[21]) ds[21].hidden = !overlays.evKeepOn // EV Standby

            try {
                if (chartRef.current) {
                    chartRef.current.data = liveData
                    // Reset selection and snapshot the new data so the panel memo
                    // reads stable React state (not a mutating ref) (S2a/S2b)
                    setSelectedIndex(null)
                    setLiveChartData(liveData)
                    chartRef.current.update()

                    // Check if tomorrow prices just became available
                    const tomorrowPricesJustArrived =
                        lastHadTomorrowPricesRef.current === false && liveData.hasTomorrowPrices

                    // Update tracking ref
                    lastHadTomorrowPricesRef.current = liveData.hasTomorrowPrices

                    // Only apply auto-zoom if user hasn't manually zoomed, or if tomorrow prices just arrived
                    if (tomorrowPricesJustArrived) {
                        // Tomorrow prices arrived - reset to full 48h view
                        chartRef.current.resetZoom()
                        userHasZoomedRef.current = false
                        setIsZoomed(false)
                    } else if (!userHasZoomedRef.current) {
                        // User hasn't zoomed yet - apply initial auto-zoom logic
                        if (!liveData.hasTomorrowPrices) {
                            // Zoom to show roughly first 24h (approx slots 0-96 for 15m resolution)
                            chartRef.current.zoomScale('x', { min: 0, max: 95 }, 'default')
                        } else {
                            chartRef.current.resetZoom()
                        }
                    }
                    // else: user has zoomed and tomorrow prices haven't changed - preserve zoom
                }
            } catch (err) {
                console.error('Chart update error:', err)
            }
        }

        if (slotsOverride && slotsOverride.length) {
            applyData(slotsOverride)
            return
        }

        const shouldLoadHistory = useHistoryForToday && currentDay === 'today'
        const loader = shouldLoadHistory
            ? Api.scheduleTodayWithHistory().then((res) => ({ schedule: res.slots }))
            : Api.schedule()

        loader
            .then((data) => {
                applyData(data.schedule ?? [])
                setHasRealData(true)
            })
            .catch((err) => {
                console.error('Failed to load schedule:', err)
                setHasNoDataMessage(true)
            })
    }, [
        currentDay,
        overlays,
        themeColors,
        refreshToken,
        slotsOverride,
        useHistoryForToday,
        pricingConfig,
        excessPvPowerKw,
    ])

    // Memoize theme colors to prevent unnecessary re-computations
    return (
        // Outer wrapper holds ref for click-away detection (clears selection when tapping outside card on mobile)
        <div ref={cardRef}>
            <Card className={`p-4 md:p-6 ${isMobile && !!selectedSlotPanel ? '' : 'h-[380px]'}`}>
                <div className="flex items-baseline justify-between pb-2">
                    <div className="text-sm text-muted">Schedule Overview</div>
                    <div className="flex items-center gap-2">
                        {isZoomed && (
                            <button
                                className="rounded-pill px-3 py-1 text-[11px] font-semibold uppercase tracking-wide border border-line/60 text-muted hover:border-accent hover:text-accent transition"
                                onClick={() => {
                                    if (chartRef.current) {
                                        chartRef.current.resetZoom()
                                        userHasZoomedRef.current = false
                                        setIsZoomed(false)
                                    }
                                }}
                            >
                                Reset Zoom
                            </button>
                        )}
                        <button
                            className="rounded-pill px-3 py-1 text-[11px] font-semibold uppercase tracking-wide border border-line/60 text-muted hover:border-accent hover:text-accent transition"
                            onClick={() => setShowOverlayMenu((v) => !v)}
                        >
                            Overlays
                        </button>
                    </div>
                </div>
                {showOverlayMenu && (
                    <div className="mt-2 flex items-center justify-between gap-4">
                        {/* Main overlay toggles  */}
                        <div className="flex flex-wrap gap-1.5 text-[10px]">
                            {(
                                [
                                    ['Price', 'price', 'bg-grid/20 border-grid'],
                                    ['PV', 'pv', 'bg-accent/20 border-accent'],
                                    ['Load', 'load', 'bg-house/20 border-house'],
                                    ['Charge', 'charge', 'bg-bad/20 border-bad'],
                                    ['Discharge', 'discharge', 'bg-peak/20 border-peak'],
                                    ['EV', 'ev', 'bg-ai/20 border-ai'],
                                    ['EV Standby', 'evKeepOn', 'bg-ai/20 border-ai'],
                                    ['Export', 'export', 'bg-good/20 border-good'],
                                    ['Water', 'water', 'bg-water/20 border-water'],
                                    ['Excess PV', 'excessPvSink', 'bg-bad/20 border-good'],
                                    ['SoC Target', 'socTarget', 'bg-night/20 border-night'],
                                    ['SoC Proj', 'socProjected', 'bg-night/20 border-night'],
                                    ['SoC Act', 'socActual', 'bg-night/20 border-night'],
                                ] as const
                            ).map(([label, key, activeClass]) => (
                                <button
                                    key={key}
                                    onClick={(e) => {
                                        e.preventDefault()
                                        setOverlays((o) => ({ ...o, [key]: !o[key as keyof typeof o] }))
                                    }}
                                    className={`rounded-full px-2.5 py-0.5 border transition-all duration-150 font-medium ${
                                        overlays[key as keyof typeof overlays]
                                            ? `${activeClass} shadow-sm`
                                            : 'border-line/40 text-muted/60 hover:border-line hover:text-muted'
                                    }`}
                                >
                                    {label}
                                </button>
                            ))}
                        </div>
                        {/* Show Actual toggle - separated on right */}
                        <button
                            onClick={(e) => {
                                e.preventDefault()
                                setOverlays((o) => ({ ...o, showActual: !o.showActual }))
                            }}
                            className={`rounded-full px-3 py-1 border text-[10px] font-semibold transition-all duration-150 whitespace-nowrap ${
                                overlays.showActual
                                    ? 'bg-accent text-canvas border-accent shadow-md shadow-accent/30'
                                    : 'border-line/40 text-muted/60 hover:border-accent hover:text-accent'
                            }`}
                        >
                            📊 Actual
                        </button>
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
                {/* Mobile tap-to-select info panel — only rendered when a slot is selected on mobile */}
                {isMobile && selectedSlotPanel && (
                    <div
                        className="mt-2 rounded-xl border border-line/50 bg-surface2 px-3 py-2.5 shadow-inner"
                        onClick={(e) => e.stopPropagation()}
                    >
                        <div className="text-[11px] font-semibold text-accent font-mono mb-1.5">
                            {selectedSlotPanel.label}
                        </div>
                        <div className="flex flex-col gap-0.5">
                            {selectedSlotPanel.rows.map((row, i) => (
                                <div key={i} className="flex items-baseline gap-1.5 text-[11px]">
                                    {row.label ? (
                                        <>
                                            <span
                                                className="inline-block w-2 h-2 rounded-sm flex-shrink-0 mt-0.5"
                                                style={{ backgroundColor: row.color }}
                                            />
                                            <span className="text-muted flex-1 truncate">{row.label}:</span>
                                            <span className="text-text font-mono">{row.value}</span>
                                        </>
                                    ) : (
                                        <span className="text-muted/70 font-mono pl-3.5 text-[10px]">{row.value}</span>
                                    )}
                                </div>
                            ))}
                        </div>
                    </div>
                )}
            </Card>
        </div>
    )
}

// eslint-disable-next-line react-refresh/only-export-components -- pure helper, tested directly
export function buildLiveData(
    slots: ScheduleSlot[],
    day: DaySel,
    themeColors: Record<string, string> = {},
    pricing?: { vat: number; fees: number },
    excessPvPowerKw: number = 1.0,
): (ExtendedChartData & { hasTomorrowPrices: boolean }) | null {
    const hasTomorrowPrices = slots.some((slot) => isTomorrow(slot.start_time) && slot.import_price_sek_kwh != null)
    const filtered = slots.filter((slot) => isToday(slot.start_time) || isTomorrow(slot.start_time))

    if (!filtered.length) {
        console.log('[buildLiveData] No slots found for 48h range, creating fallback')
        const labels = Array.from({ length: 48 }, (_, i) => {
            const hour = i % 24
            return `${String(hour).padStart(2, '0')}:00`
        })
        return {
            ...createChartData(
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
            ),
            hasTomorrowPrices,
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

    // Use the first slot's time as the anchor if available, otherwise fallback to today 00:00
    // This ensures we align with the actual data being returned, shielding against timezone/date mismatches
    const anchor = new Date()
    if (ordered.length > 0) {
        // Parse the ISO string to extract Date and Offset, resetting time to 00:00:00
        // Format: YYYY-MM-DDTHH:MM:SS+HH:MM or YYYY-MM-DDTHH:MM:SSZ
        // We want: YYYY-MM-DDT00:00:00+HH:MM
        const startStr = ordered[0].start_time
        try {
            // Assume ISO 8601 standard length for YYYY-MM-DD
            const datePart = startStr.substring(0, 10)

            // Robust offset extraction: match Z or +HH:MM or -HH:MM
            const offsetMatch = startStr.match(/(Z|[+-]\d{2}:?\d{2})$/)
            const offset = offsetMatch ? offsetMatch[0] : 'Z'

            const midnightIso = `${datePart}T00:00:00${offset}`
            anchor.setTime(new Date(midnightIso).getTime())
        } catch (e) {
            console.error('Failed to parse anchor time from string:', startStr, e)
            const d = new Date(startStr)
            d.setHours(0, 0, 0, 0)
            anchor.setTime(d.getTime())
        }
    } else {
        anchor.setHours(0, 0, 0, 0)
    }

    const stepMs = resolutionMinutes * 60 * 1000
    const steps = Math.round((48 * 60) / resolutionMinutes)

    const slotByTime = new Map<string, ScheduleSlot>()
    for (const s of ordered) {
        // Standardize on UTC ISO strings for keys to avoid timezone mess
        const iso = new Date(s.start_time).toISOString()
        slotByTime.set(iso, s)
    }

    const labels: string[] = []
    const price: (number | null)[] = []
    const pv: (number | null)[] = []
    const load: (number | null)[] = []
    const charge: (number | null)[] = []
    const discharge: (number | null)[] = []
    const exp: (number | null)[] = []
    const water: (number | null)[] = []
    const waterBoost: (boolean | null)[] = []
    const customEntityActive: (number | null)[] = []
    const evCharging: (number | null)[] = []
    const evSurplus: (number | null)[] = []
    const evKeepOn: (number | null)[] = []
    const socTarget: (number | null)[] = []
    const socProjected: (number | null)[] = []
    const socActual: (number | null)[] = []
    const actualPv: (number | null)[] = []
    const actualLoad: (number | null)[] = []
    const actualCharge: (number | null)[] = []
    const actualDischarge: (number | null)[] = []
    const actualExport: (number | null)[] = []
    const actualWater: (number | null)[] = []
    const actualEvCharging: (number | null)[] = []

    let nowIndex: number | null = null
    const now = new Date()

    for (let i = 0; i < steps; i++) {
        const bucketStart = new Date(anchor.getTime() + i * stepMs)
        const bucketEnd = new Date(bucketStart.getTime() + stepMs)
        const slot = slotByTime.get(bucketStart.toISOString())

        labels.push(formatHour(bucketStart.toISOString()))

        if (slot) {
            const hourFraction = resolutionMinutes / 60

            price.push(slot.import_price_sek_kwh ?? null)
            // Main bars: always show planned/forecasted values
            // Actuals are shown in overlay lines
            const rawPvKwh = slot.pv_forecast_kwh ?? null
            pv.push(rawPvKwh != null ? rawPvKwh / hourFraction : null)

            const rawLoadKwh = slot.load_forecast_kwh ?? null
            load.push(rawLoadKwh != null ? rawLoadKwh / hourFraction : null)

            // Main bars: always show planned/forecasted values
            charge.push(slot.battery_charge_kw ?? slot.charge_kw ?? null)
            discharge.push(slot.battery_discharge_kw ?? slot.discharge_kw ?? null)

            const rawExportKwh = slot.export_kwh ?? null
            exp.push(rawExportKwh != null ? rawExportKwh / hourFraction : null)

            water.push(slot.water_heating_kw ?? null)
            waterBoost.push(
                slot.water_heating_boost && Object.values(slot.water_heating_boost).some(Boolean) ? true : null,
            )
            customEntityActive.push(
                slot.custom_entity_active && Object.values(slot.custom_entity_active).some(Boolean)
                    ? excessPvPowerKw
                    : null,
            )
            const regularEv = slot.ev_charging_kw ?? 0
            evCharging.push(regularEv > 0.01 ? regularEv : null)

            const surplusEv = slot.ev_surplus_kw
                ? Object.values(slot.ev_surplus_kw).reduce((sum: number, val: number) => sum + (val || 0), 0)
                : 0
            evSurplus.push(surplusEv > 0.01 ? surplusEv : null)

            const keepOnActive = slot.ev_keep_on ? Object.values(slot.ev_keep_on).some(Boolean) : false
            evKeepOn.push(keepOnActive && regularEv <= 0.01 ? EV_STANDBY_BAND_KW : null)
            socTarget.push(slot.soc_target_percent ?? null)
            socProjected.push(slot.projected_soc_percent ?? null)
            socActual.push(slot.actual_soc != null ? slot.actual_soc : null)

            // Populate actual* arrays
            const hourFrac = resolutionMinutes / 60
            actualPv.push(slot.actual_pv_kwh != null ? slot.actual_pv_kwh / hourFrac : null)
            actualLoad.push(slot.actual_load_kwh != null ? slot.actual_load_kwh / hourFrac : null)
            actualCharge.push(slot.actual_charge_kw ?? null)
            actualDischarge.push(slot.actual_discharge_kw ?? null)
            actualExport.push(slot.actual_export_kw ?? null)
            actualWater.push(slot.actual_water_kw ?? null)
            actualEvCharging.push(slot.actual_ev_charging_kw ?? null)
        } else {
            price.push(null)
            pv.push(null)
            load.push(null)
            charge.push(null)
            discharge.push(null)
            exp.push(null)
            evCharging.push(null)
            evSurplus.push(null)
            evKeepOn.push(null)
            water.push(null)
            waterBoost.push(null)
            customEntityActive.push(null)
            socTarget.push(null)
            socProjected.push(null)
            socActual.push(null)
            actualPv.push(null)
            actualLoad.push(null)
            actualCharge.push(null)
            actualDischarge.push(null)
            actualExport.push(null)
            actualWater.push(null)
            actualEvCharging.push(null)
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

    return {
        ...createChartData(
            {
                labels,
                price,
                pv,
                load,
                charge,
                discharge,
                export: exp,
                water,
                waterBoost,
                customEntityActive,
                evCharging,
                evSurplus,
                evKeepOn,
                socTarget,
                socProjected,
                socActual,
                nowIndex,
                actualPv,
                actualLoad,
                actualCharge,
                actualDischarge,
                actualExport,
                actualWater,
                actualEvCharging,
                nowPct,
            },
            themeColors,
            pricing,
        ),
        hasTomorrowPrices,
    }
}
