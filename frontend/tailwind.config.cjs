/** @type {import('tailwindcss').Config} */
module.exports = {
    content: ['./index.html', './src/**/*.{ts,tsx}'],
    theme: {
        extend: {
            fontFamily: {
                mono: ['JetBrains Mono', 'ui-monospace', 'SFMono-Regular', 'Menlo', 'monospace'],
            },
            colors: {
                // Teenage-engineering inspired, never full black.
                canvas: '#0f1216',
                surface: '#14191f',
                surface2: '#181e25',
                line: '#242b34',
                text: '#e6e9ef',
                muted: '#a6b0bf',
                accent: '#F5D547',       // Yellow accent
                accent2: '#ffe066',
                good: '#87F0A3',
                warn: '#FFD966',
                bad: '#FF7A7A'
            },
            borderRadius: {
                'xl2': '1.25rem',
                'pill': '9999px'
            },
            boxShadow: {
                float: '0 8px 30px rgba(0,0,0,0.35)',
                inset1: 'inset 0 0 0 1px rgba(255,255,255,0.04)'
            }
        },
    },
    plugins: [],
}
