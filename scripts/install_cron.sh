#!/bin/bash
#
# cron 定时备份安装脚本
# 功能：安装/卸载/查看定时备份任务
#
# 用法：
#   ./install_cron.sh           # 安装定时备份（每小时）
#   ./install_cron.sh --hourly  # 每小时备份（默认）
#   ./install_cron.sh --daily   # 每天凌晨 2 点备份
#   ./install_cron.sh --remove  # 卸载定时备份
#   ./install_cron.sh --status  # 查看当前状态
#

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
BACKUP_SCRIPT="$SCRIPT_DIR/backup_db.sh"
LOG_FILE="/var/log/dashboard_backup.log"
CRON_MARKER="# vLLM Dashboard - auto backup"
FREQUENCY="--hourly"

while [[ $# -gt 0 ]]; do
    case "$1" in
        --hourly) FREQUENCY="--hourly"; shift ;;
        --daily)  FREQUENCY="--daily"; shift ;;
        --remove) FREQUENCY="--remove"; shift ;;
        --status) FREQUENCY="--status"; shift ;;
        *)        shift ;;
    esac
done

# 查看状态
if [ "$FREQUENCY" = "--status" ]; then
    echo "=== 当前 cron 任务 ==="
    crontab -l 2>/dev/null | grep -A1 "$CRON_MARKER" || echo "(未安装)"
    echo ""
    echo "=== 备份文件 ==="
    PROJECT_ROOT="$(dirname "$SCRIPT_DIR")"
    ls -lh "$PROJECT_ROOT/backups/"dashboard_*.db 2>/dev/null | tail -5 || echo "(无备份)"
    exit 0
fi

# 卸载
if [ "$FREQUENCY" = "--remove" ]; then
    echo "卸载定时备份任务..."
    (crontab -l 2>/dev/null | grep -v "$CRON_MARKER" | grep -v "$BACKUP_SCRIPT") | crontab -
    echo "✓ 已卸载"
    exit 0
fi

# 安装
echo "安装定时备份任务..."

# 检查备份脚本是否存在且可执行
if [ ! -x "$BACKUP_SCRIPT" ]; then
    echo "✗ 备份脚本不存在或不可执行: $BACKUP_SCRIPT"
    exit 1
fi

# 确保日志文件存在
touch "$LOG_FILE" 2>/dev/null || true

# 构建 cron 行
if [ "$FREQUENCY" = "--daily" ]; then
    CRON_LINE="0 2 * * * $BACKUP_SCRIPT --silent >> $LOG_FILE 2>&1"
    echo "  频率: 每天 02:00"
else
    CRON_LINE="0 * * * * $BACKUP_SCRIPT --silent >> $LOG_FILE 2>&1"
    echo "  频率: 每小时整点"
fi

# 移除旧任务（如果有），添加新任务
(crontab -l 2>/dev/null | grep -v "$CRON_MARKER" | grep -v "$BACKUP_SCRIPT"; echo "$CRON_MARKER"; echo "$CRON_LINE") | crontab -

echo "  脚本: $BACKUP_SCRIPT"
echo "  日志: $LOG_FILE"
echo "✓ 安装完成"
echo ""
echo "查看状态: $0 --status"
echo "卸载:     $0 --remove"
