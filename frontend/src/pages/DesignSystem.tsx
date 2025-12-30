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
                            className="mt-2 w-full"
                        />
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

            {/* Footer */}
            <footer className="text-center text-muted text-sm pt-8 border-t border-line">
                <p>SSOT: <code className="bg-surface2 px-2 py-1 rounded text-xs">frontend/src/index.css</code></p>
                <p className="mt-2">Toggle dark/light mode using the switch in the header.</p>
            </footer>
        </main>
    )
}
