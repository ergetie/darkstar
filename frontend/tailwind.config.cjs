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
                // Use CSS custom properties for theme-aware colors
                canvas: 'var(--color-canvas)',
                surface: 'var(--color-surface)',
                surface2: 'var(--color-surface2)',
                line: 'var(--color-line)',
                text: 'var(--color-text)',
                muted: 'var(--color-muted)',
                accent: 'var(--color-accent)',
                accent2: 'var(--color-accent2)',
                good: 'var(--color-good)',
                warn: 'var(--color-warn)',
                bad: 'var(--color-bad)',
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
