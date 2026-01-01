/* eslint-disable @typescript-eslint/no-explicit-any */
import { useState, useEffect } from 'react'
import { FlaskConical, Play, RotateCcw, Zap } from 'lucide-react'
import { Api, ScheduleResponse } from '../lib/api'
import ChartCard from '../components/ChartCard'

export default function Lab() {
    const [loading, setLoading] = useState(false)
    const [config, setConfig] = useState<any>(null)
    const [simResult, setSimResult] = useState<ScheduleResponse | null>(null)

    // Lab Parameters
    const [batteryCap, setBatteryCap] = useState(10)
    const [maxPower, setMaxPower] = useState(5)

    useEffect(() => {
        Api.config().then((c) => {
            setConfig(c)
            setBatteryCap(c.battery?.capacity_kwh || 10)
            setMaxPower(c.battery?.max_charge_power_kw || 5)
        })
    }, [])

    const runSimulation = async () => {
        setLoading(true)
        try {
            const overrides = {
                battery: {
                    capacity_kwh: batteryCap,
                    max_charge_power_kw: maxPower,
                    max_discharge_power_kw: maxPower,
                },
            }

            const res = await Api.simulate({ manual_plan: [], overrides })
            setSimResult(res)
        } catch (e) {
            console.error(e)
        } finally {
            setLoading(false)
        }
    }

    const resetToDefaults = () => {
        if (config) {
            setBatteryCap(config.battery?.capacity_kwh || 10)
            setMaxPower(config.battery?.max_charge_power_kw || 5)
            setSimResult(null)
        }
    }

    return (
        <div className="max-w-7xl mx-auto space-y-6 pb-20">
            <header>
                <h1 className="text-3xl font-bold tracking-tight text-text flex items-center gap-3">
                    <FlaskConical className="h-8 w-8 text-accent" />
                    The Lab
                </h1>
                <p className="text-muted mt-1">Run "What If?" simulations without affecting your real schedule.</p>
            </header>

            <div className="grid grid-cols-1 lg:grid-cols-3 gap-6">
                <div className="space-y-6">
                    <div className="card p-5 space-y-6">
                        <div className="flex items-center gap-2 text-lg font-medium text-text">
                            <Zap className="h-5 w-5 text-accent" />
                            <span>Hardware Config</span>
                        </div>

                        <div className="space-y-4">
                            <div>
                                <div className="flex justify-between text-sm mb-2">
                                    <span className="text-muted">Battery Capacity</span>
                                    <span className="text-text font-mono">{batteryCap} kWh</span>
                                </div>
                                <input
                                    type="range"
                                    min="5"
                                    max="100"
                                    step="1"
                                    value={batteryCap}
                                    onChange={(e) => setBatteryCap(parseFloat(e.target.value))}
                                    className="w-full accent-accent h-2 bg-surface2 rounded-lg appearance-none cursor-pointer"
                                />
                            </div>

                            <div>
                                <div className="flex justify-between text-sm mb-2">
                                    <span className="text-muted">Max Power (Charge/Discharge)</span>
                                    <span className="text-text font-mono">{maxPower} kW</span>
                                </div>
                                <input
                                    type="range"
                                    min="1"
                                    max="25"
                                    step="0.5"
                                    value={maxPower}
                                    onChange={(e) => setMaxPower(parseFloat(e.target.value))}
                                    className="w-full accent-accent h-2 bg-surface2 rounded-lg appearance-none cursor-pointer"
                                />
                            </div>
                        </div>

                        <div className="pt-4 flex gap-3">
                            <button
                                onClick={runSimulation}
                                disabled={loading}
                                className="flex-1 btn btn-primary flex items-center justify-center gap-2"
                            >
                                {loading ? (
                                    'Simulating...'
                                ) : (
                                    <>
                                        <Play className="h-4 w-4" /> Run Sim
                                    </>
                                )}
                            </button>
                            <button onClick={resetToDefaults} className="btn btn-ghost px-3" title="Reset to Config">
                                <RotateCcw className="h-4 w-4" />
                            </button>
                        </div>
                    </div>

                    <div className="card p-5 bg-surface/50 border-dashed">
                        <p className="text-xs text-muted leading-relaxed">
                            <strong>Note:</strong> These simulations use live market prices and forecasts. Adjusting
                            capacity scales your current SoC% to the new size. Results are not saved to the planner.
                        </p>
                    </div>
                </div>

                <div className="lg:col-span-2 space-y-6">
                    {simResult ? (
                        <ChartCard range="48h" showDayToggle={false} slotsOverride={simResult.schedule} />
                    ) : (
                        <div className="h-full min-h-[400px] card flex flex-col items-center justify-center text-muted space-y-4">
                            <FlaskConical className="h-12 w-12 opacity-20" />
                            <p>Adjust parameters and click Run Sim to see results.</p>
                        </div>
                    )}
                </div>
            </div>
        </div>
    )
}
