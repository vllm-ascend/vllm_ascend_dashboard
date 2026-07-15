#!/bin/bash
#
# 生产环境安全部署脚本
#
# 流程：备份 → 验证备份 → 记录部署前状态 → 拉取代码 → 更新依赖 →
#       数据库迁移(不重置用户) → 重启服务 → 部署后验证 → 异常自动回滚
#
# 用法：
#   ./deploy_prod.sh              # 部署最新代码
#   ./deploy_prod.sh --no-pull    # 不拉取代码，仅重新部署当前版本
#   ./deploy_prod.sh --rollback   # 回滚到最近一次备份
#

set -euo pipefail

# ── 配置 ──────────────────────────────────────
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PROJECT_ROOT="$(dirname "$SCRIPT_DIR")"
BACKEND_DIR="$PROJECT_ROOT/backend"
DB_PATH="$PROJECT_ROOT/backend/data/dashboard.db"
BACKUP_DIR="$PROJECT_ROOT/backups"
SERVICE_NAME="dashboard-backend"
MAX_WAIT=30  # 服务启动最大等待秒数

# 解析参数
DO_PULL=true
FORCE_ROLLBACK=false
for arg in "$@"; do
    case $arg in
        --no-pull)   DO_PULL=false ;;
        --rollback)  FORCE_ROLLBACK=true ;;
    esac
done

# ── 日志函数 ──────────────────────────────────
RED='\033[0;31m'; GREEN='\033[0;32m'; YELLOW='\033[1;33m'; BLUE='\033[0;34m'; NC='\033[0m'
step()  { echo -e "\n${BLUE}━━━ $1 ━━━${NC}"; }
ok()    { echo -e "  ${GREEN}✓${NC} $1"; }
fail()  { echo -e "  ${RED}✗${NC} $1"; }
warn()  { echo -e "  ${YELLOW}⚠${NC} $1"; }

# ── 工具函数 ──────────────────────────────────
get_user_count() {
    sqlite3 "$DB_PATH" "SELECT COUNT(*) FROM users;" 2>/dev/null || echo "0"
}

get_table_count() {
    sqlite3 "$DB_PATH" "SELECT COUNT(*) FROM sqlite_master WHERE type='table';" 2>/dev/null || echo "0"
}

get_user_list() {
    sqlite3 "$DB_PATH" "SELECT id, username, role FROM users ORDER BY id;" 2>/dev/null || echo "(无法读取)"
}

wait_for_service() {
    local elapsed=0
    while [ $elapsed -lt $MAX_WAIT ]; do
        if curl -sf http://127.0.0.1:8000/api/v1/health >/dev/null 2>&1; then
            return 0
        fi
        sleep 1
        elapsed=$((elapsed + 1))
    done
    return 1
}

# ── 回滚函数 ──────────────────────────────────
rollback() {
    local backup_file="$1"
    echo ""
    step "紧急回滚"
    warn "正在从备份恢复: $backup_file"

    systemctl stop "$SERVICE_NAME" 2>/dev/null || true
    sleep 2

    cp "$backup_file" "$DB_PATH"
    chown root:root "$DB_PATH"
    chmod 644 "$DB_PATH"

    systemctl start "$SERVICE_NAME"
    sleep 3

    if wait_for_service; then
        ok "回滚成功，服务已恢复"
        ok "当前用户数: $(get_user_count)"
        ok "用户列表:"
        get_user_list | while read -r line; do echo "    $line"; done
    else
        fail "回滚后服务仍无法启动，请手动检查"
        fail "手动恢复: cp $backup_file $DB_PATH && systemctl start $SERVICE_NAME"
    fi
    exit 1
}

# ── 回滚模式 ──────────────────────────────────
if [ "$FORCE_ROLLBACK" = true ]; then
    LATEST_BACKUP=$(ls -t "$BACKUP_DIR"/dashboard_*.db 2>/dev/null | head -1)
    if [ -z "$LATEST_BACKUP" ]; then
        fail "没有可用的备份文件"
        exit 1
    fi
    rollback "$LATEST_BACKUP"
fi

# ── 正式部署流程 ──────────────────────────────
echo ""
echo "================================================"
echo "  vLLM Ascend Dashboard — 生产部署"
echo "  $(date '+%Y-%m-%d %H:%M:%S')"
echo "================================================"

# ── Step 1: 备份数据库 ────────────────────────
step "Step 1/8: 备份数据库"

BACKUP_FILE=$(bash "$SCRIPT_DIR/backup_db.sh" 2>&1 | tail -1)
if [ ! -f "$BACKUP_FILE" ]; then
    fail "备份失败，部署中止"
    fail "输出: $BACKUP_FILE"
    exit 1
fi
ok "备份成功: $BACKUP_FILE"

# ── Step 2: 验证备份 ──────────────────────────
step "Step 2/8: 验证备份"

INTEGRITY=$(sqlite3 "$BACKUP_FILE" "PRAGMA integrity_check;" 2>&1)
if [ "$INTEGRITY" != "ok" ]; then
    fail "备份完整性校验失败: $INTEGRITY"
    exit 1
fi
ok "完整性校验通过"

