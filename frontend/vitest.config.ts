/// <reference types="vitest" />
import { defineConfig } from 'vitest/config'
import react from '@vitejs/plugin-react'

// Date/DST tests assume the installation's local time zone. Pin it here so
// `vitest` gives the same result on any host (CI runs UTC). Set before workers
// spawn so every test process inherits it.
const TEST_TZ = 'Europe/Stockholm'
process.env.TZ = TEST_TZ

export default defineConfig({
    plugins: [react()],
    test: {
        globals: true,
        environment: 'jsdom',
        setupFiles: './src/test/setup.ts',
        include: ['src/**/*.test.{ts,tsx}'],
        env: { TZ: TEST_TZ },
    },
})
