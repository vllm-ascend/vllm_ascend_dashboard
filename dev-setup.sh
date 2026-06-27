#!/bin/bash
# ============================================================
# vLLM Ascend Dashboard - 本地开发环境一键搭建脚本
# ============================================================
set -e

RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
NC='\033[0m'

log()  { echo -e "${GREEN}[OK]${NC} $1"; }
warn() { echo -e "${YELLOW}[WARN]${NC} $1"; }
err()  { echo -e "${RED}[ERR]${NC} $1"; exit 1; }

echo ""
echo "============================================================"
echo " vLLM Ascend Dashboard - 本地开发环境搭建"
echo "============================================================"
echo ""

# ── 0. 检查前置依赖 ──
echo "--- 检查依赖 ---"
command -v node   >/dev/null 2>&1 || err "需要 Node.js 20+"
command -v pnpm   >/dev/null 2>&1 || err "需要 pnpm"
command -v docker >/dev/null 2>&1 || err "需要 Docker Desktop"
command -v python >/dev/null 2>&1 || err "需要 Python 3.11+"
log "依赖检查通过"

# ── 1. 创建 .env ──
echo ""
echo "--- 配置环境变量 ---"
if [ ! -f .env ]; then
    echo "请粘贴 GITHUB_TOKEN（输入后按回车）："
    read -r GITHUB_TOKEN
    cat > .env << EOF
GITHUB_TOKEN=${GITHUB_TOKEN}
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
EOF
    cp .env backend/.env
    log ".env 创建完成"
else
    warn ".env 已存在，跳过"
    [ ! -f backend/.env ] && cp .env backend/.env
fi

# ── 2. 修复 Windows 换行符 ──
echo ""
echo "--- 修复换行符 ---"
if [ -f backend/docker-entrypoint.sh ]; then
    sed -i 's/\r$//' backend/docker-entrypoint.sh 2>/dev/null || true
fi
log "换行符修复完成"

# ── 3. 构建 + 启动 Docker ──
echo ""
echo "--- 构建并启动后端 (Docker) ---"

# 创建数据目录
mkdir -p backend/data backend/logs

docker build -t vllm-dashboard-backend -f backend/Dockerfile.prod backend
docker rm -f vllm-backend-dev 2>/dev/null || true

DOCKER_RUN="docker run"
if [[ "$OSTYPE" == "msys" || "$OSTYPE" == "cygwin" ]]; then
    # Git Bash 路径转换保护
    export MSYS_NO_PATHCONV=1
fi

docker run -d --name vllm-backend-dev \
  -p 8000:8000 \
  -v vllm_backend_data:/app/data \
  --env-file .env \
  -e DATABASE_URL=sqlite+aiosqlite:////app/data/app.db \
  --entrypoint "" \
  vllm-dashboard-backend \
  /opt/venv/bin/uvicorn app.main:app --host 0.0.0.0 --port 8000

sleep 5
docker logs vllm-backend-dev --tail 3
log "后端启动完成: http://localhost:8000"

# ── 4. 创建管理员 ──
echo ""
echo "--- 创建管理员账号 ---"
docker exec vllm-backend-dev python3 -c "
import sqlite3, os, sys
sys.path.insert(0, '/app')
os.environ['GITHUB_TOKEN'] = 'init'
os.environ['JWT_SECRET'] = 'init-init-init-init-init-init-init-init'
os.environ['DATABASE_URL'] = 'sqlite+aiosqlite:////app/data/app.db'
from app.core.security import hash_password
conn = sqlite3.connect('/app/data/app.db')
try:
    conn.execute('SELECT 1 FROM users WHERE username=?', ('admin',)).fetchone()
except:
    conn.execute('CREATE TABLE IF NOT EXISTS users (id INTEGER PRIMARY KEY, username TEXT, password_hash TEXT, email TEXT, role TEXT, is_active INTEGER, created_at TEXT)')
hashed = hash_password('admin123')
conn.execute('INSERT OR IGNORE INTO users (username, password_hash, email, role, is_active, created_at) VALUES (?,?,?,?,?,datetime(\"now\"))',
    ('admin', hashed, 'admin@local.dev', 'super_admin', 1))
conn.commit()
conn.close()
print('admin / admin123')
"
log "管理员: admin / admin123"

# ── 5. 安装前端依赖 ──
echo ""
echo "--- 安装前端依赖 ---"
cd frontend
pnpm install --silent 2>/dev/null || pnpm install
cd ..

# ── 6. 完成 ──
echo ""
echo "============================================================"
echo " 环境搭建完成！"
echo "============================================================"
echo ""
echo " 启动前端:  cd frontend && pnpm dev"
echo " 后端 API:  http://localhost:8000/docs"
echo " 前端页面:  http://localhost:3000"
echo " 管理员:    admin / admin123"
echo ""
echo " 停止:      docker stop vllm-backend-dev"
echo " 重启:      docker restart vllm-backend-dev"
echo ""
