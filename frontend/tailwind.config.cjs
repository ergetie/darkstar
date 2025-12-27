/** @type {import('tailwindcss').Config} */
module.exports = {
    darkMode: 'class',
    content: ['./index.html', './src/**/*.{ts,tsx}'],
    theme: {
        extend: {
            fontFamily: {
                mono: ['JetBrains Mono', 'ui-monospace', 'SFMono-Regular', 'Menlo', 'monospace'],
            },
            colors: {
                // Use CSS custom properties with RGB format for opacity support
                canvas: 'rgb(var(--color-canvas) / <alpha-value>)',
                surface: 'rgb(var(--color-surface) / <alpha-value>)',
                surface2: 'rgb(var(--color-surface2) / <alpha-value>)',
                line: 'rgb(var(--color-line) / <alpha-value>)',
                text: 'rgb(var(--color-text) / <alpha-value>)',
                muted: 'rgb(var(--color-muted) / <alpha-value>)',
                accent: 'rgb(var(--color-accent) / <alpha-value>)',
                accent2: 'rgb(var(--color-accent2) / <alpha-value>)',
                good: 'rgb(var(--color-good) / <alpha-value>)',
                warn: 'rgb(var(--color-warn) / <alpha-value>)',
                bad: 'rgb(var(--color-bad) / <alpha-value>)',
            },
            borderRadius: {
                'xl2': '1.25rem',
                'pill': '9999px'
            },
            boxShadow: {
                float: 'var(--shadow-float)',
                inset1: 'var(--shadow-inset1)'
            }
        },
    },
    plugins: [],
}
