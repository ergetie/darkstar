import { expect, test, type Page } from '@playwright/test'

// Console errors that are expected while Home Assistant is unavailable. Every
// entry needs a comment saying why it is expected. Prefer fixing the app over
// adding entries here.
const EXPECTED_CONSOLE_ERRORS: RegExp[] = [
    // The in-app updater exists only on Docker installs with an update service
    // configured; everywhere else the API answers 404 by design.
    /404 .*\/api\/updater\/status/,
    // Home Assistant discovery and sensor suggestions proxy to Home Assistant and
    // answer 502 when it is unreachable, which is the state under test.
    /502 .*\/api\/ha\/discovery/,
    /502 .*\/api\/setup\/suggestions/,
]

interface Collected {
    pageErrors: string[]
    consoleErrors: string[]
}

function collectErrors(page: Page): Collected {
    const collected: Collected = { pageErrors: [], consoleErrors: [] }
    page.on('pageerror', (error) => collected.pageErrors.push(error.message))
    page.on('console', (message) => {
        if (message.type() !== 'error') return
        const { url } = message.location()
        const text = url ? `${message.text()} (${url})` : message.text()
        if (EXPECTED_CONSOLE_ERRORS.some((pattern) => pattern.test(text))) return
        collected.consoleErrors.push(text)
    })
    return collected
}

// A fresh install has no inverter profile, so the setup wizard opens over the
// routed page. Either state is valid; the test accepts the wizard (accepting the
// "save progress" confirm) and continues, instead of assuming which one shows.
async function openRoute(page: Page, path: string): Promise<'wizard' | 'app'> {
    page.on('dialog', (dialog) => void dialog.accept())
    await page.goto(path)
    // The shell renders before the config check decides whether the wizard opens.
    await page.waitForLoadState('networkidle')
    const shell = page.getByRole('link', { name: 'Settings' }).first()
    await expect(shell).toBeVisible()

    const wizard = page.getByText('Darkstar setup', { exact: true })
    if (await wizard.isVisible()) {
        await expect(page.getByText(/Step \d+ of \d+/)).toBeVisible()
        await page.getByRole('button', { name: 'Close setup' }).click()
        await expect(wizard).toBeHidden()
        return 'wizard'
    }
    return 'app'
}

async function settle(page: Page) {
    await page.waitForLoadState('networkidle')
}

test.describe('built UI against the real backend without Home Assistant', () => {
    test('dashboard renders', async ({ page }) => {
        const errors = collectErrors(page)
        await openRoute(page, '/')
        await settle(page)

        await expect(page.getByRole('link', { name: 'Dash' }).first()).toBeVisible()
        await expect(page.locator('#root')).not.toBeEmpty()
        expect(errors.pageErrors).toEqual([])
        expect(errors.consoleErrors).toEqual([])
    })

    test('settings renders', async ({ page }) => {
        const errors = collectErrors(page)
        await openRoute(page, '/settings')
        await settle(page)

        await expect(page).toHaveURL(/\/settings$/)
        await expect(page.getByText('Inverter profile').first()).toBeVisible()
        expect(errors.pageErrors).toEqual([])
        expect(errors.consoleErrors).toEqual([])
    })
})
