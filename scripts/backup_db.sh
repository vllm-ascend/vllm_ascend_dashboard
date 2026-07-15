#!/bin/bash
#
# 数据库备份脚本
# 功能：在线备份 SQLite 数据库 + 完整性校验 + 用户数确认 + 自动清理旧备份
#
# 用法：
#   ./backup_db.sh              # 执行备份
#   ./backup_db.sh --silent     # 静默模式（cron 使用）
#   ./backup_db.sh --retention 7 # 保留最近 7 天
#

set -euo pipefail

# ── 配置 ──────────────────────────────────────
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PROJECT_ROOT="$(dirname "$SCRIPT_DIR")"
DB_PATH="${DASHBOARD_DB_PATH:-$PROJECT_ROOT/backend/data/dashboard.db}"
BACKUP_DIR="${DASHBOARD_BACKUP_DIR:-$PROJECT_ROOT/backups}"
RETENTION_DAYS=30
SILENT=false

# 解析参数
while [[ $# -gt 0 ]]; do
    case "$1" in
        --silent)    SILENT=true; shift ;;
        --retention) RETENTION_DAYS="${2:-30}"; shift 2 ;;
        *)           shift ;;
    esac
done

# ── 日志函数 ──────────────────────────────────
log()  { $SILENT || echo -e "\033[0;32m[BACKUP]\033[0m $1"; }
warn() { $SILENT || echo -e "\033[1;33m[WARN]\033[0m $1"; }
err()  { echo -e "\033[0;31m[ERROR]\033[0m $1" >&2; }

# ── 前置检查 ──────────────────────────────────
if [ ! -f "$DB_PATH" ]; then
    err "数据库文件不存在: $DB_PATH"
    exit 1
fi

if ! command -v sqlite3 &> /dev/null; then
    err "sqlite3 未安装，请执行: apt-get install -y sqlite3"
    exit 1
fi

# ── 执行备份 ──────────────────────────────────
TIMESTAMP=$(date +%Y%m%d_%H%M%S)
BACKUP_FILE="$BACKUP_DIR/dashboard_${TIMESTAMP}.db"

mkdir -p "$BACKUP_DIR"

log "开始备份数据库..."
log "  源文件: $DB_PATH"
log "  目标:   $BACKUP_FILE"

# 使用 sqlite3 .backup 命令（在线安全备份，不会锁定数据库）
if ! sqlite3 "$DB_PATH" ".backup '$BACKUP_FILE'"; then
    err "备份失败"
    exit 1
fi

# ── 验证备份 ──────────────────────────────────
log "验证备份完整性..."

# 检查文件是否存在且非空
if [ ! -s "$BACKUP_FILE" ]; then
    err "备份文件为空或不存在"
    rm -f "$BACKUP_FILE"
    exit 1
fi

# 完整性校验
INTEGRITY=$(sqlite3 "$BACKUP_FILE" "PRAGMA integrity_check;" 2>&1)
if [ "$INTEGRITY" != "ok" ]; then
    err "完整性校验失败: $INTEGRITY"
    rm -f "$BACKUP_FILE"
    exit 1
fi

# 统计备份数据
DB_SIZE=$(du -h "$BACKUP_FILE" | cut -f1)
USER_COUNT=$(sqlite3 "$BACKUP_FILE" "SELECT COUNT(*) FROM users;" 2>/dev/null || echo "N/A")
TABLE_COUNT=$(sqlite3 "$BACKUP_FILE" "SELECT COUNT(*) FROM sqlite_master WHERE type='table';" 2>/dev/null || echo "N/A")

log "备份完成 ✓"
log "  文件大小:   $DB_SIZE"
log "  用户数:     $USER_COUNT"
log "  数据表数:   $TABLE_COUNT"
log "  完整性:     通过"

# ── 清理旧备份 ────────────────────────────────
DELETED_COUNT=$(find "$BACKUP_DIR" -name "dashboard_*.db" -mtime +${RETENTION_DAYS} -delete -print 2>/dev/null | wc -l)
if [ "$DELETED_COUNT" -gt 0 ]; then
    log "清理 ${DELETED_COUNT} 个超过 ${RETENTION_DAYS} 天的旧备份"
fi

# 输出备份文件路径（供其他脚本使用）
echo "$BACKUP_FILE"