BACKUP_USERS=$(sqlite3 "$BACKUP_FILE" "SELECT COUNT(*) FROM users;" 2>/dev/null || echo "0")
ok "备份中用户数: $BACKUP_USERS"

if [ "$BACKUP_USERS" -eq 0 ]; then
    fail "备份中用户数为 0，可能数据异常"
    fail "部署中止，请检查数据库"
    exit 1
fi
ok "用户数检查通过"

# ── Step 3: 记录部署前状态 ────────────────────
step "Step 3/8: 记录部署前状态"

PRE_USERS=$(get_user_count)
PRE_TABLES=$(get_table_count)
PRE_GIT=$(cd "$PROJECT_ROOT" && git rev-parse --short HEAD 2>/dev/null || echo "unknown")

ok "当前 Git commit: $PRE_GIT"
ok "用户数: $PRE_USERS"
ok "数据表数: $PRE_TABLES"
ok "用户列表:"
get_user_list | while read -r line; do echo "    $line"; done

# ── Step 4: 拉取最新代码 ──────────────────────
step "Step 4/8: 拉取最新代码"

if [ "$DO_PULL" = true ]; then
    cd "$PROJECT_ROOT"
    if git pull origin main; then
        NEW_GIT=$(git rev-parse --short HEAD)
        ok "代码已更新: $PRE_GIT → $NEW_GIT"
    else
        fail "拉取代码失败"
        exit 1
    fi
else
    warn "跳过拉取代码 (--no-pull)"
fi

# ── Step 5: 更新后端依赖 ──────────────────────
step "Step 5/8: 更新后端依赖"

cd "$BACKEND_DIR"
if uv sync --dev; then
    ok "依赖更新完成"
else
    fail "依赖更新失败"
    exit 1
fi

# ── Step 6: 数据库迁移（不重置用户）────────────
step "Step 6/8: 数据库迁移"

cd "$BACKEND_DIR"
# 关键：使用 --no-users 防止 init_db.py 重置用户
if .venv/bin/python scripts/init_db.py --no-users; then
    ok "数据库迁移完成"
else
    warn "数据库迁移出错，检查是否影响现有数据"
    # 验证用户数据是否还在
    POST_MIGRATION_USERS=$(get_user_count)
    if [ "$POST_MIGRATION_USERS" -lt "$PRE_USERS" ]; then
        fail "迁移后用户数减少 ($PRE_USERS → $POST_MIGRATION_USERS)！"
        fail "正在回滚..."
        rollback "$BACKUP_FILE"
    fi
    warn "迁移有警告但用户数据完好，继续部署"
fi

# ── Step 7: 重启服务 ──────────────────────────
step "Step 7/8: 重启服务"

systemctl restart "$SERVICE_NAME"
ok "服务已重启，等待启动..."

if wait_for_service; then
    ok "服务已启动"
else
    fail "服务在 ${MAX_WAIT}s 内未响应"
    fail "正在回滚..."
    rollback "$BACKUP_FILE"
fi

# ── Step 8: 部署后验证 ────────────────────────
step "Step 8/8: 部署后验证"

# 8a. 服务状态
if systemctl is-active --quiet "$SERVICE_NAME"; then
    ok "服务状态: running"
else
    fail "服务状态: inactive"
    rollback "$BACKUP_FILE"
fi

# 8b. 用户数对比
POST_USERS=$(get_user_count)
POST_TABLES=$(get_table_count)

if [ "$POST_USERS" -lt "$PRE_USERS" ]; then
    fail "用户数减少！部署前 $PRE_USERS → 部署后 $POST_USERS"
    fail "正在回滚..."
    rollback "$BACKUP_FILE"
fi
ok "用户数: $PRE_USERS → $POST_USERS ✓"
ok "数据表数: $PRE_TABLES → $POST_TABLES"

# 8c. API 健康检查
if curl -sf http://127.0.0.1:8000/api/v1/health >/dev/null 2>&1; then
    ok "API 健康检查: 通过"
else
    warn "API 健康检查: 失败（服务可能还在初始化）"
fi

# 8d. 验证登录功能
LOGIN_TEST=$(curl -sf -X POST http://127.0.0.1:8000/api/v1/auth/login \
    -H 'Content-Type: application/json' \
    -d '{"username":"admin","password":"admin123"}' 2>/dev/null || echo "FAIL")

if echo "$LOGIN_TEST" | grep -q "access_token"; then
    ok "登录功能验证: 通过"
else
    warn "登录功能验证: admin/admin123 登录失败"
    warn "如果已修改 admin 密码，此警告可忽略"
fi

# 8e. 用户列表确认
ok "当前用户列表:"
get_user_list | while read -r line; do echo "    $line"; done

# ── 部署完成 ──────────────────────────────────
echo ""
echo "================================================"
echo "  ✓ 部署完成"
echo "================================================"
echo "  备份文件:   $BACKUP_FILE"
echo "  Git commit: $PRE_GIT → $(cd "$PROJECT_ROOT" && git rev-parse --short HEAD)"
echo "  用户数:     $PRE_USERS → $POST_USERS"
echo ""
echo "  如需回滚:"
echo "    $0 --rollback"
echo "    或手动: cp $BACKUP_FILE $DB_PATH && systemctl restart $SERVICE_NAME"
echo "================================================"
