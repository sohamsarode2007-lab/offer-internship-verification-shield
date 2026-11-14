@echo off
rem One-step demo: synthetic registry + demo reports + demo frontend build + one server.
rem All demo data is synthetic (fictional companies, .example domains). Never use DEMO_MODE in production.
setlocal EnableExtensions
cd /d "%~dp0"

set "PY=%~dp0.venv\Scripts\python.exe"
set "URL=http://127.0.0.1:8000"

if not exist "%PY%" (
  echo [run_demo] ERROR: Python virtual environment not found at .venv\Scripts\python.exe
  echo [run_demo] Create it first:
  echo [run_demo]   python -m venv .venv
  echo [run_demo]   .venv\Scripts\python.exe -m pip install -r requirements-dev.txt
  exit /b 1
)
where node >nul 2>nul
if errorlevel 1 (
  echo [run_demo] ERROR: Node.js was not found on PATH. Install Node.js 20+ from https://nodejs.org and reopen the terminal.
  exit /b 1
)
where npm >nul 2>nul
if errorlevel 1 (
  echo [run_demo] ERROR: npm was not found on PATH. Reinstall Node.js with npm and reopen the terminal.
  exit /b 1
)

rem --- Demo environment -------------------------------------------------------
set "DEMO_MODE=1"
set "DEMO_FIXTURE_DOMAINS=emberlakeanalytics.example,brightpathedtech.example,quillmeresoftware.example,tarnwicklogistics.example,halvornfintech.example"
set "DATABASE_URL=sqlite:///./data/demo/demo.sqlite3"
set "MCA_DB_PATH=data\demo\registry.sqlite3"
set "RATE_LIMIT=100/minute"
set "INDICATOR_KEY_VERSION=1"
set "ALLOWED_ORIGINS=%URL%"
if not exist "data\demo" mkdir "data\demo"
for /f "usebackq delims=" %%P in (`call "%PY%" scripts\demo_helpers.py pepper data\demo\indicator_pepper.txt`) do set "INDICATOR_PEPPER=%%P"
if not defined INDICATOR_PEPPER (
  echo [run_demo] ERROR: could not create the demo indicator pepper.
  exit /b 1
)

rem --- Synthetic company registry (fictional companies, DEMO_MODE only) --------
echo [run_demo] Building the synthetic company registry...
"%PY%" scripts\load_mca_master.py fixtures\demo\synthetic_mca_master.csv --synthetic --db data\demo\registry.sqlite3
if errorlevel 1 ( echo [run_demo] ERROR: registry build failed. & exit /b 1 )

rem --- Demo community reports (idempotent) -------------------------------------
echo [run_demo] Seeding demo community reports...
"%PY%" scripts\seed_demo_reports.py
if errorlevel 1 ( echo [run_demo] ERROR: seeding demo reports failed. & exit /b 1 )

rem --- Frontend (demo build with sample buttons), only when stale --------------
"%PY%" scripts\demo_helpers.py frontend-stale
if not errorlevel 1 (
  if not exist "frontend\node_modules" (
    echo [run_demo] Installing frontend dependencies...
    call npm --prefix frontend ci
    if errorlevel 1 ( echo [run_demo] ERROR: npm ci failed. & exit /b 1 )
  )
  echo [run_demo] Building the frontend with VITE_DEMO=1...
  set "VITE_DEMO=1"
  set "VITE_API_URL="
  call npm --prefix frontend run build
  if errorlevel 1 ( echo [run_demo] ERROR: frontend build failed. & exit /b 1 )
  "%PY%" scripts\demo_helpers.py mark-demo-build
)

rem --- One server: API + frontend/dist ----------------------------------------
echo.
echo [run_demo] Demo running at %URL%   (press Ctrl+C to stop)
echo.
if not "%DEMO_NO_BROWSER%"=="1" start "" /b "%PY%" scripts\demo_helpers.py open-when-ready %URL%
"%PY%" -m uvicorn app.main:app --host 127.0.0.1 --port 8000
endlocal
