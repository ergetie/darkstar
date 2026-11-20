import { defineConfig, devices } from '@playwright/test'

// Browser smoke test: the built UI (backend/static) served by the real backend
// with Home Assistant unavailable. See e2e/start-backend.mjs for the throwaway
// runtime. `@playwright/test` is pinned exactly so its Chromium revision matches
// the browser cache (chromium-headless-shell-1248); bumping it needs a new
// browser download.
// Config runs in Node; @types/node is not a dependency of this package.
declare const process: { env: Record<string, string | undefined> }

const port = Number(process.env.E2E_PORT ?? 5055)
const baseURL = `http://127.0.0.1:${port}`

export default defineConfig({
    testDir: './e2e',
    fullyParallel: false,
    workers: 1,
    forbidOnly: !!process.env.CI,
    retries: process.env.CI ? 2 : 0,
    reporter: process.env.CI ? [['list'], ['html', { open: 'never' }]] : 'list',
    use: {
        baseURL,
        trace: 'retain-on-failure',
    },
    projects: [{ name: 'chromium', use: { ...devices['Desktop Chrome'] } }],
    webServer: {
        command: 'node e2e/start-backend.mjs',
        url: `${baseURL}/api/health`,
        // A leftover server would run against a different config and data dir.
        reuseExistingServer: false,
        timeout: 120_000,
        env: { E2E_PORT: String(port) },
        stdout: 'pipe',
        stderr: 'pipe',
    },
})
