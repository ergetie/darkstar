/** @type {import('tailwindcss').Config} */
module.exports = {
    darkMode: 'class',
    content: ['./index.html', './src/**/*.{ts,tsx}'],
    theme: {
        extend: {
            fontFamily: {
                sans: ['var(--font-sans)'],
                mono: ['var(--font-mono)'],
            },
            fontSize: {
                'xs': ['0.625rem', { lineHeight: '1' }],      // 10px
                'sm': ['0.6875rem', { lineHeight: '1.3' }],   // 11px
                'base': ['0.75rem', { lineHeight: '1.4' }],   // 12px
                'md': ['0.8125rem', { lineHeight: '1.4' }],   // 13px
                'lg': ['0.875rem', { lineHeight: '1.45' }],   // 14px
                'xl': ['1rem', { lineHeight: '1.5' }],        // 16px
                '2xl': ['1.125rem', { lineHeight: '1.4' }],   // 18px
                '3xl': ['1.5rem', { lineHeight: '1.3' }],     // 24px
                '4xl': ['1.75rem', { lineHeight: '1.2' }],    // 28px
            },
            spacing: {
                'ds-1': 'var(--space-1)',
                'ds-2': 'var(--space-2)',
                'ds-3': 'var(--space-3)',
                'ds-4': 'var(--space-4)',
                'ds-5': 'var(--space-5)',
                'ds-6': 'var(--space-6)',
                'ds-8': 'var(--space-8)',
                'ds-10': 'var(--space-10)',
                'ds-12': 'var(--space-12)',
            },
            colors: {
                // Use CSS custom properties with RGB format for opacity support
                canvas: 'rgb(var(--color-canvas) / <alpha-value>)',
                surface: 'rgb(var(--color-surface) / <alpha-value>)',
                surface2: 'rgb(var(--color-surface2) / <alpha-value>)',
                line: 'rgb(var(--color-line) / <alpha-value>)',
                text: 'rgb(var(--color-text) / <alpha-value>)',
                muted: 'rgb(var(--color-muted) / <alpha-value>)',
                neutral: 'rgb(var(--color-neutral) / <alpha-value>)',
                accent: 'rgb(var(--color-accent) / <alpha-value>)',
                accent2: 'rgb(var(--color-accent2) / <alpha-value>)',
                good: 'rgb(var(--color-good) / <alpha-value>)',
                house: 'rgb(var(--color-house) / <alpha-value>)',
                water: 'rgb(var(--color-water) / <alpha-value>)',
                grid: 'rgb(var(--color-grid) / <alpha-value>)',
                warn: 'rgb(var(--color-warn) / <alpha-value>)',
                bad: 'rgb(var(--color-bad) / <alpha-value>)',
                peak: 'rgb(var(--color-peak) / <alpha-value>)',
                night: 'rgb(var(--color-night) / <alpha-value>)',
                ai: 'rgb(var(--color-ai) / <alpha-value>)',
            },
            borderRadius: {
                'ds-sm': 'var(--radius-sm)',
                'ds-md': 'var(--radius-md)',
                'ds-lg': 'var(--radius-lg)',
                'ds-xl': 'var(--radius-xl)',
                'xl2': '1.25rem',
                'pill': 'var(--radius-pill)',
            },
            boxShadow: {
                float: 'var(--shadow-float)',
                inset1: 'var(--shadow-inset1)'
            }
        },
    },
    plugins: [],
}
