# vLLM Ascend Dashboard - Dev Environment Setup (PowerShell)
Write-Host ""
Write-Host "============================================================"
Write-Host " vLLM Ascend Dashboard - Dev Setup"
Write-Host "============================================================"
Write-Host ""

Set-Location $PSScriptRoot

# Check prerequisites
Write-Host "--- Checking prerequisites ---"
$missing = @()
if (-not (Get-Command node -ErrorAction SilentlyContinue))   { $missing += "Node.js 20+" }
if (-not (Get-Command pnpm -ErrorAction SilentlyContinue))   { $missing += "pnpm" }
if (-not (Get-Command docker -ErrorAction SilentlyContinue)) { $missing += "Docker Desktop" }
if (-not (Get-Command python -ErrorAction SilentlyContinue)) { $missing += "Python 3.11+" }
if ($missing.Count -gt 0) {
    Write-Host "[ERR] Missing: $($missing -join ', ')" -ForegroundColor Red
    exit 1
}
Write-Host "[OK] All dependencies found" -ForegroundColor Green

# Create .env
Write-Host ""
Write-Host "--- Configuring .env ---"
if (Test-Path .env) {
    Write-Host "[WARN] .env already exists, skipping" -ForegroundColor Yellow
} else {
    $GITHUB_TOKEN = Read-Host "Enter GITHUB_TOKEN"
    @"
GITHUB_TOKEN=$GITHUB_TOKEN
GITHUB_OWNER=vllm-project
GITHUB_REPO=vllm-ascend
DATABASE_URL=sqlite+aiosqlite:///./app.db
JWT_SECRET=local-dev-jwt-secret-123
ENVIRONMENT=development
DEBUG=true
LOG_LEVEL=INFO
CI_SYNC_INTERVAL_MINUTES=720
REPORT_ENABLED=false
DAILY_SUMMARY_ENABLED=false
"@ | Out-File -FilePath .env -Encoding ascii
    Write-Host "[OK] .env created" -ForegroundColor Green
}
if (-not (Test-Path backend\.env)) { Copy-Item .env backend\.env }

# Create data directories
Write-Host ""
Write-Host "--- Creating directories ---"
@("backend\data", "backend\logs", "deploy\config") | ForEach-Object {
    if (-not (Test-Path $_)) { New-Item -ItemType Directory -Path $_ -Force | Out-Null }
}
Write-Host "[OK] Directories ready" -ForegroundColor Green

# Build Docker image
Write-Host ""
Write-Host "--- Building Docker image (takes a few minutes) ---"
docker build -t vllm-dashboard-backend -f backend\Dockerfile.prod backend
if ($LASTEXITCODE -ne 0) { Write-Host "[ERR] Build failed" -ForegroundColor Red; exit 1 }
Write-Host "[OK] Image built" -ForegroundColor Green

# Start backend
Write-Host ""
Write-Host "--- Starting backend ---"
docker rm -f vllm-backend-dev 2>$null
docker run -d --name vllm-backend-dev -p 8000:8000 -v vllm_backend_data:/app/data --env-file .env -e DATABASE_URL=sqlite+aiosqlite:////app/data/app.db --entrypoint '""' vllm-dashboard-backend //opt/venv/bin/uvicorn app.main:app --host 0.0.0.0 --port 8000
if ($LASTEXITCODE -ne 0) { Write-Host "[ERR] Container failed" -ForegroundColor Red; exit 1 }
Start-Sleep -Seconds 8
docker logs vllm-backend-dev --tail 3
Write-Host "[OK] Backend running: http://localhost:8000" -ForegroundColor Green

# LiteLLM (optional)
Write-Host ""
Write-Host "--- LiteLLM (for AI analysis) ---"
$enableLitellm = Read-Host "Enable LiteLLM for AI analysis? [y/N]"
if ($enableLitellm -eq "y" -or $enableLitellm -eq "Y") {
    docker network create vllm-dev-net 2>$null
    Write-Host "Generating LiteLLM config..."
    @"
general_settings:
  master_key: sk-litellm-master-key-change-me

model_list: []

litellm_settings:
  drop_params: true

router_settings:
  disable_responses_api: true
  num_retries: 1
  request_timeout: 600
"@ | Out-File -FilePath deploy\config\litellm_runtime.yaml -Encoding ascii

    docker rm -f vllm-litellm-dev 2>$null
    docker run -d --name vllm-litellm-dev --network vllm-dev-net -p 4000:4000 -v "${PWD}\deploy\config\litellm_runtime.yaml:/app/config.yaml" -e LITELLM_MASTER_KEY=sk-litellm-master-key-change-me ghcr.io/berriai/litellm:main-latest --config /app/config.yaml --port 4000

    docker stop vllm-backend-dev 2>$null
    docker rm vllm-backend-dev 2>$null
    docker run -d --name vllm-backend-dev --network vllm-dev-net -p 8000:8000 -v vllm_backend_data:/app/data -v "${PWD}\deploy\config\litellm_runtime.yaml:/app/litellm_config.yaml" --env-file .env -e DATABASE_URL=sqlite+aiosqlite:////app/data/app.db -e LITELLM_PROXY_URL=http://vllm-litellm-dev:4000 --entrypoint '""' vllm-dashboard-backend //opt/venv/bin/uvicorn app.main:app --host 0.0.0.0 --port 8000
    Start-Sleep -Seconds 5
    Write-Host "[OK] LiteLLM running" -ForegroundColor Green
    Write-Host "[INFO] Configure LLM Provider API Key in Dashboard UI: System Config -> LLM Provider"
} else {
    Write-Host "[INFO] Skipped LiteLLM"
}

# Create admin account
Write-Host ""
Write-Host "--- Creating admin account ---"
docker exec vllm-backend-dev python3 -c @"
import sqlite3,os,sys
sys.path.insert(0,'/app')
os.environ['GITHUB_TOKEN']='ghp_xxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxx'
os.environ['JWT_SECRET']='init-init-init-init-init-init-init-init'
os.environ['DATABASE_URL']='sqlite+aiosqlite:////app/data/app.db'
from app.core.security import hash_password
conn=sqlite3.connect('/app/data/app.db')
hashed=hash_password('admin123')
conn.execute('INSERT OR IGNORE INTO users (username,password_hash,email,role,is_active,created_at) VALUES (?,?,?,?,?,datetime(\"now\"))',
    ('admin',hashed,'admin@local.dev','super_admin',1))
conn.commit()
conn.close()
print('OK')
"@
Write-Host "[OK] Admin: admin / admin123" -ForegroundColor Green

# Install frontend deps
Write-Host ""
Write-Host "--- Installing frontend deps ---"
Set-Location frontend
pnpm install
Set-Location ..

# Done
Write-Host ""
Write-Host "============================================================"
Write-Host " Setup Complete!"
Write-Host "============================================================"
Write-Host ""
Write-Host " Start frontend:  cd frontend; pnpm dev"
Write-Host " Backend API:     http://localhost:8000/docs"
Write-Host " Frontend:        http://localhost:3000"
Write-Host " Admin:           admin / admin123"
Write-Host ""
Write-Host " Stop:    docker stop vllm-backend-dev"
Write-Host " Restart: docker restart vllm-backend-dev"
Write-Host ""
Read-Host "Press Enter to exit"
