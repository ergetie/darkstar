/**
 * DesignSystem Page
 *
 * Visual reference for all design system components.
 * Uses actual CSS classes from index.css for live preview.
 */

import { useState } from 'react'
import ThemeToggle from '../components/ThemeToggle'
import ChartCard from '../components/ChartCard'
import Select from '../components/ui/Select'
import Modal from '../components/ui/Modal'
import { Banner, Badge } from '../components/ui/Banner'
import Switch from '../components/ui/Switch'
import { useToast } from '../lib/useToast'

export default function DesignSystem() {
    const { toast } = useToast()
    const [toggleActive, setToggleActive] = useState(false)
    const [progressValue, setProgressValue] = useState(65)
    const [accordionOpen, setAccordionOpen] = useState(false)
    const [modalOpen, setModalOpen] = useState(false)
    const [searchValue, setSearchValue] = useState('')

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
                            <div className="h-16" style={{ backgroundColor: `rgb(var(${color.var}))` }} />
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
                    <button className="btn btn-primary" disabled>
                        Disabled Primary
                    </button>
                    <button className="btn btn-secondary" disabled>
                        Disabled Secondary
                    </button>
                    <button className="btn btn-ghost" disabled>
                        Disabled Ghost
                    </button>
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
                    <Banner variant="info">
                        <span>ℹ️</span>
                        <span>Info Banner — Neutral information message</span>
                    </Banner>
                    <Banner variant="success">
                        <span>✅</span>
                        <span>Success Banner — Action completed successfully</span>
                    </Banner>
                    <Banner variant="warning">
                        <span>⚠️</span>
                        <span>Warning Banner — Requires attention</span>
                    </Banner>
                    <Banner variant="error">
                        <span>❌</span>
                        <span>Error Banner — Critical issue detected</span>
                    </Banner>
                    <Banner variant="purple">
                        <span>👻</span>
                        <span>Purple Banner — Special mode (shadow mode)</span>
                    </Banner>
                </div>
            </section>

            {/* Badges */}
            <section>
                <h2 className="text-2xl font-semibold text-text mb-4">Badges</h2>
                <div className="flex flex-wrap gap-3 items-center">
                    <Badge variant="accent">Accent</Badge>
                    <Badge variant="good">Good</Badge>
                    <Badge variant="warn">Warning</Badge>
                    <Badge variant="bad">Error</Badge>
                    <Badge variant="muted">Muted</Badge>
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
                            <Switch checked={toggleActive} onCheckedChange={setToggleActive} />
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

            {/* Live Chart.js Example */}
            <section>
                <h2 className="text-2xl font-semibold text-text mb-4">📈 Chart.js — Live Example</h2>
                <p className="text-muted text-sm mb-4">
                    This is the actual ChartCard component used throughout Darkstar.
                </p>
                <div className="bg-surface rounded-ds-lg p-4 shadow-float">
                    <ChartCard day="today" showDayToggle={false} />
                </div>
            </section>

            {/* Power Flow Visualization */}
            <section>
                <h2 className="text-2xl font-semibold text-text mb-4">⚡ Power Flow Visualization</h2>
                <p className="text-muted text-sm mb-4">
                    Animated energy flow between sources and loads (inspired by power-flow-card-plus).
                </p>
                <div className="bg-surface rounded-ds-lg p-8 shadow-float">
                    <svg viewBox="0 0 400 300" className="w-full max-w-lg mx-auto">
                        {/* Flow lines with animation */}
                        <g
                            className="power-flow-line"
                            style={{ stroke: 'rgb(var(--color-accent))', strokeWidth: 3, fill: 'none' }}
                        >
                            <path d="M100,50 L200,150" />
                        </g>
                        <g
                            className="power-flow-line"
                            style={{
                                stroke: 'rgb(var(--color-good))',
                                strokeWidth: 3,
                                fill: 'none',
                                animationDelay: '0.25s',
                            }}
                        >
                            <path d="M200,150 L200,250" />
                        </g>
                        <g
                            className="power-flow-line"
                            style={{
                                stroke: 'rgb(var(--color-house))',
                                strokeWidth: 3,
                                fill: 'none',
                                animationDelay: '0.5s',
                            }}
                        >
                            <path d="M200,150 L300,150" />
                        </g>
                        <g
                            style={{
                                stroke: 'rgb(var(--color-grid))',
                                strokeWidth: 3,
                                fill: 'none',
                                strokeDasharray: '5 5',
                            }}
                        >
                            <path d="M100,250 L200,150" />
                        </g>

                        {/* Solar node */}
                        <g transform="translate(100, 50)">
                            <circle
                                r="35"
                                fill="rgb(var(--color-surface))"
                                stroke="rgb(var(--color-accent))"
                                strokeWidth="3"
                                className="animate-glow"
                            />
                            <text y="5" textAnchor="middle" fill="rgb(var(--color-accent))" fontSize="24">
                                ☀️
                            </text>
                            <text
                                y="55"
                                textAnchor="middle"
                                fill="rgb(var(--color-text))"
                                fontSize="11"
                                fontWeight="600"
                            >
                                4.2 kW
                            </text>
                            <text y="70" textAnchor="middle" fill="rgb(var(--color-muted))" fontSize="9">
                                Solar
                            </text>
                        </g>

                        {/* Home node (center) */}
                        <g transform="translate(200, 150)">
                            <circle
                                r="40"
                                fill="rgb(var(--color-surface))"
                                stroke="rgb(var(--color-house))"
                                strokeWidth="3"
                            />
                            <text y="5" textAnchor="middle" fill="rgb(var(--color-house))" fontSize="24">
                                🏠
                            </text>
                            <text
                                y="-50"
                                textAnchor="middle"
                                fill="rgb(var(--color-text))"
                                fontSize="11"
                                fontWeight="600"
                            >
                                3.1 kW
                            </text>
                        </g>

                        {/* Battery node */}
                        <g transform="translate(200, 250)">
                            <circle
                                r="35"
                                fill="rgb(var(--color-surface))"
                                stroke="rgb(var(--color-good))"
                                strokeWidth="3"
                            />
                            <text y="5" textAnchor="middle" fill="rgb(var(--color-good))" fontSize="24">
                                🔋
                            </text>
                            <text
                                y="55"
                                textAnchor="middle"
                                fill="rgb(var(--color-text))"
                                fontSize="11"
                                fontWeight="600"
                            >
                                85%
                            </text>
                            <text y="70" textAnchor="middle" fill="rgb(var(--color-muted))" fontSize="9">
                                +0.6 kW
                            </text>
                        </g>

                        {/* Grid node */}
                        <g transform="translate(100, 250)">
                            <circle
                                r="35"
                                fill="rgb(var(--color-surface))"
                                stroke="rgb(var(--color-grid))"
                                strokeWidth="3"
                            />
                            <text y="5" textAnchor="middle" fill="rgb(var(--color-grid))" fontSize="24">
                                ⚡
                            </text>
                            <text
                                y="55"
                                textAnchor="middle"
                                fill="rgb(var(--color-text))"
                                fontSize="11"
                                fontWeight="600"
                            >
                                0 W
                            </text>
                            <text y="70" textAnchor="middle" fill="rgb(var(--color-muted))" fontSize="9">
                                Grid
                            </text>
                        </g>

                        {/* Water heater node */}
                        <g transform="translate(300, 150)">
                            <circle
                                r="30"
                                fill="rgb(var(--color-surface))"
                                stroke="rgb(var(--color-water))"
                                strokeWidth="3"
                            />
                            <text y="5" textAnchor="middle" fill="rgb(var(--color-water))" fontSize="20">
                                💧
                            </text>
                            <text
                                y="50"
                                textAnchor="middle"
                                fill="rgb(var(--color-text))"
                                fontSize="11"
                                fontWeight="600"
                            >
                                0.5 kW
                            </text>
                            <text y="65" textAnchor="middle" fill="rgb(var(--color-muted))" fontSize="9">
                                Water
                            </text>
                        </g>
                    </svg>
                </div>
            </section>

            {/* Animation Examples */}
            <section>
                <h2 className="text-2xl font-semibold text-text mb-4">✨ Animation Examples</h2>
                <p className="text-muted text-sm mb-4">CSS animations available in the design system.</p>
                <div className="grid md:grid-cols-2 lg:grid-cols-4 gap-6">
                    {/* Pulse */}
                    <div className="bg-surface rounded-ds-lg p-4 shadow-float text-center">
                        <div className="w-12 h-12 mx-auto mb-3 rounded-full bg-accent animate-pulse" />
                        <div className="text-sm font-medium text-text">Pulse</div>
                        <code className="text-xs text-muted">.animate-pulse</code>
                    </div>

                    {/* Bounce */}
                    <div className="bg-surface rounded-ds-lg p-4 shadow-float text-center">
                        <div className="w-12 h-12 mx-auto mb-3 rounded-full bg-good animate-bounce" />
                        <div className="text-sm font-medium text-text">Bounce</div>
                        <code className="text-xs text-muted">.animate-bounce</code>
                    </div>

                    {/* Glow */}
                    <div className="bg-surface rounded-ds-lg p-4 shadow-float text-center">
                        <div className="w-12 h-12 mx-auto mb-3 rounded-full bg-accent animate-glow" />
                        <div className="text-sm font-medium text-text">Glow</div>
                        <code className="text-xs text-muted">.animate-glow</code>
                    </div>

                    {/* Spinner */}
                    <div className="bg-surface rounded-ds-lg p-4 shadow-float text-center">
                        <div
                            className="spinner mx-auto mb-3"
                            style={{ width: '3rem', height: '3rem', borderWidth: '4px' }}
                        />
                        <div className="text-sm font-medium text-text">Spinner</div>
                        <code className="text-xs text-muted">.spinner</code>
                    </div>

                    {/* Skeleton */}
                    <div className="bg-surface rounded-ds-lg p-4 shadow-float">
                        <div className="text-sm font-medium text-text mb-2">Skeleton Loading</div>
                        <div className="space-y-2">
                            <div className="skeleton h-4 w-3/4" />
                            <div className="skeleton h-4 w-1/2" />
                            <div className="skeleton h-4 w-full" />
                        </div>
                        <code className="text-xs text-muted mt-2 block">.skeleton</code>
                    </div>

                    {/* Mini Bars Animation */}
                    <div className="bg-surface rounded-ds-lg p-4 shadow-float">
                        <div className="text-sm font-medium text-text mb-2">Mini Bar Animation</div>
                        <div className="mini-bars">
                            {[40, 60, 80, 100, 80, 60, 40, 20].map((h, i) => (
                                <div
                                    key={i}
                                    className="mini-bar animate-pulse"
                                    style={{
                                        height: `${h}%`,
                                        background: 'rgb(var(--color-accent))',
                                        animationDelay: `${i * 0.1}s`,
                                    }}
                                />
                            ))}
                        </div>
                        <code className="text-xs text-muted mt-2 block">.mini-bars</code>
                    </div>

                    {/* Button Glow */}
                    <div className="bg-surface rounded-ds-lg p-4 shadow-float text-center">
                        <button className="btn btn-primary animate-glow mb-2">Glowing Button</button>
                        <div className="text-sm font-medium text-text">Button Glow</div>
                        <code className="text-xs text-muted">.btn + .animate-glow</code>
                    </div>

                    {/* Progress Animation */}
                    <div className="bg-surface rounded-ds-lg p-4 shadow-float">
                        <div className="text-sm font-medium text-text mb-2">Animated Progress</div>
                        <div className="progress-bar">
                            <div
                                className="progress-bar-fill"
                                style={{
                                    width: '75%',
                                    animation: 'skeleton-shimmer 1.5s infinite',
                                    background:
                                        'linear-gradient(90deg, rgb(var(--color-accent)), rgb(var(--color-accent2)), rgb(var(--color-accent)))',
                                    backgroundSize: '200% 100%',
                                }}
                            />
                        </div>
                        <code className="text-xs text-muted mt-2 block">.progress-bar</code>
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
                            <div className={`w-16 h-16 bg-accent rounded-ds-${r.name}`} />
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
                                    minHeight: '4px',
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
                            <span className="text-sm font-semibold" style={{ color: '#e6e9ef' }}>
                                🌙 Dark Mode — Glow Buttons
                            </span>
                        </div>
                        <div className="p-4 space-y-2" style={{ background: '#14191f' }}>
                            <div
                                className="flex justify-between items-center p-3 rounded-lg"
                                style={{ background: '#181e25' }}
                            >
                                <span style={{ color: '#FFCE59' }}>☀️ Solar</span>
                                <span className="font-mono font-bold" style={{ color: '#FFCE59' }}>
                                    4.2kW
                                </span>
                            </div>
                            <div
                                className="flex justify-between items-center p-3 rounded-lg"
                                style={{ background: '#181e25' }}
                            >
                                <span style={{ color: '#1FB256' }}>🔋 Battery</span>
                                <span className="font-mono font-bold" style={{ color: '#1FB256' }}>
                                    85%
                                </span>
                            </div>
                            <div
                                className="flex justify-between items-center p-3 rounded-lg"
                                style={{ background: '#181e25' }}
                            >
                                <span style={{ color: '#A855F7' }}>🏠 House</span>
                                <span className="font-mono font-bold" style={{ color: '#e6e9ef' }}>
                                    1.8kW
                                </span>
                            </div>
                            <div
                                className="flex justify-between items-center p-3 rounded-lg"
                                style={{ background: '#181e25' }}
                            >
                                <span style={{ color: '#4EA8DE' }}>💧 Water</span>
                                <span className="font-mono font-bold" style={{ color: '#e6e9ef' }}>
                                    58°C
                                </span>
                            </div>
                            <div className="flex gap-2 pt-3">
                                <button
                                    style={{
                                        background: '#FFCE59',
                                        color: '#1a1d23',
                                        padding: '8px 16px',
                                        borderRadius: '8px',
                                        fontWeight: 600,
                                        fontSize: '11px',
                                        boxShadow: '0 0 16px rgba(255, 206, 89, 0.4), 0 0 32px rgba(255, 206, 89, 0.2)',
                                    }}
                                >
                                    ⚡ Boost
                                </button>
                                <button
                                    style={{
                                        background: '#989FA5',
                                        color: '#fff',
                                        padding: '8px 16px',
                                        borderRadius: '8px',
                                        fontWeight: 600,
                                        fontSize: '11px',
                                        boxShadow: '0 0 12px rgba(152, 159, 165, 0.3)',
                                    }}
                                >
                                    🏖️ Vacation
                                </button>
                            </div>
                        </div>
                    </div>

                    {/* Light Mode Preview */}
                    <div className="rounded-ds-lg overflow-hidden" style={{ background: '#DFDFDF' }}>
                        <div className="px-4 py-3" style={{ background: '#EFEFEF' }}>
                            <span className="text-sm font-semibold" style={{ color: '#2D2D2D' }}>
                                ☀️ Light Mode — Flat Buttons (TE Style)
                            </span>
                        </div>
                        <div className="p-4 space-y-2" style={{ background: '#EFEFEF' }}>
                            <div
                                className="flex justify-between items-center p-3 rounded-lg"
                                style={{ background: '#D0D0D0' }}
                            >
                                <span style={{ color: '#2D2D2D' }}>
                                    ☀️ <b style={{ color: '#b38b00' }}>Solar</b>
                                </span>
                                <span className="font-mono font-bold" style={{ color: '#2D2D2D' }}>
                                    4.2kW
                                </span>
                            </div>
                            <div
                                className="flex justify-between items-center p-3 rounded-lg"
                                style={{ background: '#D0D0D0' }}
                            >
                                <span style={{ color: '#2D2D2D' }}>
                                    🔋 <b style={{ color: '#1FB256' }}>Battery</b>
                                </span>
                                <span className="font-mono font-bold" style={{ color: '#2D2D2D' }}>
                                    85%
                                </span>
                            </div>
                            <div
                                className="flex justify-between items-center p-3 rounded-lg"
                                style={{ background: '#D0D0D0' }}
                            >
                                <span style={{ color: '#2D2D2D' }}>
                                    🏠 <b style={{ color: '#A855F7' }}>House</b>
                                </span>
                                <span className="font-mono font-bold" style={{ color: '#2D2D2D' }}>
                                    1.8kW
                                </span>
                            </div>
                            <div
                                className="flex justify-between items-center p-3 rounded-lg"
                                style={{ background: '#D0D0D0' }}
                            >
                                <span style={{ color: '#2D2D2D' }}>
                                    💧 <b style={{ color: '#4EA8DE' }}>Water</b>
                                </span>
                                <span className="font-mono font-bold" style={{ color: '#2D2D2D' }}>
                                    58°C
                                </span>
                            </div>
                            <div className="flex gap-2 pt-3">
                                <button
                                    style={{
                                        background: '#FFCE59',
                                        color: '#2D2D2D',
                                        padding: '8px 16px',
                                        borderRadius: '8px',
                                        fontWeight: 600,
                                        fontSize: '11px',
                                        border: 'none',
                                    }}
                                >
                                    ⚡ Boost
                                </button>
                                <button
                                    style={{
                                        background: '#989FA5',
                                        color: '#fff',
                                        padding: '8px 16px',
                                        borderRadius: '8px',
                                        fontWeight: 600,
                                        fontSize: '11px',
                                        border: 'none',
                                    }}
                                >
                                    🏖️ Vacation
                                </button>
                            </div>
                        </div>
                    </div>
                </div>
            </section>

            {/* Future Components — Inspiration */}
            <section>
                <h2 className="text-2xl font-semibold text-text mb-4">🚀 Future Components (Inspiration)</h2>
                <p className="text-muted text-sm mb-6">
                    These components are not yet implemented but can be added as needed.
                </p>

                <div className="grid md:grid-cols-2 lg:grid-cols-3 gap-6">
                    {/* Card */}
                    <div className="bg-surface rounded-ds-lg p-4 shadow-float">
                        <h4 className="text-sm font-semibold text-text mb-2">📦 Card</h4>
                        <p className="text-xs text-muted">
                            Container with shadow, padding, and rounded corners for grouping content.
                        </p>
                        <div className="mt-3 p-3 bg-surface2 rounded-ds-md">
                            <div className="text-xs text-text">Card content goes here...</div>
                        </div>
                    </div>

                    {/* Select (Dropdown) */}
                    <div className="bg-surface rounded-ds-lg p-4 shadow-float">
                        <h4 className="text-sm font-semibold text-text mb-2">📋 Select (Dropdown)</h4>
                        <p className="text-xs text-muted mb-3">Custom searchable dropdown.</p>
                        <Select
                            options={[
                                { label: 'Option 1', value: '1' },
                                { label: 'Option 2', value: '2' },
                                { label: 'Delete', value: '3', group: 'Danger' },
                            ]}
                            value="1"
                            onChange={() => {}}
                        />
                    </div>

                    {/* Tabs */}
                    <div className="bg-surface rounded-ds-lg p-4 shadow-float">
                        <h4 className="text-sm font-semibold text-text mb-2">📑 Tabs</h4>
                        <p className="text-xs text-muted mb-3">Navigation between views.</p>
                        <div className="flex gap-1 bg-surface2 p-1 rounded-ds-md">
                            <div className="px-3 py-1.5 text-xs font-medium bg-accent text-black rounded">Active</div>
                            <div className="px-3 py-1.5 text-xs text-muted rounded">Tab 2</div>
                            <div className="px-3 py-1.5 text-xs text-muted rounded">Tab 3</div>
                        </div>
                    </div>

                    {/* Avatars */}
                    <div className="bg-surface rounded-ds-lg p-4 shadow-float">
                        <h4 className="text-sm font-semibold text-text mb-2">👤 Avatars</h4>
                        <p className="text-xs text-muted mb-3">User profile images or initials.</p>
                        <div className="flex gap-2 items-center">
                            <div className="w-8 h-8 rounded-full bg-accent flex items-center justify-center text-xs font-bold text-black">
                                JD
                            </div>
                            <div className="w-8 h-8 rounded-full bg-water flex items-center justify-center text-xs font-bold text-white">
                                AB
                            </div>
                            <div className="w-8 h-8 rounded-full bg-house flex items-center justify-center text-xs font-bold text-white">
                                ?
                            </div>
                        </div>
                    </div>

                    {/* Tooltip */}
                    <div className="bg-surface rounded-ds-lg p-4 shadow-float">
                        <h4 className="text-sm font-semibold text-text mb-2">💬 Tooltip</h4>
                        <p className="text-xs text-muted mb-3">Hover for more info.</p>
                        <span
                            className="tooltip px-3 py-1.5 bg-surface2 rounded text-xs text-text cursor-help"
                            data-tooltip="This is a tooltip!"
                        >
                            Hover me
                        </span>
                    </div>

                    {/* Table */}
                    <div className="bg-surface rounded-ds-lg p-4 shadow-float">
                        <h4 className="text-sm font-semibold text-text mb-2">📊 Data Table</h4>
                        <p className="text-xs text-muted mb-3">Tabular data display.</p>
                        <div className="text-xs">
                            <div className="flex gap-2 py-1 border-b border-line text-muted font-medium">
                                <span className="flex-1">Name</span>
                                <span className="w-16 text-right">Value</span>
                            </div>
                            <div className="flex gap-2 py-1 text-text">
                                <span className="flex-1">Solar</span>
                                <span className="w-16 text-right text-accent">4.2kW</span>
                            </div>
                            <div className="flex gap-2 py-1 text-text">
                                <span className="flex-1">Battery</span>
                                <span className="w-16 text-right text-good">85%</span>
                            </div>
                        </div>
                    </div>

                    {/* Gauge */}
                    <div className="bg-surface rounded-ds-lg p-4 shadow-float">
                        <h4 className="text-sm font-semibold text-text mb-2">⏱️ Gauge / Dial</h4>
                        <p className="text-xs text-muted mb-3">Circular progress indicator.</p>
                        <div className="w-16 h-16 rounded-full border-4 border-surface2 relative">
                            <div
                                className="absolute inset-0 rounded-full border-4 border-transparent border-t-accent border-r-accent"
                                style={{ transform: 'rotate(45deg)' }}
                            />
                            <div className="absolute inset-0 flex items-center justify-center text-xs font-bold text-text">
                                75%
                            </div>
                        </div>
                    </div>

                    {/* Notification Badge */}
                    <div className="bg-surface rounded-ds-lg p-4 shadow-float">
                        <h4 className="text-sm font-semibold text-text mb-2">🔔 Notification Badge</h4>
                        <p className="text-xs text-muted mb-3">Alert indicator on icons.</p>
                        <div className="relative inline-block">
                            <div className="w-10 h-10 bg-surface2 rounded-lg flex items-center justify-center text-lg">
                                🔔
                            </div>
                            <div className="absolute -top-1 -right-1 w-5 h-5 bg-bad rounded-full flex items-center justify-center text-[10px] font-bold text-white">
                                3
                            </div>
                        </div>
                    </div>

                    {/* Stepper */}
                    <div className="bg-surface rounded-ds-lg p-4 shadow-float">
                        <h4 className="text-sm font-semibold text-text mb-2">🔢 Stepper</h4>
                        <p className="text-xs text-muted mb-3">Multi-step progress.</p>
                        <div className="flex items-center gap-2">
                            <div className="w-6 h-6 rounded-full bg-accent flex items-center justify-center text-[10px] font-bold text-black">
                                1
                            </div>
                            <div className="flex-1 h-0.5 bg-accent" />
                            <div className="w-6 h-6 rounded-full bg-accent flex items-center justify-center text-[10px] font-bold text-black">
                                2
                            </div>
                            <div className="flex-1 h-0.5 bg-surface2" />
                            <div className="w-6 h-6 rounded-full bg-surface2 flex items-center justify-center text-[10px] font-bold text-muted">
                                3
                            </div>
                        </div>
                    </div>
                </div>
            </section>

            {/* More Future Components */}
            <section>
                <h2 className="text-2xl font-semibold text-text mb-4">🔮 More Future Components</h2>
                <p className="text-muted text-sm mb-6">Additional component patterns for future implementation.</p>

                <div className="grid md:grid-cols-2 lg:grid-cols-3 gap-6">
                    {/* Modal */}
                    <div className="bg-surface rounded-ds-lg p-4 shadow-float">
                        <h4 className="text-sm font-semibold text-text mb-2">🪟 Modal / Dialog</h4>
                        <p className="text-xs text-muted mb-3">Overlay for confirmations & forms.</p>
                        <button className="btn btn-primary text-xs" onClick={() => setModalOpen(true)}>
                            Open Modal
                        </button>
                        <Modal
                            open={modalOpen}
                            onOpenChange={setModalOpen}
                            title="Example Modal"
                            footer={
                                <>
                                    <button className="btn btn-ghost" onClick={() => setModalOpen(false)}>
                                        Cancel
                                    </button>
                                    <button className="btn btn-primary" onClick={() => setModalOpen(false)}>
                                        Confirm
                                    </button>
                                </>
                            }
                        >
                            <p className="text-text">This is a reusable modal component using React Portal.</p>
                        </Modal>
                    </div>

                    {/* Accordion */}
                    <div className="bg-surface rounded-ds-lg p-4 shadow-float">
                        <h4 className="text-sm font-semibold text-text mb-2">📂 Accordion</h4>
                        <p className="text-xs text-muted mb-3">Expandable content sections.</p>
                        <div className="bg-surface2 rounded-ds-md overflow-hidden">
                            <div
                                className="px-3 py-2 text-xs font-medium text-text flex justify-between items-center cursor-pointer"
                                onClick={() => setAccordionOpen(!accordionOpen)}
                            >
                                <span>Click to expand</span>
                                <span>{accordionOpen ? '−' : '+'}</span>
                            </div>
                            {accordionOpen && (
                                <div className="px-3 py-2 text-xs text-muted border-t border-line">
                                    Hidden content revealed!
                                </div>
                            )}
                        </div>
                    </div>

                    {/* Search Input */}
                    <div className="bg-surface rounded-ds-lg p-4 shadow-float">
                        <h4 className="text-sm font-semibold text-text mb-2">🔍 Search Input</h4>
                        <p className="text-xs text-muted mb-3">With autocomplete dropdown.</p>
                        <div className="relative">
                            <input
                                type="text"
                                className="input pr-8"
                                placeholder="Search entities..."
                                value={searchValue}
                                onChange={(e) => setSearchValue(e.target.value)}
                            />
                            <span className="absolute right-3 top-1/2 -translate-y-1/2 text-muted">🔍</span>
                        </div>
                        {searchValue && (
                            <div className="mt-1 bg-surface2 rounded-ds-md p-1 shadow-lg">
                                <div className="px-3 py-2 text-xs text-text hover:bg-accent/10 rounded cursor-pointer">
                                    sensor.solar_power
                                </div>
                                <div className="px-3 py-2 text-xs text-text hover:bg-accent/10 rounded cursor-pointer">
                                    sensor.battery_soc
                                </div>
                            </div>
                        )}
                    </div>

                    {/* Date Picker */}
                    <div className="bg-surface rounded-ds-lg p-4 shadow-float">
                        <h4 className="text-sm font-semibold text-text mb-2">📅 Date Picker</h4>
                        <p className="text-xs text-muted mb-3">Calendar date selection.</p>
                        <div className="bg-surface2 rounded-ds-md p-2 w-48">
                            <div className="text-xs font-medium text-text text-center mb-2">December 2024</div>
                            <div className="grid grid-cols-7 gap-1 text-[10px] text-center">
                                {['M', 'T', 'W', 'T', 'F', 'S', 'S'].map((d, i) => (
                                    <div key={i} className="text-muted">
                                        {d}
                                    </div>
                                ))}
                                {[...Array(31)].map((_, i) => (
                                    <div
                                        key={i}
                                        className={`py-1 rounded cursor-pointer ${i === 30 ? 'bg-accent text-black font-bold' : 'text-text hover:bg-accent/20'}`}
                                    >
                                        {i + 1}
                                    </div>
                                ))}
                            </div>
                        </div>
                    </div>

                    {/* Toast Notification */}
                    <div className="bg-surface rounded-ds-lg p-4 shadow-float">
                        <h4 className="text-sm font-semibold text-text mb-2">🍞 Toast Notification</h4>
                        <p className="text-xs text-muted mb-3">Temporary status messages.</p>
                        <div className="space-y-2">
                            <button
                                className="btn btn-secondary w-full text-xs"
                                onClick={() =>
                                    toast({
                                        variant: 'success',
                                        message: 'Success!',
                                        description: 'Action completed successfully.',
                                    })
                                }
                            >
                                Trigger Success Toast
                            </button>
                            <button
                                className="btn btn-ghost w-full text-xs border border-bad/50 text-bad hover:bg-bad/10"
                                onClick={() =>
                                    toast({ variant: 'error', message: 'Error!', description: 'Something went wrong.' })
                                }
                            >
                                Trigger Error Toast
                            </button>
                        </div>
                    </div>

                    {/* Breadcrumbs */}
                    <div className="bg-surface rounded-ds-lg p-4 shadow-float">
                        <h4 className="text-sm font-semibold text-text mb-2">🥖 Breadcrumbs</h4>
                        <p className="text-xs text-muted mb-3">Navigation path trail.</p>
                        <div className="flex items-center gap-2 text-xs">
                            <span className="text-accent hover:underline cursor-pointer">Home</span>
                            <span className="text-muted">/</span>
                            <span className="text-accent hover:underline cursor-pointer">Settings</span>
                            <span className="text-muted">/</span>
                            <span className="text-text font-medium">Entities</span>
                        </div>
                    </div>

                    {/* Timeline */}
                    <div className="bg-surface rounded-ds-lg p-4 shadow-float col-span-full lg:col-span-2">
                        <h4 className="text-sm font-semibold text-text mb-2">⏰ Timeline / Activity Log</h4>
                        <p className="text-xs text-muted mb-3">Chronological event display.</p>
                        <div className="space-y-3">
                            {[
                                { time: '14:32', event: 'Battery charging started', color: 'good' },
                                { time: '14:15', event: 'Solar production peaked at 4.2kW', color: 'accent' },
                                { time: '13:45', event: 'Grid export enabled', color: 'water' },
                            ].map((item, i) => (
                                <div key={i} className="flex items-start gap-3">
                                    <div className={`w-2 h-2 rounded-full mt-1.5 bg-${item.color}`} />
                                    <div>
                                        <div className="text-xs font-mono text-muted">{item.time}</div>
                                        <div className="text-xs text-text">{item.event}</div>
                                    </div>
                                </div>
                            ))}
                        </div>
                    </div>
                </div>
            </section>

            {/* Modal Overlay */}
            {modalOpen && (
                <div className="modal-overlay" onClick={() => setModalOpen(false)}>
                    <div className="modal" onClick={(e) => e.stopPropagation()}>
                        <h3 className="text-lg font-semibold text-text mb-2">Modal Title</h3>
                        <p className="text-sm text-muted mb-4">
                            This is a sample modal dialog. It uses the design system's modal classes.
                        </p>
                        <div className="flex gap-2 justify-end">
                            <button className="btn btn-ghost" onClick={() => setModalOpen(false)}>
                                Cancel
                            </button>
                            <button className="btn btn-primary" onClick={() => setModalOpen(false)}>
                                Confirm
                            </button>
                        </div>
                    </div>
                </div>
            )}

            {/* Footer */}
            <footer className="text-center text-muted text-sm pt-8 border-t border-line">
                <p>
                    SSOT: <code className="bg-surface2 px-2 py-1 rounded text-xs">frontend/src/index.css</code>
                </p>
                <p className="mt-2">Toggle dark/light mode using the switch in the header.</p>
            </footer>
        </main>
    )
}
