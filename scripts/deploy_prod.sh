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
#   ./deploy_prod.sh --dry-run    # 演练模式（仅备份+验证+记录状态，不实际部署）
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

# 确保 uv 在 PATH 中（非交互 SSH 可能缺少 ~/.local/bin）
export PATH="$HOME/.local/bin:$HOME/.cargo/bin:$PATH"

# 解析参数
DO_PULL=true
FORCE_ROLLBACK=false
DRY_RUN=false
while [[ $# -gt 0 ]]; do
    case "$1" in
        --no-pull)   DO_PULL=false; shift ;;
        --rollback)  FORCE_ROLLBACK=true; shift ;;
        --dry-run)   DRY_RUN=true; shift ;;
        *)           shift ;;
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

get_service_user() {
    systemctl show "$SERVICE_NAME" -p User --value 2>/dev/null | tr -d ' ' || echo "root"
}

wait_for_service() {
    local elapsed=0
    while [ $elapsed -lt $MAX_WAIT ]; do
        if curl -sf http://127.0.0.1:8000/health >/dev/null 2>&1; then
            return 0
        fi
        sleep 1
        elapsed=$((elapsed + 1))
    done
    return 1
}

# ── 回滚函数 ──────────────────────────────────
# 回滚数据库 + 代码 + 依赖，确保完全恢复到部署前状态
rollback() {
    local backup_file="$1"
    local pre_git="$2"
    local service_user="$3"
    echo ""
    step "紧急回滚"
    warn "正在从备份恢复: $backup_file"

    systemctl stop "$SERVICE_NAME" 2>/dev/null || true
    sleep 2

    # 回滚数据库
    cp "$backup_file" "$DB_PATH"
    chown "${service_user}:${service_user}" "$DB_PATH" 2>/dev/null || chown root:root "$DB_PATH"
    chmod 644 "$DB_PATH"

    # 回滚代码到部署前 commit
    if [ -n "$pre_git" ] && [ "$pre_git" != "unknown" ]; then
        warn "回滚代码到 commit: $pre_git"
        cd "$PROJECT_ROOT"
        git checkout "$pre_git" 2>/dev/null || warn "git checkout 失败，保持当前代码"
    fi

    # 回滚依赖
    if command -v uv &> /dev/null; then
        warn "回滚依赖..."
        cd "$BACKEND_DIR"
        uv sync --dev 2>/dev/null || warn "依赖回滚失败，请手动检查"
    else
        warn "uv 未安装，跳过依赖回滚"
    fi

    # 重启服务
    systemctl start "$SERVICE_NAME"
    sleep 3

    if wait_for_service; then
        ok "回滚成功，服务已恢复"
        ok "当前用户数: $(get_user_count)"
        ok "用户列表:"
        get_user_list | while read -r line; do echo "    $line"; done
    else
        fail "回滚后服务仍无法启动，请手动检查"
        fail "手动恢复步骤:"
        fail "  1. cp $backup_file $DB_PATH"
        fail "  2. cd $PROJECT_ROOT && git checkout $pre_git"
        fail "  3. cd $BACKEND_DIR && uv sync --dev"
        fail "  4. systemctl start $SERVICE_NAME"
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
    SERVICE_USER=$(get_service_user)
    PRE_GIT=$(cd "$PROJECT_ROOT" && git rev-parse --short HEAD 2>/dev/null || echo "unknown")
    rollback "$LATEST_BACKUP" "$PRE_GIT" "$SERVICE_USER"
fi

# ── 正式部署流程 ──────────────────────────────
echo ""
echo "================================================"
echo "  vLLM Ascend Dashboard — 生产部署"
echo "  $(date '+%Y-%m-%d %H:%M:%S')"
[ "$DRY_RUN" = true ] && echo "  ⚠ 演练模式（--dry-run）：仅备份+验证，不实际部署"
echo "================================================"

# 获取服务运行用户（用于回滚时设置文件权限）
SERVICE_USER=$(get_service_user)

# ── Step 1: 备份数据库 ────────────────────────
step "Step 1/8: 备份数据库"

# 不使用管道，避免 set -e + pipefail 下 backup_db.sh 失败导致脚本直接退出
BACKUP_OUTPUT=$(bash "$SCRIPT_DIR/backup_db.sh" 2>&1) || {
    fail "备份失败，部署中止"
    fail "输出: $BACKUP_OUTPUT"
    exit 1
}
BACKUP_FILE=$(echo "$BACKUP_OUTPUT" | tail -1)

if [ ! -f "$BACKUP_FILE" ]; then
    fail "备份文件不存在，部署中止"
    fail "输出: $BACKUP_OUTPUT"
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
ok "服务运行用户: $SERVICE_USER"
ok "用户列表:"
get_user_list | while read -r line; do echo "    $line"; done

# 致命检查：部署前用户数为 0 说明数据库已损坏，回滚条件无法触发
if [ "$PRE_USERS" -eq 0 ]; then
    fail "部署前用户数为 0，数据库可能已损坏！"
    fail "此时回滚条件（POST < PRE）永远为假，保护机制将失效"
    fail "部署中止，请先手动恢复数据库"
    fail "  恢复方式: ls -t $BACKUP_DIR/dashboard_*.db | head -1"
    fail "  然后: cp <最新备份> $DB_PATH"
    exit 1
fi

# 演练模式：到此为止
if [ "$DRY_RUN" = true ]; then
    echo ""
    step "演练完成（--dry-run）"
    ok "备份和验证均通过，可以安全部署"
    ok "备份文件: $BACKUP_FILE"
    exit 0
fi

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
if command -v uv &> /dev/null; then
    if uv sync --dev; then
        ok "依赖更新完成"
    else
        fail "依赖更新失败"
        rollback "$BACKUP_FILE" "$PRE_GIT" "$SERVICE_USER"
    fi
else
    warn "uv 未安装，跳过依赖更新"
    warn "如需更新依赖，请先安装 uv: curl -LsSf https://astral.sh/uv/install.sh | sh"
fi

# ── Step 6: 数据库迁移（不重置用户）────────────
step "Step 6/8: 数据库迁移"

cd "$BACKEND_DIR"

# 加载环境变量（systemd 通过 EnvironmentFile 加载，命令行需手动 source）
if [ -f "$PROJECT_ROOT/.env" ]; then
    set -a; source "$PROJECT_ROOT/.env"; set +a
fi

# 关键：使用 --no-users 防止 init_db.py 重置用户
if .venv/bin/python scripts/init_db.py --no-users; then
    ok "数据库迁移完成"
else
    # 迁移失败：默认中止，让运维人工核查
    fail "数据库迁移失败"
    POST_MIGRATION_USERS=$(get_user_count)
    POST_MIGRATION_TABLES=$(get_table_count)
    fail "迁移后用户数: $PRE_USERS → $POST_MIGRATION_USERS"
    fail "迁移后数据表数: $PRE_TABLES → $POST_MIGRATION_TABLES"

    if [ "$POST_MIGRATION_USERS" -lt "$PRE_USERS" ]; then
        fail "用户数减少！正在回滚..."
        rollback "$BACKUP_FILE" "$PRE_GIT" "$SERVICE_USER"
    fi
    if [ "$POST_MIGRATION_TABLES" -lt "$PRE_TABLES" ]; then
        fail "数据表数减少！正在回滚..."
        rollback "$BACKUP_FILE" "$PRE_GIT" "$SERVICE_USER"
    fi

    fail "用户数和表数未减少，但迁移失败可能意味着其他数据损坏"
    fail "部署中止，请人工核查后再手动继续"
    exit 1
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
    rollback "$BACKUP_FILE" "$PRE_GIT" "$SERVICE_USER"
fi

# ── Step 8: 部署后验证 ────────────────────────
step "Step 8/8: 部署后验证"

# 8a. 服务状态
if systemctl is-active --quiet "$SERVICE_NAME"; then
    ok "服务状态: running"
else
    fail "服务状态: inactive"
    rollback "$BACKUP_FILE" "$PRE_GIT" "$SERVICE_USER"
fi

# 8b. 用户数 + 表数对比
POST_USERS=$(get_user_count)
POST_TABLES=$(get_table_count)

if [ "$POST_USERS" -lt "$PRE_USERS" ]; then
    fail "用户数减少！部署前 $PRE_USERS → 部署后 $POST_USERS"
    fail "正在回滚..."
    rollback "$BACKUP_FILE" "$PRE_GIT" "$SERVICE_USER"
fi
ok "用户数: $PRE_USERS → $POST_USERS ✓"

if [ "$POST_TABLES" -lt "$PRE_TABLES" ]; then
    fail "数据表数减少！部署前 $PRE_TABLES → 部署后 $POST_TABLES"
    fail "正在回滚..."
    rollback "$BACKUP_FILE" "$PRE_GIT" "$SERVICE_USER"
fi
ok "数据表数: $PRE_TABLES → $POST_TABLES ✓"

# 8c. API 健康检查
if curl -sf http://127.0.0.1:8000/health >/dev/null 2>&1; then
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
echo "  数据表数:   $PRE_TABLES → $POST_TABLES"
echo ""
echo "  如需回滚:"
echo "    $0 --rollback"
echo "    或手动: cp $BACKUP_FILE $DB_PATH && systemctl restart $SERVICE_NAME"
echo "================================================"
