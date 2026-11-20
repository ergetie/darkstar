// Starts the real Darkstar backend for the Playwright smoke test.
//
// Hermetic by construction: the backend runs with its working directory set to a
// throwaway runtime dir (frontend/e2e/.runtime/, gitignored) holding a copy of
// config.default.yaml and an empty secrets.yaml. With no Home Assistant url or
// token, Home Assistant is simply unavailable, like on a fresh install. The
// developer's own config.yaml, secrets.yaml and databases are never read or written.
import { spawn, spawnSync } from 'node:child_process'
import { existsSync } from 'node:fs'
import { mkdir, readFile, rm, symlink, writeFile } from 'node:fs/promises'
import path from 'node:path'
import { fileURLToPath } from 'node:url'

const here = path.dirname(fileURLToPath(import.meta.url))
const repoRoot = path.resolve(here, '..', '..')
const runtimeDir = path.join(here, '.runtime')
const port = process.env.E2E_PORT ?? '5055'

await rm(runtimeDir, { recursive: true, force: true })
await mkdir(path.join(runtimeDir, 'data'), { recursive: true })

// Copy of the shipped defaults, with outbound installation statistics switched off.
const defaults = await readFile(path.join(repoRoot, 'config.default.yaml'), 'utf8')
const statsOff = /^(installation_stats:\r?\n {2}enabled:) true/m
if (!statsOff.test(defaults)) {
    throw new Error('config.default.yaml: installation_stats.enabled not found, update start-backend.mjs')
}
await writeFile(path.join(runtimeDir, 'config.yaml'), defaults.replace(statsOff, '$1 false'))
await writeFile(path.join(runtimeDir, 'secrets.yaml'), '')
await symlink(path.join(repoRoot, 'profiles'), path.join(runtimeDir, 'profiles'), 'dir')

const venvPython = path.join(repoRoot, '.venv', 'bin', 'python')
const python = process.env.E2E_PYTHON ?? (existsSync(venvPython) ? venvPython : 'python')

const env = {
    ...process.env,
    PYTHONPATH: repoRoot,
    DB_PATH: path.join(runtimeDir, 'data', 'planner_learning.db'),
}

// Like docker-entrypoint.sh, create the schema before the application starts.
const migrate = spawnSync(python, ['-m', 'alembic', '-c', path.join(repoRoot, 'alembic.ini'), 'upgrade', 'head'], {
    cwd: runtimeDir,
    stdio: 'inherit',
    env,
})
if (migrate.status !== 0) {
    throw new Error(`alembic upgrade head failed with status ${migrate.status}`)
}

const child = spawn(python, ['-m', 'uvicorn', 'backend.main:app', '--host', '127.0.0.1', '--port', port], {
    cwd: runtimeDir,
    stdio: 'inherit',
    env,
})

for (const signal of ['SIGINT', 'SIGTERM', 'SIGHUP']) {
    process.on(signal, () => child.kill('SIGTERM'))
}
process.on('exit', () => child.kill('SIGTERM'))
child.on('exit', (code, signal) => process.exit(signal ? 1 : (code ?? 1)))
