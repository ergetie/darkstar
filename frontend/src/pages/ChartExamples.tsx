import { useState } from 'react'
import DecompositionChart from '../components/DecompositionChart'
import type { AuroraHorizonSlot } from '../lib/types'

function generateMockSlots(): AuroraHorizonSlot[] {
    const slots: AuroraHorizonSlot[] = []
    const now = new Date()
    now.setMinutes(0, 0, 0)

    for (let i = 0; i < 48; i++) {
        const time = new Date(now.getTime() + i * 3600 * 1000)
        const hour = time.getHours()

        // PV Curve (bell curve centered at 13:00)
        let pv = 0
        if (hour > 5 && hour < 20) {
            pv = 5 * Math.sin(((hour - 6) / 14) * Math.PI)
        }
        // Add some noise
        pv = Math.max(0, pv + (Math.random() * 0.5 - 0.25))

        // Load Curve (morning and evening peaks)
        let load = 1.0 // base load
        // Morning peak 7-9
        load += 2 * Math.exp(-Math.pow(hour - 8, 2) / 4)
        // Evening peak 18-21
        load += 3 * Math.exp(-Math.pow(hour - 19, 2) / 6)
        // Noise
        load = Math.max(0.5, load + (Math.random() * 0.5 - 0.25))

        slots.push({
            slot_start: time.toISOString(),
            base: { pv_kwh: pv * 0.8, load_kwh: load * 0.9 }, // Base plan
            correction: { pv_kwh: pv * 0.2, load_kwh: load * 0.1 }, // Correction
            final: { pv_kwh: pv, load_kwh: load },
        })
    }
    return slots
}

export default function ChartExamples() {
    const [slots] = useState(generateMockSlots())

    return (
        <div className="p-8 space-y-16 max-w-5xl mx-auto pb-32">
            <header>
                <div className="inline-block px-3 py-1 rounded-full bg-surface2 text-[10px] text-muted uppercase tracking-wider font-bold mb-4">
                    Rev UI6 Brainstorm V2
                </div>
                <h1 className="text-3xl font-bold mb-2">Chart Makeover Concepts</h1>
                <p className="text-muted text-lg">Exploring radically different aesthetics.</p>
            </header>

            {/* Option A: The Field - Updated with CSS Dot Grid */}
            <section className="space-y-4">
                <div className="flex items-baseline justify-between">
                    <div>
                        <h2 className="text-xl font-bold text-accent">Option A: "The Field" (Fixed)</h2>
                        <p className="text-sm text-muted">
                            Tactile, vertical gradients, glowing lines. Now with a real CSS dot grid.
                        </p>
                    </div>
                </div>
                <div className="relative h-[360px] w-full bg-surface rounded-2xl border border-line shadow-float overflow-hidden p-6">
                    <div className="absolute top-4 right-4 px-2 py-1 bg-surface/50 backdrop-blur rounded text-[10px] text-muted font-mono z-10">
                        OP-1 / TE Inspired
                    </div>
                    <DecompositionChart slots={slots} mode="pv" variant="field" />
                </div>
            </section>

            {/* Option B: The OLED */}
            <section className="space-y-4">
                <div className="flex items-baseline justify-between">
                    <div>
                        <h2 className="text-xl font-bold text-[#22d3ee] font-mono">Option B: "The OLED"</h2>
                        <p className="text-sm text-muted">Pure black, neon thin lines, high contrast. No fills.</p>
                    </div>
                </div>
                <div className="relative h-[360px] w-full bg-black rounded-xl border border-[#333] p-6 shadow-2xl font-mono">
                    <DecompositionChart slots={slots} mode="pv" variant="oled" />
                </div>
            </section>

            {/* Option C: The Swiss */}
            <section className="space-y-4">
                <div className="flex items-baseline justify-between">
                    <div>
                        <h2 className="text-xl font-bold text-black dark:text-white">Option C: "The Swiss"</h2>
                        <p className="text-sm text-muted">
                            Brutalist, thick lines, solid colors. No gradients, no fluff.
                        </p>
                    </div>
                </div>
                <div className="relative h-[360px] w-full bg-[#f4f4f5] border-4 border-black p-8">
                    <div className="absolute top-0 left-0 bg-black text-white px-3 py-1 text-xs font-bold uppercase tracking-widest">
                        Power Log
                    </div>
                    <DecompositionChart slots={slots} mode="pv" variant="swiss" />
                </div>
            </section>
        </div>
    )
}
