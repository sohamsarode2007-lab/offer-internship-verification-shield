import { defineConfig, devices } from '@playwright/test'
import { randomBytes } from 'node:crypto'

const db = 'sqlite:///./frontend/e2e-test.db'
const pepper = process.env.E2E_DEMO_PEPPER ?? randomBytes(32).toString('hex')
const baseEnv = {
  ...process.env,
  DATABASE_URL: db,
  DEMO_MODE: '1',
  DEMO_FIXTURE_DOMAINS: 'emberlakeanalytics.example,brightpathedtech.example,quillmeresoftware.example,tarnwicklogistics.example,halvornfintech.example',
  // Synthetic company master built by playwright/run-e2e.mjs (fictional companies; DEMO_MODE only).
  MCA_DB_PATH: process.env.E2E_REGISTRY_DB ?? 'frontend/e2e-registry.sqlite3',
  INDICATOR_PEPPER: pepper,
  INDICATOR_KEY_VERSION: '1',
  RATE_LIMIT: '100/minute',
  ALLOWED_ORIGINS: 'http://localhost:5173,http://127.0.0.1:5173',
}

export default defineConfig({
  testDir: './playwright',
  fullyParallel: false,
  workers: 1,
  reporter: 'list',
  timeout: 90_000,
  expect: { timeout: 15_000 },
  outputDir: 'test-results',
  use: {
    baseURL: 'http://127.0.0.1:5173', trace: 'retain-on-failure', ...devices['Desktop Chrome'],
    // Optional: PLAYWRIGHT_CHANNEL=msedge (or chrome) uses an installed, signed browser. Needed on
    // Windows PCs whose Application Control policy blocks Playwright's downloaded Chromium.
    ...(process.env.PLAYWRIGHT_CHANNEL ? { channel: process.env.PLAYWRIGHT_CHANNEL } : {}),
  },
  projects: [
    { name: 'desktop', use: { viewport: { width: 1440, height: 900 } } },
    { name: 'mobile', use: { viewport: { width: 390, height: 844 }, isMobile: true, hasTouch: true } },
  ],
  webServer: [
    {
      command: `${process.env.PYTHON ?? (process.platform === 'win32' ? '.venv\\Scripts\\python.exe' : 'python')} -m uvicorn app.main:app --host 127.0.0.1 --port 8000`,
      cwd: '..',
      url: 'http://127.0.0.1:8000/health',
      reuseExistingServer: false,
      timeout: 60_000,
      env: baseEnv,
    },
    {
      command: 'npm run dev',
      url: 'http://127.0.0.1:5173',
      reuseExistingServer: false,
      timeout: 60_000,
      env: { ...process.env, VITE_DEMO: '1', VITE_API_URL: '' },
    },
  ],
})
