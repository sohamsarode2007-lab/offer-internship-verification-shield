import { randomBytes } from 'node:crypto'
import { spawnSync } from 'node:child_process'
import { existsSync, rmSync } from 'node:fs'
import path from 'node:path'
import { fileURLToPath } from 'node:url'

const frontend = path.resolve(path.dirname(fileURLToPath(import.meta.url)), '..')
const dbPath = path.join(frontend, 'e2e-test.db')
if (!dbPath.startsWith(frontend + path.sep)) throw new Error('E2E database path escaped frontend directory')
for (const suffix of ['', '-wal', '-shm']) if (existsSync(dbPath + suffix)) rmSync(dbPath + suffix)
// The server that playwright.config.ts starts must use this pepper (report tokens depend on it).
process.env.E2E_PEPPER = randomBytes(32).toString('hex')

const playwrightCli = path.join(frontend, 'node_modules', 'playwright', 'cli.js')
const result = spawnSync(process.execPath, [playwrightCli, 'test', '--config', 'playwright.config.ts'], { cwd: frontend, env: process.env, stdio: 'inherit' })
if (result.error) throw result.error
process.exitCode = result.status ?? 1
