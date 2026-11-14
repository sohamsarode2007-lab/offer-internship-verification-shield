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
// Synthetic company master (fictional companies only), used by the backend only in DEMO_MODE.
const registryPath = path.join(frontend, 'e2e-registry.sqlite3')
if (existsSync(registryPath)) rmSync(registryPath)

const python = process.env.PYTHON ?? (process.platform === 'win32'
  ? path.join(root, '.venv', 'Scripts', 'python.exe')
  : 'python')
execFileSync(python, ['scripts/load_mca_master.py', 'fixtures/demo/synthetic_mca_master.csv', '--synthetic', '--db', registryPath], { cwd: root, stdio: 'inherit' })
const demoEnv = {
  ...process.env,
  DATABASE_URL: 'sqlite:///./frontend/e2e-test.db',
  DEMO_MODE: '1',
  DEMO_FIXTURE_DOMAINS: 'emberlakeanalytics.example,brightpathedtech.example,quillmeresoftware.example,tarnwicklogistics.example,halvornfintech.example',
  MCA_DB_PATH: registryPath,
  INDICATOR_PEPPER: randomBytes(32).toString('hex'),
  INDICATOR_KEY_VERSION: '1',
  RATE_LIMIT: '100/minute',
  ALLOWED_ORIGINS: 'http://localhost:5173,http://127.0.0.1:5173',
}
process.env.E2E_DATABASE_URL = demoEnv.DATABASE_URL
process.env.E2E_DEMO_PEPPER = demoEnv.INDICATOR_PEPPER
process.env.E2E_REGISTRY_DB = registryPath
execFileSync(python, ['scripts/seed_demo_reports.py'], { cwd: root, env: demoEnv, stdio: 'inherit' })

const playwrightCli = path.join(frontend, 'node_modules', 'playwright', 'cli.js')
const result = spawnSync(process.execPath, [playwrightCli, 'test', '--config', 'playwright.config.ts'], { cwd: frontend, env: process.env, stdio: 'inherit' })
if (result.error) throw result.error
process.exitCode = result.status ?? 1
