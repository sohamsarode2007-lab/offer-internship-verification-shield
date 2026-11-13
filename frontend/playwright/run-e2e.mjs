import { randomBytes } from 'node:crypto'
import { execFileSync, spawnSync } from 'node:child_process'
import { existsSync, rmSync } from 'node:fs'
import path from 'node:path'
import { fileURLToPath } from 'node:url'

const frontend = path.resolve(path.dirname(fileURLToPath(import.meta.url)), '..')
const root = path.resolve(frontend, '..')
const dbPath = path.join(frontend, 'e2e-test.db')
if (!dbPath.startsWith(frontend + path.sep)) throw new Error('E2E database path escaped frontend directory')
for (const suffix of ['', '-wal', '-shm']) if (existsSync(dbPath + suffix)) rmSync(dbPath + suffix)

const python = process.env.PYTHON ?? (process.platform === 'win32'
  ? path.join(root, '.venv', 'Scripts', 'python.exe')
  : 'python')
const demoEnv = {
  ...process.env,
  DATABASE_URL: 'sqlite:///./frontend/e2e-test.db',
  DEMO_MODE: '1',
  DEMO_FIXTURE_DOMAINS: 'emberlakeanalytics.example,brightpathedtech.example',
  DEMO_REGISTRY_FIXTURES: 'U74999DL2016PTC298345',
  INDICATOR_PEPPER: randomBytes(32).toString('hex'),
  INDICATOR_KEY_VERSION: '1',
  RATE_LIMIT: '100/minute',
  ALLOWED_ORIGINS: 'http://localhost:5173,http://127.0.0.1:5173',
}
const output = execFileSync(python, ['scripts/add_institution.py', '--name', 'Synthetic placement cell', '--code', 'DEMO-PLACEMENT'], { cwd: root, env: demoEnv, encoding: 'utf8' })
const apiKey = output.trim().split(/\r?\n/).at(-1)
if (!apiKey || apiKey.startsWith('Institution')) throw new Error('Institution CLI did not return its one-time test key')
process.env.E2E_INSTITUTION_KEY = apiKey
process.env.E2E_DATABASE_URL = demoEnv.DATABASE_URL
process.env.E2E_DEMO_PEPPER = demoEnv.INDICATOR_PEPPER
execFileSync(python, ['scripts/seed_demo_reports.py'], { cwd: root, env: demoEnv, stdio: 'inherit' })

const playwrightCli = path.join(frontend, 'node_modules', 'playwright', 'cli.js')
const result = spawnSync(process.execPath, [playwrightCli, 'test', '--config', 'playwright.config.ts'], { cwd: frontend, env: process.env, stdio: 'inherit' })
if (result.error) throw result.error
process.exitCode = result.status ?? 1
