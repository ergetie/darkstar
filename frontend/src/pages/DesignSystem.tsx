/**
 * DesignSystem Page
 * 
 * Visual reference for all design system components.
 * Uses actual CSS classes from index.css for live preview.
 */

import { useState } from 'react'
import ThemeToggle from '../components/ThemeToggle'

export default function DesignSystem() {
    const [toggleActive, setToggleActive] = useState(false)
    const [progressValue, setProgressValue] = useState(65)

    return (
        <main className="mx-auto max-w-6xl px-6 py-10 space-y-12">
            {/* Header */}
            <header className="flex items-center justify-between">
                <div>
                    <h1 className="text-4xl font-bold text-text">Darkstar Design System</h1>
                    <p className="text-muted text-lg mt-2">Visual reference &amp; component showcase</p>
                </div>
                <ThemeToggle />
            </header>

            {/* Color Palette */}
            <section>
                <h2 className="text-2xl font-semibold text-text mb-4">Color Palette</h2>
                <div className="grid grid-cols-2 md:grid-cols-4 lg:grid-cols-6 gap-4">
                    {[
                        { name: 'Accent', var: '--color-accent', hex: '#FFCE59' },
                        { name: 'Good', var: '--color-good', hex: '#1FB256' },
                        { name: 'Warn', var: '--color-warn', hex: '#F59E0B' },
                        { name: 'Bad', var: '--color-bad', hex: '#F15132' },
                        { name: 'Water', var: '--color-water', hex: '#4EA8DE' },
                        { name: 'House', var: '--color-house', hex: '#A855F7' },
                        { name: 'Peak', var: '--color-peak', hex: '#EC4899' },
                        { name: 'Night', var: '--color-night', hex: '#06B6D4' },
                        { name: 'Grid', var: '--color-grid', hex: '#64748B' },
                        { name: 'Neutral', var: '--color-neutral', hex: '#989FA5' },
                        { name: 'AI', var: '--color-ai', hex: '#8B5CF6' },
                    ].map((color) => (
                        <div key={color.name} className="rounded-ds-md overflow-hidden shadow-float bg-surface">
                            <div
                                className="h-16"
                                style={{ backgroundColor: `rgb(var(${color.var}))` }}
                            />
                            <div className="p-2">
                                <div className="text-sm font-medium text-text">{color.name}</div>
                                <div className="text-xs text-muted font-mono">{color.hex}</div>
                            </div>
                        </div>
                    ))}
                </div>

                <h3 className="text-lg font-medium text-text mt-6 mb-3">Surface Colors</h3>
                <div className="grid grid-cols-2 md:grid-cols-4 gap-4">
                    {[
                        { name: 'Canvas', var: '--color-canvas' },
                        { name: 'Surface', var: '--color-surface' },
                        { name: 'Surface2', var: '--color-surface2' },
                        { name: 'Line', var: '--color-line' },
                    ].map((color) => (
                        <div
                            key={color.name}
                            className="h-20 rounded-ds-md border border-line flex items-center justify-center"
                            style={{ backgroundColor: `rgb(var(${color.var}))` }}
                        >
                            <span className="text-sm font-medium text-text">{color.name}</span>
                        </div>
                    ))}
                </div>
            </section>

            {/* Typography */}
            <section>
                <h2 className="text-2xl font-semibold text-text mb-4">Typography</h2>
                <div className="space-y-3 bg-surface p-6 rounded-ds-lg">
                    <div className="text-4xl">text-4xl (28px) — Page Titles</div>
                    <div className="text-3xl">text-3xl (24px) — Section Headers</div>
                    <div className="text-2xl">text-2xl (18px) — Subsections</div>
                    <div className="text-xl">text-xl (16px) — Large Body</div>
                    <div className="text-lg">text-lg (14px) — Body Text</div>
                    <div className="text-md">text-md (13px) — Secondary</div>
                    <div className="text-base">text-base (12px) — Small Body</div>
                    <div className="text-sm">text-sm (11px) — Labels</div>
                    <div className="text-xs">text-xs (10px) — Micro</div>
                </div>
            </section>

            {/* Buttons */}
            <section>
                <h2 className="text-2xl font-semibold text-text mb-4">Buttons</h2>
                <div className="flex flex-wrap gap-4 items-center">
                    <button className="btn btn-primary">Primary</button>
                    <button className="btn btn-secondary">Secondary</button>
                    <button className="btn btn-danger">Danger</button>
                    <button className="btn btn-ghost">Ghost</button>
                    <button className="btn btn-primary btn-pill">Pill Primary</button>
                    <button className="btn btn-ghost btn-pill">Pill Ghost</button>
                </div>
                <div className="flex flex-wrap gap-4 items-center mt-4">
                    <button className="btn btn-primary" disabled>Disabled Primary</button>
                    <button className="btn btn-secondary" disabled>Disabled Secondary</button>
                    <button className="btn btn-ghost" disabled>Disabled Ghost</button>
                </div>
                <div className="mt-4">
                    <p className="text-sm text-muted mb-2">Dynamic color (using CSS custom property):</p>
                    <button
                        className="btn btn-pill btn-dynamic"
                        style={{ '--btn-bg': 'rgb(var(--color-water))', '--btn-text': '#fff' } as React.CSSProperties}
                    >
                        Custom Water Color
                    </button>
                </div>
            </section>

            {/* Banners */}
            <section>
                <h2 className="text-2xl font-semibold text-text mb-4">Banners / Alerts</h2>
                <div className="space-y-2">
                    <div className="banner banner-info">
                        <span>ℹ️</span>
                        <span>Info Banner — Neutral information message</span>
                    </div>
                    <div className="banner banner-success">
                        <span>✅</span>
                        <span>Success Banner — Action completed successfully</span>
                    </div>
                    <div className="banner banner-warning">
                        <span>⚠️</span>
                        <span>Warning Banner — Requires attention</span>
                    </div>
                    <div className="banner banner-error">
                        <span>❌</span>
                        <span>Error Banner — Critical issue detected</span>
                    </div>
                    <div className="banner banner-purple">
                        <span>👻</span>
                        <span>Purple Banner — Special mode (shadow mode)</span>
                    </div>
                </div>
            </section>

            {/* Badges */}
            <section>
                <h2 className="text-2xl font-semibold text-text mb-4">Badges</h2>
                <div className="flex flex-wrap gap-3 items-center">
                    <span className="badge badge-accent">Accent</span>
                    <span className="badge badge-good">Good</span>
                    <span className="badge badge-warn">Warning</span>
                    <span className="badge badge-bad">Error</span>
                    <span className="badge badge-muted">Muted</span>
                </div>
            </section>

            {/* Form Elements */}
            <section>
                <h2 className="text-2xl font-semibold text-text mb-4">Form Elements</h2>
                <div className="grid md:grid-cols-2 gap-6">
                    <div>
                        <label className="block text-sm text-muted mb-2">Text Input</label>
                        <input type="text" className="input" placeholder="Enter value..." />
                    </div>
                    <div>
                        <label className="block text-sm text-muted mb-2">Number Input</label>
                        <input type="number" className="input" placeholder="0" />
                    </div>
                    <div>
                        <label className="block text-sm text-muted mb-2">Toggle Switch</label>
                        <div className="flex items-center gap-3">
                            <div
                                className={`toggle ${toggleActive ? 'active' : ''}`}
                                onClick={() => setToggleActive(!toggleActive)}
                            >
                                <div className="toggle-knob" />
                            </div>
                            <span className="text-sm text-text">{toggleActive ? 'On' : 'Off'}</span>
                        </div>
                    </div>
                </div>
            </section>

            {/* Loading States */}
            <section>
                <h2 className="text-2xl font-semibold text-text mb-4">Loading States</h2>
                <div className="flex items-center gap-8">
                    <div>
                        <div className="text-sm text-muted mb-2">Spinner</div>
                        <div className="spinner" />
                    </div>
                    <div className="flex-1">
                        <div className="text-sm text-muted mb-2">Skeleton</div>
                        <div className="skeleton h-8 w-full" />
                    </div>
                    <div className="flex-1">
                        <div className="text-sm text-muted mb-2">Progress Bar ({progressValue}%)</div>
                        <div className="progress-bar">
                            <div className="progress-bar-fill" style={{ width: `${progressValue}%` }} />
                        </div>
                        <input
                            type="range"
                            min="0"
                            max="100"
                            value={progressValue}
                            onChange={(e) => setProgressValue(Number(e.target.value))}
                            className="slider mt-2"
                        />
                    </div>
                </div>
            </section>

            {/* Data Visualization */}
            <section>
                <h2 className="text-2xl font-semibold text-text mb-4">Data Visualization</h2>
                <div className="grid md:grid-cols-2 gap-6">
                    <div className="bg-surface p-4 rounded-ds-lg">
                        <div className="text-sm text-muted mb-3">Mini-Bar Chart (Solar)</div>
                        <div className="flex items-center gap-4">
                            <div className="mini-bars">
                                {[40, 55, 75, 90, 100, 85, 70, 45].map((h, i) => (
                                    <div
                                        key={i}
                                        className="mini-bar"
                                        style={{ height: `${h}%`, background: 'rgb(var(--color-accent))' }}
                                    />
                                ))}
                            </div>
                            <span className="font-mono font-bold text-accent">4.2kW</span>
                        </div>
                    </div>
                    <div className="bg-surface p-4 rounded-ds-lg">
                        <div className="text-sm text-muted mb-3">Mini-Bar Chart (Battery)</div>
                        <div className="flex items-center gap-4">
                            <div className="mini-bars">
                                {[60, 65, 70, 75, 80, 82, 85, 85].map((h, i) => (
                                    <div
                                        key={i}
                                        className="mini-bar"
                                        style={{ height: `${h}%`, background: 'rgb(var(--color-good))' }}
                                    />
                                ))}
                            </div>
                            <span className="font-mono font-bold text-good">85%</span>
                        </div>
                    </div>
                </div>
            </section>


            {/* Metric Cards */}
            <section>
                <h2 className="text-2xl font-semibold text-text mb-4">Metric Cards</h2>
                <div className="grid md:grid-cols-3 gap-4">
                    {[
                        { border: 'solar', label: 'Solar', value: '4.2 kW', sub: '+12% today' },
                        { border: 'battery', label: 'Battery', value: '78%', sub: 'Target: 85%' },
                        { border: 'house', label: 'House Load', value: '1.8 kW', sub: 'Avg: 2.1 kW' },
                        { border: 'water', label: 'Water', value: '2.4 kWh', sub: 'Today' },
                        { border: 'grid', label: 'Grid', value: '-0.5 kW', sub: 'Exporting' },
                        { border: 'bad', label: 'Error', value: '3', sub: 'Issues detected' },
                    ].map((card) => (
                        <div
                            key={card.border}
                            className={`metric-card-border metric-card-border-${card.border} bg-surface p-4`}
                        >
                            <div className="text-xs text-muted uppercase tracking-wider">{card.label}</div>
                            <div className="text-2xl font-bold text-text mt-1">{card.value}</div>
                            <div className="text-xs text-muted mt-1">{card.sub}</div>
                        </div>
                    ))}
                </div>
            </section>

            {/* Border Radius */}
            <section>
                <h2 className="text-2xl font-semibold text-text mb-4">Border Radius</h2>
                <div className="flex gap-4 items-end">
                    {[
                        { name: 'sm', size: '8px' },
                        { name: 'md', size: '12px' },
                        { name: 'lg', size: '16px' },
                        { name: 'xl', size: '20px' },
                        { name: 'pill', size: '9999px' },
                    ].map((r) => (
                        <div key={r.name} className="text-center">
                            <div
                                className={`w-16 h-16 bg-accent rounded-ds-${r.name}`}
                            />
                            <div className="text-xs text-muted mt-2">{r.name}</div>
                            <div className="text-xs text-muted">{r.size}</div>
                        </div>
                    ))}
                </div>
            </section>

            {/* Spacing */}
            <section>
                <h2 className="text-2xl font-semibold text-text mb-4">Spacing Scale (4px grid)</h2>
                <div className="flex gap-4 items-end flex-wrap">
                    {[1, 2, 3, 4, 5, 6, 8, 10, 12].map((n) => (
                        <div key={n} className="text-center">
                            <div
                                className="bg-accent"
                                style={{
                                    width: `var(--space-${n})`,
                                    height: `var(--space-${n})`,
                                    minWidth: '4px',
                                    minHeight: '4px'
                                }}
                            />
                            <div className="text-xs text-muted mt-2">ds-{n}</div>
                        </div>
                    ))}
                </div>
            </section>

            {/* Side-by-Side Dark/Light Preview */}
            <section>
                <h2 className="text-2xl font-semibold text-text mb-4">Dark / Light Mode Comparison</h2>
                <div className="grid md:grid-cols-2 gap-6">
                    {/* Dark Mode Preview */}
                    <div className="rounded-ds-lg overflow-hidden" style={{ background: '#0f1216' }}>
                        <div className="px-4 py-3" style={{ background: '#14191f' }}>
                            <span className="text-sm font-semibold" style={{ color: '#e6e9ef' }}>🌙 Dark Mode — Glow Buttons</span>
                        </div>
                        <div className="p-4 space-y-2" style={{ background: '#14191f' }}>
                            <div className="flex justify-between items-center p-3 rounded-lg" style={{ background: '#181e25' }}>
                                <span style={{ color: '#FFCE59' }}>☀️ Solar</span>
                                <span className="font-mono font-bold" style={{ color: '#FFCE59' }}>4.2kW</span>
                            </div>
                            <div className="flex justify-between items-center p-3 rounded-lg" style={{ background: '#181e25' }}>
                                <span style={{ color: '#1FB256' }}>🔋 Battery</span>
                                <span className="font-mono font-bold" style={{ color: '#1FB256' }}>85%</span>
                            </div>
                            <div className="flex justify-between items-center p-3 rounded-lg" style={{ background: '#181e25' }}>
                                <span style={{ color: '#A855F7' }}>🏠 House</span>
                                <span className="font-mono font-bold" style={{ color: '#e6e9ef' }}>1.8kW</span>
                            </div>
                            <div className="flex justify-between items-center p-3 rounded-lg" style={{ background: '#181e25' }}>
                                <span style={{ color: '#4EA8DE' }}>💧 Water</span>
                                <span className="font-mono font-bold" style={{ color: '#e6e9ef' }}>58°C</span>
                            </div>
                            <div className="flex gap-2 pt-3">
                                <button style={{
                                    background: '#FFCE59',
                                    color: '#1a1d23',
                                    padding: '8px 16px',
                                    borderRadius: '8px',
                                    fontWeight: 600,
                                    fontSize: '11px',
                                    boxShadow: '0 0 16px rgba(255, 206, 89, 0.4), 0 0 32px rgba(255, 206, 89, 0.2)'
                                }}>⚡ Boost</button>
                                <button style={{
                                    background: '#989FA5',
                                    color: '#fff',
                                    padding: '8px 16px',
                                    borderRadius: '8px',
                                    fontWeight: 600,
                                    fontSize: '11px',
                                    boxShadow: '0 0 12px rgba(152, 159, 165, 0.3)'
                                }}>🏖️ Vacation</button>
                            </div>
                        </div>
                    </div>

                    {/* Light Mode Preview */}
                    <div className="rounded-ds-lg overflow-hidden" style={{ background: '#DFDFDF' }}>
                        <div className="px-4 py-3" style={{ background: '#EFEFEF' }}>
                            <span className="text-sm font-semibold" style={{ color: '#2D2D2D' }}>☀️ Light Mode — Flat Buttons (TE Style)</span>
                        </div>
                        <div className="p-4 space-y-2" style={{ background: '#EFEFEF' }}>
                            <div className="flex justify-between items-center p-3 rounded-lg" style={{ background: '#D0D0D0' }}>
                                <span style={{ color: '#2D2D2D' }}>☀️ <b style={{ color: '#b38b00' }}>Solar</b></span>
                                <span className="font-mono font-bold" style={{ color: '#2D2D2D' }}>4.2kW</span>
                            </div>
                            <div className="flex justify-between items-center p-3 rounded-lg" style={{ background: '#D0D0D0' }}>
                                <span style={{ color: '#2D2D2D' }}>🔋 <b style={{ color: '#1FB256' }}>Battery</b></span>
                                <span className="font-mono font-bold" style={{ color: '#2D2D2D' }}>85%</span>
                            </div>
                            <div className="flex justify-between items-center p-3 rounded-lg" style={{ background: '#D0D0D0' }}>
                                <span style={{ color: '#2D2D2D' }}>🏠 <b style={{ color: '#A855F7' }}>House</b></span>
                                <span className="font-mono font-bold" style={{ color: '#2D2D2D' }}>1.8kW</span>
                            </div>
                            <div className="flex justify-between items-center p-3 rounded-lg" style={{ background: '#D0D0D0' }}>
                                <span style={{ color: '#2D2D2D' }}>💧 <b style={{ color: '#4EA8DE' }}>Water</b></span>
                                <span className="font-mono font-bold" style={{ color: '#2D2D2D' }}>58°C</span>
                            </div>
                            <div className="flex gap-2 pt-3">
                                <button style={{
                                    background: '#FFCE59',
                                    color: '#2D2D2D',
                                    padding: '8px 16px',
                                    borderRadius: '8px',
                                    fontWeight: 600,
                                    fontSize: '11px',
                                    border: 'none'
                                }}>⚡ Boost</button>
                                <button style={{
                                    background: '#989FA5',
                                    color: '#fff',
                                    padding: '8px 16px',
                                    borderRadius: '8px',
                                    fontWeight: 600,
                                    fontSize: '11px',
                                    border: 'none'
                                }}>🏖️ Vacation</button>
                            </div>
                        </div>
                    </div>
                </div>
            </section>

            {/* Footer */}
            <footer className="text-center text-muted text-sm pt-8 border-t border-line">
                <p>SSOT: <code className="bg-surface2 px-2 py-1 rounded text-xs">frontend/src/index.css</code></p>
                <p className="mt-2">Toggle dark/light mode using the switch in the header.</p>
            </footer>
        </main>
    )
}
